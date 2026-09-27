"""
image_scale.py - downscale, thumbnail and JPEG helpers for snapshot PNGs.

Stdlib only; Pillow is used when it imports (better filtering), otherwise a
strided nearest-neighbour decimation runs in pure Python. That path is fast
for the filter-0 PNGs image_utils produces from VMD's TGA renders (about
40 ms for 2048x1536 -> 1024x768), and still correct, but slower, for PNGs
that use PNG row filters.

image_utils.py is deliberately left byte-identical (the benchmark scores
its output); this module never imports from it.
"""
from __future__ import annotations

import io
import operator
import struct
import zlib
from typing import Any, List, Optional, Tuple

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}  # PNG colour type -> samples per pixel


def _load_pil() -> Any:
    """Return the PIL.Image module, or None. Tests patch this to force the
    stdlib path."""
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return None
    return Image


def png_size(png: bytes) -> Tuple[int, int]:
    """(width, height) from the IHDR chunk. Raises ValueError for non-PNG input."""
    if len(png) < 24 or png[:8] != _PNG_SIGNATURE or png[12:16] != b"IHDR":
        raise ValueError("not a PNG image")
    width, height = struct.unpack(">II", png[16:24])
    return int(width), int(height)


def _fit(width: int, height: int, box_w: int, box_h: int) -> Tuple[int, int]:
    """Largest size with the same aspect ratio inside box; never upscales."""
    scale = min(float(box_w) / width, float(box_h) / height, 1.0)
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _encode_rgb_png(rows: List[bytes], width: int, height: int) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)
    return (
        _PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )


def _unfilter(raw: bytes, height: int, stride: int, bpp: int) -> List[bytes]:
    """Undo PNG row filters 0-4 (pure Python; used only for filtered PNGs)."""
    rows: List[bytes] = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        ftype = raw[pos]
        cur = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += stride + 1
        if ftype == 1:
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                cur[i] = (cur[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    pred = a
                elif pb <= pc:
                    pred = b
                else:
                    pred = c
                cur[i] = (cur[i] + pred) & 0xFF
        elif ftype != 0:
            raise ValueError("unknown PNG filter type %d" % ftype)
        rows.append(bytes(cur))
        prev = cur
    return rows


def _to_rgb(row: bytes, channels: int) -> bytes:
    if channels == 3:
        return row
    if channels == 4:
        out = bytearray((len(row) // 4) * 3)
        out[0::3] = row[0::4]
        out[1::3] = row[1::4]
        out[2::3] = row[2::4]
        return bytes(out)
    grey = row[0::channels]  # grey (1) or grey+alpha (2)
    out = bytearray(len(grey) * 3)
    out[0::3] = grey
    out[1::3] = grey
    out[2::3] = grey
    return bytes(out)


def _decode_rgb_rows(png: bytes) -> Tuple[List[bytes], int, int]:
    """Decode an 8-bit, non-interlaced grey/RGB/RGBA PNG into RGB rows."""
    width, height = png_size(png)
    header: Optional[bytes] = None
    idat: List[bytes] = []
    pos = 8
    while pos + 8 <= len(png):
        length, tag = struct.unpack(">I4s", png[pos:pos + 8])
        data = png[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            header = data
        elif tag == b"IDAT":
            idat.append(data)
        elif tag == b"IEND":
            break
    if header is None:
        raise ValueError("PNG without IHDR")
    depth, ctype, _compression, _filter, interlace = struct.unpack(">BBBBB", header[8:13])
    if depth != 8 or interlace != 0 or ctype not in _CHANNELS:
        raise ValueError("unsupported PNG layout")
    channels = _CHANNELS[ctype]
    stride = width * channels
    step = stride + 1
    raw = zlib.decompress(b"".join(idat))
    if len(raw) < height * step:
        raise ValueError("truncated PNG data")
    filters = raw[0:height * step:step]
    if filters.count(0) == height:
        rows = [raw[y * step + 1:(y + 1) * step] for y in range(height)]
    else:
        rows = _unfilter(raw, height, stride, channels)
    if channels != 3:
        rows = [_to_rgb(row, channels) for row in rows]
    return rows, width, height


def _resample(rows: List[bytes], width: int, height: int, new_w: int, new_h: int) -> List[bytes]:
    """Nearest-neighbour (pixel-centre) decimation with C-speed row picking."""
    ys = [min(height - 1, (2 * y + 1) * height // (2 * new_h)) for y in range(new_h)]
    index: List[int] = []
    for x in range(new_w):
        base = min(width - 1, (2 * x + 1) * width // (2 * new_w)) * 3
        index.extend((base, base + 1, base + 2))
    pick = operator.itemgetter(*index)  # at least 3 indices, so it returns a tuple
    return [bytes(pick(rows[y])) for y in ys]


def _pil_resize(pil: Any, png: bytes, new_w: int, new_h: int) -> bytes:
    img = pil.open(io.BytesIO(png)).convert("RGB")
    resampling = getattr(pil, "Resampling", pil)  # Pillow >= 9.1 moved the enum
    img = img.resize((new_w, new_h), getattr(resampling, "LANCZOS"))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _shrink(png: bytes, box_w: int, box_h: int) -> Tuple[bytes, int, int]:
    width, height = png_size(png)
    new_w, new_h = _fit(width, height, box_w, box_h)
    if (new_w, new_h) == (width, height):
        return png, width, height
    pil = _load_pil()
    if pil is not None:
        try:
            return _pil_resize(pil, png, new_w, new_h), new_w, new_h
        except Exception:
            pass
    rows, width, height = _decode_rgb_rows(png)
    small = _resample(rows, width, height, new_w, new_h)
    return _encode_rgb_png(small, new_w, new_h), new_w, new_h


def downscale_png(png: bytes, max_edge: int) -> Tuple[bytes, int, int]:
    """Fit the long edge within max_edge (1024 local models, 1568 Anthropic).
    Returns (png, width, height); the input object itself when no resize is
    needed or max_edge <= 0."""
    if int(max_edge) <= 0:
        width, height = png_size(png)
        return png, width, height
    return _shrink(png, int(max_edge), int(max_edge))


def make_thumbnail(png: bytes, box_w: int = 256, box_h: int = 192) -> Tuple[bytes, int, int]:
    """Fit inside box_w x box_h (the snapshot card's box), keeping the aspect ratio."""
    return _shrink(png, int(box_w), int(box_h))


def to_jpeg(png: bytes, quality: int = 90) -> Optional[bytes]:
    """JPEG bytes via Pillow, or None when Pillow is missing or the input is bad."""
    pil = _load_pil()
    if pil is None:
        return None
    try:
        img = pil.open(io.BytesIO(png)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=int(quality))
        return buf.getvalue()
    except Exception:
        return None
