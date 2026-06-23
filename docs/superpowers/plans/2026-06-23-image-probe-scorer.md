# Reference-free image probes for vmdbench — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two deterministic, reference-free image checks (`image_foreground`, `image_palette`) to vmdbench so a visualization task is scored on whether the *rendered picture* is non-empty and correctly colored, not just on the scene graph.

**Architecture:** A new pure-stdlib module `vmdbench/env/image_probe.py` decodes the agent's rendered TGA and computes foreground coverage + dominant colors. Two new evaluators in `verify/checks.py` consume it and return `CheckResult`s, registered into the existing assertion vocabulary (`spec/assertions.py`) and dimension map (`spec/dimensions.py`). No changes to the env, scene_state, scorer, runner, or CLI — the checks read the rendered file straight from `ctx.workdir`.

**Tech Stack:** Python 3 stdlib only (`struct`, `pathlib`). Pillow is an **optional** PNG path. Tests are `unittest.TestCase`, run with pytest.

## Global Constraints

- **Pure-stdlib core.** No numpy/skimage/Pillow as a hard dependency. Pillow used only if importable, for PNG; absence yields a clean failure, never a crash.
- **Reference-free.** No oracle-image comparison, no camera matching, no per-atom coords, no VLM. (All deferred per the spec's non-goals.)
- **TGA support = uncompressed type-2 only.** VMD's `render TachyonInternal` writes uncompressed BGR type-2 (confirmed in `runtime/vmd_ai_runtime/image_utils.py`). RLE type-10 is intentionally **not** implemented (YAGNI); the decoder raises a clear error for any non-type-2 image. *(Deviation from spec, which listed RLE — dropped because VMD never produces it; trivial to add later.)*
- **Checks never raise.** Every failure path (missing file, undecodable, zero-dim, all-background) returns a failing `CheckResult` with a descriptive `observed`.
- **Behaves like any assertion.** A card places these in `verify.required` (gates) or `verify.optional` (scored, non-gating); no runner special-casing.
- **Tests:** `unittest.TestCase`; every test file starts with `ROOT = Path(__file__).resolve().parents[2]` + `sys.path.insert`. Run all commands from the repo root `vmd_ai/`.
- **Default constants (verbatim):** downsample long-edge `200`; color match tolerance `tol=0.06` (max-channel, fraction of 255); palette `min_fraction=0.03`; quantization `levels=4`; `color_matches(hue_tol=25.0, sat_min=0.15, val_tol=0.25)`; `image_foreground` default `min_coverage=0.02`, `max_coverage=1.0`.

---

### Task 1: TGA decode + `load_pixels`

**Files:**
- Create: `vmdbench/env/image_probe.py`
- Test: `vmdbench/tests/test_image_probe.py`

**Interfaces:**
- Produces:
  - `class ImageDecodeError(Exception)`
  - `load_pixels(path) -> (pixels: list[tuple[int,int,int]], width: int, height: int)` — flat row-major RGB pixels (top-to-bottom), already downsampled so the long edge ≤ 200. Raises `ImageDecodeError` on missing/unsupported/truncated.
  - `DOWNSAMPLE_MAX = 200`

- [ ] **Step 1: Write the failing test**

Create `vmdbench/tests/test_image_probe.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_image_probe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vmdbench.env.image_probe'`.

- [ ] **Step 3: Write minimal implementation**

Create `vmdbench/env/image_probe.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_image_probe.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add vmdbench/env/image_probe.py vmdbench/tests/test_image_probe.py
git commit -m "feat(vmdbench): TGA decode + load_pixels for image probes"
```

---

### Task 2: Background detection + foreground coverage + color helpers

**Files:**
- Modify: `vmdbench/env/image_probe.py`
- Test: `vmdbench/tests/test_image_probe.py`

**Interfaces:**
- Consumes: `load_pixels` (Task 1).
- Produces:
  - `parse_color(name_or_hex) -> (r,g,b)` (named VMD-ish colors or `#rrggbb`; raises `ValueError` on unknown)
  - `colors_close(c1, c2, tol) -> bool` (max-channel distance ≤ `tol*255`)
  - `rgb_to_hsv(r,g,b) -> (h: float[0,360), s: float[0,1], v: float[0,1])`
  - `detect_background(pixels, w, h) -> (r,g,b)` (median of border pixels)
  - `foreground_coverage(pixels, bg, tol) -> float`

- [ ] **Step 1: Write the failing test**

Add to `vmdbench/tests/test_image_probe.py` (new imports + class):

```python
from vmdbench.env.image_probe import (
    parse_color, colors_close, detect_background, foreground_coverage,
)


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_image_probe.py::CoverageTests -v`
Expected: FAIL — `ImportError: cannot import name 'parse_color'`.

- [ ] **Step 3: Write minimal implementation**

Append to `vmdbench/env/image_probe.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_image_probe.py -v`
Expected: PASS (Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add vmdbench/env/image_probe.py vmdbench/tests/test_image_probe.py
git commit -m "feat(vmdbench): background detection + foreground coverage"
```

---

### Task 3: Dominant colors + color matching

**Files:**
- Modify: `vmdbench/env/image_probe.py`
- Test: `vmdbench/tests/test_image_probe.py`

**Interfaces:**
- Consumes: `colors_close`, `rgb_to_hsv`, `parse_color` (Task 2).
- Produces:
  - `dominant_colors(pixels, bg, tol, min_fraction, levels=4) -> list[tuple[(r,g,b), float]]` — non-background colors, coarse-RGB-quantized, share ≥ `min_fraction`, sorted by share desc.
  - `color_matches(target, color, hue_tol=25.0, sat_min=0.15, val_tol=0.25) -> bool` — hue proximity for chromatic targets, value proximity for achromatic.

- [ ] **Step 1: Write the failing test**

Add to `vmdbench/tests/test_image_probe.py`:

```python
from vmdbench.env.image_probe import dominant_colors, color_matches


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_image_probe.py::PaletteTests -v`
Expected: FAIL — `ImportError: cannot import name 'dominant_colors'`.

- [ ] **Step 3: Write minimal implementation**

Append to `vmdbench/env/image_probe.py`:

```python
def dominant_colors(pixels, bg, tol, min_fraction, levels=4):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_image_probe.py -v`
Expected: PASS (all probe tests).

- [ ] **Step 5: Commit**

```bash
git add vmdbench/env/image_probe.py vmdbench/tests/test_image_probe.py
git commit -m "feat(vmdbench): dominant-color extraction + shading-robust color match"
```

---

### Task 4: `image_foreground` evaluator

**Files:**
- Modify: `vmdbench/verify/checks.py` (add evaluator after `_file_rendered`, ~line 185)
- Test: `vmdbench/tests/test_image_probe.py`

**Interfaces:**
- Consumes: `load_pixels`, `detect_background`, `foreground_coverage`, `parse_color`, `colors_close`, `ImageDecodeError` (Tasks 1–2); `evaluate`, `CheckContext`, `CheckResult` (existing).
- Produces: a registered `image_foreground` evaluator.

- [ ] **Step 1: Write the failing test**

Add to `vmdbench/tests/test_image_probe.py`:

```python
from vmdbench.verify.checks import evaluate, CheckContext
from vmdbench.env.scene_state import SceneState


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_image_probe.py::ImageForegroundEvalTests -v`
Expected: FAIL — `KeyError: "no evaluator for assertion kind 'image_foreground'"`.

- [ ] **Step 3: Write minimal implementation**

Add the import near the top of `vmdbench/verify/checks.py` (after the existing imports, ~line 7) — only the names this evaluator uses (Task 5 extends this line):

```python
from vmdbench.env.image_probe import (
    ImageDecodeError, load_pixels, detect_background, foreground_coverage,
    parse_color, colors_close,
)
```

Add this evaluator after `_file_rendered` (after ~line 185):

```python
@_register("image_foreground")
def _image_foreground(where, scene, ctx, a):
    """Reference-free: is the rendered image non-empty (and the background correct)?
    Catches the empty-scene-saved-as-a-valid-image failure."""
    tol = float(where.get("tol", 0.06))
    try:
        pixels, w, h = load_pixels(ctx.workdir / where["path"])
    except ImageDecodeError as exc:
        return CheckResult("image_foreground", False, observed=str(exc), where=where)
    declared = parse_color(where["background"]) if where.get("background") else None
    border = detect_background(pixels, w, h)
    bg = declared if declared is not None else border
    cov = foreground_coverage(pixels, bg, tol)
    ok = float(where.get("min_coverage", 0.02)) <= cov <= float(where.get("max_coverage", 1.0))
    if where.get("check_background") and declared is not None:
        ok = ok and colors_close(border, declared, tol)
    observed = {"coverage": round(cov, 4), "background_rgb": list(border),
                "width": w, "height": h}
    return CheckResult("image_foreground", bool(ok), observed=observed, where=where)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_image_probe.py::ImageForegroundEvalTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add vmdbench/verify/checks.py vmdbench/tests/test_image_probe.py
git commit -m "feat(vmdbench): image_foreground evaluator"
```

---

### Task 5: `image_palette` evaluator

**Files:**
- Modify: `vmdbench/verify/checks.py` (add evaluator after `_image_foreground`)
- Test: `vmdbench/tests/test_image_probe.py`

**Interfaces:**
- Consumes: `dominant_colors`, `color_matches`, `parse_color`, `detect_background`, `load_pixels`, `ImageDecodeError`. `parse_color`/`detect_background`/`load_pixels`/`ImageDecodeError` were imported in Task 4; this task extends the import line to add `dominant_colors`, `color_matches`.
- Produces: a registered `image_palette` evaluator.

- [ ] **Step 1: Write the failing test**

Add to `vmdbench/tests/test_image_probe.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_image_probe.py::ImagePaletteEvalTests -v`
Expected: FAIL — `KeyError: "no evaluator for assertion kind 'image_palette'"`.

- [ ] **Step 3: Write minimal implementation**

Add after `_image_foreground` in `vmdbench/verify/checks.py`:

```python
@_register("image_palette")
def _image_palette(where, scene, ctx, a):
    """Reference-free: did the requested colors actually render? Catches
    'ran mol modcolor but the image came out one color'."""
    tol = float(where.get("tol", 0.06))
    min_fraction = float(where.get("min_fraction", 0.03))
    try:
        pixels, w, h = load_pixels(ctx.workdir / where["path"])
    except ImageDecodeError as exc:
        return CheckResult("image_palette", False, observed=str(exc), where=where)
    bg = parse_color(where["background"]) if where.get("background") else detect_background(pixels, w, h)
    dom = dominant_colors(pixels, bg, tol, min_fraction)
    ok = True
    if "min_distinct" in where:
        ok = ok and len(dom) >= int(where["min_distinct"])
    for cname in where.get("expect_colors", []) or []:
        target = parse_color(cname)
        ok = ok and any(color_matches(target, c) for c, _ in dom)
    observed = {"distinct": len(dom),
                "dominant": [[list(c), round(f, 3)] for c, f in dom[:6]],
                "background_rgb": list(bg)}
    return CheckResult("image_palette", bool(ok), observed=observed, where=where)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_image_probe.py -v`
Expected: PASS (all unit + evaluator tests).

- [ ] **Step 5: Commit**

```bash
git add vmdbench/verify/checks.py vmdbench/tests/test_image_probe.py
git commit -m "feat(vmdbench): image_palette evaluator"
```

---

### Task 6: Register kinds in the assertion vocabulary + dimensions

**Files:**
- Modify: `vmdbench/spec/dimensions.py` (`KIND_DIMENSIONS`, ~line 18-32)
- Modify: `vmdbench/spec/assertions.py` (`_REQUIRED_WHERE` ~line 20-26; `validate_assertion` ~line 44)
- Test: `vmdbench/tests/test_assertions.py`, `vmdbench/tests/test_dimensions.py`

**Interfaces:**
- Consumes: existing `validate_assertion`, `KNOWN_KINDS`, `KIND_DIMENSIONS`.
- Produces: `image_foreground` → `[ACTIONABILITY]`, `image_palette` → `[SEMANTIC_GROUNDING]`; both require `where.path`; `image_palette` requires `min_distinct` or `expect_colors`.

- [ ] **Step 1: Write the failing test**

Add to `vmdbench/tests/test_assertions.py` (inside `AssertionContractTests`):

```python
    def test_image_kinds_known(self):
        self.assertIn("image_foreground", KNOWN_KINDS)
        self.assertIn("image_palette", KNOWN_KINDS)

    def test_image_foreground_requires_path(self):
        with self.assertRaises(VBAssertionError):
            validate_assertion({"kind": "image_foreground", "where": {}})
        validate_assertion({"kind": "image_foreground", "where": {"path": "out.tga"}})

    def test_image_palette_requires_path_and_criterion(self):
        with self.assertRaises(VBAssertionError):
            validate_assertion({"kind": "image_palette", "where": {"path": "out.tga"}})
        validate_assertion({"kind": "image_palette", "where": {"path": "out.tga", "min_distinct": 2}})
        validate_assertion({"kind": "image_palette", "where": {"path": "out.tga", "expect_colors": ["red"]}})
```

Append this self-contained class to `vmdbench/tests/test_dimensions.py` (it already has the `unittest` + `sys.path` header, like every other test file in this dir):

```python
class ImageKindDimensionTests(unittest.TestCase):
    def test_image_kinds_mapped(self):
        from vmdbench.spec.dimensions import KIND_DIMENSIONS, Dimension
        self.assertEqual(KIND_DIMENSIONS["image_foreground"], [Dimension.ACTIONABILITY])
        self.assertEqual(KIND_DIMENSIONS["image_palette"], [Dimension.SEMANTIC_GROUNDING])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_assertions.py vmdbench/tests/test_dimensions.py -v`
Expected: FAIL — `image_foreground` not in `KNOWN_KINDS` / `KeyError` in the dimensions test.

- [ ] **Step 3: Write minimal implementation**

In `vmdbench/spec/dimensions.py`, add two entries to `KIND_DIMENSIONS` (after the `scalar_within` line):

```python
    "image_foreground":       [Dimension.ACTIONABILITY],      # rendered image is non-empty
    "image_palette":          [Dimension.SEMANTIC_GROUNDING], # requested colors actually rendered
```

In `vmdbench/spec/assertions.py`, add to `_REQUIRED_WHERE`:

```python
    "image_foreground": ["path"],
    "image_palette": ["path"],
```

And in `validate_assertion`, after the `custom_check` block (~line 49), add:

```python
    if kind == "image_palette" and not (
        "min_distinct" in a["where"] or "expect_colors" in a["where"]
    ):
        raise AssertionError("image_palette requires where.min_distinct or where.expect_colors")
```

(`KNOWN_KINDS` is derived from `KIND_DIMENSIONS`, so adding the two dimension entries auto-admits the kinds.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_assertions.py vmdbench/tests/test_dimensions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vmdbench/spec/dimensions.py vmdbench/spec/assertions.py vmdbench/tests/test_assertions.py vmdbench/tests/test_dimensions.py
git commit -m "feat(vmdbench): register image_foreground/image_palette kinds + dimensions"
```

---

### Task 7: Demo card + oracle + end-to-end VMD render test

**Files:**
- Create: `vmdbench/tasks/viz/viz_render_element_1crn_001.yaml`
- Create: `vmdbench/oracles/viz_render_element_1crn_001.tcl`
- Test: `vmdbench/tests/test_image_probe.py` (live, VMD-backed — matches `test_oracle.py`)

**Interfaces:**
- Consumes: `load_card`, `run_oracle` (existing); `evaluate`, `CheckContext` (existing); the image evaluators (Tasks 4–5). Uses fixture `vmdbench/fixtures/1crn.pdb` (already present).
- Produces: a calibrated visualization card whose gate includes the two image checks. Auto-covered by `test_cards_load.py` (it rglobs every card).

- [ ] **Step 1: Write the oracle and card, then the failing live test**

Create `vmdbench/oracles/viz_render_element_1crn_001.tcl`:

```tcl
# viz_render_element_1crn_001 oracle. Bare body — HeadlessVMDEnv adds the PROBE
# introspection and quit. Render with TachyonInternal (works headless; `render
# snapshot` needs a GL context and yields an invalid stub). White background so
# image_foreground/check_background and the element palette read cleanly.
mol new 1crn.pdb waitfor all
mol modstyle 0 0 VDW
mol modcolor 0 0 Element
color Display Background white
display projection Orthographic
display resetview
render TachyonInternal out.tga
```

Create `vmdbench/tasks/viz/viz_render_element_1crn_001.yaml`:

```yaml
task_id: viz_render_element_1crn_001
category: visualization
bucket: synthesis
difficulty: easy
dimensions: [actionability, semantic_grounding]
initial_state:
  files: [1crn.pdb]
  pdb: 1CRN
  molecules_loaded: false
allowed_interface: [raw_tcl]
# Verifies the PICTURE, not just the scene graph: the render is non-empty on a white
# background (image_foreground) and the element colors actually appear — oxygen red,
# nitrogen blue (image_palette). Bands calibrated from the oracle via score-oracle.
user_prompt: >
  Load 1CRN, color it by element, set a white background, and render the scene to out.tga.
verify:
  required:
    - {kind: molecule_loaded,       where: {}}
    - {kind: representation_exists, where: {color: Element}}
    - {kind: file_rendered,         where: {path: out.tga, must_be_image: true, min_bytes: 1000}}
    - {kind: image_foreground,      where: {path: out.tga, background: white, check_background: true, min_coverage: 0.02}}
    - {kind: image_palette,         where: {path: out.tga, min_distinct: 2, expect_colors: [red, blue]}}
  optional:
    - {kind: no_runtime_errors,     where: {}}
reproducibility:
  exports: [tcl]
```

Add the live test to `vmdbench/tests/test_image_probe.py` (mirrors `test_oracle.py` — requires VMD, like the existing oracle tests):

```python
from vmdbench.spec.task_card import load_card
from vmdbench.adapters.oracle_tcl import run_oracle

_TASKS = ROOT / "vmdbench" / "tasks"
_ORACLES = ROOT / "vmdbench" / "oracles"


class ImageProbeLiveTests(unittest.TestCase):
    def test_image_probes_on_real_element_render(self):
        card = load_card(_TASKS / "viz" / "viz_render_element_1crn_001.yaml")
        with tempfile.TemporaryDirectory() as d:
            run = run_oracle(card, _ORACLES / "viz_render_element_1crn_001.tcl", Path(d))
            self.assertTrue((run.workdir / "out.tga").exists(), run.result.stderr)
            ctx = CheckContext(workdir=run.workdir)
            fg = evaluate({"kind": "image_foreground",
                           "where": {"path": "out.tga", "background": "white",
                                     "check_background": True, "min_coverage": 0.02}},
                          run.result.scene, ctx)
            self.assertTrue(fg.passed, fg.observed)
            pal = evaluate({"kind": "image_palette",
                            "where": {"path": "out.tga", "min_distinct": 2,
                                      "expect_colors": ["red", "blue"]}},
                           run.result.scene, ctx)
            self.assertTrue(pal.passed, pal.observed)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_image_probe.py::ImageProbeLiveTests -v`
Expected: FAIL — `FileNotFoundError` on the card/oracle path (not yet created) if you run this step before creating the files above; otherwise it exercises the real render. (If VMD is not installed on the machine, this test errors like the existing `test_oracle.py` tests — run it where VMD is available.)

- [ ] **Step 3: Calibrate the bands against the gold render**

Run the oracle through the scorer and confirm the gate passes:

Run: `python -m vmdbench.cli score-oracle vmdbench/tasks/viz/viz_render_element_1crn_001.yaml vmdbench/oracles/viz_render_element_1crn_001.tcl --timeout 240`
Expected: JSON with `"gate": true` and `"replay_clean": true`. Read the `image_palette` `observed.distinct` and `observed.dominant`, and `image_foreground` `observed.coverage`. If the gold render's distinct count or colors differ from the card's bands, adjust `min_distinct` / `expect_colors` / `min_coverage` in the card to match the gold (same calibration workflow as `scalar_within`). Re-run until `gate: true`.

- [ ] **Step 4: Run the full suite to verify everything passes**

Run: `python -m pytest vmdbench/tests/ -v`
Expected: PASS — the new `test_image_probe.py` (all classes incl. live), plus `test_cards_load.py` now loads the new card, and the pre-existing suite is green.

- [ ] **Step 5: Commit**

```bash
git add vmdbench/tasks/viz/viz_render_element_1crn_001.yaml vmdbench/oracles/viz_render_element_1crn_001.tcl vmdbench/tests/test_image_probe.py
git commit -m "feat(vmdbench): calibrated element-render demo card + live image-probe test"
```

---

## Notes / deviations from the spec

- **RLE TGA dropped (YAGNI):** VMD's `render TachyonInternal` writes uncompressed type-2 only; the decoder raises a clear error on any other type. The spec's round-trip test is kept for type-2 (both row orders).
- **One demo card instead of two:** the spec suggested extending `viz_color_element_1crn_001` plus a multi-chain color-by-chain card. No bundled fixture is cleanly multi-chain (`1qmz.pdb` has blank chain IDs; `1crn` is single-chain), so `min_distinct` is exercised via Element coloring (oxygen/nitrogen/carbon give ≥2–3 hues) in one self-contained card, leaving the existing element card untouched.
- **No env/scene_state changes:** confirmed unnecessary for reference-free probes (those were only for the deferred projected-coordinate probe).
