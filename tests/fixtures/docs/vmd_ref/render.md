## render snapshot

Capture the current OpenGL framebuffer to disk. Syntax:
`render snapshot <filename>`. Writes uncompressed Type-2 TGA on every
platform (BGR or BGRA depending on alpha settings). Cheapest renderer
— uses the live framebuffer with no recomputation.

## render TachyonInternal

Higher-quality ray-traced render. Syntax:
`render TachyonInternal <filename>`. Honors ambient occlusion, shadows,
and `mol material AO*` presets that `render snapshot` ignores. Slower
than `render snapshot` (typically 0.5–5 s per frame for medium scenes).

## render Tachyon

Off-screen renderer that writes a Tachyon scene file (`.dat`) instead
of an image. The scene file can then be passed to the standalone
`tachyon` binary for batch rendering. Useful in headless / cluster
contexts where the live framebuffer isn't available.

## display projection

Toggle between perspective and orthographic projection. Syntax:
`display projection Orthographic` or `display projection Perspective`.
Orthographic is the convention for paper figures; perspective is the
default and reads as more "natural" in interactive use.

## display backgroundcolor

Set the viewport background color. Syntax: `display backgroundcolor white`
(or `black`, `gray`, etc.). For PDF/print figures, always set white —
the default near-black destroys printability.

## color Display Background

Alternate way to set the background. Syntax:
`color Display Background <colorname>`. Same effect as
`display backgroundcolor` but uses VMD's named-color table.
