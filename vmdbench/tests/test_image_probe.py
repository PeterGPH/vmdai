from __future__ import annotations
import struct, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.env.image_probe import (
    load_pixels, ImageDecodeError,
    parse_color, colors_close, detect_background, foreground_coverage,
    dominant_colors, color_matches,
)
from vmdbench.verify.checks import evaluate, CheckContext
from vmdbench.env.scene_state import SceneState



def _make_tga(w: int, h: int, pixels, top_to_bottom: bool = True) -> bytes:
    """Build an uncompressed type-2 TGA. `pixels` is a flat row-major top-to-bottom
    list of (r,g,b). With top_to_bottom=False the rows are stored bottom-first."""
    desc = 0x20 if top_to_bottom else 0x00
    hdr = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 24, desc)
    rows = [pixels[ry * w:(ry + 1) * w] for ry in range(h)]
    if not top_to_bottom:
        rows = rows[::-1]
    body = bytearray()
    for row in rows:
        for (r, g, b) in row:
            body += bytes((b, g, r))
    return bytes(hdr) + bytes(body)


class ImageDecodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_top_to_bottom(self):
        px = [(10, 20, 30), (40, 50, 60), (70, 80, 90), (100, 110, 120)]
        (self.dir / "a.tga").write_bytes(_make_tga(2, 2, px, top_to_bottom=True))
        out, w, h = load_pixels(self.dir / "a.tga")
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(out, px)

    def test_roundtrip_bottom_to_top(self):
        px = [(10, 20, 30), (40, 50, 60), (70, 80, 90), (100, 110, 120)]
        (self.dir / "b.tga").write_bytes(_make_tga(2, 2, px, top_to_bottom=False))
        out, _, _ = load_pixels(self.dir / "b.tga")
        self.assertEqual(out, px)

    def test_downsample_long_edge(self):
        px = [(1, 2, 3)] * 400
        (self.dir / "c.tga").write_bytes(_make_tga(400, 1, px))
        _, w, h = load_pixels(self.dir / "c.tga")
        self.assertEqual((w, h), (200, 1))

    def test_missing_file_raises(self):
        with self.assertRaises(ImageDecodeError):
            load_pixels(self.dir / "nope.tga")

    def test_unsupported_type_raises(self):
        bad = bytearray(_make_tga(2, 2, [(0, 0, 0)] * 4))
        bad[2] = 10  # RLE type
        (self.dir / "d.tga").write_bytes(bytes(bad))
        with self.assertRaises(ImageDecodeError):
            load_pixels(self.dir / "d.tga")

    def test_downsample_non_multiple(self):
        px = [(1, 2, 3)] * 399
        (self.dir / "nm.tga").write_bytes(_make_tga(399, 1, px))
        _, w, h = load_pixels(self.dir / "nm.tga")
        self.assertLessEqual(w, 200)
        self.assertEqual((w, h), (200, 1))


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_color(self):
        self.assertEqual(parse_color("red"), (255, 0, 0))
        self.assertEqual(parse_color("#0000ff"), (0, 0, 255))
        with self.assertRaises(ValueError):
            parse_color("chartreuse")

    def test_colors_close(self):
        self.assertTrue(colors_close((255, 255, 255), (250, 252, 255), 0.06))
        self.assertFalse(colors_close((255, 255, 255), (255, 0, 0), 0.06))

    def test_background_and_coverage(self):
        W, R = (255, 255, 255), (255, 0, 0)
        px = [W, W, W, W,  W, R, R, W,  W, R, R, W,  W, W, W, W]
        (self.dir / "blob.tga").write_bytes(_make_tga(4, 4, px))
        pixels, w, h = load_pixels(self.dir / "blob.tga")
        self.assertEqual(detect_background(pixels, w, h), W)
        self.assertAlmostEqual(foreground_coverage(pixels, W, 0.06), 4 / 16, places=3)

    def test_blank_image_zero_coverage(self):
        W = (255, 255, 255)
        (self.dir / "blank.tga").write_bytes(_make_tga(4, 4, [W] * 16))
        pixels, w, h = load_pixels(self.dir / "blank.tga")
        bg = detect_background(pixels, w, h)
        self.assertEqual(foreground_coverage(pixels, bg, 0.06), 0.0)


class PaletteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _load(self, name, px):
        (self.dir / name).write_bytes(_make_tga(4, 4, px))
        pixels, w, h = load_pixels(self.dir / name)
        return pixels, detect_background(pixels, w, h)

    def test_two_dominant_colors(self):
        W, R, B = (255, 255, 255), (255, 0, 0), (0, 0, 255)
        px = [W, W, W, W,  W, R, B, W,  W, R, B, W,  W, W, W, W]
        pixels, bg = self._load("two.tga", px)
        self.assertEqual(len(dominant_colors(pixels, bg, 0.06, 0.03)), 2)

    def test_expect_colors_match_under_jitter(self):
        W = (255, 255, 255)
        R, B = (230, 20, 15), (15, 25, 235)  # shaded red / blue
        px = [W, W, W, W,  W, R, B, W,  W, R, B, W,  W, W, W, W]
        pixels, bg = self._load("jit.tga", px)
        dom = dominant_colors(pixels, bg, 0.06, 0.03)
        self.assertTrue(any(color_matches(parse_color("red"), c) for c, _ in dom))
        self.assertTrue(any(color_matches(parse_color("blue"), c) for c, _ in dom))

    def test_achromatic_distinct_from_chromatic(self):
        W, G, B = (255, 255, 255), (128, 128, 128), (0, 0, 255)
        px = [W, W, W, W,  W, G, B, W,  W, G, B, W,  W, W, W, W]
        pixels, bg = self._load("achr.tga", px)
        self.assertEqual(len(dominant_colors(pixels, bg, 0.06, 0.03)), 2)
        self.assertTrue(color_matches(parse_color("gray"), G))
        self.assertTrue(color_matches(parse_color("blue"), B))
        self.assertFalse(color_matches(parse_color("blue"), G))

    def test_levels_below_two_raises(self):
        pixels, bg = self._load("lv.tga", [(255, 0, 0)] * 16)
        self.assertRaises(ValueError, dominant_colors, pixels, bg, 0.06, 0.03, 1)

    def test_empty_foreground_returns_empty(self):
        pixels, bg = self._load("empty.tga", [(255, 255, 255)] * 16)
        self.assertEqual(dominant_colors(pixels, bg, 0.06, 0.03), [])


class ImageForegroundEvalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = CheckContext(workdir=Path(self.tmp.name))
        self.scene = SceneState()

    def tearDown(self):
        self.tmp.cleanup()

    def test_pass_on_blob(self):
        W, R = (255, 255, 255), (255, 0, 0)
        px = [W, W, W, W,  W, R, R, W,  W, R, R, W,  W, W, W, W]
        (self.ctx.workdir / "out.tga").write_bytes(_make_tga(4, 4, px))
        r = evaluate({"kind": "image_foreground",
                      "where": {"path": "out.tga", "background": "white",
                                "check_background": True, "min_coverage": 0.1}},
                     self.scene, self.ctx)
        self.assertTrue(r.passed, r.observed)

    def test_fail_on_blank(self):
        (self.ctx.workdir / "blank.tga").write_bytes(_make_tga(4, 4, [(255, 255, 255)] * 16))
        r = evaluate({"kind": "image_foreground", "where": {"path": "blank.tga", "min_coverage": 0.05}},
                     self.scene, self.ctx)
        self.assertFalse(r.passed, r.observed)

    def test_fail_on_missing(self):
        r = evaluate({"kind": "image_foreground", "where": {"path": "gone.tga"}}, self.scene, self.ctx)
        self.assertFalse(r.passed)
        self.assertIn("not found", str(r.observed))


class ImagePaletteEvalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = CheckContext(workdir=Path(self.tmp.name))
        self.scene = SceneState()
        W, R, B = (255, 255, 255), (255, 0, 0), (0, 0, 255)
        px = [W, W, W, W,  W, R, B, W,  W, R, B, W,  W, W, W, W]
        (self.ctx.workdir / "pal.tga").write_bytes(_make_tga(4, 4, px))

    def tearDown(self):
        self.tmp.cleanup()

    def _ev(self, where):
        return evaluate({"kind": "image_palette", "where": where}, self.scene, self.ctx)

    def test_min_distinct_and_expect_pass(self):
        r = self._ev({"path": "pal.tga", "min_distinct": 2, "expect_colors": ["red", "blue"]})
        self.assertTrue(r.passed, r.observed)

    def test_min_distinct_too_high_fails(self):
        self.assertFalse(self._ev({"path": "pal.tga", "min_distinct": 3}).passed)

    def test_absent_expected_color_fails(self):
        self.assertFalse(self._ev({"path": "pal.tga", "expect_colors": ["green"]}).passed)

    def test_undecodable_fails_cleanly(self):
        (self.ctx.workdir / "junk.tga").write_bytes(b"not a tga")
        r = self._ev({"path": "junk.tga", "min_distinct": 1})
        self.assertFalse(r.passed)


if __name__ == "__main__":
    unittest.main()
