"""The unified Luxe workspace, shared by the Luxe Light Tool's Attribute Manager and Extensions > Luxe."""
import json
import os

import c4d

from luxe_core import photometry, placement, recipe as recipe_mod, textures

from . import ids, lights, widgets

MODE_LABELS = {
    "reflect": "Reflection (highlight lands here)",
    "normal": "Normal (light faces the spot)",
    "orbit": "Orbit (drag to circle the spot)",
    "direct": "Direct (from the camera side)",
    "rim": "Rim (edge light from behind)",
}
RENDERER_CHOICES = ("match", "redshift", "octane")
COLOR_MODE_LABELS = ("Kelvin + Tint", "Kelvin Only", "RGB Color")


def _get_saved_gobo_folder():
    """Retrieve the user's custom Gobo folder from C4D's WorldContainer or JSON preferences."""
    try:
        wc = c4d.GetWorldContainerInstance()
        if wc is not None:
            bc = wc.GetContainerInstance(ids.DATA_ID)
            if bc is not None:
                folder = bc.GetString(20)
                if folder and os.path.isdir(folder):
                    return folder
    except Exception:
        pass
    try:
        cfg_path = os.path.join(c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS), "luxe_config.json")
        if os.path.isfile(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                folder = data.get("gobo_folder", "")
                if folder and os.path.isdir(folder):
                    return folder
    except Exception:
        pass
    return ""


def _save_gobo_folder(folder):
    """Persist the user's custom Gobo folder for future sessions."""
    folder = folder.strip() if folder else ""
    try:
        wc = c4d.GetWorldContainerInstance()
        if wc is not None:
            bc = wc.GetContainerInstance(ids.DATA_ID)
            if bc is None:
                bc = c4d.BaseContainer()
                wc.SetContainer(ids.DATA_ID, bc)
                bc = wc.GetContainerInstance(ids.DATA_ID)
            if bc is not None:
                bc.SetString(20, folder)
    except Exception:
        pass
    try:
        cfg_path = os.path.join(c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS), "luxe_config.json")
        data = {}
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data["gobo_folder"] = folder
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

(
    ID_HINT,
    ID_NEW_RENDERER,
    ID_TOOL,
    ID_SCENE_LIGHTS_GRP,
    ID_DECK_AREA,
    ID_DUPLICATE,
    ID_UNSOLO,
    ID_DELETE_LIGHT,
    ID_MODE_AREA,
    ID_DISTANCE,
    ID_ROTATION,
    ID_RESET_ROT,
    ID_CONST_LUX,
    ID_EXPOSURE,
    ID_RESET_EV,
    ID_INTENSITY,
    ID_WIDTH,
    ID_HEIGHT,
    ID_ASPECT_LOCK,
    ID_SPREAD,
    ID_COLOR_MODE,
    ID_KELVIN,
    ID_RESET_KELVIN,
    ID_KELVIN_BAR,
    ID_TINT,
    ID_RESET_TINT,
    ID_PREVIEW_AREA,
    ID_SOFTNESS,
    ID_RESET_SOFT,
    ID_CUSTOM_LABEL,
    ID_PICK_IMAGE,
    ID_GOBO_CAT,
    ID_GOBO_FILE,
    ID_GOBO_PREV,
    ID_GOBO_NEXT,
    ID_GOBO_BROWSE,
    ID_GALLERY_AREA,
    ID_LINK_MODE,
    ID_LINK_CLEAR,
    ID_LINK_GRP,
    ID_LINK_LIST,
    ID_LINK_HINT,
) = range(2000, 2042)

_LIGHT_CONTROLS = (
    ID_DUPLICATE,
    ID_DELETE_LIGHT,
    ID_DISTANCE,
    ID_ROTATION,
    ID_RESET_ROT,
    ID_CONST_LUX,
    ID_EXPOSURE,
    ID_RESET_EV,
    ID_INTENSITY,
    ID_WIDTH,
    ID_HEIGHT,
    ID_ASPECT_LOCK,
    ID_SPREAD,
    ID_COLOR_MODE,
    ID_KELVIN,
    ID_RESET_KELVIN,
    ID_TINT,
    ID_RESET_TINT,
    ID_SOFTNESS,
    ID_RESET_SOFT,
    ID_PICK_IMAGE,
    ID_GOBO_CAT,
    ID_GOBO_FILE,
    ID_GOBO_PREV,
    ID_GOBO_NEXT,
    ID_LINK_MODE,
    ID_LINK_CLEAR,
    ID_LINK_LIST,
)

_BAKE_IDS = {ID_SOFTNESS, ID_RESET_SOFT}
_PLACE_IDS = {ID_DISTANCE, ID_ROTATION, ID_RESET_ROT}


class WorkspaceMixin:
    """Shared studio layout and live parameter binding for both SubDialog (Tool) and GeDialog (Panel)."""

    def _init_workspace(self, tool=None):
        self._tool = tool
        self._scene_lights = []
        self._deck_area = widgets.LightDeckArea(self._on_deck_action)
        self._mode_area = widgets.ModeBarArea(self._on_mode_picked)
        self._kelvin_area = widgets.KelvinBarArea(self._on_kelvin_bar)
        self._preview_area = widgets.LightPreviewArea(self._pick_custom_image)
        self._gallery_area = widgets.TextureGalleryArea(self._on_texture_picked)
        self._link_gui = None
        self._link_key = "unset"  # renderer whose list settings the link GUI was built with

        self._gobo_root = _get_saved_gobo_folder()
        self._gobo_cats = []
        self._gobo_files = []
        self._gobo_cat_idx = 0
        self._gobo_file_idx = 0
        self._scan_gobo_root()

    def _scan_gobo_root(self):
        if not self._gobo_root or not os.path.isdir(self._gobo_root):
            self._gobo_cats = []
            self._gobo_files = []
            return
        try:
            entries = os.listdir(self._gobo_root)
            subdirs = [d for d in entries if os.path.isdir(os.path.join(self._gobo_root, d))]
            subdirs.sort(key=str.lower)
            valid_exts = {".exr", ".hdr", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
            root_images = [f for f in entries if os.path.isfile(os.path.join(self._gobo_root, f))
                           and os.path.splitext(f)[1].lower() in valid_exts]
            cats = []
            if root_images:
                cats.append("Root Folder")
            cats.extend(subdirs)
            self._gobo_cats = cats
            self._scan_gobo_category()
        except OSError:
            self._gobo_cats = []
            self._gobo_files = []

    def _scan_gobo_category(self):
        if not self._gobo_cats or self._gobo_cat_idx >= len(self._gobo_cats):
            self._gobo_files = []
            return
        cat_name = self._gobo_cats[self._gobo_cat_idx]
        cat_dir = self._gobo_root if cat_name == "Root Folder" else os.path.join(self._gobo_root, cat_name)
        valid_exts = {".exr", ".hdr", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
        try:
            files = []
            for root, dirs, fnames in os.walk(cat_dir):
                for f in fnames:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in valid_exts:
                        full = os.path.join(root, f)
                        rel = os.path.relpath(full, cat_dir)
                        files.append((rel, full))
            files.sort(key=lambda x: x[0].lower())
            self._gobo_files = files
        except OSError:
            self._gobo_files = []

    def _rebuild_gobo_combos(self):
        self.FreeChildren(ID_GOBO_CAT)
        if not self._gobo_root:
            self.AddChild(ID_GOBO_CAT, 0, "No Gobo Folder Set — Click 'Folder...'")
            self.Enable(ID_GOBO_CAT, False)
        elif not self._gobo_cats:
            self.AddChild(ID_GOBO_CAT, 0, "No Images or Folders Found")
            self.Enable(ID_GOBO_CAT, False)
        else:
            for idx, c in enumerate(self._gobo_cats):
                self.AddChild(ID_GOBO_CAT, idx, c)
            self.SetInt32(ID_GOBO_CAT, self._gobo_cat_idx)
            self.Enable(ID_GOBO_CAT, True)

        self.FreeChildren(ID_GOBO_FILE)
        if not self._gobo_root:
            self.AddChild(ID_GOBO_FILE, 0, "Set Gobo Folder First")
            self.Enable(ID_GOBO_FILE, False)
            self.Enable(ID_GOBO_PREV, False)
            self.Enable(ID_GOBO_NEXT, False)
        elif not self._gobo_files:
            self.AddChild(ID_GOBO_FILE, 0, "No Images in Category")
            self.Enable(ID_GOBO_FILE, False)
            self.Enable(ID_GOBO_PREV, False)
            self.Enable(ID_GOBO_NEXT, False)
        else:
            for idx, (rel, full) in enumerate(self._gobo_files):
                self.AddChild(ID_GOBO_FILE, idx, rel)
            self.SetInt32(ID_GOBO_FILE, self._gobo_file_idx)
            self.Enable(ID_GOBO_FILE, True)
            self.Enable(ID_GOBO_PREV, True)
            self.Enable(ID_GOBO_NEXT, True)

    def _apply_selected_gobo(self):
        if not self._gobo_files or self._gobo_file_idx >= len(self._gobo_files):
            return
        doc = c4d.documents.GetActiveDocument()
        light = self._active_light(doc)
        if light is None:
            return
        recipe = lights.read_recipe(light)
        full_path = self._gobo_files[self._gobo_file_idx][1]
        recipe.custom_texture = full_path
        recipe.texture = textures.CUSTOM_TEXTURE
        self._commit_recipe(doc, light, recipe, bake=True, re_place=False, dragging=False)
        self.refresh_workspace()

    def _on_deck_action(self, action, op, item):
        doc = c4d.documents.GetActiveDocument()
        if doc is None or op is None:
            return
        if action == "select":
            doc.StartUndo()
            doc.AddUndo(c4d.UNDOTYPE_BITS, op)
            doc.SetActiveObject(op, c4d.SELECTION_NEW)
            doc.EndUndo()
            c4d.EventAdd()
            self.refresh_workspace()
        elif action == "solo":
            cur = lights.solo_light(doc)
            target = None if cur == op else op
            doc.StartUndo()
            lights.set_solo(doc, target, undo=True)
            doc.EndUndo()
            c4d.EventAdd()
            self.refresh_workspace()
        elif action == "viewport":
            r = lights.read_recipe(op)
            if r is not None:
                r.viewport_visible = not r.viewport_visible
                doc.StartUndo()
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, op)
                lights.apply(doc, op, r, bake=False)
                lights.write_recipe(op, r)
                doc.EndUndo()
                c4d.EventAdd()
                self.refresh_workspace()
        elif action == "camera":
            r = lights.read_recipe(op)
            if r is not None:
                r.camera_visible = not r.camera_visible
                doc.StartUndo()
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, op)
                lights.apply(doc, op, r, bake=False)
                lights.write_recipe(op, r)
                doc.EndUndo()
                c4d.EventAdd()
                self.refresh_workspace()
        elif action == "delete":
            doc.StartUndo()
            doc.AddUndo(c4d.UNDOTYPE_DELETE, op)
            op.Remove()
            lights.sync_octane_links(doc)  # frees its light pass ID and the tags only it needed
            doc.EndUndo()
            c4d.EventAdd()
            self.refresh_workspace()

    def _section_begin(self, title, gid=0):
        self.GroupBegin(gid, c4d.BFH_SCALEFIT, 1, 0, title, 0)
        self.GroupBorder(c4d.BORDER_GROUP_IN)
        self.GroupBorderSpace(8, 6, 8, 7)
        self.GroupSpace(4, 4)

    def _section_end(self):
        self.GroupEnd()

    def _build_workspace(self):
        self.GroupSpace(4, 4)
        # Top context bar (Tool settings in Attribute Manager, or Tool activator in floating Panel)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 1, 0, "")
        self.GroupBorderSpace(6, 6, 6, 2)
        if self._tool is not None:
            self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0, "")
            self.AddStaticText(0, c4d.BFH_LEFT, name="New Lights")
            self.AddComboBox(ID_NEW_RENDERER, c4d.BFH_SCALEFIT)
            for i, label in enumerate(("Match Render Settings", "Redshift", "Octane")):
                self.AddChild(ID_NEW_RENDERER, i, label)
            self.GroupEnd()
            self.AddStaticText(
                ID_HINT,
                c4d.BFH_SCALEFIT,
                name="Click: place  ·  Shift+Click: new  ·  Drag: aim/orbit  ·  Ctrl+Drag: distance",
            )
        else:
            self.AddButton(ID_TOOL, c4d.BFH_SCALEFIT, initw=0, inith=22, name="Activate Luxe Light Tool")
        self.GroupEnd()

        scroll_flags = c4d.SCROLLGROUP_VERT | getattr(c4d, "SCROLLGROUP_AUTOVERT", 0)
        self.ScrollGroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, scroll_flags, initw=270, inith=360)
        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_TOP, 1, 0, "")
        self.GroupBorderSpace(6, 2, 6, 8)
        self.GroupSpace(6, 6)

        # 1. Scene Lights (Multi-Light Studio Deck)
        doc = c4d.documents.GetActiveDocument()
        init_count = len(lights.all_luxe_lights(doc)) if doc is not None else 0
        deck_h = max(init_count * (widgets.LightDeckArea.ROW_H + widgets.LightDeckArea.GAP) + 6, 60)
        self._section_begin("Scene Lights", gid=ID_SCENE_LIGHTS_GRP)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0, "")
        self.AddButton(ID_DUPLICATE, c4d.BFH_SCALEFIT, initw=0, inith=20, name="Duplicate")
        self.AddButton(ID_UNSOLO, c4d.BFH_SCALEFIT, initw=0, inith=20, name="Unsolo All")
        self.AddButton(ID_DELETE_LIGHT, c4d.BFH_SCALEFIT, initw=0, inith=20, name="Delete")
        self.GroupEnd()
        self.AddUserArea(ID_DECK_AREA, c4d.BFH_SCALEFIT, initw=248, inith=deck_h)
        self.AttachUserArea(self._deck_area, ID_DECK_AREA)
        self._section_end()

        # 2. Placement & Aim
        self._section_begin("Placement & Aim")
        self.AddUserArea(ID_MODE_AREA, c4d.BFH_SCALEFIT, initw=240, inith=26)
        self.AttachUserArea(self._mode_area, ID_MODE_AREA)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0, "")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Distance")
        self.AddEditSlider(ID_DISTANCE, c4d.BFH_SCALEFIT)
        self.AddStaticText(0, c4d.BFH_RIGHT, name="")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Rotation (°)")
        self.AddEditSlider(ID_ROTATION, c4d.BFH_SCALEFIT)
        self.AddButton(ID_RESET_ROT, c4d.BFH_RIGHT, initw=42, inith=0, name="0°")
        self.GroupEnd()
        self.AddCheckbox(ID_CONST_LUX, c4d.BFH_LEFT, 0, 0, "Constant Illumination (Auto EV)")
        self._section_end()

        # 3. Output & Size
        self._section_begin("Output & Size")
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0, "")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Exposure (EV)")
        self.AddEditSlider(ID_EXPOSURE, c4d.BFH_SCALEFIT)
        self.AddButton(ID_RESET_EV, c4d.BFH_RIGHT, initw=42, inith=0, name="0 EV")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Intensity")
        self.AddEditSlider(ID_INTENSITY, c4d.BFH_SCALEFIT)
        self.AddStaticText(0, c4d.BFH_RIGHT, name="")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Width")
        self.AddEditSlider(ID_WIDTH, c4d.BFH_SCALEFIT)
        self.AddStaticText(0, c4d.BFH_RIGHT, name="")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Height")
        self.AddEditSlider(ID_HEIGHT, c4d.BFH_SCALEFIT)
        self.AddStaticText(0, c4d.BFH_RIGHT, name="")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Spread")
        self.AddEditSlider(ID_SPREAD, c4d.BFH_SCALEFIT)
        self.AddStaticText(0, c4d.BFH_RIGHT, name="")
        self.GroupEnd()
        self.AddCheckbox(ID_ASPECT_LOCK, c4d.BFH_LEFT, 0, 0, "Lock Aspect Ratio")
        self._section_end()

        # 4. Color (Simplified: Kelvin + Direct Color Swatch)
        self._section_begin("Color")
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0, "")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Color Mode")
        self.AddComboBox(ID_COLOR_MODE, c4d.BFH_SCALEFIT)
        for i, label in enumerate(COLOR_MODE_LABELS):
            self.AddChild(ID_COLOR_MODE, i, label)
        self.GroupEnd()
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0, "")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Temperature")
        self.AddEditSlider(ID_KELVIN, c4d.BFH_SCALEFIT)
        self.AddButton(ID_RESET_KELVIN, c4d.BFH_RIGHT, initw=48, inith=0, name="6500K")
        self.GroupEnd()
        self.AddUserArea(ID_KELVIN_BAR, c4d.BFH_SCALEFIT, initw=200, inith=20)
        self.AttachUserArea(self._kelvin_area, ID_KELVIN_BAR)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0, "")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Color Swatch")
        self.AddColorField(ID_TINT, c4d.BFH_SCALEFIT, initw=80, inith=18, colorflags=c4d.DR_COLORFIELD_NO_BRIGHTNESS)
        self.AddButton(ID_RESET_TINT, c4d.BFH_RIGHT, initw=48, inith=0, name="White")
        self.GroupEnd()
        self._section_end()

        # 5. Light Linking: the renderer's own include/exclude list on the light, so the Attribute Manager agrees
        self._section_begin("Light Linking")
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0, "")
        self.AddComboBox(ID_LINK_MODE, c4d.BFH_SCALEFIT)
        self.AddChild(ID_LINK_MODE, lights.LINK_EXCLUDE, "Exclude: light all but these")
        self.AddChild(ID_LINK_MODE, lights.LINK_INCLUDE, "Include: light only these")
        self.AddButton(ID_LINK_CLEAR, c4d.BFH_RIGHT, initw=48, inith=0, name="Clear")
        self.GroupEnd()
        self.GroupBegin(ID_LINK_GRP, c4d.BFH_SCALEFIT, 1, 0, "")
        self._add_link_list(None)
        self.GroupEnd()
        self.AddStaticText(ID_LINK_HINT, c4d.BFH_SCALEFIT, name="")
        self._section_end()

        # 6. Visual Light Texture
        self._section_begin("Light Texture")
        self.AddUserArea(ID_PREVIEW_AREA, c4d.BFH_SCALEFIT, initw=240, inith=114)
        self.AttachUserArea(self._preview_area, ID_PREVIEW_AREA)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0, "")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Edge Softness")
        self.AddEditSlider(ID_SOFTNESS, c4d.BFH_SCALEFIT)
        self.AddButton(ID_RESET_SOFT, c4d.BFH_RIGHT, initw=42, inith=0, name="1.0")
        self.GroupEnd()

        # Gobo Library Explorer
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 1, 0, "Local Gobo Library")
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0, "")
        self.AddComboBox(ID_GOBO_CAT, c4d.BFH_SCALEFIT)
        self.AddButton(ID_GOBO_BROWSE, c4d.BFH_RIGHT, initw=64, inith=0, name="Folder...")
        self.GroupEnd()
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0, "")
        self.AddButton(ID_GOBO_PREV, c4d.BFH_LEFT, initw=28, inith=0, name="<")
        self.AddComboBox(ID_GOBO_FILE, c4d.BFH_SCALEFIT)
        self.AddButton(ID_GOBO_NEXT, c4d.BFH_RIGHT, initw=28, inith=0, name=">")
        self.GroupEnd()
        self.GroupEnd()

        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0, "")
        self.AddStaticText(ID_CUSTOM_LABEL, c4d.BFH_SCALEFIT, name="")
        self.AddButton(ID_PICK_IMAGE, c4d.BFH_RIGHT, initw=86, inith=0, name="Load File...")
        self.GroupEnd()
        self.AddUserArea(ID_GALLERY_AREA, c4d.BFH_SCALEFIT, initw=248, inith=340)
        self.AttachUserArea(self._gallery_area, ID_GALLERY_AREA)
        self._section_end()

        self.GroupEnd()
        self.GroupEnd()
        return True

    def _active_light(self, doc=None):
        d = doc or c4d.documents.GetActiveDocument()
        return lights.luxe_light(d.GetActiveObject()) if d is not None else None

    def _add_link_list(self, settings):
        """The include/exclude list. `settings` is the native list's description, so its icons match the AM's."""
        self._link_gui = self.AddCustomGui(ID_LINK_LIST, c4d.CUSTOMGUI_INEXCLUDE_LIST, "",
                                           c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 240, 70,
                                           settings if settings is not None else c4d.BaseContainer())

    def _sync_link_list(self, doc, light, recipe):
        """Show the selected light's links; rebuild the list GUI when the renderer (and so its icons) changes."""
        key = recipe.renderer if recipe is not None else None
        if key != self._link_key:
            self._link_key = key
            self.LayoutFlushGroup(ID_LINK_GRP)
            self._add_link_list(lights.link_description(light, recipe) if recipe is not None else None)
            self.LayoutChanged(ID_LINK_GRP)
        if recipe is None:
            if self._link_gui is not None:
                self._link_gui.SetData(c4d.InExcludeData())
            self.SetString(ID_LINK_HINT, "")
            return
        mode, data = lights.get_linking(light, recipe)
        self.SetInt32(ID_LINK_MODE, mode)
        if self._link_gui is not None:
            self._link_gui.SetData(data)
        n = len(lights.linked_objects(doc, light, recipe))
        if mode == lights.LINK_INCLUDE:
            hint = "Lights only %d object%s" % (n, "" if n == 1 else "s") if n else "Lights nothing: add objects"
        else:
            hint = "Skips %d object%s" % (n, "" if n == 1 else "s") if n else "Lights everything"
        self.SetString(ID_LINK_HINT, hint + "  ·  drag objects in, or press L over one")

    def _edit_links(self, doc, light, cid):
        recipe = lights.read_recipe(light)
        mode = data = None
        if cid == ID_LINK_MODE:
            mode = self.GetInt32(ID_LINK_MODE)
        elif cid == ID_LINK_CLEAR:
            data = c4d.InExcludeData()
        elif self._link_gui is not None:
            data = self._link_gui.GetData()
        doc.StartUndo()
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, light)
        lights.set_linking(light, mode=mode, data=data, recipe=recipe)
        doc.EndUndo()
        c4d.EventAdd()
        self.refresh_workspace()

    def refresh_workspace(self, force=False):
        try:
            doc = c4d.documents.GetActiveDocument()
            if doc is None:
                return
            if self._tool is not None:
                self.SetInt32(ID_NEW_RENDERER, RENDERER_CHOICES.index(self._tool.renderer))

            light = self._active_light(doc)
            recipe = lights.read_recipe(light) if light is not None else None
            has_light = recipe is not None

            scene_lights = lights.all_luxe_lights(doc) if doc is not None else []
            self._scene_lights = scene_lights
            solo = lights.solo_light(doc)

            # Build and update light deck
            deck_items = []
            for op in scene_lights:
                r = lights.read_recipe(op)
                if r is not None:
                    deck_items.append({
                        "op": op,
                        "guid": str(op.GetGUID()),
                        "name": op.GetName(),
                        "mode": r.mode,
                        "exposure": r.total_exposure(),
                        "colour": r.colour(),
                        "enabled": r.enabled,
                        "viewport": r.viewport_visible,
                        "camera": r.camera_visible,
                        "is_active": (op == light),
                        "is_solo": (solo is not None and solo == op),
                    })
            prev_deck_len = len(self._deck_area.lights)
            self._deck_area.set_lights(deck_items)
            if len(deck_items) != prev_deck_len:
                try:
                    self.LayoutChanged(ID_SCENE_LIGHTS_GRP)
                except Exception:
                    pass

            self.Enable(ID_DUPLICATE, has_light)
            self.Enable(ID_DELETE_LIGHT, has_light)
            self.Enable(ID_UNSOLO, solo is not None)

            for cid in _LIGHT_CONTROLS:
                self.Enable(cid, has_light)

            # Mode bar stays interactive in the Tool even before any light is selected
            self._mode_area.enabled = has_light or (self._tool is not None)
            if has_light:
                if recipe.mode in placement.MODES:
                    self._mode_area.mode = recipe.mode
                    self._sync_tool_mode(recipe.mode)
            else:
                self._mode_area.mode = self._get_tool_mode()
            self._mode_area.Redraw()

            self._rebuild_gobo_combos()
            self._sync_link_list(doc, light, recipe)

            if not has_light:
                self._kelvin_area.enabled = False
                self._kelvin_area.Redraw()
                self._preview_area.set_recipe(None)
                self._gallery_area.enabled = False
                self._gallery_area.selected = ""
                self._gallery_area.Redraw()
                self.SetString(ID_CUSTOM_LABEL, "Custom Image: None")
                return

            self.SetFloat(ID_DISTANCE, recipe.distance, 5.0, 1500.0, 1.0, c4d.FORMAT_METER, 0.1, 100000.0, True)
            self.SetFloat(ID_ROTATION, recipe.rotation % 360.0, 0.0, 360.0, 1.0)
            self.SetBool(ID_CONST_LUX, bool(recipe.constant_lux))

            self.SetFloat(ID_EXPOSURE, recipe.exposure, -10.0, 10.0, 0.1, c4d.FORMAT_FLOAT, -30.0, 30.0)
            self.SetFloat(ID_INTENSITY, recipe.intensity, 0.0, 4.0, 0.05, c4d.FORMAT_FLOAT, 0.0, 100.0)
            self.SetFloat(ID_WIDTH, recipe.width, 5.0, 600.0, 1.0, c4d.FORMAT_METER, 0.1, 100000.0, True)
            self.SetFloat(ID_HEIGHT, recipe.height, 5.0, 600.0, 1.0, c4d.FORMAT_METER, 0.1, 100000.0, True)
            self.SetBool(ID_ASPECT_LOCK, bool(recipe.aspect_lock))
            self.SetFloat(ID_SPREAD, recipe.spread, 0.0, 1.0, 0.01)

            cmode = recipe.color_mode if recipe.color_mode in recipe_mod.COLOR_MODES else "kelvin_tint"
            self.SetInt32(ID_COLOR_MODE, recipe_mod.COLOR_MODES.index(cmode))
            use_kelvin = cmode in ("kelvin_tint", "kelvin")
            use_tint = cmode in ("kelvin_tint", "rgb")
            self.Enable(ID_KELVIN, use_kelvin)
            self.Enable(ID_RESET_KELVIN, use_kelvin)
            self.Enable(ID_TINT, use_tint)
            self.Enable(ID_RESET_TINT, use_tint)

            self.SetFloat(ID_KELVIN, recipe.kelvin, 1800.0, 12000.0, 50.0, c4d.FORMAT_FLOAT,
                          photometry.MIN_KELVIN, photometry.MAX_KELVIN)
            self._kelvin_area.enabled = use_kelvin
            self._kelvin_area.kelvin = recipe.kelvin
            self._kelvin_area.Redraw()

            srgb_tint = photometry.linear_to_srgb(recipe.tint or [1.0, 1.0, 1.0])
            self.SetColorField(ID_TINT, c4d.Vector(*srgb_tint), 1.0, 1.0, c4d.DR_COLORFIELD_NO_BRIGHTNESS)

            has_proc = recipe.texture in textures.PRESETS
            self.Enable(ID_SOFTNESS, has_proc)
            self.Enable(ID_RESET_SOFT, has_proc)
            self.SetFloat(ID_SOFTNESS, recipe.softness, 0.15, 2.5, 0.05)

            cname = os.path.basename(recipe.custom_texture) if recipe.custom_texture else "None"
            self.SetString(ID_CUSTOM_LABEL, "Image: %s" % cname)

            self._preview_area.set_recipe(recipe)
            self._gallery_area.enabled = True
            self._gallery_area.selected = recipe.texture if recipe.texture in widgets.GALLERY_KEYS else ""
            self._gallery_area.custom_path = recipe.custom_texture or ""
            self._gallery_area.Redraw()
        except Exception:
            pass

    def _commit_recipe(self, doc, light, recipe, bake=False, re_place=False, dragging=False):
        if not dragging:
            doc.StartUndo()
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, light)
        if re_place:
            lights.place(light, recipe)
        lights.apply(doc, light, recipe, bake=bake)
        if not dragging:
            doc.EndUndo()
        else:
            light.Message(c4d.MSG_CHANGE)
            c4d.DrawViews(c4d.DRAWFLAGS_ONLY_ACTIVE_VIEW | c4d.DRAWFLAGS_NO_THREAD | c4d.DRAWFLAGS_NO_ANIMATION)
        c4d.EventAdd()
        self._preview_area.set_recipe(recipe)

    def _sync_tool_mode(self, mode):
        if self._tool is not None:
            self._tool.mode = mode
        tool_plug = c4d.plugins.FindPlugin(ids.TOOL_ID, c4d.PLUGINTYPE_TOOL)
        if tool_plug is not None:
            tool_data = tool_plug.GetNodeData()
            if tool_data is not None:
                tool_data.mode = mode

    def _get_tool_mode(self):
        if self._tool is not None:
            return self._tool.mode
        tool_plug = c4d.plugins.FindPlugin(ids.TOOL_ID, c4d.PLUGINTYPE_TOOL)
        if tool_plug is not None:
            tool_data = tool_plug.GetNodeData()
            if tool_data is not None:
                return getattr(tool_data, "mode", "reflect")
        return "reflect"

    def _on_mode_picked(self, mode):
        self._sync_tool_mode(mode)
        doc = c4d.documents.GetActiveDocument()
        light = self._active_light(doc)
        if light is None:
            self._mode_area.mode = mode
            self._mode_area.Redraw()
            return
        recipe = lights.read_recipe(light)
        recipe.mode = mode
        self._commit_recipe(doc, light, recipe, bake=False, re_place=True, dragging=False)
        self.refresh_workspace()

    def _on_kelvin_bar(self, kelvin, dragging):
        doc = c4d.documents.GetActiveDocument()
        light = self._active_light(doc)
        if light is None:
            return
        recipe = lights.read_recipe(light)
        recipe.kelvin = float(kelvin)
        recipe.gels = []
        self.SetFloat(ID_KELVIN, recipe.kelvin, 1800.0, 12000.0, 50.0, c4d.FORMAT_FLOAT,
                      photometry.MIN_KELVIN, photometry.MAX_KELVIN)
        self._commit_recipe(doc, light, recipe, bake=False, re_place=False, dragging=dragging)
        if not dragging:
            self.refresh_workspace()

    def _pick_custom_image(self):
        doc = c4d.documents.GetActiveDocument()
        light = self._active_light(doc)
        if light is None:
            return
        recipe = lights.read_recipe(light)
        start_dir = os.path.dirname(recipe.custom_texture) if recipe.custom_texture else ""
        chosen = c4d.storage.LoadDialog(
            type=c4d.FILESELECTTYPE_IMAGES,
            title="Select Light Texture (EXR, HDR, PNG, JPG, TIF)",
            flags=c4d.FILESELECT_LOAD,
            def_path=start_dir,
        )
        if not chosen:
            self.refresh_workspace()
            return
        recipe.custom_texture = chosen
        recipe.texture = textures.CUSTOM_TEXTURE
        self._commit_recipe(doc, light, recipe, bake=True, re_place=False, dragging=False)
        self.refresh_workspace()

    def _on_texture_picked(self, key):
        doc = c4d.documents.GetActiveDocument()
        light = self._active_light(doc)
        if light is None:
            return
        recipe = lights.read_recipe(light)
        if key == textures.CUSTOM_TEXTURE and (not recipe.custom_texture or recipe.texture == textures.CUSTOM_TEXTURE):
            self._pick_custom_image()
            return
        recipe.texture = key
        self._commit_recipe(doc, light, recipe, bake=True, re_place=False, dragging=False)
        self.refresh_workspace()

    def handle_command(self, cid, msg):
        if cid == ID_TOOL:
            c4d.CallCommand(ids.TOOL_ID)
            return True
        if cid == ID_NEW_RENDERER and self._tool is not None:
            self._tool.renderer = RENDERER_CHOICES[self.GetInt32(ID_NEW_RENDERER)]
            return True

        doc = c4d.documents.GetActiveDocument()
        if doc is None:
            return True

        if cid == ID_UNSOLO:
            doc.StartUndo()
            lights.set_solo(doc, None, undo=True)
            doc.EndUndo()
            c4d.EventAdd()
            self.refresh_workspace()
            return True

        if cid == ID_DELETE_LIGHT:
            light = self._active_light(doc)
            if light is not None:
                doc.StartUndo()
                doc.AddUndo(c4d.UNDOTYPE_DELETE, light)
                light.Remove()
                lights.sync_octane_links(doc)
                doc.EndUndo()
                c4d.EventAdd()
                self.refresh_workspace()
            return True

        if cid == ID_GOBO_BROWSE:
            chosen = c4d.storage.LoadDialog(
                type=c4d.FILESELECTTYPE_ANYTHING,
                title="Select Custom Gobo Texture Folder",
                flags=c4d.FILESELECT_DIRECTORY,
                def_path=self._gobo_root or "",
            )
            if chosen and os.path.isdir(chosen):
                self._gobo_root = chosen
                _save_gobo_folder(chosen)
                self._gobo_cat_idx = 0
                self._gobo_file_idx = 0
                self._scan_gobo_root()
                self._rebuild_gobo_combos()
                self.refresh_workspace()
            return True

        if cid == ID_GOBO_CAT:
            self._gobo_cat_idx = max(self.GetInt32(ID_GOBO_CAT), 0)
            self._gobo_file_idx = 0
            self._scan_gobo_category()
            self._rebuild_gobo_combos()
            self._apply_selected_gobo()
            return True

        if cid == ID_GOBO_FILE:
            self._gobo_file_idx = max(self.GetInt32(ID_GOBO_FILE), 0)
            self._apply_selected_gobo()
            return True

        if cid == ID_GOBO_PREV:
            if self._gobo_files:
                self._gobo_file_idx = (self._gobo_file_idx - 1) % len(self._gobo_files)
                self.SetInt32(ID_GOBO_FILE, self._gobo_file_idx)
                self._apply_selected_gobo()
            return True

        if cid == ID_GOBO_NEXT:
            if self._gobo_files:
                self._gobo_file_idx = (self._gobo_file_idx + 1) % len(self._gobo_files)
                self.SetInt32(ID_GOBO_FILE, self._gobo_file_idx)
                self._apply_selected_gobo()
            return True

        light = self._active_light(doc)
        if light is None:
            return True

        if cid == ID_DUPLICATE:
            doc.StartUndo()
            lights.duplicate(doc, light)
            doc.EndUndo()
            c4d.EventAdd()
            self.refresh_workspace()
            return True

        if cid == ID_PICK_IMAGE:
            self._pick_custom_image()
            return True

        if cid in (ID_LINK_MODE, ID_LINK_CLEAR, ID_LINK_LIST):
            self._edit_links(doc, light, cid)
            return True

        recipe = lights.read_recipe(light)
        old_dist = max(recipe.distance, 0.1)
        old_w, old_h = max(recipe.width, 0.1), max(recipe.height, 0.1)
        old_area = old_w * old_h

        # Explicit per-control dispatch: never read unrelated gadgets or overwrite visibility/enable state
        if cid == ID_DISTANCE:
            recipe.distance = max(self.GetFloat(ID_DISTANCE), 0.1)
            if recipe.constant_lux:
                recipe.exposure = round(
                    recipe.exposure + placement.constant_lux_ev_delta(old_dist, recipe.distance, old_area, old_area),
                    3,
                )
        elif cid == ID_ROTATION:
            recipe.rotation = self.GetFloat(ID_ROTATION) % 360.0
        elif cid == ID_RESET_ROT:
            recipe.rotation = 0.0
        elif cid == ID_EXPOSURE:
            recipe.exposure = self.GetFloat(ID_EXPOSURE)
        elif cid == ID_RESET_EV:
            recipe.exposure = 0.0
        elif cid == ID_INTENSITY:
            recipe.intensity = max(self.GetFloat(ID_INTENSITY), 0.0)
        elif cid in (ID_WIDTH, ID_HEIGHT):
            new_w = max(self.GetFloat(ID_WIDTH), 0.1)
            new_h = max(self.GetFloat(ID_HEIGHT), 0.1)
            if recipe.aspect_lock:
                ratio = old_w / old_h
                if cid == ID_WIDTH:
                    new_h = max(round(new_w / max(ratio, 1e-4), 2), 0.1)
                elif cid == ID_HEIGHT:
                    new_w = max(round(new_h * ratio, 2), 0.1)
            recipe.width, recipe.height = new_w, new_h
            if recipe.constant_lux:
                recipe.exposure = round(
                    recipe.exposure + placement.constant_lux_ev_delta(old_dist, old_dist, old_area, new_w * new_h),
                    3,
                )
        elif cid == ID_ASPECT_LOCK:
            recipe.aspect_lock = self.GetBool(ID_ASPECT_LOCK)
        elif cid == ID_CONST_LUX:
            recipe.constant_lux = self.GetBool(ID_CONST_LUX)
        elif cid == ID_SPREAD:
            recipe.spread = max(min(self.GetFloat(ID_SPREAD), 1.0), 0.0)
        elif cid == ID_COLOR_MODE:
            recipe.color_mode = recipe_mod.COLOR_MODES[self.GetInt32(ID_COLOR_MODE)]
            recipe.gels = []
        elif cid == ID_KELVIN:
            recipe.kelvin = self.GetFloat(ID_KELVIN)
            recipe.gels = []
        elif cid == ID_RESET_KELVIN:
            recipe.kelvin = 6500.0
            recipe.gels = []
        elif cid == ID_TINT:
            cf = self.GetColorField(ID_TINT)
            if cf is not None and "color" in cf:
                cv = cf["color"]
                recipe.tint = list(photometry.srgb_to_linear((cv.x, cv.y, cv.z)))
                if recipe.color_mode == "kelvin":
                    recipe.color_mode = "kelvin_tint"
            recipe.gels = []
        elif cid == ID_RESET_TINT:
            recipe.tint = [1.0, 1.0, 1.0]
            recipe.gels = []
        elif cid == ID_SOFTNESS:
            recipe.softness = max(self.GetFloat(ID_SOFTNESS), 0.05)
        elif cid == ID_RESET_SOFT:
            recipe.softness = 1.0
        else:
            return True

        dragging = bool(msg.GetBool(c4d.BFM_ACTION_INDRAG))
        bake = (cid in _BAKE_IDS) and not dragging
        self._commit_recipe(doc, light, recipe, bake=bake, re_place=(cid in _PLACE_IDS), dragging=dragging)
        if not dragging:
            self.refresh_workspace()
        else:
            # Update coupled numeric fields live while dragging without tearing down active slider drag
            if cid in (ID_DISTANCE, ID_WIDTH, ID_HEIGHT):
                if recipe.aspect_lock:
                    if cid == ID_WIDTH:
                        self.SetFloat(ID_HEIGHT, recipe.height, 5.0, 600.0, 1.0, c4d.FORMAT_METER, 0.1, 100000.0, True)
                    elif cid == ID_HEIGHT:
                        self.SetFloat(ID_WIDTH, recipe.width, 5.0, 600.0, 1.0, c4d.FORMAT_METER, 0.1, 100000.0, True)
                if recipe.constant_lux:
                    self.SetFloat(ID_EXPOSURE, recipe.exposure, -10.0, 10.0, 0.1, c4d.FORMAT_FLOAT, -30.0, 30.0)
            if cid == ID_KELVIN:
                self._kelvin_area.kelvin = recipe.kelvin
                self._kelvin_area.Redraw()
        return True


class ToolDialog(WorkspaceMixin, c4d.gui.SubDialog):
    """Full Luxe workspace embedded directly in Cinema 4D's Attribute Manager when Luxe Light Tool is active."""

    def __init__(self, tool):
        c4d.gui.SubDialog.__init__(self)
        self._init_workspace(tool=tool)

    def CreateLayout(self):
        return self._build_workspace()

    def InitValues(self):
        self.refresh_workspace(force=True)
        return True

    def CoreMessage(self, cid, msg):
        if cid == c4d.EVMSG_CHANGE:
            self.refresh_workspace()
        return c4d.gui.SubDialog.CoreMessage(self, cid, msg)

    def Command(self, cid, msg):
        return self.handle_command(cid, msg)


class LuxePanel(WorkspaceMixin, c4d.gui.GeDialog):
    """Dockable / floating Luxe studio workspace opened from Extensions > Luxe."""

    def __init__(self):
        c4d.gui.GeDialog.__init__(self)
        self._init_workspace(tool=None)

    def CreateLayout(self):
        self.SetTitle("Luxe")
        return self._build_workspace()

    def InitValues(self):
        self.refresh_workspace(force=True)
        return True

    def CoreMessage(self, cid, msg):
        if cid == c4d.EVMSG_CHANGE:
            self.refresh_workspace()
        return c4d.gui.GeDialog.CoreMessage(self, cid, msg)

    def Command(self, cid, msg):
        return self.handle_command(cid, msg)


class LuxeCommand(c4d.plugins.CommandData):
    dialog = None

    def Execute(self, doc):
        if self.dialog is None:
            self.dialog = LuxePanel()
        return self.dialog.Open(dlgtype=c4d.DLG_TYPE_ASYNC, pluginid=ids.PANEL_ID, defaultw=360, defaulth=760)

    def RestoreLayout(self, sec_ref):
        if self.dialog is None:
            self.dialog = LuxePanel()
        return self.dialog.Restore(pluginid=ids.PANEL_ID, secret=sec_ref)
