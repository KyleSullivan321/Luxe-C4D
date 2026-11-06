"""Luxe Light Tool: click a surface to place a light, drag to slide its highlight or orbit around the spot.

- Click: moves the selected Luxe light so it lights the clicked spot in the chosen mode.
- Shift+click, or click with no Luxe light selected: makes a new light sized to the object.
- Drag: glides across the surface (or circles the locked target spot in Orbit mode).
- Ctrl+drag left and right: moves the light closer or further (compensating EV if Constant Illumination is on).
- L: puts the object under the cursor in the selected light's include/exclude list, or takes it out.
"""
import math

import c4d

from luxe_core import placement, textures
from luxe_core.recipe import LightRecipe

from . import lights
from .panel import MODE_LABELS, ToolDialog
from .pick import Picker

_PRESET_CYCLE = [""] + list(textures.PRESETS.keys())
_KELVIN_STEPS = [3200.0, 4500.0, 5600.0, 6500.0, 8000.0]

REDRAW = c4d.DRAWFLAGS_ONLY_ACTIVE_VIEW | c4d.DRAWFLAGS_NO_THREAD | c4d.DRAWFLAGS_NO_ANIMATION
# Set True to print which keys and mouse events reach the tool (for debugging input handling).
LOG_INPUT = False


class LuxeTool(c4d.plugins.ToolData):
    def __init__(self):
        super().__init__()
        self.mode = "reflect"
        self.renderer = "match"
        self.picker = Picker()
        self.hover = None
        self.active_recipe = None
        self.active_light = None

    def GetState(self, doc):
        return c4d.CMD_ENABLED

    def AllocSubDialog(self, bc):
        return ToolDialog(self)

    def FreeTool(self, doc, data):
        self.hover = None
        self.picker.clear()

    def GetCursorInfo(self, doc, data, bd, x, y, bc):
        if bc.GetId() == c4d.BFM_CURSORINFO_REMOVE:
            self.hover = None
        else:
            self.hover = self.picker.hit(doc, bd, x, y)
            bc.SetString(c4d.RESULT_BUBBLEHELP, MODE_LABELS.get(self.mode, self.mode))
        c4d.DrawViews(REDRAW)
        return True

    def Draw(self, doc, data, bd, bh, bt, flags):
        bd.SetMatrix_Matrix(None, c4d.Matrix())
        active = lights.luxe_light(doc.GetActiveObject()) if doc is not None else None
        r = None
        if active is not None:
            if getattr(self, "active_light", None) == active and getattr(self, "active_recipe", None) is not None:
                r = self.active_recipe
            else:
                r = lights.read_recipe(active)
            if r is not None and r.anchor and "hit" in r.anchor:
                anchor_pt = lights.vec(r.anchor["hit"])
                light_pt = active.GetMg().off
                bd.SetPen(c4d.Vector(0.55, 0.44, 0.22))
                bd.DrawLine(light_pt, anchor_pt, 0)
                bd.DrawHandle(anchor_pt, c4d.DRAWHANDLE_MIDDLE, 0)

        if self.hover is not None:
            p, n = self.hover.point, self.hover.normal
            scale = 0.14 * self.hover.size
            # Surface normal tick (subtle cyan) + active placement direction ray (warm gold)
            bd.SetPen(c4d.Vector(0.35, 0.72, 0.95))
            bd.DrawLine(p, p + n * (0.65 * scale), 0)
            aim_dir = lights.vec(
                placement.light_direction(self.mode, lights.tup(n), lights.tup(self.hover.ray))
            )
            bd.SetPen(c4d.Vector(1.0, 0.72, 0.2))
            bd.DrawLine(p, p + aim_dir * scale, 0)
            bd.DrawHandle(p, c4d.DRAWHANDLE_BIG, 0)

        # 2D Screen-space Heads-Up Display (HUD)
        try:
            frame = bd.GetFrame()
            h = frame["cb"] - frame["ct"] + 1
            if active is not None and r is not None:
                hud = ("Shift+Click: New Light  |  Drag: Aim/Place  ·  Shift=Size  ·  Ctrl=Dist  ·  Shift+Ctrl=Roll"
                       "  |  L: Link Object")
            else:
                hud = "[%s] Click: Place Light  |  Shift+Click: New Light  |  Keys: R/N/O/D/M (Modes)" % self.mode.upper()
            bd.DrawHUDText(20, h - 50, hud)
        except Exception:
            pass

        bd.SetMatrix_Matrix(None, c4d.Matrix())
        return c4d.TOOLDRAW_HANDLES | c4d.TOOLDRAW_AXIS

    def _set_mode(self, doc, mode):
        self.mode = mode
        light = lights.luxe_light(doc.GetActiveObject()) if doc is not None else None
        if light is not None:
            recipe = lights.read_recipe(light)
            if recipe is not None:
                recipe.mode = mode
                lights.place(light, recipe)
                lights.write_recipe(light, recipe)
                lights.apply(doc, light, recipe, bake=False)
                light.Message(c4d.MSG_CHANGE)
        c4d.EventAdd()

    def _toggle_solo(self, doc):
        light = lights.luxe_light(doc.GetActiveObject()) if doc is not None else None
        if light is None:
            return
        is_solo = (lights.solo_light(doc) == light)
        doc.StartUndo()
        lights.set_solo(doc, None if is_solo else light, undo=True)
        doc.EndUndo()
        c4d.EventAdd()

    def _toggle_view_vis(self, doc):
        light = lights.luxe_light(doc.GetActiveObject()) if doc is not None else None
        if light is None:
            return
        recipe = lights.read_recipe(light)
        if recipe is None:
            return
        recipe.viewport_visible = not recipe.viewport_visible
        lights.apply(doc, light, recipe, bake=False)
        lights.write_recipe(light, recipe)
        c4d.EventAdd()

    def _toggle_cam_vis(self, doc):
        light = lights.luxe_light(doc.GetActiveObject()) if doc is not None else None
        if light is None:
            return
        recipe = lights.read_recipe(light)
        if recipe is None:
            return
        recipe.camera_visible = not recipe.camera_visible
        lights.apply(doc, light, recipe, bake=False)
        lights.write_recipe(light, recipe)
        c4d.EventAdd()

    def _cycle_preset(self, doc, step=1):
        light = lights.luxe_light(doc.GetActiveObject()) if doc is not None else None
        if light is None:
            return
        recipe = lights.read_recipe(light)
        if recipe is None:
            return
        cur_tex = recipe.texture or ""
        try:
            cur_idx = _PRESET_CYCLE.index(cur_tex)
        except ValueError:
            cur_idx = 0
        next_idx = (cur_idx + step) % len(_PRESET_CYCLE)
        recipe.texture = _PRESET_CYCLE[next_idx]
        lights.apply(doc, light, recipe, bake=True)
        lights.write_recipe(light, recipe)
        c4d.EventAdd()

    def _cycle_kelvin(self, doc):
        light = lights.luxe_light(doc.GetActiveObject()) if doc is not None else None
        if light is None:
            return
        recipe = lights.read_recipe(light)
        if recipe is None:
            return
        cur_k = recipe.kelvin
        next_k = _KELVIN_STEPS[0]
        for step_k in _KELVIN_STEPS:
            if step_k > cur_k + 50.0:
                next_k = step_k
                break
        recipe.kelvin = next_k
        recipe.gels = []
        lights.apply(doc, light, recipe, bake=False)
        lights.write_recipe(light, recipe)
        c4d.EventAdd()

    def _toggle_constant_lux(self, doc):
        light = lights.luxe_light(doc.GetActiveObject()) if doc is not None else None
        if light is None:
            return
        recipe = lights.read_recipe(light)
        if recipe is None:
            return
        recipe.constant_lux = not recipe.constant_lux
        lights.write_recipe(light, recipe)
        c4d.EventAdd()

    def _step_exposure(self, doc, delta):
        light = lights.luxe_light(doc.GetActiveObject()) if doc is not None else None
        if light is None:
            return
        recipe = lights.read_recipe(light)
        if recipe is None:
            return
        doc.StartUndo()
        recipe.exposure = round(recipe.exposure + delta, 2)
        lights.apply(doc, light, recipe, bake=False)
        lights.write_recipe(light, recipe)
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, light)
        doc.EndUndo()
        c4d.EventAdd()

    def _toggle_link(self, doc):
        """L: put the object under the cursor in the selected light's link list, or take it out."""
        light = lights.luxe_light(doc.GetActiveObject()) if doc is not None else None
        target = self.hover.obj if self.hover is not None else None
        if light is None or target is None:
            return
        recipe = lights.read_recipe(light)
        doc.StartUndo()
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, light)
        now_in = lights.toggle_link(doc, light, target, recipe)
        doc.EndUndo()
        if now_in is None:
            print("Luxe: could not link %s to %s" % (target.GetName(), light.GetName()))
        else:
            include = lights.get_linking(light, recipe)[0] == lights.LINK_INCLUDE
            lit = now_in == include
            print("Luxe: %s %s %s (%s list)" % (light.GetName(), "lights" if lit else "no longer lights",
                                                target.GetName(), "include" if include else "exclude"))
        c4d.EventAdd()

    def KeyboardInput(self, doc, data, bd, win, msg):
        key = msg.GetString(c4d.BFM_INPUT_ASC) if hasattr(msg, "GetString") else msg.get(c4d.BFM_INPUT_ASC, "")
        if not key:
            ch = msg[c4d.BFM_INPUT_CHANNEL]
            if isinstance(ch, int) and 32 <= ch <= 126:
                key = chr(ch)
        if not key:
            return False
        k = key.lower()

        if k in ("r", "n", "o", "d", "m"):
            mode_map = {"r": "reflect", "n": "normal", "o": "orbit", "d": "direct", "m": "rim"}
            self._set_mode(doc, mode_map[k])
            return True
        elif k == "s":
            self._toggle_solo(doc)
            return True
        elif k == "v":
            self._toggle_view_vis(doc)
            return True
        elif k == "c":
            self._toggle_cam_vis(doc)
            return True
        elif k == "i":
            self._toggle_constant_lux(doc)
            return True
        elif k == "[":
            self._cycle_preset(doc, step=-1)
            return True
        elif k == "]":
            self._cycle_preset(doc, step=1)
            return True
        elif k == "k":
            self._cycle_kelvin(doc)
            return True
        elif k == "l":
            self._toggle_link(doc)
            return True
        elif k in ("+", "="):
            self._step_exposure(doc, 0.5)
            return True
        elif k in ("-", "_"):
            self._step_exposure(doc, -0.5)
            return True

        return False

    def MouseInput(self, doc, data, bd, win, msg):
        channel = msg[c4d.BFM_INPUT_CHANNEL]
        if channel == c4d.BFM_INPUT_MOUSEWHEEL:
            val = msg[c4d.BFM_INPUT_VALUE]
            step = 1.0 if val > 0 else -1.0
            qual = msg[c4d.BFM_INPUT_QUALIFIER]
            light = lights.luxe_light(doc.GetActiveObject()) if doc is not None else None
            if light is None:
                return False
            recipe = lights.read_recipe(light)
            if recipe is None:
                return False

            if (qual & c4d.QCTRL) and (qual & c4d.QSHIFT):
                # Ctrl + Shift + Scroll: Spread (0.05 to 1.0)
                recipe.spread = max(min(round(recipe.spread + step * 0.05, 2), 1.0), 0.05)
                lights.apply(doc, light, recipe, bake=False)
            elif qual & c4d.QSHIFT:
                # Shift + Scroll: Size (width & height proportionally)
                delta = step * max(round(max(recipe.width, recipe.height) * 0.05), 1.0)
                old_w, old_h = recipe.width, recipe.height
                recipe.width = max(recipe.width + delta, 1.0)
                recipe.height = max(recipe.height + delta, 1.0)
                if recipe.constant_lux:
                    old_a = old_w * old_h
                    new_a = recipe.width * recipe.height
                    recipe.exposure = round(
                        recipe.exposure + placement.constant_lux_ev_delta(recipe.distance, recipe.distance, old_a, new_a),
                        3,
                    )
                lights.apply(doc, light, recipe, bake=False)
            elif qual & c4d.QALT:
                # Alt + Scroll: Distance from target
                old_dist = recipe.distance
                factor = 1.10 if step > 0 else 0.91
                recipe.distance = max(round(old_dist * factor, 1), 0.1)
                if recipe.constant_lux:
                    area = recipe.width * recipe.height
                    recipe.exposure = round(
                        recipe.exposure + placement.constant_lux_ev_delta(old_dist, recipe.distance, area, area),
                        3,
                    )
                lights.place(light, recipe)
                lights.apply(doc, light, recipe, bake=False)
            elif qual & c4d.QCTRL:
                # Ctrl + Scroll: Exposure (EV) in 0.1 EV increments
                recipe.exposure = round(recipe.exposure + step * 0.1, 2)
                lights.apply(doc, light, recipe, bake=False)
            else:
                # Bare scroll: leave untouched for normal C4D camera zoom
                return False

            doc.StartUndo()
            lights.write_recipe(light, recipe)
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, light)
            doc.EndUndo()
            c4d.EventAdd()
            return True

        if channel != c4d.BFM_INPUT_MOUSELEFT:
            return False

        x, y = msg[c4d.BFM_INPUT_X], msg[c4d.BFM_INPUT_Y]
        init_qual = msg[c4d.BFM_INPUT_QUALIFIER]
        has_ctrl = bool(init_qual & c4d.QCTRL)
        has_alt = bool(init_qual & c4d.QALT)
        has_shift = bool(init_qual & c4d.QSHIFT)

        active_light = lights.luxe_light(doc.GetActiveObject()) if doc is not None else None
        hit = self.picker.hit(doc, bd, x, y)

        # ----------------------------------------------------------------------
        # 1. No active Luxe light selected: click on surface creates initial light
        # ----------------------------------------------------------------------
        if active_light is None:
            if hit is None:
                return True
            renderer = lights.default_renderer(doc) if self.renderer == "match" else self.renderer
            init_size = placement.default_size(hit.size)
            recipe = LightRecipe(
                name="Luxe %02d" % (len(lights.all_luxe_lights(doc)) + 1),
                renderer=renderer,
                mode=self.mode,
                width=init_size,
                height=init_size,
                distance=placement.default_distance(hit.size),
                texture="Softbox",
                viewport_visible=True,
                camera_visible=False,
            )
            doc.StartUndo()
            try:
                light = lights.create(doc, recipe)
            except RuntimeError as err:
                doc.EndUndo()
                c4d.gui.MessageDialog("Luxe: %s" % err)
                return True
            lights.apply(doc, light, recipe, bake=True)
            doc.EndUndo()

            lights.place(light, recipe, hit)
            light.Message(c4d.MSG_CHANGE)
            c4d.DrawViews(REDRAW)
            self._drag(doc, bd, win, light, recipe, x, y, is_new=True, allow_glide=True)

            doc.StartUndo()
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, light)
            lights.place(light, recipe)
            lights.write_recipe(light, recipe)
            doc.EndUndo()
            c4d.EventAdd()
            return True

        # ----------------------------------------------------------------------
        # 2. An active Luxe light IS selected
        # ----------------------------------------------------------------------
        recipe = lights.read_recipe(active_light)
        if recipe is None:
            return True

        # 2A: Ctrl or Alt held at mouse down (Distance, Roll, Spread)
        # Does not change target anchor or require geometry hit; drags anywhere in viewport.
        if has_ctrl or has_alt:
            self._drag(doc, bd, win, active_light, recipe, x, y, is_new=False, allow_glide=False)
            doc.StartUndo()
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, active_light)
            lights.place(active_light, recipe)
            lights.write_recipe(active_light, recipe)
            doc.EndUndo()
            c4d.EventAdd()
            return True

        # 2B: Shift held at mouse down (Shift+Drag to Resize OR Shift+Click to Create New Light)
        if has_shift:
            orig_w, orig_h = recipe.width, recipe.height
            orig_exp = recipe.exposure
            total_moved = self._drag(doc, bd, win, active_light, recipe, x, y, is_new=False, allow_glide=False)
            if total_moved < 6 and hit is not None:
                # Click without dragging: create a new light at the clicked surface
                recipe.width = orig_w
                recipe.height = orig_h
                recipe.exposure = orig_exp
                lights.apply(doc, active_light, recipe, bake=False)

                renderer = lights.default_renderer(doc) if self.renderer == "match" else self.renderer
                init_size = placement.default_size(hit.size)
                new_recipe = LightRecipe(
                    name="Luxe %02d" % (len(lights.all_luxe_lights(doc)) + 1),
                    renderer=renderer,
                    mode=self.mode,
                    width=init_size,
                    height=init_size,
                    distance=placement.default_distance(hit.size),
                    texture="Softbox",
                    viewport_visible=True,
                    camera_visible=False,
                )
                doc.StartUndo()
                try:
                    new_light = lights.create(doc, new_recipe)
                except RuntimeError as err:
                    doc.EndUndo()
                    c4d.gui.MessageDialog("Luxe: %s" % err)
                    return True
                lights.place(new_light, new_recipe, hit)
                lights.apply(doc, new_light, new_recipe, bake=True)
                doc.EndUndo()
                c4d.EventAdd()
                return True
            else:
                # Drag with Shift: resize confirmed
                doc.StartUndo()
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, active_light)
                lights.place(active_light, recipe)
                lights.write_recipe(active_light, recipe)
                doc.EndUndo()
                c4d.EventAdd()
                return True

        # 2C: Bare Click / Drag (no modifiers held at mouse down)
        # Repositions and glides the active light across the surface under cursor.
        if hit is None:
            return True

        if recipe.mode in placement.MODES:
            self.mode = recipe.mode
        else:
            recipe.mode = self.mode

        lights.place(active_light, recipe, hit)
        active_light.Message(c4d.MSG_CHANGE)
        c4d.DrawViews(REDRAW)

        self._drag(doc, bd, win, active_light, recipe, x, y, is_new=False, allow_glide=True)

        doc.StartUndo()
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, active_light)
        lights.place(active_light, recipe)
        lights.write_recipe(active_light, recipe)
        doc.EndUndo()
        c4d.EventAdd()
        return True

    def _drag(self, doc, bd, win, light, recipe, x, y, is_new=False, allow_glide=True):
        win.MouseDragStart(c4d.KEY_MLEFT, x, y, c4d.MOUSEDRAGFLAGS_DONTHIDEMOUSE)
        self.active_recipe = recipe
        self.active_light = light
        total_moved = 0
        try:
            while True:
                result, dx, dy, channels = win.MouseDrag()
                if result != c4d.MOUSEDRAGRESULT_CONTINUE:
                    break
                if dx == 0 and dy == 0:
                    continue
                total_moved += abs(dx) + abs(dy)
                x, y = x + dx, y + dy
                qual = channels[c4d.BFM_INPUT_QUALIFIER]

                if (qual & c4d.QCTRL) and (qual & c4d.QSHIFT):
                    # Shift + Ctrl + Drag: Roll rotation around light normal
                    recipe.rotation = round((recipe.rotation + dx * 0.5) % 360.0, 1)
                    lights.place(light, recipe)
                elif (qual & c4d.QSHIFT) and not is_new:
                    # Shift + Drag (on existing light): Size scaling proportionally
                    old_w, old_h = recipe.width, recipe.height
                    factor = math.exp(dx * 0.008)
                    recipe.width = max(round(old_w * factor, 1), 1.0)
                    recipe.height = max(round(old_h * factor, 1), 1.0)
                    if recipe.constant_lux:
                        old_a = old_w * old_h
                        new_a = recipe.width * recipe.height
                        recipe.exposure = round(
                            recipe.exposure + placement.constant_lux_ev_delta(recipe.distance, recipe.distance, old_a, new_a),
                            3,
                        )
                    lights.apply(doc, light, recipe, bake=False)
                elif qual & c4d.QCTRL:
                    # Ctrl + Drag: Distance from target anchor
                    old_dist = max(recipe.distance, 0.1)
                    recipe.distance = max(round(old_dist * math.exp(dx * 0.01), 1), 0.1)
                    lights.place(light, recipe)
                    if recipe.constant_lux:
                        area = recipe.width * recipe.height
                        recipe.exposure = round(
                            recipe.exposure + placement.constant_lux_ev_delta(old_dist, recipe.distance, area, area),
                            3,
                        )
                        lights.apply(doc, light, recipe, bake=False)
                elif qual & c4d.QALT:
                    # Alt + Drag: Roll rotation fallback
                    recipe.rotation = round((recipe.rotation + dx * 0.5) % 360.0, 1)
                    lights.place(light, recipe)
                elif recipe.mode == "orbit" and allow_glide:
                    # Orbit mode drag: rotate around target anchor
                    a = recipe.anchor
                    if a:
                        cam_mg = bd.GetMg()
                        cur = a.get("orbit_dir") or placement.light_direction("reflect", a["normal"], a["ray_dir"])
                        a["orbit_dir"] = list(
                            placement.orbit_direction(
                                cur, lights.tup(cam_mg.v1), (0.0, 1.0, 0.0), -dx * 0.008, -dy * 0.008
                            )
                        )
                        lights.place(light, recipe)
                elif allow_glide:
                    # Standard glide placement across surface
                    self.hover = self.picker.hit(doc, bd, x, y)
                    if self.hover is not None:
                        lights.place(light, recipe, self.hover)

                # No MSG_CHANGE here: a move only dirties the matrix, and apply() flags the parameters it changes.
                # A full change message on every mouse move made Octane's IPR rebuild the light ~10 times a second,
                # which preceded a CUDA 700 crash (2026-11-06).
                c4d.DrawViews(REDRAW)
            return total_moved
        finally:
            self.active_recipe = None
            self.active_light = None
            win.MouseDragEnd()
