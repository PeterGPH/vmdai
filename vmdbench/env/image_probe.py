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
    stride = max(1, (max(w, h) + DOWNSAMPLE_MAX - 1) // DOWNSAMPLE_MAX)  # ceil → long edge always <= DOWNSAMPLE_MAX
    pixels, ys, xs = [], range(0, h, stride), range(0, w, stride)
    for ry in ys:
        for cx in xs:
            pixels.append(rows[ry][cx])
    return pixels, len(xs), len(ys)


_COLOR_NAMES = {
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255), "yellow": (255, 255, 0),
    "orange": (255, 128, 0), "purple": (160, 32, 240), "pink": (255, 105, 180),
    "white": (255, 255, 255), "gray": (128, 128, 128), "grey": (128, 128, 128),
    "black": (0, 0, 0), "silver": (192, 192, 192), "tan": (210, 180, 140),
}


def parse_color(name_or_hex):
    s = str(name_or_hex).strip().lower()
    if s.startswith("#") and len(s) == 7:
        return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
    if s in _COLOR_NAMES:
        return _COLOR_NAMES[s]
    raise ValueError(f"unknown color {name_or_hex!r}")


def colors_close(c1, c2, tol):
    return max(abs(a - b) for a, b in zip(c1, c2)) <= tol * 255.0


def rgb_to_hsv(r, g, b):
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d == 0:
        h = 0.0
    elif mx == r:
        h = (60 * ((g - b) / d) + 360) % 360
    elif mx == g:
        h = (60 * ((b - r) / d) + 120) % 360
    else:
        h = (60 * ((r - g) / d) + 240) % 360
    s = 0.0 if mx == 0 else d / mx
    return (h, s, mx)


def detect_background(pixels, w, h):
    border = []
    for cx in range(w):
        border.append(pixels[cx])
        border.append(pixels[(h - 1) * w + cx])
    for ry in range(h):
        border.append(pixels[ry * w])
        border.append(pixels[ry * w + (w - 1)])
    mid = len(border) // 2
    rs = sorted(c[0] for c in border)
    gs = sorted(c[1] for c in border)
    bs = sorted(c[2] for c in border)
    return (rs[mid], gs[mid], bs[mid])


def foreground_coverage(pixels, bg, tol):
    if not pixels:
        return 0.0
    fg = sum(1 for c in pixels if not colors_close(c, bg, tol))
    return fg / len(pixels)


def dominant_colors(pixels, bg, tol, min_fraction, levels=4):
    if levels < 2:
        raise ValueError(f"levels must be >= 2, got {levels}")
    fg = [c for c in pixels if not colors_close(c, bg, tol)]
    if not fg:
        return []
    step = 255.0 / (levels - 1)
    buckets = {}
    for (r, g, b) in fg:
        key = (round(r / step), round(g / step), round(b / step))
        acc = buckets.setdefault(key, [0, 0, 0, 0])
        acc[0] += r; acc[1] += g; acc[2] += b; acc[3] += 1
    n = len(fg)
    out = []
    for (sr, sg, sb, cnt) in buckets.values():
        frac = cnt / n
        if frac >= min_fraction:
            out.append(((sr // cnt, sg // cnt, sb // cnt), frac))
    out.sort(key=lambda t: -t[1])
    return out


def color_matches(target, color, hue_tol=25.0, sat_min=0.15, val_tol=0.25):
    th, ts, tv = rgb_to_hsv(*target)
    ch, cs, cv = rgb_to_hsv(*color)
    if ts < sat_min:  # achromatic target (white/gray/black) — match by lightness
        return cs < sat_min and abs(tv - cv) <= val_tol
    if cs < sat_min:
        return False
    dh = abs(th - ch) % 360
    return min(dh, 360 - dh) <= hue_tol
