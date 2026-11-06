"""Colour temperature, RGB tinting and legacy gel helpers, shared across every renderer.

Primary colour workflow is direct and artist-friendly: Kelvin blackbody temperature, RGB tint swatch, or both
multiplied together, with no hidden stop loss. Legacy gel definitions remain so older stored recipes load intact.
"""
import math

MIN_KELVIN, MAX_KELVIN = 1667.0, 25000.0  # range of the Planckian-locus fit below


def kelvin_to_xy(kelvin):
    """CIE 1931 xy of a black body (Kim et al. 2002 cubic fit, 1667-25000 K)."""
    t = min(max(float(kelvin), MIN_KELVIN), MAX_KELVIN)
    if t <= 4000:
        x = -0.2661239e9 / t**3 - 0.2343589e6 / t**2 + 0.8776956e3 / t + 0.179910
    else:
        x = -3.0258469e9 / t**3 + 2.1070379e6 / t**2 + 0.2226347e3 / t + 0.240390
    if t <= 2222:
        y = -1.1063814 * x**3 - 1.34811020 * x**2 + 2.18555832 * x - 0.20219683
    elif t <= 4000:
        y = -0.9549476 * x**3 - 1.37418593 * x**2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x**3 - 5.87338670 * x**2 + 3.75112997 * x - 0.37001483
    return x, y


def kelvin_to_rgb(kelvin):
    """Linear Rec.709/sRGB colour of a black body, scaled so the brightest channel is 1."""
    x, y = kelvin_to_xy(kelvin)
    X, Y, Z = x / y, 1.0, (1.0 - x - y) / y
    rgb = (
        3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z,
        -0.9692660 * X + 1.8760108 * Y + 0.0415560 * Z,
        0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z,
    )
    rgb = [max(c, 0.0) for c in rgb]  # very warm light falls just outside sRGB in blue
    peak = max(rgb)
    return tuple(c / peak for c in rgb)


def linear_to_srgb_byte(value):
    """Convert a linear 0..1 channel value to an 8-bit sRGB display byte (0..255)."""
    c = min(max(float(value), 0.0), 1.0)
    s = 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055
    return int(round(min(max(s, 0.0), 1.0) * 255.0))


def srgb_to_linear(rgb):
    """Convert an sRGB 0..1 tuple to linear Rec.709/sRGB."""
    out = []
    for c in rgb[:3]:
        v = min(max(float(c), 0.0), 1.0)
        out.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def linear_to_srgb(rgb):
    """Convert a linear Rec.709/sRGB 0..1 tuple to sRGB 0..1."""
    out = []
    for c in rgb[:3]:
        v = min(max(float(c), 0.0), 1.0)
        out.append(12.92 * v if v <= 0.0031308 else 1.055 * (v ** (1.0 / 2.4)) - 0.055)
    return tuple(out)


def luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def mired(kelvin):
    return 1e6 / kelvin


# Legacy theatrical gel table kept for stored recipe compatibility.
GELS = {
    "Full CTO": (159.0, (1.0, 1.0, 1.0), 0.7),
    "1/2 CTO": (81.0, (1.0, 1.0, 1.0), 0.4),
    "1/4 CTO": (40.0, (1.0, 1.0, 1.0), 0.2),
    "Full CTB": (-131.0, (1.0, 1.0, 1.0), 1.5),
    "1/2 CTB": (-68.0, (1.0, 1.0, 1.0), 0.9),
    "1/4 CTB": (-30.0, (1.0, 1.0, 1.0), 0.5),
    "Plus Green": (0.0, (0.72, 1.0, 0.72), None),
    "1/2 Plus Green": (0.0, (0.86, 1.0, 0.86), None),
    "Minus Green": (0.0, (1.0, 0.72, 1.0), None),
    "1/2 Minus Green": (0.0, (1.0, 0.86, 1.0), None),
    "ND 0.3": (0.0, (1.0, 1.0, 1.0), 1.0),
    "ND 0.6": (0.0, (1.0, 1.0, 1.0), 2.0),
    "ND 0.9": (0.0, (1.0, 1.0, 1.0), 3.0),
    "Straw": (0.0, (1.0, 0.92, 0.72), None),
    "Bastard Amber": (0.0, (1.0, 0.82, 0.66), None),
    "Amber": (0.0, (1.0, 0.70, 0.35), None),
    "Orange": (0.0, (1.0, 0.48, 0.16), None),
    "Red": (0.0, (1.0, 0.07, 0.05), None),
    "Magenta": (0.0, (1.0, 0.20, 0.72), None),
    "Pink": (0.0, (1.0, 0.62, 0.78), None),
    "Lavender": (0.0, (0.74, 0.62, 1.0), None),
    "Congo Blue": (0.0, (0.22, 0.10, 1.0), None),
    "Steel Blue": (0.0, (0.66, 0.80, 1.0), None),
    "Cyan": (0.0, (0.25, 1.0, 1.0), None),
    "Lime": (0.0, (0.62, 1.0, 0.25), None),
}


def gel_loss(name):
    shift, tint, loss = GELS[name]
    return loss if loss is not None else -math.log2(luminance(tint))


def apply_gels(kelvin, gels):
    """Return (rgb, loss_stops) for a light at `kelvin` behind the listed gels, in any order."""
    rgb = list(kelvin_to_rgb(effective_kelvin(kelvin, gels)))
    for g in gels:
        rgb = [c * t for c, t in zip(rgb, GELS[g][1])]
    return tuple(rgb), sum(gel_loss(g) for g in gels)


def effective_kelvin(kelvin, gels):
    """The temperature a light reads at after its CTO and CTB gels."""
    shift = sum(GELS[g][0] for g in gels)
    return 1e6 / max(mired(kelvin) + shift, 1e6 / MAX_KELVIN)
