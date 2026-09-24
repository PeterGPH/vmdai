"""
Tests for image_utils.py — TGA/PPM → PNG conversion.

Constructs minimal valid image files in memory and verifies that the pure-stdlib
converters produce correct PNG output.
"""
from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zlib


# ------------------------------------------------------------------
# Helpers to construct tiny test images
# ------------------------------------------------------------------

def _make_tga_uncompressed(width: int, height: int, pixels_bgr: bytes, *, bpp: int = 24, top_to_bottom: bool = False) -> bytes:
    """Build a minimal uncompressed Type-2 TGA file."""
    header = bytearray(18)
    header[2] = 2  # image type: uncompressed true-color
    struct.pack_into("<H", header, 12, width)
    struct.pack_into("<H", header, 14, height)
    header[16] = bpp
    if top_to_bottom:
        header[17] = 0x20  # bit 5 = top-to-bottom
    return bytes(header) + pixels_bgr


def _make_ppm_p6(width: int, height: int, pixels_rgb: bytes) -> bytes:
    """Build a minimal P6 PPM file."""
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    return header + pixels_rgb


def _png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Extract width, height from a PNG IHDR chunk."""
    # IHDR starts at offset 8 (signature) + 4 (length) + 4 (tag) = 16
    assert png_bytes[:4] == b"\x89PNG", "not a PNG"
    w = struct.unpack_from(">I", png_bytes, 16)[0]
    h = struct.unpack_from(">I", png_bytes, 20)[0]
    return w, h


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

class TgaToPngTests(unittest.TestCase):

    def _import(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runtime"))
        from vmd_ai_runtime.image_utils import tga_to_png_bytes
        return tga_to_png_bytes

    def test_2x2_bottom_to_top(self):
        """Default TGA layout: bottom-to-top, BGR 24-bit."""
        tga_to_png_bytes = self._import()
        # 2×2 pixels, bottom row first: red, green, blue, white
        pixels = bytes([0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255])
        tga = _make_tga_uncompressed(2, 2, pixels)
        with tempfile.NamedTemporaryFile(suffix=".tga", delete=False) as f:
            f.write(tga)
            path = f.name
        try:
            png = tga_to_png_bytes(path)
            self.assertIsNotNone(png)
            self.assertTrue(png.startswith(b"\x89PNG"))
            w, h = _png_dimensions(png)
            self.assertEqual(w, 2)
            self.assertEqual(h, 2)
        finally:
            os.unlink(path)

    def test_2x2_top_to_bottom(self):
        """TGA with image descriptor bit 5 set → top-to-bottom."""
        tga_to_png_bytes = self._import()
        pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255])
        tga = _make_tga_uncompressed(2, 2, pixels, top_to_bottom=True)
        with tempfile.NamedTemporaryFile(suffix=".tga", delete=False) as f:
            f.write(tga)
            path = f.name
        try:
            png = tga_to_png_bytes(path)
            self.assertIsNotNone(png)
            w, h = _png_dimensions(png)
            self.assertEqual((w, h), (2, 2))
        finally:
            os.unlink(path)

    def test_rejects_rle_tga(self):
        """RLE-compressed TGA (type 10) is unsupported; should return None."""
        tga_to_png_bytes = self._import()
        header = bytearray(18)
        header[2] = 10  # RLE
        struct.pack_into("<H", header, 12, 1)
        struct.pack_into("<H", header, 14, 1)
        header[16] = 24
        tga = bytes(header) + bytes(3)
        with tempfile.NamedTemporaryFile(suffix=".tga", delete=False) as f:
            f.write(tga)
            path = f.name
        try:
            self.assertIsNone(tga_to_png_bytes(path))
        finally:
            os.unlink(path)

    def test_truncated_pixel_data(self):
        """TGA with header claiming 10×10 but only 3 bytes of pixel data."""
        tga_to_png_bytes = self._import()
        header = bytearray(18)
        header[2] = 2
        struct.pack_into("<H", header, 12, 10)
        struct.pack_into("<H", header, 14, 10)
        header[16] = 24
        tga = bytes(header) + bytes(3)
        with tempfile.NamedTemporaryFile(suffix=".tga", delete=False) as f:
            f.write(tga)
            path = f.name
        try:
            self.assertIsNone(tga_to_png_bytes(path))
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        tga_to_png_bytes = self._import()
        self.assertIsNone(tga_to_png_bytes("/tmp/this_file_does_not_exist.tga"))

    def test_32bit_bgra(self):
        """32-bit BGRA TGA (alpha channel present but dropped in PNG)."""
        tga_to_png_bytes = self._import()
        # 1×1 pixel: BGRA = (0, 255, 0, 255)
        pixels = bytes([0, 255, 0, 255])
        tga = _make_tga_uncompressed(1, 1, pixels, bpp=32)
        with tempfile.NamedTemporaryFile(suffix=".tga", delete=False) as f:
            f.write(tga)
            path = f.name
        try:
            png = tga_to_png_bytes(path)
            self.assertIsNotNone(png)
            w, h = _png_dimensions(png)
            self.assertEqual((w, h), (1, 1))
        finally:
            os.unlink(path)


class PpmToPngTests(unittest.TestCase):

    def _import(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runtime"))
        from vmd_ai_runtime.image_utils import ppm_to_png_bytes
        return ppm_to_png_bytes

    def test_valid_p6(self):
        ppm_to_png_bytes = self._import()
        pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255])
        ppm = _make_ppm_p6(2, 2, pixels)
        with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as f:
            f.write(ppm)
            path = f.name
        try:
            png = ppm_to_png_bytes(path)
            self.assertIsNotNone(png)
            w, h = _png_dimensions(png)
            self.assertEqual((w, h), (2, 2))
        finally:
            os.unlink(path)

    def test_rejects_p3(self):
        """P3 (ASCII) PPM not supported."""
        ppm_to_png_bytes = self._import()
        data = b"P3\n2 2\n255\n255 0 0 0 255 0 0 0 255 255 255 255\n"
        with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            self.assertIsNone(ppm_to_png_bytes(path))
        finally:
            os.unlink(path)

    def test_ppm_with_comments(self):
        ppm_to_png_bytes = self._import()
        pixels = bytes([128, 128, 128] * 4)
        ppm = b"P6\n# comment\n2 2\n255\n" + pixels
        with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as f:
            f.write(ppm)
            path = f.name
        try:
            png = ppm_to_png_bytes(path)
            self.assertIsNotNone(png)
        finally:
            os.unlink(path)


class ReadImageTests(unittest.TestCase):

    def _import(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runtime"))
        from vmd_ai_runtime.image_utils import read_image_as_png_bytes
        return read_image_as_png_bytes

    def test_dispatch_by_extension(self):
        """read_image_as_png_bytes picks the right parser by file extension."""
        read_image = self._import()
        # TGA file with .tga extension
        tga = _make_tga_uncompressed(1, 1, bytes([0, 0, 255]))
        with tempfile.NamedTemporaryFile(suffix=".tga", delete=False) as f:
            f.write(tga)
            path = f.name
        try:
            png = read_image(path)
            self.assertIsNotNone(png)
            self.assertTrue(png.startswith(b"\x89PNG"))
        finally:
            os.unlink(path)

    def test_unknown_extension_tries_tga(self):
        """Fallback: tries TGA parser regardless of file extension."""
        read_image = self._import()
        tga = _make_tga_uncompressed(1, 1, bytes([255, 0, 0]))
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as f:
            f.write(tga)
            path = f.name
        try:
            png = read_image(path)
            self.assertIsNotNone(png)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
