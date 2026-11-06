"""Luxe for Cinema 4D: place Redshift and Octane lights by clicking model surfaces.

Install: Preferences > Plugins > Add Folder, pick the folder that holds this file, restart Cinema 4D.
The shared core is found in `lib` beside this file (packaged build) or in the source tree's `core` folder.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REAL = os.path.dirname(os.path.realpath(__file__))
for path in (HERE, os.path.join(HERE, "lib"), os.path.normpath(os.path.join(HERE, "..", "..", "core")),
             os.path.normpath(os.path.join(REAL, "..", "..", "core"))):
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)

import c4d  # noqa: E402

from luxe_c4d import ids, panel, tool  # noqa: E402

if __name__ == "__main__":
    c4d.plugins.RegisterToolPlugin(id=ids.TOOL_ID, str="Luxe Light Tool", info=0, icon=None,
                                   help="Click a surface to place a light", dat=tool.LuxeTool())
    c4d.plugins.RegisterCommandPlugin(id=ids.PANEL_ID, str="Luxe", info=0, icon=None,
                                      help="Controls for the selected Luxe light", dat=panel.LuxeCommand())
