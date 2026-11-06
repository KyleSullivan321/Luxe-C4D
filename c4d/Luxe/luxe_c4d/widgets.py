"""Visual studio controls for the Luxe workspace: Kelvin bar, live light preview card, and texture thumbnail grid."""
import math
import os

import c4d

from luxe_core import photometry, placement, textures

GALLERY_KEYS = [""] + list(textures.PRESETS) + [textures.CUSTOM_TEXTURE]

MODE_SHORT = {
    "reflect": "Reflect",
    "normal": "Normal",
    "orbit": "Orbit",
    "direct": "Direct",
    "rim": "Rim",
}
MODE_TIPS = {
    "reflect": "Reflection — places the light at the mirror angle so its specular highlight lands where you click",
    "normal": "Normal — places the light straight out along the surface normal",
    "orbit": "Orbit — locks onto the surface target and orbits around it as you drag",
    "direct": "Direct — places the light along the camera ray between camera and target",
    "rim": "Rim — places a grazing backlight behind the object's silhouette edge",
}

_COL_BG_DARK = c4d.Vector(0.095, 0.10, 0.115)
_COL_CARD = c4d.Vector(0.145, 0.155, 0.175)
_COL_CARD_HOVER = c4d.Vector(0.21, 0.225, 0.255)
_COL_CARD_DISABLED = c4d.Vector(0.12, 0.125, 0.135)
_COL_BORDER = c4d.Vector(0.25, 0.265, 0.295)
_COL_ACCENT = c4d.Vector(0.96, 0.68, 0.24)
_COL_TEXT = c4d.Vector(0.86, 0.88, 0.91)
_COL_TEXT_DIM = c4d.Vector(0.55, 0.58, 0.63)

_THUMB_CACHE = {}  # preset_key -> BaseBitmap (48x48)
_CUSTOM_CACHE = {}  # (path, mtime, size_w, size_h, tint_key) -> BaseBitmap


def _grey_to_bmp(grey, w, h, tint=(1.0, 1.0, 1.0), bg=(18, 19, 22)):
    """Build a C4D BaseBitmap from row-major linear grey values (0..1) and a linear RGB tint."""
    bmp = c4d.bitmaps.BaseBitmap()
    bmp.Init(w, h, 24)
    tr, tg, tb = (max(float(c), 0.0) for c in tint[:3])
    br, bg_g, bb = bg
    i = 0
    for y in range(h):
        for x in range(w):
            g = grey[i]
            i += 1
            if g <= 0.0005:
                bmp.SetPixel(x, y, br, bg_g, bb)
            else:
                r8 = photometry.linear_to_srgb_byte(g * tr)
                g8 = photometry.linear_to_srgb_byte(g * tg)
                b8 = photometry.linear_to_srgb_byte(g * tb)
                # Blend near-zero edges smoothly into the dark card backdrop
                a = min(g * 8.0, 1.0)
                bmp.SetPixel(
                    x,
                    y,
                    int(br + (r8 - br) * a),
                    int(bg_g + (g8 - bg_g) * a),
                    int(bb + (b8 - bb) * a),
                )
    return bmp


def _custom_placeholder_bmp(size=48):
    """Clean procedural icon for the 'Image...' custom texture tile when no file is loaded."""
    bmp = c4d.bitmaps.BaseBitmap()
    bmp.Init(size, size, 24)
    for y in range(size):
        for x in range(size):
            # Subtle inner frame + mountain silhouette + sun dot
            u, v = (x + 0.5) / size, (y + 0.5) / size
            border = 0.14 < u < 0.86 and 0.18 < v < 0.82
            inner = 0.18 < u < 0.82 and 0.22 < v < 0.78
            sun = math.hypot(u - 0.36, v - 0.38) < 0.085
            mtn1 = v > (0.78 - max(0.0, 0.30 - abs(u - 0.58) * 1.15))
            mtn2 = v > (0.78 - max(0.0, 0.20 - abs(u - 0.35) * 1.15))
            if border and not inner:
                c = (135, 145, 162)
            elif inner and sun:
                c = (242, 184, 82)
            elif inner and (mtn1 or mtn2):
                c = (115, 128, 148)
            elif inner:
                c = (34, 37, 44)
            else:
                c = (24, 26, 30)
            bmp.SetPixel(x, y, c[0], c[1], c[2])
    return bmp


def _load_custom_bmp(path, target_w, target_h, tint=(1.0, 1.0, 1.0)):
    """Load and scale a user image file into a tinted display BaseBitmap, cached by mtime."""
    if not path or not os.path.isfile(path):
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    tint_key = tuple(round(float(c), 3) for c in tint[:3])
    key = (path, mtime, target_w, target_h, tint_key)
    cached = _CUSTOM_CACHE.get(key)
    if cached is not None:
        return cached
    src = c4d.bitmaps.BaseBitmap()
    res, _is_movie = src.InitWith(path)
    if res != c4d.IMAGERESULT_OK or src.GetBw() <= 0 or src.GetBh() <= 0:
        return None
    scaled = c4d.bitmaps.BaseBitmap()
    scaled.Init(target_w, target_h, 24)
    src.ScaleIt(scaled, 256, True, False)
    if any(abs(c - 1.0) > 1e-3 for c in tint_key):
        # Multiply in sRGB display space for quick visual tint feedback
        sr, sg, sb = photometry.linear_to_srgb(tint_key)
        for y in range(target_h):
            for x in range(target_w):
                r, g, b = scaled.GetPixel(x, y)
                scaled.SetPixel(x, y, int(min(r * sr, 255)), int(min(g * sg, 255)), int(min(b * sb, 255)))
    if len(_CUSTOM_CACHE) > 24:
        _CUSTOM_CACHE.clear()
    _CUSTOM_CACHE[key] = scaled
    return scaled


def _preset_thumb(key, size=48):
    if key in _THUMB_CACHE:
        return _THUMB_CACHE[key]
    if key == textures.CUSTOM_TEXTURE:
        bmp = _custom_placeholder_bmp(size)
    elif key == "":
        bmp = _grey_to_bmp([0.92] * (size * size), size, size)
    else:
        layers = textures.PRESETS.get(key, [textures.layer("constant")])
        bmp = _grey_to_bmp(textures.composite(layers, size, size), size, size)
    _THUMB_CACHE[key] = bmp
    return bmp


class _Area(c4d.gui.GeUserArea):
    def Redraw(self, thread=False):
        try:
            super().Redraw(thread)
        except Exception:
            pass

    def _fill_round(self, x1, y1, x2, y2, r=5.0):
        if hasattr(self, "DrawRoundedRectangle"):
            self.DrawRoundedRectangle(int(x1), int(y1), int(x2), int(y2), float(r), float(r))
        else:
            self.DrawRectangle(int(x1), int(y1), int(x2), int(y2))

    def _frame_round(self, x1, y1, x2, y2, r=5.0, width=1.0):
        if hasattr(self, "DrawRoundedFrame"):
            self.DrawRoundedFrame(int(x1), int(y1), int(x2), int(y2), float(r), float(r), float(width))
        elif hasattr(self, "DrawFrame"):
            self.DrawFrame(int(x1), int(y1), int(x2), int(y2), float(width))
        else:
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            self.DrawLine(x1, y1, x2, y1)
            self.DrawLine(x2, y1, x2, y2)
            self.DrawLine(x2, y2, x1, y2)
            self.DrawLine(x1, y2, x1, y1)

    def _bmp_round(self, bmp, x, y, w, h, r=4.0):
        bw, bh = bmp.GetBw(), bmp.GetBh()
        if hasattr(self, "DrawBitmapRounded"):
            self.DrawBitmapRounded(bmp, int(x), int(y), int(w), int(h), 0, 0, bw, bh, c4d.BMP_NORMAL, float(r))
        else:
            self.DrawBitmap(bmp, int(x), int(y), int(w), int(h), 0, 0, bw, bh, c4d.BMP_NORMAL)

    def _local_xy(self, msg):
        l2g = self.Local2Global()
        ox, oy = (l2g["x"], l2g["y"]) if l2g else (0, 0)
        return msg[c4d.BFM_INPUT_X] - ox, msg[c4d.BFM_INPUT_Y] - oy


class ModeBarArea(_Area):
    """Segmented 5-mode studio aiming selector: Reflect | Normal | Orbit | Direct | Rim."""

    GAP = 4

    def __init__(self, on_select):
        super().__init__()
        self.on_select = on_select
        self.mode = "reflect"
        self.enabled = True
        self._hover_idx = -1

    def GetMinSize(self):
        return 240, 26

    def _rect(self, idx, total_w):
        n = len(placement.MODES)
        usable = max(total_w - (n - 1) * self.GAP - 2, n * 36)
        bw = usable // n
        x = 1 + idx * (bw + self.GAP)
        return x, 1, bw, max(self.GetHeight() - 2, 22)

    def _index_at(self, lx, ly):
        w = max(self.GetWidth(), 240)
        for idx in range(len(placement.MODES)):
            x, y, bw, bh = self._rect(idx, w)
            if x <= lx < x + bw and y <= ly < y + bh:
                return idx
        return -1

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w, h = max(self.GetWidth(), 240), max(self.GetHeight(), 24)
            self.DrawSetPen(c4d.COLOR_BG)
            self.DrawRectangle(0, 0, w - 1, h - 1)
            fh = max(self.DrawGetFontHeight(), 10)
            for idx, m in enumerate(placement.MODES):
                bx, by, bw, bh = self._rect(idx, w)
                is_sel = self.enabled and (m == self.mode)
                is_hov = self.enabled and (idx == self._hover_idx)
                if not self.enabled:
                    bg = _COL_CARD_DISABLED
                elif is_sel:
                    bg = c4d.Vector(0.28, 0.22, 0.13)
                elif is_hov:
                    bg = _COL_CARD_HOVER
                else:
                    bg = _COL_CARD
                self.DrawSetPen(bg)
                self._fill_round(bx, by, bx + bw - 1, by + bh - 1, r=4.5)
                self.DrawSetPen(_COL_ACCENT if is_sel else _COL_BORDER)
                self._frame_round(bx, by, bx + bw - 1, by + bh - 1, r=4.5, width=1.6 if is_sel else 1.0)
                label = MODE_SHORT.get(m, m.capitalize())
                tw = self.DrawGetTextWidth(label)
                fg = _COL_ACCENT if is_sel else (_COL_TEXT if self.enabled else _COL_TEXT_DIM)
                self.DrawSetTextCol(fg, c4d.COLOR_TRANS)
                self.DrawText(label, bx + max((bw - tw) // 2, 2), by + max((bh - fh) // 2, 1))
        except Exception:
            pass

    def Message(self, msg, result):
        mid = msg.GetId()
        if mid == c4d.BFM_CURSORINFO_REMOVE:
            if self._hover_idx != -1:
                self._hover_idx = -1
                self.Redraw()
        elif mid == c4d.BFM_GETCURSORINFO:
            l2s = self.Local2Screen()
            sx, sy = (l2s["x"], l2s["y"]) if l2s else (0, 0)
            idx = self._index_at(msg[c4d.BFM_DRAG_SCREENX] - sx, msg[c4d.BFM_DRAG_SCREENY] - sy)
            if idx != self._hover_idx:
                self._hover_idx = idx
                self.Redraw()
            if 0 <= idx < len(placement.MODES):
                m = placement.MODES[idx]
                result.SetId(c4d.BFM_GETCURSORINFO)
                result.SetString(c4d.RESULT_BUBBLEHELP, MODE_TIPS.get(m, m))
                return True
        return super().Message(msg, result)

    def InputEvent(self, msg):
        if not self.enabled or msg[c4d.BFM_INPUT_DEVICE] != c4d.BFM_INPUT_MOUSE:
            return False
        if msg[c4d.BFM_INPUT_CHANNEL] != c4d.BFM_INPUT_MOUSELEFT:
            return False
        lx, ly = self._local_xy(msg)
        idx = self._index_at(lx, ly)
        if 0 <= idx < len(placement.MODES):
            self.mode = placement.MODES[idx]
            self.Redraw()
            self.on_select(self.mode)
            return True
        return False


class LightDeckArea(_Area):
    """Studio light deck: visual stacked list of all Luxe lights in the scene with direct
    selection, live mode pill, exposure, color swatch, solo toggle, viewport visibility,
    camera visibility, and delete."""

    ROW_H = 26
    GAP = 3

    def __init__(self, on_action=None):
        super().__init__()
        self.on_action = on_action  # callback(action, op, item)
        self.lights = []
        self._hover_row = -1
        self._hover_btn = None

    def set_lights(self, lights):
        self.lights = list(lights or [])
        self.Redraw()

    def GetMinSize(self):
        n = len(self.lights)
        h = max(n * (self.ROW_H + self.GAP) + 4, 32) if n > 0 else 32
        return 240, h

    def _row_rect(self, idx, total_w):
        y = 2 + idx * (self.ROW_H + self.GAP)
        return 2, y, max(total_w - 4, 60), self.ROW_H

    def _hit_test(self, lx, ly):
        """Return (row_idx, btn_type) under local coordinates (lx, ly)."""
        w = max(self.GetWidth(), 240)
        for idx in range(len(self.lights)):
            rx, ry, rw, rh = self._row_rect(idx, w)
            if ry <= ly < ry + rh and rx <= lx < rx + rw:
                rx2 = rx + rw
                bw = 18
                gap = 2
                x_del = rx2 - 16
                x_cam = x_del - gap - bw
                x_view = x_cam - gap - bw
                x_solo = x_view - 4 - bw
                y_btn = ry + 4
                y_btn_end = ry + rh - 4

                if y_btn <= ly <= y_btn_end:
                    if x_del <= lx < x_del + 16:
                        return idx, "delete"
                    if x_cam <= lx < x_cam + bw:
                        return idx, "camera"
                    if x_view <= lx < x_view + bw:
                        return idx, "viewport"
                    if x_solo <= lx < x_solo + bw:
                        return idx, "solo"
                return idx, "row"
        return -1, None

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w, h = max(self.GetWidth(), 240), max(self.GetHeight(), 32)
            self.DrawSetPen(c4d.COLOR_BG)
            self.DrawRectangle(0, 0, w - 1, h - 1)
            fh = max(self.DrawGetFontHeight(), 10)

            if not self.lights:
                self.DrawSetPen(_COL_BG_DARK)
                self._fill_round(2, 2, w - 3, h - 3, r=4.0)
                self.DrawSetPen(_COL_BORDER)
                self._frame_round(2, 2, w - 3, h - 3, r=4.0, width=1.0)
                self.DrawSetTextCol(_COL_TEXT_DIM, c4d.COLOR_TRANS)
                txt = "No Luxe Lights in Scene — Click Surface to Create"
                tw = self.DrawGetTextWidth(txt)
                self.DrawText(txt, max((w - tw) // 2, 6), (h - fh) // 2)
                return

            bw = 18
            gap = 2

            for idx, item in enumerate(self.lights):
                rx, ry, rw, rh = self._row_rect(idx, w)
                rx2 = rx + rw
                is_act = item.get("is_active", False)
                is_solo = item.get("is_solo", False)
                is_hov_row = (idx == self._hover_row)
                hov_btn = self._hover_btn if is_hov_row else None

                # Card background & frame
                if is_act:
                    bg = c4d.Vector(0.18, 0.20, 0.24)
                elif is_hov_row and hov_btn == "row":
                    bg = _COL_CARD_HOVER
                else:
                    bg = _COL_CARD
                self.DrawSetPen(bg)
                self._fill_round(rx, ry, rx2 - 1, ry + rh - 1, r=4.0)

                # Frame & Active accent bar
                if is_act:
                    self.DrawSetPen(_COL_ACCENT)
                    self._frame_round(rx, ry, rx2 - 1, ry + rh - 1, r=4.0, width=1.2)
                    self.DrawRectangle(rx, ry + 2, rx + 3, ry + rh - 3)
                else:
                    self.DrawSetPen(_COL_BORDER)
                    self._frame_round(rx, ry, rx2 - 1, ry + rh - 1, r=4.0, width=1.0)

                # Color swatch dot
                colour = item.get("colour", (1.0, 1.0, 1.0))
                srgb = photometry.linear_to_srgb(colour)
                sw_x, sw_y, sw_sz = rx + 8, ry + (rh - 10) // 2, 10
                self.DrawSetPen(c4d.Vector(*srgb))
                self._fill_round(sw_x, sw_y, sw_x + sw_sz, sw_y + sw_sz, r=3.0)
                self.DrawSetPen(c4d.Vector(0.1, 0.1, 0.1))
                self._frame_round(sw_x, sw_y, sw_x + sw_sz, sw_y + sw_sz, r=3.0, width=1.0)

                # Light Name
                name = item.get("name", "Light")
                name_col = _COL_ACCENT if is_act else _COL_TEXT
                self.DrawSetTextCol(name_col, c4d.COLOR_TRANS)
                name_x = sw_x + sw_sz + 6
                self.DrawText(name, name_x, ry + (rh - fh) // 2)

                # Mode pill
                mode = item.get("mode", "reflect")
                mode_label = MODE_SHORT.get(mode, mode[:4].capitalize())
                mp_w = 40
                mp_x = name_x + max(self.DrawGetTextWidth(name) + 8, 56)
                if mp_x + mp_w < rx2 - 86:
                    self.DrawSetPen(c4d.Vector(0.11, 0.12, 0.14))
                    self._fill_round(mp_x, ry + 4, mp_x + mp_w, ry + rh - 5, r=3.0)
                    self.DrawSetPen(_COL_BORDER)
                    self._frame_round(mp_x, ry + 4, mp_x + mp_w, ry + rh - 5, r=3.0, width=1.0)
                    self.DrawSetTextCol(_COL_TEXT_DIM, c4d.COLOR_TRANS)
                    mtw = self.DrawGetTextWidth(mode_label)
                    self.DrawText(mode_label, mp_x + max((mp_w - mtw) // 2, 2), ry + (rh - fh) // 2)

                # Exposure
                ev = item.get("exposure", 0.0)
                ev_str = "%+.1f EV" % ev
                ev_w = self.DrawGetTextWidth(ev_str)
                ev_x = rx2 - 88 - ev_w
                if ev_x > mp_x + mp_w + 4:
                    self.DrawSetTextCol(_COL_TEXT_DIM, c4d.COLOR_TRANS)
                    self.DrawText(ev_str, ev_x, ry + (rh - fh) // 2)

                # Action buttons (right-aligned)
                x_del = rx2 - 16
                x_cam = x_del - gap - bw
                x_view = x_cam - gap - bw
                x_solo = x_view - 4 - bw
                y_btn = ry + 4
                bh = rh - 8

                # [S] Solo button
                if is_solo:
                    s_bg = _COL_ACCENT
                    s_fg = c4d.Vector(0.1, 0.1, 0.1)
                elif is_hov_row and hov_btn == "solo":
                    s_bg = _COL_CARD_HOVER
                    s_fg = _COL_ACCENT
                else:
                    s_bg = c4d.Vector(0.12, 0.13, 0.15)
                    s_fg = _COL_TEXT_DIM
                self.DrawSetPen(s_bg)
                self._fill_round(x_solo, y_btn, x_solo + bw, y_btn + bh, r=3.0)
                self.DrawSetPen(_COL_ACCENT if is_solo else _COL_BORDER)
                self._frame_round(x_solo, y_btn, x_solo + bw, y_btn + bh, r=3.0, width=1.0)
                self.DrawSetTextCol(s_fg, c4d.COLOR_TRANS)
                stw = self.DrawGetTextWidth("S")
                self.DrawText("S", x_solo + (bw - stw) // 2, ry + (rh - fh) // 2)

                # [V] Viewport button
                vp = item.get("viewport", True)
                if vp:
                    v_bg = _COL_CARD_HOVER if (is_hov_row and hov_btn == "viewport") else c4d.Vector(0.12, 0.13, 0.15)
                    v_fg = _COL_TEXT
                    v_txt = "V"
                else:
                    v_bg = c4d.Vector(0.24, 0.12, 0.12)
                    v_fg = c4d.Vector(0.75, 0.40, 0.40)
                    v_txt = "–"
                self.DrawSetPen(v_bg)
                self._fill_round(x_view, y_btn, x_view + bw, y_btn + bh, r=3.0)
                self.DrawSetPen(_COL_BORDER)
                self._frame_round(x_view, y_btn, x_view + bw, y_btn + bh, r=3.0, width=1.0)
                self.DrawSetTextCol(v_fg, c4d.COLOR_TRANS)
                vtw = self.DrawGetTextWidth(v_txt)
                self.DrawText(v_txt, x_view + (bw - vtw) // 2, ry + (rh - fh) // 2)

                # [C] Camera button
                cam = item.get("camera", True)
                if cam:
                    c_bg = _COL_CARD_HOVER if (is_hov_row and hov_btn == "camera") else c4d.Vector(0.12, 0.13, 0.15)
                    c_fg = _COL_TEXT
                    c_txt = "C"
                else:
                    c_bg = c4d.Vector(0.24, 0.12, 0.12)
                    c_fg = c4d.Vector(0.75, 0.40, 0.40)
                    c_txt = "–"
                self.DrawSetPen(c_bg)
                self._fill_round(x_cam, y_btn, x_cam + bw, y_btn + bh, r=3.0)
                self.DrawSetPen(_COL_BORDER)
                self._frame_round(x_cam, y_btn, x_cam + bw, y_btn + bh, r=3.0, width=1.0)
                self.DrawSetTextCol(c_fg, c4d.COLOR_TRANS)
                ctw = self.DrawGetTextWidth(c_txt)
                self.DrawText(c_txt, x_cam + (bw - ctw) // 2, ry + (rh - fh) // 2)

                # [×] Delete button
                d_bg = c4d.Vector(0.35, 0.12, 0.12) if (is_hov_row and hov_btn == "delete") else c4d.Vector(0.12, 0.13, 0.15)
                d_fg = c4d.Vector(0.95, 0.85, 0.85) if (is_hov_row and hov_btn == "delete") else _COL_TEXT_DIM
                self.DrawSetPen(d_bg)
                self._fill_round(x_del, y_btn, x_del + 15, y_btn + bh, r=3.0)
                self.DrawSetPen(_COL_BORDER)
                self._frame_round(x_del, y_btn, x_del + 15, y_btn + bh, r=3.0, width=1.0)
                self.DrawSetTextCol(d_fg, c4d.COLOR_TRANS)
                dtw = self.DrawGetTextWidth("×")
                self.DrawText("×", x_del + (15 - dtw) // 2, ry + (rh - fh) // 2)

        except Exception:
            pass

    def Message(self, msg, result):
        mid = msg.GetId()
        if mid == c4d.BFM_CURSORINFO_REMOVE:
            if self._hover_row != -1 or self._hover_btn is not None:
                self._hover_row = -1
                self._hover_btn = None
                self.Redraw()
        elif mid == c4d.BFM_GETCURSORINFO:
            l2s = self.Local2Screen()
            sx, sy = (l2s["x"], l2s["y"]) if l2s else (0, 0)
            lx = msg[c4d.BFM_DRAG_SCREENX] - sx
            ly = msg[c4d.BFM_DRAG_SCREENY] - sy
            row, btn = self._hit_test(lx, ly)
            if row != self._hover_row or btn != self._hover_btn:
                self._hover_row = row
                self._hover_btn = btn
                self.Redraw()
            if 0 <= row < len(self.lights):
                item = self.lights[row]
                tip = {
                    "solo": "Solo — click to isolate %s (mutes all other scene lights)" % item["name"],
                    "viewport": "Viewport Visibility — click to toggle %s in the 3D editor" % item["name"],
                    "camera": "Seen by Camera — click to toggle %s primary ray visibility" % item["name"],
                    "delete": "Delete — click to remove %s from scene" % item["name"],
                    "row": "Click to select %s and edit its parameters" % item["name"],
                }.get(btn, item["name"])
                result.SetId(c4d.BFM_GETCURSORINFO)
                result.SetString(c4d.RESULT_BUBBLEHELP, tip)
                return True
        return super().Message(msg, result)

    def InputEvent(self, msg):
        if msg[c4d.BFM_INPUT_DEVICE] != c4d.BFM_INPUT_MOUSE:
            return False
        if msg[c4d.BFM_INPUT_CHANNEL] != c4d.BFM_INPUT_MOUSELEFT:
            return False
        lx, ly = self._local_xy(msg)
        row, btn = self._hit_test(lx, ly)
        if 0 <= row < len(self.lights) and self.on_action is not None:
            item = self.lights[row]
            action = "select" if btn == "row" else btn
            self.on_action(action, item["op"], item)
            return True
        return False


class KelvinBarArea(_Area):
    """Interactive blackbody temperature strip (1800 K .. 6500 K .. 12000 K)."""

    MIN_K, MID_K, MAX_K = 1800.0, 6500.0, 12000.0
    MID_T = 0.55  # places 6500 K daylight comfortably near the centre

    def __init__(self, on_change):
        super().__init__()
        self.on_change = on_change
        self.kelvin = 6500.0
        self.enabled = True
        self._grad_bmp = None

    def GetMinSize(self):
        return 140, 20

    @classmethod
    def _t_to_k(cls, t):
        t = min(max(float(t), 0.0), 1.0)
        if t <= cls.MID_T:
            return cls.MIN_K + (cls.MID_K - cls.MIN_K) * (t / cls.MID_T)
        return cls.MID_K + (cls.MAX_K - cls.MID_K) * ((t - cls.MID_T) / (1.0 - cls.MID_T))

    @classmethod
    def _k_to_t(cls, k):
        k = min(max(float(k), cls.MIN_K), cls.MAX_K)
        if k <= cls.MID_K:
            return cls.MID_T * (k - cls.MIN_K) / (cls.MID_K - cls.MIN_K)
        return cls.MID_T + (1.0 - cls.MID_T) * (k - cls.MID_K) / (cls.MAX_K - cls.MID_K)

    def _ensure_bmp(self):
        if self._grad_bmp is not None:
            return self._grad_bmp
        w, h = 256, 16
        bmp = c4d.bitmaps.BaseBitmap()
        bmp.Init(w, h, 24)
        for x in range(w):
            rgb = photometry.kelvin_to_rgb(self._t_to_k(x / float(w - 1)))
            r8 = photometry.linear_to_srgb_byte(rgb[0])
            g8 = photometry.linear_to_srgb_byte(rgb[1])
            b8 = photometry.linear_to_srgb_byte(rgb[2])
            for y in range(h):
                bmp.SetPixel(x, y, r8, g8, b8)
        self._grad_bmp = bmp
        return bmp

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w, h = max(self.GetWidth(), 20), max(self.GetHeight(), 16)
            self.DrawSetPen(c4d.COLOR_BG)
            self.DrawRectangle(0, 0, w - 1, h - 1)
            pad = 2
            bw, bh = max(w - 2 * pad, 8), max(h - 2 * pad, 10)
            bmp = self._ensure_bmp()
            if not self.enabled:
                self.DrawSetOpacity(0.35)
            self._bmp_round(bmp, pad, pad, bw, bh, r=4.0)
            self.DrawSetOpacity(1.0)
            self.DrawSetPen(_COL_BORDER)
            self._frame_round(pad, pad, pad + bw - 1, pad + bh - 1, r=4.0, width=1.0)

            # 6500 K neutral daylight reference tick
            dx = pad + int(round(self.MID_T * (bw - 1)))
            self.DrawSetPen(c4d.Vector(0.15, 0.15, 0.18))
            self.DrawLine(dx, pad + 1, dx, pad + 4)
            self.DrawLine(dx, pad + bh - 5, dx, pad + bh - 2)

            if self.enabled:
                hx = pad + int(round(self._k_to_t(self.kelvin) * (bw - 1)))
                hx = min(max(hx, pad + 3), pad + bw - 4)
                self.DrawSetPen(c4d.Vector(0.08, 0.08, 0.1))
                self._fill_round(hx - 3, 1, hx + 3, h - 2, r=2.5)
                self.DrawSetPen(c4d.Vector(1.0, 1.0, 1.0))
                self._fill_round(hx - 2, 2, hx + 2, h - 3, r=2.0)
        except Exception:
            pass

    def Message(self, msg, result):
        if msg.GetId() == c4d.BFM_GETCURSORINFO:
            result.SetId(c4d.BFM_GETCURSORINFO)
            result.SetString(c4d.RESULT_BUBBLEHELP,
                             "Drag to scrub Kelvin (1800 K warm .. 6500 K daylight .. 12000 K cool). Right-click resets 6500 K.")
            return True
        return super().Message(msg, result)

    def InputEvent(self, msg):
        if not self.enabled or msg[c4d.BFM_INPUT_DEVICE] != c4d.BFM_INPUT_MOUSE:
            return False
        ch = msg[c4d.BFM_INPUT_CHANNEL]
        if ch == c4d.BFM_INPUT_MOUSERIGHT or msg[c4d.BFM_INPUT_DOUBLECLICK]:
            self.kelvin = 6500.0
            self.Redraw()
            self.on_change(self.kelvin, False)
            return True
        if ch != c4d.BFM_INPUT_MOUSELEFT:
            return False
        lx, ly = self._local_xy(msg)
        w = max(self.GetWidth() - 4, 1)

        def k_at(px):
            return round(self._t_to_k((px - 2.0) / float(w)) / 25.0) * 25.0

        self.kelvin = k_at(lx)
        self.Redraw()
        self.on_change(self.kelvin, True)
        self.MouseDragStart(c4d.KEY_MLEFT, lx, ly, c4d.MOUSEDRAGFLAGS_DONTHIDEMOUSE | c4d.MOUSEDRAGFLAGS_NOMOVE)
        cur_x = float(lx)
        while True:
            res, dx, _dy, _ch = self.MouseDrag()
            if res != c4d.MOUSEDRAGRESULT_CONTINUE:
                break
            if dx == 0:
                continue
            cur_x += dx
            nk = k_at(cur_x)
            if abs(nk - self.kelvin) >= 1.0:
                self.kelvin = nk
                self.Redraw()
                self.on_change(self.kelvin, True)
        self.MouseDragEnd()
        self.on_change(self.kelvin, False)
        return True


class LightPreviewArea(_Area):
    """Aspect-accurate live light emitter card with tint, softness, custom image preview, and status readout."""

    def __init__(self, on_pick_custom=None):
        super().__init__()
        self.on_pick_custom = on_pick_custom
        self.recipe = None
        self._cache_key = None
        self._cache_bmp = None

    def GetMinSize(self):
        return 220, 114

    def set_recipe(self, recipe):
        self.recipe = recipe
        self.Redraw()

    def _card_dims(self, avail_w, avail_h):
        r = self.recipe
        aspect = (max(r.width, 0.1) / max(r.height, 0.1)) if r is not None else 1.0
        aspect = min(max(aspect, 1.0 / 6.0), 6.0)
        if avail_w / float(max(avail_h, 1)) > aspect:
            ch = max(avail_h, 12)
            cw = max(int(round(ch * aspect)), 12)
        else:
            cw = max(avail_w, 12)
            ch = max(int(round(cw / aspect)), 12)
        return cw, ch

    def _preview_bmp(self, cw, ch):
        r = self.recipe
        if r is None:
            return None
        colour = r.colour()
        bw, bh = textures.size_for(cw, ch, resolution=96)
        if r.texture == textures.CUSTOM_TEXTURE:
            bmp = _load_custom_bmp(r.custom_texture, bw, bh, colour)
            if bmp is not None:
                return bmp
            return _custom_placeholder_bmp(64)
        key = (r.texture, round(r.softness, 3), bw, bh, tuple(round(c, 3) for c in colour))
        if key == self._cache_key and self._cache_bmp is not None:
            return self._cache_bmp
        if r.texture in textures.PRESETS:
            layers = textures.scale_softness(textures.PRESETS[r.texture], r.softness)
            grey = textures.composite(layers, bw, bh)
        else:
            grey = [1.0] * (bw * bh)
        self._cache_key = key
        self._cache_bmp = _grey_to_bmp(grey, bw, bh, tint=colour, bg=(16, 17, 20))
        return self._cache_bmp

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w, h = max(self.GetWidth(), 60), max(self.GetHeight(), 60)
            self.DrawSetPen(c4d.COLOR_BG)
            self.DrawRectangle(0, 0, w - 1, h - 1)
            self.DrawSetPen(_COL_BG_DARK)
            self._fill_round(0, 0, w - 1, h - 1, r=6.0)
            self.DrawSetPen(_COL_BORDER)
            self._frame_round(0, 0, w - 1, h - 1, r=6.0, width=1.0)

            fh = max(self.DrawGetFontHeight(), 11)
            r = self.recipe
            if r is None:
                self.DrawSetTextCol(_COL_TEXT_DIM, c4d.COLOR_TRANS)
                txt = "Click any surface with Luxe Light Tool to create a light"
                tw = self.DrawGetTextWidth(txt)
                self.DrawText(txt, max((w - tw) // 2, 8), (h - fh) // 2)
                return

            footer_h = fh + 8
            avail_w, avail_h = max(w - 24, 24), max(h - footer_h - 14, 24)
            cw, ch = self._card_dims(avail_w, avail_h)
            cx = (w - cw) // 2
            cy = 7 + (avail_h - ch) // 2

            bmp = self._preview_bmp(cw, ch)
            if bmp is not None:
                self._bmp_round(bmp, cx, cy, cw, ch, r=3.0)
            self.DrawSetPen(c4d.Vector(0.32, 0.34, 0.38))
            self._frame_round(cx - 1, cy - 1, cx + cw, cy + ch, r=3.0, width=1.0)

            # Bottom telemetry bar
            if r.texture == textures.CUSTOM_TEXTURE:
                tname = os.path.basename(r.custom_texture) if r.custom_texture else "Choose Image..."
                if r.custom_texture:
                    from . import lights
                    seq = lights.detect_sequence(r.custom_texture)
                    if seq and seq.get("is_sequence"):
                        tname += " [%d f]" % seq["count"]
            else:
                tname = r.texture or "Plain Area"
            left = "%s | %.0f x %.0f cm | %+.1f EV" % (tname, r.width, r.height, r.total_exposure())
            right_parts = []
            if abs(r.rotation) >= 0.5:
                right_parts.append("%.0f deg" % (r.rotation % 360.0))
            if r.color_mode != "rgb":
                right_parts.append("%d K" % round(r.kelvin))
            right = " | ".join(right_parts)

            ty = h - fh - 4
            self.DrawSetTextCol(_COL_TEXT, c4d.COLOR_TRANS)
            self.DrawText(left, 8, ty)
            if right:
                rw = self.DrawGetTextWidth(right)
                if rw + self.DrawGetTextWidth(left) + 24 < w:
                    self.DrawSetTextCol(_COL_TEXT_DIM, c4d.COLOR_TRANS)
                    self.DrawText(right, w - rw - 8, ty)
        except Exception:
            pass

    def InputEvent(self, msg):
        if (self.recipe is not None and self.recipe.texture == textures.CUSTOM_TEXTURE
                and self.on_pick_custom is not None
                and msg[c4d.BFM_INPUT_DEVICE] == c4d.BFM_INPUT_MOUSE
                and msg[c4d.BFM_INPUT_CHANNEL] == c4d.BFM_INPUT_MOUSELEFT):
            self.on_pick_custom()
            return True
        return False


class TextureGalleryArea(_Area):
    """Clickable 4-column visual preset gallery (Plain + 16 procedural shapes + Custom Image)."""

    COLS = 4
    TILE_H = 62
    GAP = 5

    def __init__(self, on_select):
        super().__init__()
        self.on_select = on_select
        self.selected = ""
        self.custom_path = ""
        self.enabled = True
        self._hover_idx = -1

    def GetMinSize(self):
        rows = (len(GALLERY_KEYS) + self.COLS - 1) // self.COLS
        return 248, rows * self.TILE_H + (rows - 1) * self.GAP + 4

    def _tile_rect(self, idx, total_w):
        cols = self.COLS
        usable = max(total_w - (cols - 1) * self.GAP - 4, cols * 44)
        tw = usable // cols
        col, row = idx % cols, idx // cols
        x = 2 + col * (tw + self.GAP)
        y = 2 + row * (self.TILE_H + self.GAP)
        return x, y, tw, self.TILE_H

    def _index_at(self, lx, ly):
        w = max(self.GetWidth(), 248)
        for idx in range(len(GALLERY_KEYS)):
            x, y, tw, th = self._tile_rect(idx, w)
            if x <= lx < x + tw and y <= ly < y + th:
                return idx
        return -1

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w, h = max(self.GetWidth(), 248), max(self.GetHeight(), 60)
            self.DrawSetPen(c4d.COLOR_BG)
            self.DrawRectangle(0, 0, w - 1, h - 1)
            fh = max(self.DrawGetFontHeight(), 10)
            thumb_sz = 38

            for idx, key in enumerate(GALLERY_KEYS):
                tx, ty, tw, th = self._tile_rect(idx, w)
                is_sel = self.enabled and (key == self.selected)
                is_hov = self.enabled and (idx == self._hover_idx)

                bg = _COL_CARD_DISABLED if not self.enabled else (_COL_CARD_HOVER if is_hov else _COL_CARD)
                self.DrawSetPen(bg)
                self._fill_round(tx, ty, tx + tw - 1, ty + th - 1, r=5.0)

                bmp = None
                if key == textures.CUSTOM_TEXTURE and self.custom_path:
                    bmp = _load_custom_bmp(self.custom_path, thumb_sz, thumb_sz)
                if bmp is None:
                    bmp = _preset_thumb(key, 48)

                bx = tx + (tw - thumb_sz) // 2
                by = ty + 4
                if not self.enabled:
                    self.DrawSetOpacity(0.35)
                self._bmp_round(bmp, bx, by, thumb_sz, thumb_sz, r=3.0)
                self.DrawSetOpacity(1.0)

                label = textures.PRESET_LABELS.get(key, key)
                lw = self.DrawGetTextWidth(label)
                lx = tx + max((tw - lw) // 2, 2)
                ly = ty + th - fh - 2
                self.DrawSetTextCol(_COL_ACCENT if is_sel else (_COL_TEXT if self.enabled else _COL_TEXT_DIM), c4d.COLOR_TRANS)
                self.DrawText(label, lx, ly)

                if is_sel:
                    self.DrawSetPen(_COL_ACCENT)
                    self._frame_round(tx, ty, tx + tw - 1, ty + th - 1, r=5.0, width=2.0)
                else:
                    self.DrawSetPen(_COL_BORDER)
                    self._frame_round(tx, ty, tx + tw - 1, ty + th - 1, r=5.0, width=1.0)
        except Exception:
            pass

    def Message(self, msg, result):
        mid = msg.GetId()
        if mid == c4d.BFM_CURSORINFO_REMOVE:
            if self._hover_idx != -1:
                self._hover_idx = -1
                self.Redraw()
        elif mid == c4d.BFM_GETCURSORINFO:
            l2s = self.Local2Screen()
            sx, sy = (l2s["x"], l2s["y"]) if l2s else (0, 0)
            lx = msg[c4d.BFM_DRAG_SCREENX] - sx
            ly = msg[c4d.BFM_DRAG_SCREENY] - sy
            idx = self._index_at(lx, ly)
            if idx != self._hover_idx:
                self._hover_idx = idx
                self.Redraw()
            if 0 <= idx < len(GALLERY_KEYS):
                key = GALLERY_KEYS[idx]
                tip = {
                    "": "Plain Area Light — uniform emission with zero texture file overhead",
                    textures.CUSTOM_TEXTURE: "Custom Image — load an EXR, HDR, PNG, JPG, or TIF gobo/softbox map",
                }.get(key, "%s — procedural HDR light texture" % key)
                result.SetId(c4d.BFM_GETCURSORINFO)
                result.SetString(c4d.RESULT_BUBBLEHELP, tip)
                return True
        return super().Message(msg, result)

    def InputEvent(self, msg):
        if not self.enabled or msg[c4d.BFM_INPUT_DEVICE] != c4d.BFM_INPUT_MOUSE:
            return False
        if msg[c4d.BFM_INPUT_CHANNEL] != c4d.BFM_INPUT_MOUSELEFT:
            return False
        lx, ly = self._local_xy(msg)
        idx = self._index_at(lx, ly)
        if 0 <= idx < len(GALLERY_KEYS):
            key = GALLERY_KEYS[idx]
            self.selected = key
            self.Redraw()
            self.on_select(key)
            return True
        return False
