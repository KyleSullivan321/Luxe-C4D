"""Luxe lights in a C4D scene: create them, store their recipe, place them and push the recipe to the renderer.

Parameter IDs and brightness calibration were verified against Cinema 4D 2027.0.0 (Redshift 2027 and Octane 2.0.3) via
a parameter probe script and rendered sphere tests. Direct IDs are used for fast,
lock-free updates during IPR interactive dragging, with display-name fallbacks for older builds. Octane gobos and light
linking for both renderers were checked in final renders on 2026-11-03; their behaviour in the Live Viewer and IPR is
UNVERIFIED (needs a manual Live Viewer and IPR check).
"""
import math
import os
import re

import c4d

from luxe_core import photometry, placement, textures
from luxe_core.recipe import LightRecipe

from . import ids

_reported = set()
_PARAM_CACHE = {}
_SOLO_SLOT = 10

# Direct verified parameter IDs for Redshift 2027:
_RS_TYPE = 10000
_RS_AREA_GEOM = 11010
_RS_COLOR_MODE = 11002
_RS_EXPOSURE = 11022
_RS_INTENSITY = 11004
_RS_COLOR = 11000
_RS_SIZEX = 11016
_RS_SIZEY = 11017
_RS_SPREAD = 11023
_RS_CAM_VIS = 10042  # Camera ray scale: 1.0 (visible in render) vs 0.0 (invisible)
_RS_WIREFRAME = 10024  # Viewport wireframe
_RS_TEXTURE = 11001
_RS_FILE_PATH = 1000

# Direct verified parameter IDs for Octane 2.0.3:
_OCT_LIGHT_TYPE = 90002
_OCT_AREA_SHAPE = 100015
_OCT_SIZEX = 100010
_OCT_SIZEY = 100011
_OCT_TAG_ENABLE = 1161
_OCT_TAG_VIS_CAM = 1163
_OCT_TAG_EMISSION_TYPE = 1159
_OCT_TAG_POWER = 1151
_OCT_TAG_TEXTURE = 1155
_OCT_TAG_DISTRIBUTION = 1154
_OCT_TAG_NORMALIZE = 1153
_OCT_TAG_SURFACE_BRIGHTNESS = 1166
_OCT_TAG_BARN_DOORS = 1177
_OCT_TAG_PRIMITIVE_TYPE = 1183
_OCT_TAG_SPREAD = 1196
_OCT_IMG_COLOR_SPACE = 1118
_OCT_IMG_FILE = 1100
_OCT_IMG_POWER = 1101
_OCT_IMG_TRANSFORM = 1110
_OCT_IMG_BORDER_U = 1112
_OCT_IMG_BORDER_V = 1122
_OCT_IMG_PROJECTION = 1111
_OCT_TRANSFORM_SX = 1269
_OCT_TRANSFORM_SY = 1270
_OCT_TRANSFORM_SZ = 1271
_OCT_TRANSFORM_TX = 1272
_OCT_TRANSFORM_TY = 1273
_OCT_TRANSFORM_TZ = 1274
_OCT_PROJ_TYPE = 1360
_OCT_PROJ_SPACE = 1361
_OCT_PROJ_TRANS_TYPE = 1367
_OCT_PROJ_SX = 1372
_OCT_PROJ_SY = 1373
_OCT_PROJ_SZ = 1374
_OCT_PROJ_RX = 1369
_OCT_PROJ_RY = 1370
_OCT_PROJ_RZ = 1371
_OCT_PROJ_TX = 1375
_OCT_PROJ_TY = 1376
_OCT_PROJ_TZ = 1377
_OCT_PROJ_OBJECT_LINK = 1387
_OCT_TRANSFORM_LOCK_ASPECT = 1275


_GOBO_PRESETS = {
    "Window 2x2",
    "Window 4x3",
    "Blinds",
    "Dapple",
    "Foliage",
    "Caustic",
    "Ring",
    "Round",
    textures.CUSTOM_TEXTURE,
}



def gobo_scale(spread):
    """Octane gobo size from Spread: the beam's half angle runs from 5 degrees (Spread 0) to 45 (Spread 1)."""
    return math.tan(math.radians(5.0 + 40.0 * min(max(spread, 0.0), 1.0)))


_ASPECT_CACHE = {}


def _image_aspect(path):
    """Width / height of an image file, 1.0 if it cannot be read. Cached by path and modification time."""
    try:
        key = (path, os.path.getmtime(path))
    except (OSError, TypeError):
        return 1.0
    if key not in _ASPECT_CACHE:
        bmp = c4d.bitmaps.BaseBitmap()
        ok = bmp.InitWith(path)[0] == c4d.IMAGERESULT_OK and bmp.GetBh() > 0
        _ASPECT_CACHE[key] = bmp.GetBw() / float(bmp.GetBh()) if ok else 1.0
    return _ASPECT_CACHE[key]


def vec(t):
    return c4d.Vector(*t)


def tup(v):
    return (v.x, v.y, v.z)


# --- finding parameters ---------------------------------------------------------------------------------------

_SKIP_TYPES = {c4d.DTYPE_GROUP, c4d.DTYPE_SEPARATOR, c4d.DTYPE_STATICTEXT, c4d.DTYPE_BUTTON}


def find_param(node, symbols=(), names=()):
    """DescID of a parameter on `node`, by symbol name first, then by display name. None if it has neither."""
    if node is None:
        return None
    cache_key = (node.GetType(), tuple(symbols), tuple(names))
    if cache_key in _PARAM_CACHE:
        return _PARAM_CACHE[cache_key]
    for sym in symbols:
        pid = getattr(c4d, sym, None)
        if isinstance(pid, int):
            did = c4d.DescID(c4d.DescLevel(pid))
            _PARAM_CACHE[cache_key] = did
            return did
    for bc, pid, _group in node.GetDescription(c4d.DESCFLAGS_DESC_NONE):
        if bc[c4d.DESC_NAME] in names and pid[pid.GetDepth() - 1].dtype not in _SKIP_TYPES:
            _PARAM_CACHE[cache_key] = pid
            return pid
    _PARAM_CACHE[cache_key] = None
    return None


def _set_if_diff(node, pid_or_desc, value):
    """Set parameter on `node` only if different to avoid redundant IPR shader/scene invalidation.

    Returns True when the value changed.
    """
    if node is None:
        return False
    try:
        cur = node[pid_or_desc]
        if cur == value:
            return False
    except Exception:
        pass
    try:
        node[pid_or_desc] = value
        return True
    except Exception:
        return False


class _Writer:
    """Sets parameters by logical name, direct ID first, then symbol/display name."""

    def __init__(self, label):
        self.label, self.missing = label, []

    def put_direct(self, node, key, direct_id, value):
        if node is None:
            return None
        did = c4d.DescID(c4d.DescLevel(direct_id))
        try:
            cur = node[did]
            if cur == value:
                return did
        except Exception:
            pass
        try:
            node[did] = value
            return did
        except Exception:
            self.missing.append(key)
            return None

    def put(self, node, key, value, symbols=(), names=()):
        pid = find_param(node, symbols, names) if node is not None else None
        if pid is None:
            self.missing.append(key)
            return None
        _set_if_diff(node, pid, value)
        return pid

    def report(self):
        new = [k for k in self.missing if (self.label, k) not in _reported]
        if new:
            _reported.update((self.label, k) for k in new)
            print("Luxe: %s light is missing %s. Parameter names may differ in this build; please report it."
                  % (self.label, ", ".join(new)))


# --- renderers ------------------------------------------------------------------------------------------------

def detect_sequence(path):
    """Detect if `path` points to a frame of an image sequence or video file."""
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext in (".mp4", ".mov", ".avi", ".m4v"):
        return {"is_movie": True, "is_sequence": True, "count": 0, "start": 0, "end": 0}
    dir_name = os.path.dirname(path)
    base_name = os.path.basename(path)
    m = re.search(r"^(.*?)(?:_|-|\b)?(\d+)(\.[a-zA-Z0-9]+)$", base_name, re.IGNORECASE)
    if not m:
        return None
    prefix, suffix = m.group(1), m.group(3)
    try:
        all_files = os.listdir(dir_name)
    except OSError:
        return None
    pat = re.compile(r"^" + re.escape(prefix) + r"(?:_|-|\b)?(\d+)" + re.escape(suffix) + r"$", re.IGNORECASE)
    frames = []
    for f in all_files:
        fm = pat.match(f)
        if fm:
            frames.append(int(fm.group(1)))
    if len(frames) < 2:
        return None
    frames.sort()

    # Identify whether it's an animated sequence or just a set of numbered still variations
    path_lower = path.lower()
    is_anim = any(k in path_lower for k in ("anim", "sequence", "seq")) or len(frames) >= 24
    if not is_anim:
        return None

    return {
        "is_movie": False,
        "is_sequence": True,
        "count": len(frames),
        "start": frames[0],
        "end": frames[-1],
    }


class Redshift:
    label = "Redshift"
    base_intensity = 100.0  # matches C4D's default RS Area Light intensity (100.0) for cm-scale scenes at 0 EV

    def create(self):
        op = c4d.BaseObject(ids.REDSHIFT_LIGHT)
        if op is None:
            raise RuntimeError("Redshift is not loaded in this Cinema 4D")
        op[_RS_TYPE] = 3  # Physical Area
        op[_RS_AREA_GEOM] = 0  # Rectangle
        return op

    def apply(self, op, recipe, texture, active=True, is_custom=False, doc=None):
        w = _Writer(self.label)
        # 1. Generator enable & Viewport visibility (hides light gizmo from 3D view when disabled)
        _set_if_diff(op, c4d.ID_BASEOBJECT_GENERATOR_FLAG, bool(active))
        vis_editor = c4d.OBJECT_UNDEF if recipe.viewport_visible else c4d.OBJECT_OFF
        _set_if_diff(op, c4d.ID_BASEOBJECT_VISIBILITY_EDITOR, vis_editor)
        w.put_direct(op, "wireframe", _RS_WIREFRAME, 1 if recipe.viewport_visible else 0)

        # 2. Type & Shape & Mode
        w.put_direct(op, "type", _RS_TYPE, 3)  # Physical Area
        w.put_direct(op, "shape", _RS_AREA_GEOM, 0)  # Rectangle
        w.put_direct(op, "color_mode", _RS_COLOR_MODE, 0)  # Color

        # 3. Brightness & Color
        w.put_direct(op, "exposure", _RS_EXPOSURE, recipe.total_exposure())
        w.put_direct(op, "intensity", _RS_INTENSITY, self.base_intensity * recipe.intensity)
        w.put_direct(op, "colour", _RS_COLOR, vec(recipe.colour()))

        # 4. Geometry & Spread
        w.put_direct(op, "width", _RS_SIZEX, recipe.width)
        w.put_direct(op, "height", _RS_SIZEY, recipe.height)
        w.put_direct(op, "spread", _RS_SPREAD, recipe.spread)

        # 5. Seen by Camera (visible to primary camera rays)
        w.put_direct(op, "camera_visible", _RS_CAM_VIS, 1.0 if recipe.camera_visible else 0.0)

        # 6. Texture assignment & Sequence playback
        self._texture(op, texture, w, doc=doc)
        w.report()
        return w.missing

    def _texture(self, op, path, w, doc=None):
        path = path or ""
        did = c4d.DescID(c4d.DescLevel(_RS_TEXTURE), c4d.DescLevel(_RS_FILE_PATH))
        assigned = False
        try:
            cur = op[did]
            if cur != path:
                op[did] = path
            assigned = True
        except Exception:
            pass
        if not assigned:
            # Fallback to symbol search
            pid = find_param(op, ["REDSHIFT_LIGHT_PHYSICAL_TEXTURE"], ["Texture"])
            if pid is None:
                w.missing.append("texture")
            elif pid[pid.GetDepth() - 1].dtype == c4d.DTYPE_FILENAME:
                _set_if_diff(op, pid, path)
            else:
                try:
                    op[pid[0].id, _RS_FILE_PATH] = path
                except (TypeError, AttributeError):
                    w.missing.append("texture (type %s)" % pid[pid.GetDepth() - 1].dtype)

        # Detect animated image sequence or movie
        seq = detect_sequence(path)
        if seq:
            fps = int(doc.GetFps()) if doc is not None else 30
            try:
                op[c4d.DescID(c4d.DescLevel(_RS_TEXTURE), c4d.DescLevel(1001))] = 2  # Loop mode
                op[c4d.DescID(c4d.DescLevel(_RS_TEXTURE), c4d.DescLevel(1002))] = 0  # Frame timing
                op[c4d.DescID(c4d.DescLevel(_RS_TEXTURE), c4d.DescLevel(1003))] = seq["start"]
                op[c4d.DescID(c4d.DescLevel(_RS_TEXTURE), c4d.DescLevel(1004))] = seq["end"]
                op[c4d.DescID(c4d.DescLevel(_RS_TEXTURE), c4d.DescLevel(1005))] = fps
            except Exception:
                pass
        else:
            try:
                op[c4d.DescID(c4d.DescLevel(_RS_TEXTURE), c4d.DescLevel(1001))] = 0  # Mode: Off
            except Exception:
                pass


class Octane:
    label = "Octane"
    base_power = 65.0  # calibrated against Redshift (base_intensity 100.0) on a diffuse sphere at 0 EV
    # A gobo puts all its power through a 1.5-7.5 cm aperture into one beam. 120 was 5.6 stops brighter than a plain
    # 40 x 30 cm light at the same EV and distance (test renders, 2026-11-03); this matches the gobo's open areas.
    gobo_power = 2.5

    def create(self):
        op = c4d.BaseObject(c4d.Olight)
        _set_if_diff(op, _OCT_LIGHT_TYPE, c4d.LIGHT_TYPE_AREA)
        _set_if_diff(op, _OCT_AREA_SHAPE, c4d.LIGHT_AREADETAILS_SHAPE_RECTANGLE)
        _set_if_diff(op, c4d.DescID(c4d.DescLevel(90046)), 1)
        if op.MakeTag(ids.OCTANE_LIGHT_TAG) is None:
            raise RuntimeError("Octane is not loaded in this Cinema 4D")
        return op

    def apply(self, op, recipe, texture, active=True, is_custom=False, doc=None):
        w = _Writer(self.label)
        _set_if_diff(op, c4d.ID_BASEOBJECT_GENERATOR_FLAG, bool(active))
        vis_editor = c4d.OBJECT_UNDEF if recipe.viewport_visible else c4d.OBJECT_OFF
        _set_if_diff(op, c4d.ID_BASEOBJECT_VISIBILITY_EDITOR, vis_editor)
        _set_if_diff(op, _OCT_LIGHT_TYPE, c4d.LIGHT_TYPE_AREA)
        _set_if_diff(op, _OCT_AREA_SHAPE, c4d.LIGHT_AREADETAILS_SHAPE_RECTANGLE)
        _set_if_diff(op, c4d.DescID(c4d.DescLevel(90046)), 1)

        is_gobo = bool(texture) and (recipe.texture in _GOBO_PRESETS or is_custom)
        if is_gobo:
            # Physical projector aperture for crisp, defined gobo casting in Octane's path tracer.
            # Range: 1.5 cm (pinhole, sharp ellipsoidal) to 7.5 cm (softly feathered).
            # Clamping to this range ensures the gobo NEVER blows up to 50-100 cm and
            # loses contrast/washes out, even if the user resets or maxes Softness.
            s = min(max(recipe.softness, 0.0), 1.0)
            aperture = 1.5 + 6.0 * s
            aspect = max(recipe.width, 1.0) / max(recipe.height, 1.0)
            if aspect >= 1.0:
                w_eff = aperture * aspect
                h_eff = aperture
            else:
                w_eff = aperture
                h_eff = aperture / aspect
            _set_if_diff(op, _OCT_SIZEX, w_eff)
            _set_if_diff(op, _OCT_SIZEY, h_eff)
        else:
            _set_if_diff(op, _OCT_SIZEX, recipe.width)
            _set_if_diff(op, _OCT_SIZEY, recipe.height)

        tag = op.GetTag(ids.OCTANE_LIGHT_TAG)
        if tag is not None:
            base = self.gobo_power if is_gobo else self.base_power
            power = base * recipe.intensity * 2.0 ** recipe.total_exposure()
            changed = False
            for pid, value in ((_OCT_TAG_SURFACE_BRIGHTNESS, 0 if is_gobo else 1),  # off: full power via the aperture
                               (_OCT_TAG_ENABLE, 1 if active else 0),
                               (_OCT_TAG_VIS_CAM, 1 if recipe.camera_visible else 0),
                               (_OCT_TAG_EMISSION_TYPE, 1),  # Texture emission
                               (_OCT_TAG_NORMALIZE, 1),
                               (_OCT_TAG_PRIMITIVE_TYPE, 1),  # Fast primitives
                               (_OCT_TAG_BARN_DOORS, 0),  # No clipping
                               (_OCT_TAG_POWER, power),
                               (_OCT_TAG_SPREAD, recipe.spread)):
                changed |= _set_if_diff(tag, pid, value)
            links = (tag[_OCT_TAG_TEXTURE], tag[_OCT_TAG_DISTRIBUTION])

            if is_gobo:
                # 1. Texture slot = clean tinted emitter (bulb)
                sh_tex = self._color(tag, _OCT_TAG_TEXTURE, recipe.colour())
                if sh_tex is None:
                    w.missing.append("texture")
                # 2. Distribution slot = gobo stencil with perspective projection & transform scaling
                sh_dist = self._distribution(tag, _OCT_TAG_DISTRIBUTION, texture, recipe.spread, is_custom, doc=doc)
                if sh_dist is None:
                    w.missing.append("distribution")
            elif texture:
                # Diffuse modifier (softbox/strip) mapped to emitter quad, seen in reflections
                sh_tex = self._image(tag, _OCT_TAG_TEXTURE, texture, recipe.colour(), is_custom, doc=doc)
                if sh_tex is None:
                    w.missing.append("texture")
                changed |= _set_if_diff(tag, _OCT_TAG_DISTRIBUTION, None)
            else:
                sh = self._color(tag, _OCT_TAG_TEXTURE, recipe.colour())
                if sh is None:
                    w.missing.append("color")
                changed |= _set_if_diff(tag, _OCT_TAG_DISTRIBUTION, None)

            # Only on a real change: in Octane's IPR each MSG_CHANGE rebuilds the light (a CUDA 700 crash on
            # 2026-11-06 came after ~10 rebuilds a second while a new light was dragged)
            if changed or links != (tag[_OCT_TAG_TEXTURE], tag[_OCT_TAG_DISTRIBUTION]):
                tag.Message(c4d.MSG_CHANGE)
        else:
            w.missing.append("octane_tag")
        w.report()
        return w.missing

    def _distribution(self, tag, link_id, path, spread=1.0, is_custom=False, doc=None):
        """The gobo: an ImageTexture in the tag's Distribution slot, projected from the light like a slide.

        Checked in final Octane renders of a test chart on a wall (C4D 2027, 2026-11-03): a Perspective projection
        in Object Space gives a sharp, undistorted slide; Normal Space and an object link do not. On its own the
        slide lands upside down (projection R.Z, in degrees, turns it) and square (the UV transform locks its aspect).
        The UV transform's scale is tan(half the beam angle), so 1.0 is a 90-degree beam. Shaders get MSG_CHANGE only
        when a value changed, so an exposure or colour drag does not make the IPR rebuild the gobo.
        """
        changed = False
        shader = tag[link_id]
        if shader is None or shader.GetType() != ids.OCTANE_IMAGE_TEXTURE:
            shader = c4d.BaseShader(ids.OCTANE_IMAGE_TEXTURE)
            if shader is None:
                return None
            tag.InsertShader(shader)
            tag[link_id] = shader
            changed = True
        is_linear = (not is_custom) or path.lower().endswith((".exr", ".hdr"))
        cs_val = getattr(c4d, "IMAGETEX_CS_LINEAR_SRGB", 2) if is_linear else getattr(c4d, "IMAGETEX_CS_SRGB", 1)
        changed |= _set_if_diff(shader, _OCT_IMG_COLOR_SPACE, cs_val)
        changed |= _set_if_diff(shader, _OCT_IMG_BORDER_U, 1)  # black outside the slide, so it never tiles
        changed |= _set_if_diff(shader, _OCT_IMG_BORDER_V, 1)
        changed |= _set_if_diff(shader, _OCT_IMG_FILE, path or "")

        proj = shader[_OCT_IMG_PROJECTION]
        if proj is None or proj.GetType() != ids.OCTANE_PROJECTION:
            proj = c4d.BaseShader(ids.OCTANE_PROJECTION)
            if proj is not None:
                shader.InsertShader(proj)
                shader[_OCT_IMG_PROJECTION] = proj
                changed = True
        if proj is not None:
            proj_changed = _set_if_diff(proj, _OCT_PROJ_OBJECT_LINK, None)
            for pid, value in ((_OCT_PROJ_TYPE, 3), (_OCT_PROJ_SPACE, 1), (_OCT_PROJ_TRANS_TYPE, 4),  # Perspective,
                               (_OCT_PROJ_SX, 1.0), (_OCT_PROJ_SY, 1.0), (_OCT_PROJ_SZ, 1.0),       # Object Space,
                               (_OCT_PROJ_RX, 0.0), (_OCT_PROJ_RY, 0.0), (_OCT_PROJ_RZ, 180.0),     # values
                               (_OCT_PROJ_TX, 0.0), (_OCT_PROJ_TY, 0.0), (_OCT_PROJ_TZ, 0.0)):
                proj_changed |= _set_if_diff(proj, pid, value)
            if proj_changed:
                proj.Message(c4d.MSG_CHANGE)
                changed = True

        trans = shader[_OCT_IMG_TRANSFORM]
        if trans is None or trans.GetType() != ids.OCTANE_TRANSFORM:
            trans = c4d.BaseShader(ids.OCTANE_TRANSFORM)
            if trans is not None:
                shader.InsertShader(trans)
                shader[_OCT_IMG_TRANSFORM] = trans
                changed = True
        if trans is not None:
            scale = gobo_scale(spread)
            aspect = _image_aspect(path)
            trans_changed = False
            for pid, value in ((_OCT_TRANSFORM_LOCK_ASPECT, 0), (_OCT_TRANSFORM_SX, scale * aspect),
                               (_OCT_TRANSFORM_SY, scale), (_OCT_TRANSFORM_SZ, scale),
                               (_OCT_TRANSFORM_TX, 0.0), (_OCT_TRANSFORM_TY, 0.0), (_OCT_TRANSFORM_TZ, 0.0)):
                trans_changed |= _set_if_diff(trans, pid, value)
            if trans_changed:
                trans.Message(c4d.MSG_CHANGE)
                changed = True

        # Animation handling
        seq = detect_sequence(path)
        if seq:
            fps = float(doc.GetFps()) if doc is not None else 30.0
            for pid, value in ((2005, 2), (2000, seq["start"]), (2001, seq["end"]), (2002, fps)):  # Mode: Loop
                changed |= _set_if_diff(shader, pid, value)
        else:
            for pid, value in ((2005, 0), (2000, 0), (2001, 0)):
                changed |= _set_if_diff(shader, pid, value)

        if changed:
            shader.Message(c4d.MSG_CHANGE)
        return shader

    def _color(self, tag, link_id, colour):
        shader = tag[link_id]
        if shader is None or shader.GetType() != ids.OCTANE_RGB_SPECTRUM:
            shader = c4d.BaseShader(ids.OCTANE_RGB_SPECTRUM)
            if shader is None:
                return None
            tag.InsertShader(shader)
            tag[link_id] = shader
        if _set_if_diff(shader, 1200, vec(photometry.linear_to_srgb(colour))):
            shader.Message(c4d.MSG_CHANGE)
        return shader

    def _image(self, tag, link_id, path, colour=(1.0, 1.0, 1.0), is_custom=False, doc=None):
        shader = tag[link_id]
        if shader is None or shader.GetType() != ids.OCTANE_IMAGE_TEXTURE:
            shader = c4d.BaseShader(ids.OCTANE_IMAGE_TEXTURE)
            if shader is None:
                return None
            tag.InsertShader(shader)
            tag[link_id] = shader
            changed = True
        else:
            changed = False
        is_linear = (not is_custom) or path.lower().endswith((".exr", ".hdr"))
        cs_val = getattr(c4d, "IMAGETEX_CS_LINEAR_SRGB", 2) if is_linear else getattr(c4d, "IMAGETEX_CS_SRGB", 1)
        changed |= _set_if_diff(shader, _OCT_IMG_COLOR_SPACE, cs_val)

        changed |= _set_if_diff(shader, _OCT_IMG_BORDER_U, 0)
        changed |= _set_if_diff(shader, _OCT_IMG_BORDER_V, 0)
        if shader[_OCT_IMG_PROJECTION] is not None:
            shader[_OCT_IMG_PROJECTION] = None
            changed = True

        needs_tint = any(abs(c - 1.0) > 1e-4 for c in colour)
        if needs_tint:
            rgb_sh = shader[_OCT_IMG_POWER]
            if rgb_sh is None or rgb_sh.GetType() != ids.OCTANE_RGB_SPECTRUM:
                rgb_sh = c4d.BaseShader(ids.OCTANE_RGB_SPECTRUM)
                if rgb_sh is not None:
                    shader.InsertShader(rgb_sh)
                    shader[_OCT_IMG_POWER] = rgb_sh
                    changed = True
            if rgb_sh is not None and _set_if_diff(rgb_sh, 1200, vec(photometry.linear_to_srgb(colour))):
                rgb_sh.Message(c4d.MSG_CHANGE)
        else:
            if shader[_OCT_IMG_POWER] is not None:
                shader[_OCT_IMG_POWER] = None
                changed = True

        changed |= _set_if_diff(shader, _OCT_IMG_FILE, path or "")

        # Animation & sequence handling in Octane
        seq = detect_sequence(path)
        if seq:
            fps = float(doc.GetFps()) if doc is not None else 30.0
            for pid, value in ((2005, 2), (2000, seq["start"]), (2001, seq["end"]), (2002, fps)):  # Mode: Loop
                changed |= _set_if_diff(shader, pid, value)
        else:
            for pid, value in ((2005, 0), (2000, 0), (2001, 0)):
                changed |= _set_if_diff(shader, pid, value)

        # Only on a real change: during an IPR every MSG_CHANGE makes Octane rebuild the light and its texture
        if changed:
            shader.Message(c4d.MSG_CHANGE)
        return shader


RENDERERS = {"redshift": Redshift(), "octane": Octane()}

# Verified in Cinema 4D 2027: both Redshift and Octane area lights emit along their local +Z axis.
FORWARD_SIGN = {"redshift": 1.0, "octane": 1.0}


def default_renderer(doc):
    engine = doc.GetActiveRenderData()[c4d.RDATA_RENDERENGINE]
    return "octane" if engine == ids.OCTANE_ENGINE else "redshift"


# --- storage on the light & solo state on the document --------------------------------------------------------

def luxe_data(node):
    """Luxe's container on `node` (a light, the document or a tag), or None. Falls back to the slot Luxe used before
    its permanent plugin ID, so older scenes still load; _set_luxe_data moves it."""
    if node is None:
        return None
    data = node.GetDataInstance()
    bc = data.GetContainerInstance(ids.DATA_ID)
    return bc if bc is not None else data.GetContainerInstance(ids.LEGACY_DATA_ID)


def _set_luxe_data(node, bc):
    data = node.GetDataInstance()
    data.SetContainer(ids.DATA_ID, bc)
    if data.GetContainerInstance(ids.LEGACY_DATA_ID) is not None:
        data.RemoveData(ids.LEGACY_DATA_ID)


def read_recipe(op):
    bc = luxe_data(op)
    return LightRecipe.from_json(bc.GetString(1)) if bc is not None and bc.GetString(1) else None


def _texture_path(op):
    bc = luxe_data(op)
    return bc.GetString(2) if bc is not None else ""


def write_recipe(op, recipe, texture=None):
    old = luxe_data(op)
    bc = c4d.BaseContainer()
    bc.SetString(1, recipe.to_json())
    bc.SetString(2, _texture_path(op) if texture is None else texture)
    if old is not None and old.GetInt32(_PASS_SLOT):
        bc.SetInt32(_PASS_SLOT, old.GetInt32(_PASS_SLOT))
    _set_luxe_data(op, bc)


def luxe_light(op):
    return op if read_recipe(op) is not None else None


def walk(op):
    """op, its siblings and all their children, depth first."""
    while op is not None:
        yield op
        yield from walk(op.GetDown())
        op = op.GetNext()


def all_luxe_lights(doc):
    return [op for op in walk(doc.GetFirstObject()) if luxe_light(op)]


def solo_light(doc):
    """Return the currently soloed Luxe light in `doc`, or None."""
    if doc is None:
        return None
    bc = luxe_data(doc)
    guid = bc.GetString(_SOLO_SLOT) if bc is not None else ""
    if not guid:
        return None
    for op in all_luxe_lights(doc):
        if str(op.GetGUID()) == guid:
            return op
    bc.SetString(_SOLO_SLOT, "")
    return None


def effective_enabled(doc, op, recipe=None):
    r = recipe if recipe is not None else read_recipe(op)
    if r is None:
        return True
    solo = solo_light(doc)
    return bool(r.enabled) and (solo is None or solo == op)


def set_solo(doc, target=None, undo=True):
    """Solo `target` (or clear solo when `target` is None) and refresh every Luxe light's active state."""
    old = luxe_data(doc)
    bc = old.GetClone(c4d.COPYFLAGS_NONE) if old is not None else c4d.BaseContainer()
    bc.SetString(_SOLO_SLOT, str(target.GetGUID()) if target is not None else "")
    _set_luxe_data(doc, bc)
    for op in all_luxe_lights(doc):
        r = read_recipe(op)
        if r is None:
            continue
        if undo:
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, op)
        active = bool(r.enabled) and (target is None or target == op)
        _set_if_diff(op, c4d.ID_BASEOBJECT_GENERATOR_FLAG, active)
        if r.renderer == "octane":
            tag = op.GetTag(ids.OCTANE_LIGHT_TAG)
            if tag is not None:
                _set_if_diff(tag, _OCT_TAG_ENABLE, 1 if active else 0)


# --- light linking ----------------------------------------------------------------------------------------------
# The list Luxe edits is the light's own Project list, so the Attribute Manager and Luxe always show the same links.
# Redshift renders from that list (verified in final renders, 2026-11-03). Octane ignores it, and its light tag's own
# list, even with "C4D Light Linking" ticked in its render settings (same tests). It does honour light pass IDs with
# Octane Object tags, so for Octane lights Luxe mirrors the list into those: see sync_octane_links.

LINK_INCLUDE, LINK_EXCLUDE = 0, 1  # the value of REDSHIFT_LIGHT_EXCLUSION_MODE and LIGHT_EXCLUSION_MODE
_RS_LINK_MODE, _RS_LINK_LIST = 10021, 10022
_C4D_LINK_MODE, _C4D_LINK_LIST = 100001, 100000  # a C4D light's Project tab

_OCT_TAG_PASS_ID = 1165  # LIGHTTAG_LIGHT_PASSID, 1-20
_OCT_OBJECT_TAG = 1029603
_OBJ_USE_MASK, _OBJ_MASK_ON = 1326, 1327  # OBJECTTAG_USE_LGHT_MASK, OBJECTTAG_LGHT_MASK_ENABLE
_OBJ_LIGHT_ID = dict(zip(range(1, 21), list(range(1331, 1339)) + list(range(1345, 1357))))  # OBJECTTAG_LIGHTID_n
_PASS_SLOT = 3  # in a Luxe light's container: the pass ID Luxe gave it
_TAG_MARK = 1  # in an Octane Object tag's DATA_ID container: 1 = Luxe made it, 2 = Luxe turned on its mask


def _link_node(op, renderer):
    """(node, mode ID, list ID) that hold `op`'s light links."""
    if renderer == "octane":
        return op, _C4D_LINK_MODE, _C4D_LINK_LIST
    return op, _RS_LINK_MODE, _RS_LINK_LIST


def _is_light(op):
    return op.GetType() in (c4d.Olight, ids.REDSHIFT_LIGHT) or op.GetTag(ids.OCTANE_LIGHT_TAG) is not None


def _renders_geometry(op):
    """Objects an Octane Object tag should go on: meshes and generators, not nulls, lights, cameras or inputs.

    Generators carry BIT_CONTROLOBJECT themselves (see pick.py), so the bit only rules out plain meshes.
    """
    if _is_light(op) or op.GetType() in (c4d.Onull, c4d.Ocamera):
        return False
    if op.GetCache() is not None or op.GetDeformCache() is not None:
        return True
    return op.IsInstanceOf(c4d.Opolygon) and not op.GetBit(c4d.BIT_CONTROLOBJECT)


def sync_octane_links(doc):
    """Mirror every Octane Luxe light's link list into light pass IDs and Octane Object tags (inside an open undo).

    Each linked light gets its own pass ID from 2 to 20, avoiding IDs other lights use. Each mesh or generator the
    light must skip gets that ID unticked in its Octane Object tag: the listed objects in Exclude mode, every other
    one in Include mode. A listed object's children follow it. Tags Luxe added go again when nothing needs them; on
    a tag that was already there, Luxe touches only its own IDs and the mask switch. Include mode covers the objects
    in the scene now: objects added later stay lit until the list changes again.
    """
    objs = list(walk(doc.GetFirstObject()))
    used, linked, luxe_octane = {1}, [], []
    for op in objs:
        tag = op.GetTag(ids.OCTANE_LIGHT_TAG)
        r = read_recipe(op)
        if r is not None and r.renderer == "octane" and tag is not None:
            luxe_octane.append((op, tag))
        elif tag is not None:
            used.add(tag[_OCT_TAG_PASS_ID])
    for op, tag in luxe_octane:
        bc = luxe_data(op)
        mode, data = get_linking(op)
        listed = set()  # GUIDs
        for i in range(data.GetObjectCount()):
            obj = data.ObjectFromIndex(doc, i)
            if obj is not None:
                listed.update(o.GetGUID() for o in walk_one(obj))
        if mode == LINK_EXCLUDE and not listed:
            if bc is not None and bc.GetInt32(_PASS_SLOT):  # unlinked: give back the ID Luxe set
                doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, tag)
                tag[_OCT_TAG_PASS_ID] = 1
                bc.SetInt32(_PASS_SLOT, 0)
            continue
        pid = bc.GetInt32(_PASS_SLOT) if bc is not None else 0
        if not 2 <= pid <= 20 or pid in used:
            pid = next((n for n in range(2, 21) if n not in used), 0)
        if not pid:
            print("Luxe: no free Octane light pass ID for %s (20 at most); its links are not applied" % op.GetName())
            continue
        used.add(pid)
        if tag[_OCT_TAG_PASS_ID] != pid:
            doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, tag)
            tag[_OCT_TAG_PASS_ID] = pid
        if bc is not None:
            bc.SetInt32(_PASS_SLOT, pid)
        linked.append((pid, mode, listed))
    managed = {pid for pid, _m, _l in linked}
    stale = set(range(2, 21)) - used  # IDs no light uses any more
    for obj in objs:
        if not _renders_geometry(obj):
            continue
        guid = obj.GetGUID()
        off = {pid for pid, mode, listed in linked if (guid in listed) == (mode == LINK_EXCLUDE)}
        _set_object_mask(doc, obj, off, managed | stale)


def walk_one(op):
    """op and everything under it."""
    yield op
    yield from walk(op.GetDown())


def _set_object_mask(doc, obj, off, ids_to_set):
    tag = obj.GetTag(_OCT_OBJECT_TAG)
    mark = luxe_data(tag)
    flag = mark.GetInt32(_TAG_MARK) if mark is not None else 0
    if not off:
        if tag is None or not flag:
            if tag is not None:  # a tag Luxe never switched on: only reset IDs Luxe owns
                for n in ids_to_set:
                    if not tag[_OBJ_LIGHT_ID[n]]:
                        doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, tag)
                        tag[_OBJ_LIGHT_ID[n]] = 1
            return
        if flag == 1:
            doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, tag)
            tag.Remove()
            return
        doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, tag)
        for n in ids_to_set:
            tag[_OBJ_LIGHT_ID[n]] = 1
        tag[_OBJ_USE_MASK] = mark.GetInt32(_TAG_MARK + 1) or 1328  # its mask setting from before Luxe
        mark.SetInt32(_TAG_MARK, 0)
        return
    if tag is None:
        tag = obj.MakeTag(_OCT_OBJECT_TAG)
        if tag is None:
            return
        tag.SetName("Luxe Light Links")
        doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, tag)
        bc = c4d.BaseContainer()
        bc.SetInt32(_TAG_MARK, 1)
        _set_luxe_data(tag, bc)
    else:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, tag)
        if not flag:
            bc = c4d.BaseContainer()
            bc.SetInt32(_TAG_MARK, 2)
            bc.SetInt32(_TAG_MARK + 1, tag[_OBJ_USE_MASK])
            _set_luxe_data(tag, bc)
    tag[_OBJ_USE_MASK] = _OBJ_MASK_ON
    for n in ids_to_set:
        tag[_OBJ_LIGHT_ID[n]] = 0 if n in off else 1
    tag.Message(c4d.MSG_CHANGE)


def link_description(op, recipe=None):
    """The description container of `op`'s native link list: it sets up the same list GUI and icons in the panel."""
    r = recipe or read_recipe(op)
    node, _mid, lid = _link_node(op, r.renderer) if r is not None else (None, 0, 0)
    if node is None:
        return None
    for bc, pid, _group in node.GetDescription(c4d.DESCFLAGS_DESC_NONE):
        if pid[0].id == lid:
            return bc
    return None


def get_linking(op, recipe=None):
    """(mode, InExcludeData) for a Luxe light. Exclude with an empty list, the default, lights everything."""
    r = recipe or read_recipe(op)
    node, mid, lid = _link_node(op, r.renderer) if r is not None else (None, 0, 0)
    if node is None:
        return LINK_EXCLUDE, c4d.InExcludeData()
    try:
        mode, data = node[mid], node[lid]
    except (AttributeError, TypeError):
        return LINK_EXCLUDE, c4d.InExcludeData()
    return (LINK_INCLUDE if mode == LINK_INCLUDE else LINK_EXCLUDE), (data or c4d.InExcludeData())


def set_linking(op, mode=None, data=None, recipe=None):
    """Write the link mode and/or list (inside an open undo). Returns False when the light has nowhere to keep them."""
    r = recipe or read_recipe(op)
    node, mid, lid = _link_node(op, r.renderer) if r is not None else (None, 0, 0)
    if node is None:
        return False
    if data is not None:
        node[lid] = _with_flags(op, r, data)
    if mode is not None:
        node[mid] = mode
    node.Message(c4d.MSG_CHANGE)
    if r.renderer == "octane" and op.GetDocument() is not None:
        sync_octane_links(op.GetDocument())
    return True


def _link_flags(op, recipe):
    """The icon flags a newly linked object gets: the list's own default (light on, as when dragged in by hand)."""
    bc = link_description(op, recipe)
    key = getattr(c4d, "IN_EXCLUDE_FLAG_INIT_STATE", None)
    flags = bc.GetInt32(key) if bc is not None and key is not None else 0
    return flags or 1


def _with_flags(op, recipe, data):
    """`data` with every entry's icons set. The panel's list hands back new entries with no icons on, and C4D's
    viewport then ignores them, so an excluded object stays lit there and an included one goes dark."""
    doc = op.GetDocument()
    if doc is None or not hasattr(data, "GetFlags"):
        return data
    init = _link_flags(op, recipe)
    out = c4d.InExcludeData()
    for i in range(data.GetObjectCount()):
        obj = data.ObjectFromIndex(doc, i)
        if obj is not None:
            out.InsertObject(obj, data.GetFlags(i) or init)
    return out


def toggle_link(doc, op, target, recipe=None):
    """Add `target` to the light's list, or take it out if it is there (inside an open undo).

    Returns True when `target` is now in the list, False when it was removed, None when nothing changed.
    """
    r = recipe or read_recipe(op)
    if r is None or target is None or target == op:
        return None
    _mode, data = get_linking(op, r)
    index = data.GetObjectIndex(doc, target)
    if index >= 0:
        data.DeleteObject(index)  # takes the index in Python, not the object
        now_in = False
    else:
        data.InsertObject(target, _link_flags(op, r))
        now_in = True
    return now_in if set_linking(op, data=data, recipe=r) else None


def linked_objects(doc, op, recipe=None):
    """The objects in the light's list, in order (deleted objects are skipped)."""
    _mode, data = get_linking(op, recipe)
    objs = (data.ObjectFromIndex(doc, i) for i in range(data.GetObjectCount()))
    return [o for o in objs if o is not None]


# --- the operations the tool and panel use ----------------------------------------------------------------------

def create(doc, recipe):
    """Insert a new light for `recipe` (inside an open undo) and select it."""
    op = RENDERERS[recipe.renderer].create()
    op.SetName(recipe.name)
    doc.InsertObject(op)
    doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, op)
    doc.SetActiveObject(op, c4d.SELECTION_NEW)
    write_recipe(op, recipe, "")
    if solo_light(doc) is not None:
        set_solo(doc, op, undo=True)
    return op


def duplicate(doc, op):
    """Duplicate a Luxe light (inside an open undo), select the copy, and give it its own baked texture."""
    recipe = read_recipe(op)
    if recipe is None:
        return None
    clone = op.GetClone(c4d.COPYFLAGS_NONE)
    recipe.name = "%s Copy" % op.GetName()
    clone.SetName(recipe.name)
    doc.InsertObject(clone, pred=op)
    doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, clone)
    doc.SetActiveObject(clone, c4d.SELECTION_NEW)
    write_recipe(clone, recipe, "")
    if solo_light(doc) is not None:
        set_solo(doc, clone, undo=True)
    apply(doc, clone, recipe, bake=True)
    if recipe.renderer == "octane":
        sync_octane_links(doc)  # the copy keeps the links and needs its own pass ID
    return clone


def place(op, recipe, hit=None):
    """Move the light. With a hit, it becomes the new anchor; without, the light re-places from its anchor."""
    if hit is not None:
        h, n, d = list(tup(hit.point)), list(tup(hit.normal)), list(tup(hit.ray))
        orbit_dir = list(placement.light_direction("reflect", n, d))
        recipe.anchor = {"hit": h, "normal": n, "ray_dir": d, "orbit_dir": orbit_dir}
    a = recipe.anchor
    if not a:
        return
    orbit_dir = a.get("orbit_dir")
    if recipe.mode == "orbit" and not orbit_dir:
        orbit_dir = list(placement.light_direction("reflect", a["normal"], a["ray_dir"]))
        a["orbit_dir"] = orbit_dir
    position, forward = placement.place(
        recipe.mode, a["hit"], a["normal"], a["ray_dir"], recipe.distance, orbit_dir=orbit_dir
    )
    forward = tuple(c * FORWARD_SIGN[recipe.renderer] for c in forward)
    off, x, y, z = placement.look_at(position, forward, roll_deg=recipe.rotation)
    op.SetMg(c4d.Matrix(vec(off), vec(x), vec(y), vec(z)))


def texture_dir(doc):
    folder = doc.GetDocumentPath()
    path = os.path.join(folder, "tex", "luxe") if folder else os.path.join(
        c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS), "luxe_textures")
    os.makedirs(path, exist_ok=True)
    return path


def _is_our_texture(doc, path):
    """Only files Luxe baked, in its own folder, are ever deleted."""
    return (bool(path) and os.path.isfile(path) and os.path.basename(path).startswith("luxe_")
            and os.path.dirname(os.path.abspath(path)) == os.path.abspath(texture_dir(doc)))


def _safe_remove(doc, path):
    """Safely remove a Luxe-baked texture without throwing if Redshift IPR is accessing it."""
    if _is_our_texture(doc, path):
        try:
            os.remove(path)
        except OSError:
            pass


def _safe_bake(layers, target_path, width, height, colour, res):
    """Atomically bake and replace to avoid file read collisions while Redshift IPR is rendering."""
    tmp_path = target_path + ".tmp"
    textures.bake(layers, tmp_path, width, height, colour, res)
    try:
        if os.path.isfile(target_path):
            os.replace(tmp_path, target_path)
        else:
            os.rename(tmp_path, target_path)
    except OSError:
        pass


def apply(doc, op, recipe, bake=True):
    """Push the recipe to the renderer; return the parameters it could not set.

    Procedural presets are baked as neutral (1, 1, 1) EXRs; color/kelvin/tint modulates
    dynamically on the light so dragging temperature/exposure never stalls on disk I/O.
    bake=False skips re-baking textures during interactive slider dragging.
    """
    texture = _texture_path(op)
    is_custom = recipe.texture == textures.CUSTOM_TEXTURE
    if is_custom:
        custom = (recipe.custom_texture or "").strip()
        if custom and os.path.isfile(custom):
            _safe_remove(doc, texture)
            texture = custom
        else:
            is_custom = False
            if _is_our_texture(doc, texture):
                _safe_remove(doc, texture)
            texture = ""
    elif recipe.texture in textures.PRESETS:
        slug = "".join(c if c.isalnum() else "_" for c in recipe.texture.lower())
        soft_int = int(round(recipe.softness * 100))
        new = os.path.join(texture_dir(doc), "luxe_%08x_%s_%d.exr" % (op.GetGUID() & 0xFFFFFFFF, slug, soft_int))
        if bake or not os.path.isfile(new):
            base_layers = textures.PRESETS[recipe.texture]
            layers = textures.scale_softness(base_layers, recipe.softness)
            _safe_bake(layers, new, recipe.width, recipe.height, (1.0, 1.0, 1.0), 512)
        if texture != new:
            _safe_remove(doc, texture)
        texture = new
    else:
        # Plain Area Light
        if _is_our_texture(doc, texture):
            _safe_remove(doc, texture)
        texture = ""

    active = effective_enabled(doc, op, recipe)
    missing = RENDERERS[recipe.renderer].apply(op, recipe, texture, active=active, is_custom=is_custom, doc=doc)
    write_recipe(op, recipe, texture)
    return missing
