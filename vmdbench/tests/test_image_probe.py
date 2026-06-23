from __future__ import annotations
import struct, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.env.image_probe import load_pixels, ImageDecodeError


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


if __name__ == "__main__":
    unittest.main()
