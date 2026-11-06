"""Where a light goes when you click a surface.

Every mode takes the hit point, the surface normal there and the direction of the camera ray that found it, and
returns the light position plus the direction the light faces (always back at the hit point).

- reflect: the light sits at the mirror point, so its highlight lands exactly where you clicked. r = d - 2(d.n)n,
  the same rule as r = 2(n.v)n - v with v = -d pointing at the camera.
- normal:  the light sits on the surface normal and lights the spot head-on.
- orbit:   the light circles a locked target spot along `orbit_dir` (starting from the reflection direction).
- direct:  the light sits on the camera ray, between the camera and the spot.
- rim:     the light sits behind the spot as seen from the camera, off to the side the surface faces, so it draws
           an edge. `rim_back` tilts it further behind (0 = beside the object, 1 = 45 degrees behind).
"""
import math

from . import vec

MODES = ("reflect", "normal", "orbit", "direct", "rim")

# Lighting by reflection: a source 0.6-0.7 object sizes away gives a face a gradient.
DEFAULT_DISTANCE_FACTOR = 0.65
DEFAULT_SIZE_FACTOR = 0.28


def default_distance(object_size):
    return DEFAULT_DISTANCE_FACTOR * object_size


def default_size(object_size):
    """Sensible initial width/height scaled from the hit mesh's bounding diagonal."""
    return min(max(round(DEFAULT_SIZE_FACTOR * object_size, 1), 10.0), 500.0)


def constant_lux_ev_delta(old_distance, new_distance, old_area, new_area):
    """EV offset that keeps surface illuminance constant when distance or emitter area changes."""
    d_ratio = max(float(new_distance), 1e-4) / max(float(old_distance), 1e-4)
    a_ratio = max(float(old_area), 1e-4) / max(float(new_area), 1e-4)
    return 2.0 * math.log2(d_ratio) + math.log2(a_ratio)


def _rodrigues(v, axis, angle):
    k = vec.normalize(axis)
    c, s = math.cos(angle), math.sin(angle)
    return vec.add(
        vec.add(vec.scale(v, c), vec.scale(vec.cross(k, v), s)),
        vec.scale(k, vec.dot(k, v) * (1.0 - c)),
    )


def orbit_direction(direction, right, up, yaw_rad, pitch_rad):
    """Rotate unit `direction` around `up` by `yaw_rad` and around horizontal `right` by `pitch_rad`."""
    d = vec.normalize(direction)
    u = vec.normalize(up)
    if abs(yaw_rad) > 1e-9:
        d = vec.normalize(_rodrigues(d, u, yaw_rad))
    if abs(pitch_rad) > 1e-9:
        r_proj = vec.sub(right, vec.scale(u, vec.dot(right, u)))
        r = vec.normalize(r_proj) if vec.length(r_proj) > 1e-6 else vec.normalize(right)
        cand = vec.normalize(_rodrigues(d, r, pitch_rad))
        if abs(vec.dot(cand, u)) < 0.995:  # avoid flipping past the poles
            d = cand
    return d


def light_direction(mode, normal, ray_dir, rim_back=1.0, orbit_dir=None):
    """Unit vector from the hit point toward the light."""
    n = vec.normalize(normal)
    d = vec.normalize(ray_dir)
    if vec.dot(n, d) > 0:  # the ray hit a back face: use the side that faces the camera
        n = vec.scale(n, -1.0)
    if mode == "reflect":
        return vec.normalize(vec.sub(d, vec.scale(n, 2.0 * vec.dot(d, n))))
    if mode == "orbit":
        if orbit_dir is not None and vec.length(orbit_dir) > 1e-9:
            return vec.normalize(orbit_dir)
        return vec.normalize(vec.sub(d, vec.scale(n, 2.0 * vec.dot(d, n))))
    if mode == "normal":
        return n
    if mode == "direct":
        return vec.scale(d, -1.0)
    if mode == "rim":
        side = vec.sub(n, vec.scale(d, vec.dot(n, d)))  # the part of n across the view
        if vec.length(side) < 1e-6:  # surface faces the camera square-on: pick screen-up
            side = vec.cross(d, (1.0, 0.0, 0.0))
            if vec.length(side) < 1e-6:
                side = vec.cross(d, (0.0, 0.0, 1.0))
        return vec.normalize(vec.add(vec.normalize(side), vec.scale(d, rim_back)))
    raise ValueError("unknown mode %r, expected one of %s" % (mode, ", ".join(MODES)))


def place(mode, hit, normal, ray_dir, distance, rim_back=1.0, orbit_dir=None):
    """Return (position, forward) for a light placed from a surface hit."""
    direction = light_direction(mode, normal, ray_dir, rim_back, orbit_dir)
    position = vec.add(hit, vec.scale(direction, distance))
    return position, vec.scale(direction, -1.0)


def look_at(position, forward, up=(0.0, 1.0, 0.0), roll_deg=0.0):
    """A frame (offset, x, y, z) whose z axis is `forward`, rotated about z by `roll_deg`.

    x = up cross z and y = z cross x, which reproduces the identity frame for forward = +Z and up = +Y.
    """
    z = vec.normalize(forward)
    if abs(vec.dot(z, vec.normalize(up))) > 0.999:  # looking straight up or down
        up = (0.0, 0.0, 1.0)
    x = vec.normalize(vec.cross(up, z))
    y = vec.cross(z, x)
    if abs(roll_deg) > 1e-9:
        rad = math.radians(roll_deg)
        c, s = math.cos(rad), math.sin(rad)
        x, y = vec.add(vec.scale(x, c), vec.scale(y, s)), vec.add(vec.scale(x, -s), vec.scale(y, c))
    return position, x, y, z
