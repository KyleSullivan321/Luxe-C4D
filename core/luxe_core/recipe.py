"""A Luxe light as plain data: what the workspace edits, what the scene stores, what each renderer adapter applies."""
import json
from dataclasses import asdict, dataclass, field, fields

from . import photometry

RENDERERS = ("redshift", "octane")
COLOR_MODES = ("kelvin_tint", "kelvin", "rgb")


@dataclass
class LightRecipe:
    name: str = "Luxe Light"
    renderer: str = "redshift"
    mode: str = "reflect"
    exposure: float = 0.0  # EV
    intensity: float = 1.0  # multiplier on top of exposure
    color_mode: str = "kelvin_tint"  # "kelvin_tint", "kelvin", or "rgb"
    kelvin: float = 6500.0
    tint: list = field(default_factory=lambda: [1.0, 1.0, 1.0])  # linear RGB 0..1
    gels: list = field(default_factory=list)  # legacy stored recipes only
    gel_loss: bool = True  # legacy stop loss when `gels` is non-empty
    width: float = 30.0  # cm, the light's own size
    height: float = 30.0
    rotation: float = 0.0  # degrees around the light's +Z aim axis
    spread: float = 1.0  # 1 = full hemisphere, lower = more directional
    texture: str = ""  # a textures.PRESETS name, "__custom__", or "" for a plain light
    softness: float = 1.0  # multiplier on procedural texture edge feathering
    custom_texture: str = ""  # user image file path when texture == "__custom__"
    distance: float = 100.0  # cm from the anchor point
    aspect_lock: bool = False
    constant_lux: bool = False  # auto-compensate EV when distance or size changes
    viewport_visible: bool = True  # drawn in C4D 3D viewport editor
    camera_visible: bool = False  # seen directly by primary camera rays (default False for studio lighting)
    enabled: bool = True
    anchor: dict = field(default_factory=dict)  # hit, normal, ray_dir (and optional orbit_dir)

    def colour(self):
        t = [min(max(float(c), 0.0), 1.0) for c in (self.tint or [1.0, 1.0, 1.0])[:3]]
        while len(t) < 3:
            t.append(1.0)
        if self.color_mode == "rgb":
            return (t[0], t[1], t[2])
        k_rgb = photometry.apply_gels(self.kelvin, self.gels)[0]
        if self.color_mode == "kelvin":
            return k_rgb
        return (k_rgb[0] * t[0], k_rgb[1] * t[1], k_rgb[2] * t[2])

    def total_exposure(self):
        loss = photometry.apply_gels(self.kelvin, self.gels)[1] if (self.gel_loss and self.gels) else 0.0
        return self.exposure - loss

    def to_json(self):
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text):
        """Read a stored recipe; keys this version does not know are dropped, missing ones get defaults."""
        data = json.loads(text)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
