"""Procedural light textures: shapes stacked as layers, baked to an EXR the light shows on its surface.

Every texture is generated here from a few parameters, so Luxe ships no image files and owes no licences. A
texture is a list of layers. Each layer is a shape, its parameters, a blend mode and an opacity, composited from
black in order. Shapes take (u, v) in 0-1 with v = 0 at the top, plus the texture's aspect (width / height) so
round shapes stay round on a long light.

Pure Python on purpose: Cinema 4D's Python has no numpy. 512 px is the default: most presets bake in 0.2-1 s,
the noise ones in about 3 s (measured on the cloud test machine, 2026-11-01).
"""
import math
import struct

CUSTOM_TEXTURE = "__custom__"
SHAPES = {}


def _shape(fn):
    SHAPES[fn.__name__] = fn
    return fn


def _smoothstep(e0, e1, x):
    if e1 == e0:
        return 0.0 if x < e0 else 1.0
    t = (x - e0) / (e1 - e0)
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return t * t * (3.0 - 2.0 * t)


def _round_coords(u, v, aspect):
    """Centred coordinates scaled so the shorter side spans -1..1."""
    return (2.0 * u - 1.0) * max(aspect, 1.0), (2.0 * v - 1.0) * max(1.0 / aspect, 1.0)


@_shape
def constant(u, v, aspect, value=1.0):
    return value


@_shape
def softbox(u, v, aspect, edge=0.12):
    """A rectangle filling the light, its border fading over `edge` (fraction of the half-size)."""
    return _smoothstep(0.0, edge, 1.0 - abs(2.0 * u - 1.0)) * _smoothstep(0.0, edge, 1.0 - abs(2.0 * v - 1.0))


@_shape
def polygon(u, v, aspect, sides=8, edge=0.08, rotation=0.0):
    """A regular polygon (sides < 3 gives a circle) inscribed in the shorter side."""
    x, y = _round_coords(u, v, aspect)
    r = math.hypot(x, y)
    limit = 1.0
    if sides >= 3:
        a = (math.atan2(y, x) - rotation) % (2.0 * math.pi / sides) - math.pi / sides
        limit = math.cos(math.pi / sides) / math.cos(a)
    return _smoothstep(0.0, edge, 1.0 - r / limit)


@_shape
def ring(u, v, aspect, inner=0.55, outer=0.9, edge=0.06):
    x, y = _round_coords(u, v, aspect)
    r = math.hypot(x, y)
    return _smoothstep(inner - edge, inner, r) * (1.0 - _smoothstep(outer, outer + edge, r))


@_shape
def spot(u, v, aspect, radius=0.8):
    """A soft glow, brightest at the centre."""
    x, y = _round_coords(u, v, aspect)
    return 1.0 - _smoothstep(0.0, radius, math.hypot(x, y))


def _axis(u, v, axis):
    return u if axis == "u" else v


@_shape
def ramp(u, v, aspect, axis="u", start=1.0, end=0.0, gamma=1.0):
    t = _axis(u, v, axis)
    return start + (end - start) * t**gamma


@_shape
def step(u, v, aspect, axis="u", position=0.5, softness=0.02):
    t = _axis(u, v, axis)
    return 1.0 - _smoothstep(position - softness, position + softness, t)


@_shape
def band(u, v, aspect, axis="u", center=0.5, width=0.18):
    t = _axis(u, v, axis)
    return math.exp(-0.5 * ((t - center) / width) ** 2)


@_shape
def fade_ends(u, v, aspect, axis="v", fade=0.25):
    t = _axis(u, v, axis)
    return _smoothstep(0.0, fade, t) * _smoothstep(0.0, fade, 1.0 - t)


@_shape
def grid(u, v, aspect, cols=2, rows=2, bar=0.04, softness=0.006):
    """Window panes: 1 inside the panes, 0 on the bars and the frame."""
    du = min(abs(u - k / cols) for k in range(cols + 1))
    dv = min(abs(v - k / rows) for k in range(rows + 1))
    half = bar / 2.0
    return _smoothstep(half, half + softness, du) * _smoothstep(half, half + softness, dv)


@_shape
def stripes(u, v, aspect, axis="v", count=10, duty=0.6, softness=0.04):
    f = (_axis(u, v, axis) * count) % 1.0
    return _smoothstep(0.0, softness, f) * (1.0 - _smoothstep(duty - softness, duty, f))


def _hash(ix, iy, seed):
    h = (ix * 374761393 + iy * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFF) / float(0x1000000)


def _value_noise(x, y, seed):
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash(ix, iy, seed), _hash(ix + 1, iy, seed)
    c, d = _hash(ix, iy + 1, seed), _hash(ix + 1, iy + 1, seed)
    return (a + (b - a) * sx) + ((c + (d - c) * sx) - (a + (b - a) * sx)) * sy


@_shape
def noise(u, v, aspect, scale=5.0, seed=1, octaves=3, contrast=1.0):
    total, amp, norm, freq = 0.0, 1.0, 0.0, scale
    for o in range(octaves):
        total += amp * _value_noise(u * freq * aspect, v * freq, seed + o)
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return min(max(0.5 + (total / norm - 0.5) * contrast, 0.0), 1.0)


@_shape
def foliage(u, v, aspect, scale=6.0, density=0.55, edge=0.15, seed=7):
    """Organic dappled leaf canopy: scattered cellular apertures with smooth edge falloff."""
    x, y = u * scale * aspect, v * scale
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    d1 = 1e9
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            cx, cy = ix + dx, iy + dy
            h = (cx * 374761393 + cy * 668265263 + seed * 2147483647) & 0xFFFFFFFF
            h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
            h1 = ((h ^ (h >> 16)) & 0xFFFF) / 65536.0
            h2 = (((h * 13) ^ (h >> 16)) & 0xFFFF) / 65536.0
            r = 0.35 + 0.30 * (((h * 31) ^ (h >> 12)) & 0xFF) / 255.0
            dist = math.hypot(dx + h1 - fx, dy + h2 - fy) / r
            if dist < d1:
                d1 = dist
    t = (d1 - (density - edge)) / max(2.0 * edge, 1e-4)
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return t * t * (3.0 - 2.0 * t)


@_shape
def caustic(u, v, aspect, scale=7.0, power=2.0, seed=12):
    """Organic water ripple caustics using second-order cellular distances."""
    x, y = u * scale * aspect, v * scale
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    d1, d2 = 1e9, 1e9
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            cx, cy = ix + dx, iy + dy
            h = (cx * 374761393 + cy * 668265263 + seed * 2147483647) & 0xFFFFFFFF
            h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
            h1 = ((h ^ (h >> 16)) & 0xFFFF) / 65536.0
            h2 = (((h * 13) ^ (h >> 16)) & 0xFFFF) / 65536.0
            dist = math.hypot(dx + h1 - fx, dy + h2 - fy)
            if dist < d1:
                d2 = d1
                d1 = dist
            elif dist < d2:
                d2 = dist
    val = min(max((d2 - d1) * 1.8, 0.0), 1.0)
    return val ** max(power, 0.1)


def _blend(mode, base, top, opacity):
    if mode == "normal":
        result = top
    elif mode == "add":
        result = base + top
    elif mode == "multiply":
        result = base * top
    elif mode == "screen":
        result = 1.0 - (1.0 - base) * (1.0 - top)
    elif mode == "max":
        result = max(base, top)
    elif mode == "subtract":
        result = max(base - top, 0.0)
    else:
        raise ValueError("unknown blend mode %r" % mode)
    return base + (result - base) * opacity


BLEND_MODES = ("normal", "add", "multiply", "screen", "max", "subtract")


def layer(shape, blend="normal", opacity=1.0, **params):
    if shape not in SHAPES:
        raise ValueError("unknown shape %r" % shape)
    return {"shape": shape, "blend": blend, "opacity": opacity, "params": params}


PRESETS = {
    "Softbox": [layer("softbox", edge=0.12)],
    "Softbox Hard Edge": [layer("softbox", edge=0.02)],
    "Softbox Hot Centre": [layer("softbox", edge=0.12), layer("spot", "add", 0.6, radius=0.9)],
    "Strip": [layer("softbox", edge=0.08), layer("fade_ends", "multiply", axis="v", fade=0.2)],
    "Octabox": [layer("polygon", sides=8, edge=0.06)],
    "Round": [layer("polygon", sides=0, edge=0.1)],
    "Ring": [layer("ring")],
    "Window 2x2": [layer("softbox", edge=0.03), layer("grid", "multiply", cols=2, rows=2)],
    "Window 4x3": [layer("softbox", edge=0.03), layer("grid", "multiply", cols=4, rows=3, bar=0.03)],
    "Blinds": [layer("softbox", edge=0.02), layer("stripes", "multiply", count=8, duty=0.55)],
    "Gradient Soft Fade": [layer("ramp", axis="u")],
    "Gradient Hard Edge": [layer("step", axis="u")],
    "Gradient Centre Hot": [layer("band", axis="u")],
    "Gradient Fade Both Ends": [layer("fade_ends", axis="u", fade=0.3)],
    "Dapple": [layer("softbox", edge=0.03), layer("noise", "multiply", scale=2.5, contrast=2.5)],
    "Scrim": [layer("softbox", edge=0.25), layer("noise", "multiply", 0.5, scale=3.0, contrast=0.4)],
    "Foliage": [layer("foliage", scale=3.2, density=0.55), layer("softbox", "multiply", edge=0.03)],
    "Caustic": [layer("caustic", scale=4.0, power=2.0), layer("softbox", "multiply", edge=0.03)],
}

PRESET_LABELS = {
    "": "Plain",
    "Softbox": "Softbox",
    "Softbox Hard Edge": "Hard Box",
    "Softbox Hot Centre": "Hot Box",
    "Strip": "Strip",
    "Octabox": "Octabox",
    "Round": "Round",
    "Ring": "Ring",
    "Window 2x2": "Win 2x2",
    "Window 4x3": "Win 4x3",
    "Blinds": "Blinds",
    "Gradient Soft Fade": "Soft Ramp",
    "Gradient Hard Edge": "Hard Step",
    "Gradient Centre Hot": "Band",
    "Gradient Fade Both Ends": "End Fade",
    "Dapple": "Dapple",
    "Scrim": "Scrim",
    "Foliage": "Foliage",
    "Caustic": "Caustic",
    CUSTOM_TEXTURE: "Image...",
}


def scale_softness(layers, softness=1.0):
    """Return a copy of `layers` with edge/feather parameters scaled by `softness` (1.0 = unchanged)."""
    s = float(softness)
    if abs(s - 1.0) < 1e-4:
        return layers
    out = []
    for lay in layers:
        p = dict(lay.get("params", {}))
        sh = lay["shape"]
        if sh in ("softbox", "polygon"):
            base = p.get("edge", 0.12 if sh == "softbox" else 0.08)
            p["edge"] = min(max(base * s, 0.002), 0.95)
        elif sh == "ring":
            p["edge"] = min(max(p.get("edge", 0.06) * s, 0.002), 0.45)
        elif sh in ("step", "grid", "stripes"):
            default_soft = {"step": 0.02, "grid": 0.006, "stripes": 0.04}[sh]
            p["softness"] = min(max(p.get("softness", default_soft) * s, 0.001), 0.45)
        elif sh == "fade_ends":
            p["fade"] = min(max(p.get("fade", 0.25) * s, 0.005), 0.5)
        elif sh == "band":
            p["width"] = min(max(p.get("width", 0.18) * s, 0.02), 0.8)
        elif sh == "ramp":
            p["gamma"] = min(max(p.get("gamma", 1.0) / max(s, 0.1), 0.2), 5.0)
        elif sh == "foliage":
            p["edge"] = min(max(p.get("edge", 0.15) * s, 0.02), 0.5)
        elif sh == "caustic":
            p["power"] = min(max(p.get("power", 2.0) / max(s, 0.2), 0.5), 6.0)
        out.append({"shape": sh, "blend": lay.get("blend", "normal"), "opacity": lay.get("opacity", 1.0), "params": p})
    return out


def composite(layers, width, height):
    """Row-major grey values, top row first."""
    out = [0.0] * (width * height)
    aspect = width / float(height)
    for lay in layers:
        fn, params = SHAPES[lay["shape"]], lay.get("params", {})
        mode, opacity = lay.get("blend", "normal"), lay.get("opacity", 1.0)
        i = 0
        for row in range(height):
            v = (row + 0.5) / height
            for col in range(width):
                out[i] = _blend(mode, out[i], fn((col + 0.5) / width, v, aspect, **params), opacity)
                i += 1
    return out


def size_for(light_width, light_height, resolution=512):
    """Pixel size whose aspect matches the light, long side = resolution."""
    if light_width >= light_height:
        return resolution, max(1, round(resolution * light_height / light_width))
    return max(1, round(resolution * light_width / light_height)), resolution


HALF_MAX = 65504.0


def write_exr(path, width, height, grey, tint=(1.0, 1.0, 1.0)):
    """Write grey values times an RGB tint as an uncompressed half-float scanline EXR."""
    def attr(name, kind, data):
        return name.encode() + b"\0" + kind.encode() + b"\0" + struct.pack("<i", len(data)) + data

    channels = b"".join(c + b"\0" + struct.pack("<iB3xii", 1, 0, 1, 1) for c in (b"B", b"G", b"R")) + b"\0"
    box = struct.pack("<iiii", 0, 0, width - 1, height - 1)
    header = (
        struct.pack("<ii", 20000630, 2)
        + attr("channels", "chlist", channels)
        + attr("compression", "compression", b"\0")
        + attr("dataWindow", "box2i", box)
        + attr("displayWindow", "box2i", box)
        + attr("lineOrder", "lineOrder", b"\0")
        + attr("pixelAspectRatio", "float", struct.pack("<f", 1.0))
        + attr("screenWindowCenter", "v2f", struct.pack("<ff", 0.0, 0.0))
        + attr("screenWindowWidth", "float", struct.pack("<f", 1.0))
        + b"\0"
    )
    row_bytes = width * 3 * 2
    first = len(header) + 8 * height
    offsets = struct.pack("<%dQ" % height, *(first + y * (8 + row_bytes) for y in range(height)))
    fmt = "<%de" % width
    with open(path, "wb") as f:
        f.write(header + offsets)
        for y in range(height):
            row = grey[y * width:(y + 1) * width]
            f.write(struct.pack("<ii", y, row_bytes))
            for t in (tint[2], tint[1], tint[0]):  # channels in name order: B, G, R
                f.write(struct.pack(fmt, *(min(max(g * t, 0.0), HALF_MAX) for g in row)))


def bake(preset_or_layers, path, light_width, light_height, tint=(1.0, 1.0, 1.0), resolution=512):
    """Generate a texture for a light of the given size and write it to `path`. Returns (width, height)."""
    layers = PRESETS[preset_or_layers] if isinstance(preset_or_layers, str) else preset_or_layers
    w, h = size_for(light_width, light_height, resolution)
    write_exr(path, w, h, composite(layers, w, h), tint)
    return w, h
