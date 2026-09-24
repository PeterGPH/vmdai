"""
image_utils.py - Pure stdlib image conversion utilities for VMD AI.

Converts VMD snapshot files (TGA, PPM) to PNG bytes without any
external dependencies. Used to feed viewport images to Claude's vision.
"""
from __future__ import annotations

import struct
import zlib
from typing import Optional


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _rgb_rows_to_png(rows: list[bytes], width: int, height: int) -> bytes:
    """Encode a list of raw RGB row bytes (no filter byte) as a PNG."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_scanlines = b"".join(b"\x00" + row for row in rows)
    idat_data = zlib.compress(raw_scanlines, 6)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat_data)
        + _png_chunk(b"IEND", b"")
    )


def tga_to_png_bytes(tga_path: str) -> Optional[bytes]:
    """
    Convert an uncompressed Type-2 TGA file (24- or 32-bit) to PNG bytes.
    VMD's 'render snapshot' and 'render TachyonInternal' both produce
    uncompressed BGR(A) TGA files on all platforms.

    Returns None if the file cannot be parsed (wrong type, RLE-compressed, etc.).
    """
    try:
        with open(tga_path, "rb") as f:
            raw = f.read()

        id_len = raw[0]
        cm_type = raw[1]
        img_type = raw[2]  # 2 = uncompressed true-color

        if img_type != 2:
            return None  # RLE or paletted — not supported here

        # color-map spec bytes 3-7
        cm_len = struct.unpack_from("<H", raw, 5)[0]
        cm_bpp = raw[7]

        # image spec bytes 8-17
        width = struct.unpack_from("<H", raw, 12)[0]
        height = struct.unpack_from("<H", raw, 14)[0]
        bpp = raw[16]
        img_desc = raw[17]  # bit5=1 → top-to-bottom storage

        if bpp not in (24, 32) or width == 0 or height == 0:
            return None

        # Pixel data offset
        offset = 18 + id_len
        if cm_type == 1:
            offset += cm_len * (cm_bpp // 8)

        bytes_per_px = bpp // 8
        pixels = raw[offset:]
        expected = width * height * bytes_per_px
        if len(pixels) < expected:
            return None

        # Build RGB rows (TGA stores pixels in BGR order)
        rows: list[bytes] = []
        for row_idx in range(height):
            row = bytearray(width * 3)
            base = row_idx * width * bytes_per_px
            for col in range(width):
                px = base + col * bytes_per_px
                b_val = pixels[px]
                g_val = pixels[px + 1]
                r_val = pixels[px + 2]
                dst = col * 3
                row[dst] = r_val
                row[dst + 1] = g_val
                row[dst + 2] = b_val
            rows.append(bytes(row))

        # TGA default is bottom-to-top unless bit 5 of img_desc is set
        if not (img_desc & 0x20):
            rows = rows[::-1]

        return _rgb_rows_to_png(rows, width, height)

    except Exception:
        return None


def ppm_to_png_bytes(ppm_path: str) -> Optional[bytes]:
    """
    Convert a P6 (binary) PPM file to PNG bytes.
    Fallback for VMD versions that write PPM instead of TGA.
    """
    try:
        with open(ppm_path, "rb") as f:
            # Parse ASCII header
            def _readline() -> str:
                line = b""
                while True:
                    ch = f.read(1)
                    if not ch or ch == b"\n":
                        break
                    line += ch
                return line.decode("ascii", errors="replace").strip()

            magic = _readline()
            if magic != "P6":
                return None

            # Skip comments
            line = _readline()
            while line.startswith("#"):
                line = _readline()

            parts = line.split()
            if len(parts) < 2:
                line2 = _readline()
                parts = (line + " " + line2).split()

            width, height = int(parts[0]), int(parts[1])
            maxval = int(_readline())

            if maxval != 255 or width == 0 or height == 0:
                return None

            pixel_data = f.read()

        expected = width * height * 3
        if len(pixel_data) < expected:
            return None

        rows = [pixel_data[r * width * 3 : (r + 1) * width * 3] for r in range(height)]
        return _rgb_rows_to_png(rows, width, height)

    except Exception:
        return None


def read_image_as_png_bytes(path: str) -> Optional[bytes]:
    """
    Try to read any VMD-rendered image file as PNG bytes.
    Tries TGA first (most common from VMD), then PPM.
    Falls back to raw bytes if it's already a PNG.
    """
    lower = str(path or "").lower()

    if lower.endswith(".tga") or lower.endswith(".rgb"):
        result = tga_to_png_bytes(path)
        if result:
            return result

    if lower.endswith(".ppm"):
        result = ppm_to_png_bytes(path)
        if result:
            return result

    # Try Pillow if available (handles any format VMD might produce)
    try:
        import importlib
        pil_image = importlib.import_module("PIL.Image")
        pil_io = importlib.import_module("io")
        img = pil_image.open(path).convert("RGB")
        buf = pil_io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        pass

    # Try TGA parser regardless of extension (VMD often ignores extensions)
    result = tga_to_png_bytes(path)
    if result:
        return result

    return None
