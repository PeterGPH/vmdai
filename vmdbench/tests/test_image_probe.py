from __future__ import annotations
import struct, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.env.image_probe import (
    load_pixels, ImageDecodeError,
    parse_color, colors_close, detect_background, foreground_coverage,
)


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


if __name__ == "__main__":
    unittest.main()
