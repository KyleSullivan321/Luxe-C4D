import math
import os
import shutil
import subprocess
import struct
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from luxe_core import photometry, placement, textures, vec  # noqa: E402
from luxe_core.recipe import LightRecipe  # noqa: E402

S2 = math.sqrt(0.5)


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


class PlacementTest(unittest.TestCase):
    # Camera looks down at 45 degrees onto a floor; the ray hits the origin.
    ray = (0.0, -S2, S2)
    up = (0.0, 1.0, 0.0)

    def test_reflect_is_the_mirror_point(self):
        pos, fwd = placement.place("reflect", (0, 0, 0), self.up, self.ray, 10.0)
        self.assertTrue(close(pos, (0.0, 10 * S2, 10 * S2)))
        self.assertTrue(close(fwd, (0.0, -S2, -S2)))

    def test_reflect_obeys_the_mirror_law_on_a_tilted_face(self):
        n = vec.normalize((1.0, 2.0, -0.5))
        d = vec.normalize((0.3, -1.0, 0.8))
        r = placement.light_direction("reflect", n, d)
        self.assertAlmostEqual(vec.dot(r, n), -vec.dot(d, n))  # angle in = angle out
        self.assertAlmostEqual(vec.length(vec.cross(vec.cross(d, n), vec.cross(r, n))), 0.0)  # same plane

    def test_normal_and_direct(self):
        pos, _ = placement.place("normal", (1, 2, 3), self.up, self.ray, 5.0)
        self.assertTrue(close(pos, (1, 7, 3)))
        pos, _ = placement.place("direct", (0, 0, 0), self.up, self.ray, 4.0)
        self.assertTrue(close(pos, (0.0, 4 * S2, -4 * S2)))  # back along the ray, toward the camera

    def test_orbit_uses_explicit_direction_and_orbits_cleanly(self):
        pos, fwd = placement.place("orbit", (0, 0, 0), self.up, self.ray, 10.0, orbit_dir=(1.0, 0.0, 0.0))
        self.assertTrue(close(pos, (10.0, 0.0, 0.0)))
        self.assertTrue(close(fwd, (-1.0, 0.0, 0.0)))
        rotated = placement.orbit_direction((0.0, 0.0, -1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), math.pi / 2.0, 0.0)
        self.assertTrue(close(rotated, (-1.0, 0.0, 0.0)))

    def test_rim_sits_behind_the_spot(self):
        side_normal = (1.0, 0.0, 0.0)  # a wall seen edge-on from a camera looking down +Z
        pos, _ = placement.place("rim", (0, 0, 0), side_normal, (0.0, 0.0, 1.0), 10.0)
        self.assertGreater(pos[2], 0.0)  # behind, relative to the camera
        self.assertGreater(pos[0], 0.0)  # on the side the surface faces

    def test_rim_survives_a_square_on_surface(self):
        pos, _ = placement.place("rim", (0, 0, 0), (0.0, 0.0, -1.0), (0.0, 0.0, 1.0), 10.0)
        self.assertAlmostEqual(vec.length(pos), 10.0)

    def test_back_face_hit_uses_the_camera_side(self):
        a, _ = placement.place("normal", (0, 0, 0), self.up, self.ray, 1.0)
        b, _ = placement.place("normal", (0, 0, 0), (0, -1, 0), self.ray, 1.0)
        self.assertTrue(close(a, b))

    def test_every_light_faces_its_hit(self):
        for mode in placement.MODES:
            pos, fwd = placement.place(mode, (1, 1, 1), (0, 0, -1), vec.normalize((0.2, 0.1, 1.0)), 7.0)
            self.assertTrue(close(vec.normalize(vec.sub((1, 1, 1), pos)), fwd), mode)

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            placement.place("sideways", (0, 0, 0), self.up, self.ray, 1.0)

    def test_look_at_is_orthonormal_and_supports_roll(self):
        _, x, y, z = placement.look_at((0, 0, 0), (0, 0, 1))
        self.assertTrue(close(x, (1, 0, 0)) and close(y, (0, 1, 0)) and close(z, (0, 0, 1)))
        _, rx, ry, rz = placement.look_at((0, 0, 0), (0, 0, 1), roll_deg=90.0)
        self.assertTrue(close(rx, (0, 1, 0)) and close(ry, (-1, 0, 0)) and close(rz, (0, 0, 1)))
        for fwd in [(0.3, -0.8, 0.5), (0, -1, 0), (0, 1, 0)]:
            _, x, y, z = placement.look_at((0, 0, 0), fwd, roll_deg=37.5)
            self.assertTrue(close(z, vec.normalize(fwd)))
            for a, b in [(x, y), (y, z), (x, z)]:
                self.assertAlmostEqual(vec.dot(a, b), 0.0)
            self.assertAlmostEqual(vec.dot(vec.cross(x, y), z), 1.0)  # same handedness as the identity

    def test_default_distance_size_and_constant_lux(self):
        self.assertAlmostEqual(placement.default_distance(200.0), 130.0)
        self.assertAlmostEqual(placement.default_size(200.0), 56.0)
        # Doubling distance needs +2 EV; quadrupling area needs -2 EV.
        self.assertAlmostEqual(placement.constant_lux_ev_delta(100.0, 200.0, 900.0, 900.0), 2.0)
        self.assertAlmostEqual(placement.constant_lux_ev_delta(100.0, 100.0, 900.0, 3600.0), -2.0)


class PhotometryTest(unittest.TestCase):
    def test_6500k_is_near_white(self):
        rgb = photometry.kelvin_to_rgb(6500)
        self.assertLess(max(rgb) / min(rgb), 1.15)

    def test_warm_and_cool(self):
        r, g, b = photometry.kelvin_to_rgb(3200)
        self.assertTrue(r > g > b)
        r, g, b = photometry.kelvin_to_rgb(12000)
        self.assertTrue(b > g > r)

    def test_out_of_range_kelvin_is_clamped(self):
        self.assertEqual(photometry.kelvin_to_rgb(500), photometry.kelvin_to_rgb(1667))

    def test_srgb_round_trip(self):
        lin = (0.18, 0.5, 0.9)
        self.assertTrue(close(photometry.srgb_to_linear(photometry.linear_to_srgb(lin)), lin, 1e-5))
        self.assertEqual(photometry.linear_to_srgb_byte(0.0), 0)
        self.assertEqual(photometry.linear_to_srgb_byte(1.0), 255)

    def test_full_cto_turns_daylight_into_tungsten(self):
        self.assertAlmostEqual(photometry.effective_kelvin(6500, ["Full CTO"]), 3200, delta=50)
        self.assertAlmostEqual(photometry.effective_kelvin(3200, ["Full CTB"]), 5500, delta=60)

    def test_gels_stack(self):
        rgb, loss = photometry.apply_gels(6500, ["ND 0.6", "ND 0.3"])
        self.assertAlmostEqual(loss, 3.0)
        self.assertTrue(close(rgb, photometry.kelvin_to_rgb(6500)))
        _, one = photometry.apply_gels(5600, ["1/2 CTO"])
        _, two = photometry.apply_gels(5600, ["1/2 CTO", "1/2 CTO"])
        self.assertAlmostEqual(two, 2 * one)

    def test_colour_gel_loss_comes_from_its_tint(self):
        self.assertGreater(photometry.gel_loss("Red"), photometry.gel_loss("Straw"))
        self.assertGreater(photometry.gel_loss("Straw"), 0.0)


class TextureTest(unittest.TestCase):
    def sample(self, preset, u, v, w=64, h=64):
        grey = textures.composite(textures.PRESETS[preset], w, h)
        return grey[int(v * (h - 1)) * w + int(u * (w - 1))]

    def test_every_preset_bakes_finite_non_negative_values(self):
        for name, layers in textures.PRESETS.items():
            grey = textures.composite(layers, 24, 16)
            self.assertTrue(all(g >= 0.0 and math.isfinite(g) for g in grey), name)
            self.assertGreater(max(grey), 0.2, name)

    def test_softness_scales_feather_without_mutating_preset(self):
        base = textures.PRESETS["Softbox"]
        harder = textures.scale_softness(base, 0.25)
        softer = textures.scale_softness(base, 2.5)
        self.assertEqual(base[0]["params"]["edge"], 0.12)
        g_hard = textures.composite(harder, 32, 32)[2 * 32 + 16]
        g_soft = textures.composite(softer, 32, 32)[2 * 32 + 16]
        self.assertGreater(g_hard, g_soft)

    def test_shapes(self):
        self.assertGreater(self.sample("Softbox", 0.5, 0.5), 0.99)
        self.assertLess(self.sample("Softbox", 0.0, 0.0), 0.01)
        self.assertLess(self.sample("Ring", 0.5, 0.5), 0.01)
        self.assertGreater(self.sample("Gradient Soft Fade", 0.05, 0.5), self.sample("Gradient Soft Fade", 0.95, 0.5))
        self.assertLess(self.sample("Window 2x2", 0.5, 0.5), 0.01)  # the centre bar
        self.assertGreater(self.sample("Window 2x2", 0.25, 0.25), 0.9)

    def test_round_shapes_stay_round_on_a_long_light(self):
        w, h = 128, 32
        grey = textures.composite(textures.PRESETS["Round"], w, h)
        row = grey[(h // 2) * w:(h // 2 + 1) * w]
        lit = sum(1 for g in row if g > 0.5)
        self.assertLess(lit, w // 2)  # the circle spans the short side only

    def test_size_for_keeps_the_light_aspect(self):
        self.assertEqual(textures.size_for(30, 60, 512), (256, 512))
        self.assertEqual(textures.size_for(90, 30, 300), (300, 100))

    def test_unknown_names_fail_loudly(self):
        with self.assertRaises(ValueError):
            textures.layer("blob")
        with self.assertRaises(ValueError):
            textures.composite([{"shape": "softbox", "blend": "dodge"}], 2, 2)

    def test_exr_round_trip(self):
        w, h = 5, 3
        grey = [i / 4.0 for i in range(w * h)]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.exr")
            textures.write_exr(path, w, h, grey, tint=(1.0, 0.5, 0.25))
            r, g, b = read_exr(path)
            self.assertTrue(close(r, grey, 1e-3))
            self.assertTrue(close(g, [x * 0.5 for x in grey], 1e-3))
            self.assertTrue(close(b, [x * 0.25 for x in grey], 1e-3))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_exr_decodes_in_ffmpeg(self):
        w, h = 8, 4
        grey = [((i % w) / (w - 1)) for i in range(w * h)]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.exr")
            textures.write_exr(path, w, h, grey, tint=(1.0, 0.5, 0.25))
            raw = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "gbrpf32le", "-"],
                check=True, capture_output=True).stdout
            planes = struct.unpack("<%df" % (3 * w * h), raw)
            g, b, r = planes[:w * h], planes[w * h:2 * w * h], planes[2 * w * h:]
            self.assertTrue(close(r, grey, 1e-3))
            self.assertTrue(close(g, [x * 0.5 for x in grey], 1e-3))
            self.assertTrue(close(b, [x * 0.25 for x in grey], 1e-3))

    def test_bake_512_is_fast_enough(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = time.time()
            size = textures.bake("Strip", os.path.join(tmp, "s.exr"), 20, 80)
            self.assertEqual(size, (128, 512))
            self.assertLess(time.time() - start, 5.0)

    def test_foliage_and_caustic_presets(self):
        for name in ("Foliage", "Caustic"):
            self.assertIn(name, textures.PRESETS)
            layers = textures.scale_softness(textures.PRESETS[name], 1.2)
            grey = textures.composite(layers, 32, 32)
            self.assertEqual(len(grey), 1024)
            self.assertTrue(all(0.0 <= g <= 1.0 for g in grey))
            self.assertGreater(max(grey), 0.0)


def read_exr(path):
    """Read back the files write_exr makes (uncompressed half RGB), for the round-trip test."""
    with open(path, "rb") as f:
        data = f.read()
    assert struct.unpack_from("<ii", data, 0) == (20000630, 2)
    pos, attrs = 8, {}
    while data[pos] != 0:
        name_end = data.index(b"\0", pos)
        kind_end = data.index(b"\0", name_end + 1)
        size = struct.unpack_from("<i", data, kind_end + 1)[0]
        attrs[data[pos:name_end].decode()] = data[kind_end + 5:kind_end + 5 + size]
        pos = kind_end + 5 + size
    x0, y0, x1, y1 = struct.unpack("<iiii", attrs["dataWindow"])
    w, h = x1 - x0 + 1, y1 - y0 + 1
    offsets = struct.unpack_from("<%dQ" % h, data, pos + 1)
    chans = {"B": [], "G": [], "R": []}
    for off in offsets:
        p = off + 8
        for c in ("B", "G", "R"):
            chans[c].extend(struct.unpack_from("<%de" % w, data, p))
            p += 2 * w
    return chans["R"], chans["G"], chans["B"]


class RecipeTest(unittest.TestCase):
    def test_json_round_trip_and_tolerance(self):
        r = LightRecipe(name="Key", exposure=1.5, color_mode="rgb", tint=[1.0, 0.4, 0.1], rotation=45.0,
                        texture="Strip", softness=1.4, camera_visible=False,
                        anchor={"hit": [1, 2, 3], "normal": [0, 1, 0], "ray_dir": [0, 0, 1]})
        self.assertEqual(LightRecipe.from_json(r.to_json()), r)
        old = LightRecipe.from_json('{"name": "Old", "from_the_future": 1}')
        self.assertEqual(old.name, "Old")
        self.assertEqual(old.kelvin, 6500.0)
        self.assertEqual(old.color_mode, "kelvin_tint")
        # Links live in the renderer's own list on the light, not in the recipe; old recipes that carry them load
        linked = LightRecipe.from_json('{"name": "Linked", "linking_mode": "include", "linked_objects": ["Floor"]}')
        self.assertEqual(linked.name, "Linked")

    def test_colour_modes_have_no_hidden_exposure_loss(self):
        r = LightRecipe(exposure=2.0, color_mode="rgb", tint=[1.0, 0.2, 0.1])
        self.assertEqual(r.colour(), (1.0, 0.2, 0.1))
        self.assertAlmostEqual(r.total_exposure(), 2.0)
        r.color_mode = "kelvin_tint"
        r.kelvin = 3200.0
        c = r.colour()
        self.assertGreater(c[0], c[2])

    def test_gel_loss_lowers_exposure(self):
        r = LightRecipe(exposure=2.0, gels=["ND 0.6"])
        self.assertAlmostEqual(r.total_exposure(), 0.0)
        r.gel_loss = False
        self.assertAlmostEqual(r.total_exposure(), 2.0)


if __name__ == "__main__":
    unittest.main()
