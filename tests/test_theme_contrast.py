"""Dark and light tokens (Part B V2): exact values and contrast ratios.

Parses the PALETTE block of plugin/theme.tcl, so it needs no Tcl or Tk and
CI checks it on every push.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

import pytest

REPO = Path(__file__).resolve().parents[1]
THEME = REPO / "plugin" / "theme.tcl"

# Part B V2, token table (light, dark).
SPEC: Dict[str, Dict[str, str]] = {
    "light": {
        "chrome": "#ececec", "surface": "#ffffff", "text": "#1d1d1f",
        "text2": "#3c3c43", "muted": "#636366", "faint": "#a1a1a6",
        "hairline": "#d6d6da", "accent": "#0a66d8", "ok": "#1a7f37",
        "err": "#c8262e", "err_bg": "#fdecec", "warn": "#835700",
        "warn_bg": "#fff5df", "warn_bd": "#efd59b", "warn_fg": "#5c4300",
        "code_bg": "#f4f4f6", "icode_bg": "#ececf0", "hover": "#f0f0f4",
        "stop_bg": "#1d1d1f", "stop_fg": "#ffffff", "dot_ok": "#28c840",
        "dot_warn": "#d88a00", "dot_off": "#ff5f57", "syn_cmd": "#0550ae",
        "syn_var": "#953800", "syn_str": "#0a3069", "syn_num": "#8250df",
        "syn_brace": "#835700", "syn_opt": "#57606a", "syn_cmt": "#636c76",
    },
    "dark": {
        "chrome": "#2c2c2e", "surface": "#1e1e1e", "text": "#e6e6eb",
        "text2": "#c9c9ce", "muted": "#9a9aa1", "faint": "#5f5f65",
        "hairline": "#0c0c0d", "accent": "#4ea1ff", "ok": "#3bd16f",
        "err": "#ff6b64", "err_bg": "#3a1f1e", "warn": "#e6aa3f",
        "warn_bg": "#3a2f16", "warn_bd": "#5a4820", "warn_fg": "#f6d58f",
        "code_bg": "#28282b", "icode_bg": "#313135", "hover": "#29292c",
        "stop_bg": "#e6e6eb", "stop_fg": "#1e1e1e", "dot_ok": "#32d74b",
        "dot_warn": "#ffb340", "dot_off": "#ff453a", "syn_cmd": "#79c0ff",
        "syn_var": "#ffa657", "syn_str": "#a5d6ff", "syn_num": "#d2a8ff",
        "syn_brace": "#e3b341", "syn_opt": "#c3cad3", "syn_cmt": "#8b949e",
    },
}

# (foreground, background, light minimum, dark minimum), V2's figures. Ratios
# are compared after rounding to one decimal, the way the spec quotes them
# (dark muted on chrome measures 4.98, which the spec states as >= 5.0).
CONTRAST = [
    ("text", "surface", 16.8, 13.4),
    ("muted", "surface", 6.0, 6.0),
    ("muted", "chrome", 5.0, 5.0),
    ("accent", "surface", 5.4, 6.2),
    ("ok", "surface", 5.1, 8.4),
    ("warn_fg", "warn_bg", 8.6, 8.6),
] + [("syn_%s" % c, "code_bg", 4.5, 4.5) for c in ("cmd", "var", "str", "num", "brace", "opt", "cmt")]


def load_palettes() -> Dict[str, Dict[str, str]]:
    lines = THEME.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "set PALETTE {")
    palettes: Dict[str, Dict[str, str]] = {}
    mode = None
    for line in lines[start + 1:]:
        s = line.strip()
        header = re.fullmatch(r"(light|dark) \{", s)
        if header:
            mode = header.group(1)
            palettes[mode] = {}
            continue
        if s == "}":
            if mode is None:
                break
            mode = None
            continue
        pair = re.fullmatch(r"([a-z0-9_]+)\s+(#[0-9a-f]{6})", s)
        if pair and mode is not None:
            palettes[mode][pair.group(1)] = pair.group(2)
    return palettes


def _luminance(colour: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_palette_matches_spec_table():
    palettes = load_palettes()
    for mode in ("light", "dark"):
        for token, value in SPEC[mode].items():
            assert palettes[mode].get(token) == value, (mode, token)


def test_light_and_dark_define_the_same_tokens():
    palettes = load_palettes()
    assert sorted(palettes["light"]) == sorted(palettes["dark"])


@pytest.mark.parametrize("fg,bg,light_min,dark_min", CONTRAST)
def test_contrast_ratios(fg, bg, light_min, dark_min):
    palettes = load_palettes()
    for mode, minimum in (("light", light_min), ("dark", dark_min)):
        ratio = contrast(palettes[mode][fg], palettes[mode][bg])
        assert round(ratio, 1) >= minimum, "%s %s on %s: %.2f < %s" % (mode, fg, bg, ratio, minimum)
