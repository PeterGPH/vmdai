"""P04-T05: image_scale downscale, thumbnail and JPEG helpers (spec 2c, 2f)."""
from __future__ import annotations

import io
import time

import pytest

from helpers.provider_fakes import rgb_png, solid_png
from vmd_ai_runtime import image_scale


@pytest.fixture
def no_pillow(monkeypatch):
    monkeypatch.setattr(image_scale, "_load_pil", lambda: None)


def test_png_size():
    assert image_scale.png_size(solid_png(7, 5, (1, 2, 3))) == (7, 5)
    with pytest.raises(ValueError):
        image_scale.png_size(b"GIF89a" + b"\x00" * 30)


def test_downscale_2048_to_1024_fast(no_pillow):
    png = solid_png(2048, 1536, (200, 30, 90))
    started = time.perf_counter()
    small, width, height = image_scale.downscale_png(png, 1024)
    elapsed = time.perf_counter() - started
    assert (width, height) == (1024, 768) == image_scale.png_size(small)
    assert elapsed < 1.0
    rows, _w, _h = image_scale._decode_rgb_rows(small)
    assert rows[0][:3] == bytes((200, 30, 90))


def test_downscale_keeps_small_images_untouched():
    png = solid_png(640, 480, (9, 9, 9))
    out, width, height = image_scale.downscale_png(png, 1024)
    assert out is png and (width, height) == (640, 480)


def test_nearest_neighbour_samples_pixel_centres(no_pillow):
    rows = [bytes(v for x in range(8) for v in (x * 30, 0, 0)) for _ in range(4)]
    small, width, height = image_scale.downscale_png(rgb_png(rows, 8, 4), 4)
    assert (width, height) == (4, 2)
    out_rows, _w, _h = image_scale._decode_rgb_rows(small)
    assert [out_rows[0][i] for i in range(0, 12, 3)] == [30, 90, 150, 210]


@pytest.mark.parametrize("src,expected", [
    ((1280, 1547), (159, 192)),
    ((2048, 1536), (256, 192)),
    ((1000, 200), (256, 51)),
    ((100, 80), (100, 80)),
])
def test_thumbnail_fits_256x192_keeps_aspect(no_pillow, src, expected):
    thumb, width, height = image_scale.make_thumbnail(solid_png(src[0], src[1], (1, 2, 3)))
    assert (width, height) == expected == image_scale.png_size(thumb)
    assert width <= 256 and height <= 192


def test_jpeg_none_without_pillow(no_pillow):
    assert image_scale.to_jpeg(solid_png(16, 16, (1, 2, 3))) is None


def test_jpeg_with_pillow():
    pytest.importorskip("PIL")
    data = image_scale.to_jpeg(solid_png(16, 16, (1, 2, 3)), quality=80)
    assert data is not None and data[:2] == b"\xff\xd8"


def test_decoder_matches_pillow_on_filtered_png():
    image_mod = pytest.importorskip("PIL.Image")
    img = image_mod.new("RGB", (37, 23))
    img.putdata([((x * 7) % 256, (y * 11) % 256, (x * y) % 256)
                 for y in range(23) for x in range(37)])
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    rows, width, height = image_scale._decode_rgb_rows(buf.getvalue())
    assert (width, height) == (37, 23)
    assert b"".join(rows) == img.tobytes()
    buf = io.BytesIO()
    img.convert("RGBA").save(buf, format="PNG")
    rows, _w, _h = image_scale._decode_rgb_rows(buf.getvalue())
    assert b"".join(rows) == img.tobytes()
