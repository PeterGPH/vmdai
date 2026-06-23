"""Pure-stdlib, reference-free image probes for vmdbench.

Decodes a VMD-rendered TGA (uncompressed type-2, what `render TachyonInternal`
writes) and exposes coverage / palette helpers used by the image_* evaluators.
No numpy/Pillow required (Pillow used only as an optional PNG path).
"""
from __future__ import annotations
import struct
from pathlib import Path

DOWNSAMPLE_MAX = 200


class ImageDecodeError(Exception):
    """Raised when an image file cannot be read/decoded for probing."""


def _decode_tga(raw: bytes):
    if len(raw) < 18:
        raise ImageDecodeError("file too small to be a TGA")
    id_len, cm_type, img_type = raw[0], raw[1], raw[2]
    if img_type != 2:
        raise ImageDecodeError(f"unsupported TGA image type {img_type} (only uncompressed type 2)")
    cm_len = struct.unpack_from("<H", raw, 5)[0]
    cm_bpp = raw[7]
    width = struct.unpack_from("<H", raw, 12)[0]
    height = struct.unpack_from("<H", raw, 14)[0]
    bpp = raw[16]
    img_desc = raw[17]
    if bpp not in (24, 32) or width == 0 or height == 0:
        raise ImageDecodeError(f"unsupported TGA geometry bpp={bpp} {width}x{height}")
    offset = 18 + id_len + (cm_len * (cm_bpp // 8) if cm_type == 1 else 0)
    bpx = bpp // 8
    data = raw[offset:]
    if len(data) < width * height * bpx:
        raise ImageDecodeError("truncated TGA pixel data")
    rows = []
    for ry in range(height):
        base = ry * width * bpx
        row = [(data[base + cx * bpx + 2], data[base + cx * bpx + 1], data[base + cx * bpx])
               for cx in range(width)]
        rows.append(row)
    if not (img_desc & 0x20):  # TGA default is bottom-to-top
        rows.reverse()
    return rows, width, height


def _decode_png(raw: bytes) -> "tuple[list, int, int]":
    try:
        import io
        from PIL import Image  # optional dependency
    except ImportError:
        raise ImageDecodeError("PNG decode needs pillow; render TGA via TachyonInternal or `pip install pillow`")
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = img.size
    flat = list(img.getdata())
    rows = [flat[ry * w:(ry + 1) * w] for ry in range(h)]
    return rows, w, h


def load_pixels(path):
    p = Path(path)
    if not p.exists():
        raise ImageDecodeError(f"image not found: {p}")
    raw = p.read_bytes()
    rows, w, h = _decode_png(raw) if raw[:8] == b"\x89PNG\r\n\x1a\n" else _decode_tga(raw)
    stride = max(1, max(w, h) // DOWNSAMPLE_MAX)
    pixels, ys, xs = [], range(0, h, stride), range(0, w, stride)
    for ry in ys:
        for cx in xs:
            pixels.append(rows[ry][cx])
    return pixels, len(xs), len(ys)
