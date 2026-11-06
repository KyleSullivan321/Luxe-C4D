# Luxe user guide

Luxe places lights by clicking your model. Click where the light should land, drag to slide the highlight across
the surface, and shape the light in photographic terms: EV, Kelvin, gels, size and spread.

Tested on Windows with Cinema 4D 2027, Redshift 2027 and Octane 2027.1 Beta. Nothing else has been tested.

## Install

Pick one:

- **Add Folder:** unzip the release anywhere, then in Cinema 4D choose **Edit > Preferences > Plugins > Add Folder**
  and pick the `Luxe` folder. Restart Cinema 4D.
- **Plugins folder:** unzip the release so the `Luxe` folder sits inside Cinema 4D's `plugins` folder. Restart.

You get two new entries under **Extensions**: **Luxe Light Tool** and **Luxe** (the panel).

## The Luxe Light Tool

Choose **Extensions > Luxe Light Tool**. Hover a model: markers show the spot under the cursor and the
direction the light will point from it. New lights use the renderer in Render Settings, or the one picked under
"New Lights" in the tool's settings.

### Mouse

| Action | Result |
| --- | --- |
| Click | With no Luxe light selected, makes a light sized to the object. With one selected, moves it to light the clicked spot. |
| Shift+click | Makes another new light at the clicked spot. |
| Drag | Slides the highlight across the surface. In Orbit mode it circles the locked spot instead. |
| Shift+drag | Resizes the selected light, keeping its shape. |
| Ctrl+drag | Moves the light closer or further. |
| Shift+Ctrl+drag | Rolls the light around its own axis. (Alt+drag also rolls.) |
| Scroll | Normal camera zoom. |
| Shift+scroll | Size. |
| Ctrl+scroll | Exposure, 0.1 EV per step. |
| Alt+scroll | Distance. |
| Shift+Ctrl+scroll | Spread. |

With **Constant Illumination** on, size and distance changes adjust EV so the light on the spot stays the same.

### Keys

These work while the tool is active.

| Key | Result |
| --- | --- |
| R | Reflection mode: the highlight lands where you click. |
| N | Normal mode: the light faces the spot. |
| O | Orbit mode: drag to circle the spot. |
| D | Direct mode: light from the camera side. |
| M | Rim mode: edge light from behind. |
| S | Solo the selected light (mutes all other scene lights). Press again to undo. |
| V | Show or hide the light in the viewport. |
| C | Make the light visible or invisible to the camera. |
| I | Constant Illumination on or off. |
| K | Step the colour temperature through 3200, 4500, 5600, 6500 and 8000 K. |
| [ and ] | Previous or next built-in light texture. |
| + and - | Exposure up or down by 0.5 EV. |
| L | Add the object under the cursor to the selected light's link list, or remove it. |

## The Luxe panel

Open **Extensions > Luxe**, or use the same controls in the tool's Attribute Manager page.

- **New Lights:** which renderer new lights use (Match Render Settings, Redshift or Octane).
- **Scene Lights:** one row per Luxe light with its mode, EV and colour. Buttons on each row switch solo,
  viewport visibility and camera visibility, or delete the light. Below the rows: Duplicate, Unsolo All, Delete.
- **Placement & Aim:** the five modes, Distance, Rotation, and Constant Illumination (Auto EV).
- **Output & Size:** Exposure (EV), Intensity, Width, Height, Spread, and a Lock Aspect Ratio switch.
- **Color:** Kelvin + Tint, Kelvin Only or RGB Color; a Temperature slider with a Kelvin strip; a colour swatch.
- **Light Linking:** choose which objects the light affects. See below.
- **Light Texture:** the shape of the light. See below.

## Textures and gobos

A light texture sets the shape and pattern of the light. Luxe has built-in textures: Softbox, Strip, Octabox,
Round, Ring, Window, Blinds, gradients, Dapple, Scrim, Foliage and Caustic. Pick one in the gallery, or step
through them with [ and ]. **Edge Softness** blurs the edges of the shape.

To use your own gobo images:

1. Under **Local Gobo Library**, press **Folder...** and pick a folder. Luxe remembers it between sessions.
2. Subfolders appear in the first list and the images in the second. Use the list, or the < and > buttons.
3. Or press **Load File...** to use a single image from anywhere.

Luxe reads EXR, HDR, PNG, JPG and TIFF images.

**Spread** on an Octane gobo is the beam angle: 1.0 is 90 degrees, and smaller values narrow the beam.

## Light linking

Light linking limits which objects a light affects. Pick a mode in the panel:

- **Exclude:** the light affects everything except the listed objects.
- **Include:** the light affects only the listed objects.

Press **L** over an object in the viewport to add or remove it, or edit the list in the panel. **Clear** empties it.

How it reaches the renderer:

- **Redshift:** Luxe fills the light's own Project list (include or exclude).
- **Octane:** Luxe gives each linked light a light pass ID and adds Octane Object tags named "Luxe Light Links"
  to the objects involved. Up to 20 Octane lights can be linked at once. In Include mode, only objects that
  existed when the list was last edited are covered, so edit the list again after adding new objects.

## Known issues

- **Octane 2027.1 Beta 1 can crash with CUDA error 700** when lights change during a Live Viewer render on a
  multi-GPU setup that includes an RTX 4070 Ti SUPER. Rendering on one GPU avoids it.
- Octane gobos and light linking were checked in final renders. Their behaviour in the Live Viewer is less tested.
- Luxe lights made with versions before 0.1.0 store their settings under an old ID. Luxe still reads them and moves
  them to its permanent ID the next time you edit the light.
- Windows only, so far.
