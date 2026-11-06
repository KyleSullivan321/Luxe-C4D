"""Plugin IDs and renderer IDs.

Both plugin IDs are permanent, registered at developers.maxon.net on 2026-11-06. Following Maxon's convention, the
tool's ID also keys Luxe's data containers.
"""
TOOL_ID = 1073479  # Luxe Light Tool
PANEL_ID = 1073480  # Luxe panel command
# Container slot on each Luxe light (1 = recipe JSON, 2 = texture path, 3 = Octane pass ID), on the document
# (10 = solo GUID) and on Octane Object tags Luxe touches (1-2 = marks).
DATA_ID = TOOL_ID
LEGACY_DATA_ID = 1000003  # where Luxe kept the same data before 2026-11-06: still read, moved on the next write

REDSHIFT_ENGINE = 1036219  # render engine IDs in Render Settings
OCTANE_ENGINE = 1029525
REDSHIFT_LIGHT = 1036751  # Redshift Light object
OCTANE_LIGHT_TAG = 1029526  # Octane Light tag, on a C4D area light
OCTANE_IMAGE_TEXTURE = 1029508  # Octane ImageTexture shader
OCTANE_RGB_SPECTRUM = 1029504  # Octane RGB color shader (tints custom image textures)
OCTANE_TRANSFORM = 1030961  # Octane Transform shader (scales/rotates gobo distributions)
OCTANE_PROJECTION = 1031460  # Octane Projection shader (perspective frustum projector for gobos)

