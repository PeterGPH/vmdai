"""S7 hash pins (spec §2a "Hashes", "Image bytes"; §2c "Thumbnails").

VMD_SYSTEM_PROMPT, WIKI_SYSTEM_PROMPT_ADDENDUM, the tool schemas and the PNG
bytes image_utils produces are frozen for the benchmark.  A failure here means
a benchmark-visible change: revert it, or put the new behaviour behind a
LoopOptions flag (spec §2a).  Never update these constants to make a test pass.
"""
from __future__ import annotations

import hashlib
import json
import zlib
from pathlib import Path
from typing import Any

import pytest

from vmd_ai_runtime import claude_loop, image_utils

FIXTURE_TGA = Path(__file__).resolve().parent / "fixtures" / "images" / "pin_8x6.tga"
FIXTURE_TGA_SHA256 = "595b1de25339c1c17f8a5acfbdc2dc89de528b080138295e24b3c6bb0e846fd3"
PNG_SHA256 = "bc2e97db09caa57c79d6908fd201836b06ae0c8ea1198a046dbcb717601e0f32"

PROMPT_HASHES = {
    "VMD_SYSTEM_PROMPT": "e6ae7af23836101f82b65c1bcf59f95874af062c7711b8e348b2e9324dafe252",
    "WIKI_SYSTEM_PROMPT_ADDENDUM": "4e17154cc2b74dfcaf5b22b648de1bf2843d1d1d3c819c4872ade177cb18ab63",
}
TOOL_CONSTANT_HASHES = {
    "SEARCH_DOCS_TOOL": "13ad90d9b0c7dfb5fc322f2fa3f41cff6cc2b00b3fb3c4156a60491377ce863d",
    "WIKI_LIST_TOOL": "c7e3c679bb64d9e8fed4106fca8f46e76e46efabbb4fa8170a50b64122b0f19e",
    "WIKI_READ_TOOL": "b8ec993c316b723d7e4912abe7eb62af276b179449ca7ac0dcfa6bb2d2cda9d4",
    "WIKI_UPDATE_TOOL": "0f65b26341194759e83da78ef4b79d65736de2ea51530c0461d185f6595cf094",
    "WIKI_VERIFY_TOOL": "4391a6537b3f263b63bb09de5cf592c0ef2107f47d5f12d9ccb8737b9cbbecbe",
}
VMD_TOOLS_HASH = "64f79dbc1aa851bbaaeb72ee26cefeb43578b8a1cf0c9561a8bc23adb8f19614"
VMD_TOOLS_FN_HASHES = {
    (False, False): "58593769d174dd7dc42a1940ed3696b371b7b1c15751c96c68b4680e670b6210",
    (False, True): "a6d5051ba3c542809537165ff180f048b8feddb525fca5cacd57466e570cafbe",
    (True, False): "64f79dbc1aa851bbaaeb72ee26cefeb43578b8a1cf0c9561a8bc23adb8f19614",
    (True, True): "f28a2ef6444876191d704b54f39c78559303d0a63d61ba768a8913da79c2cb32",
}


def canonical_sha256(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("name", sorted(PROMPT_HASHES))
def test_prompt_hashes(name):
    assert canonical_sha256(getattr(claude_loop, name)) == PROMPT_HASHES[name]


@pytest.mark.parametrize("name", sorted(TOOL_CONSTANT_HASHES))
def test_tool_constant_hashes(name):
    assert canonical_sha256(getattr(claude_loop, name)) == TOOL_CONSTANT_HASHES[name]


@pytest.mark.parametrize("include_search_docs,include_wiki", sorted(VMD_TOOLS_FN_HASHES))
def test_tool_schema_hashes(include_search_docs, include_wiki):
    tools = claude_loop._vmd_tools(include_search_docs=include_search_docs,
                                   include_wiki=include_wiki)
    assert canonical_sha256(tools) == VMD_TOOLS_FN_HASHES[(include_search_docs, include_wiki)]


def test_vmd_tools_constant_hash():
    assert canonical_sha256(claude_loop.VMD_TOOLS) == VMD_TOOLS_HASH


def test_max_turns_pinned():
    assert claude_loop.ClaudeToolLoop.MAX_TURNS == 28


def test_image_utils_png_bytes():
    assert hashlib.sha256(FIXTURE_TGA.read_bytes()).hexdigest() == FIXTURE_TGA_SHA256
    for convert in (image_utils.read_image_as_png_bytes, image_utils.tga_to_png_bytes):
        png = convert(str(FIXTURE_TGA))
        assert png is not None
        assert hashlib.sha256(png).hexdigest() == PNG_SHA256, (
            f"{convert.__name__} output changed (zlib {zlib.ZLIB_RUNTIME_VERSION})"
        )
