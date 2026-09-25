"""S7 golden-request harness (spec §2a "Golden requests", P01-T04/T05).

Builds the benchmark adapter exactly as SciVisAgentBench does
(``VmdAiAgent(config)`` + ``setup()``), swaps in a scripted bridge, and drives
one task through ``run_task`` while a fake ``urlopen`` records every request.
Goldens store each request's url, method, headers and raw ``body_text`` and
are compared byte-for-byte: json.dumps key order and separators are part of
the pinned behaviour, so parsed-dict equality is not enough.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import difflib
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

from helpers.fake_evaluation_framework import install as install_fake_framework

REPO = Path(__file__).resolve().parents[2]
SCIVIS_DIR = REPO / "integrations" / "scivisagentbench"
GOLDEN_DIR = REPO / "tests" / "fixtures" / "golden_requests"
UPDATE_ENV = "CHATVMD_UPDATE_GOLDENS"

# S7 (spec §2a): "goldens never regenerated" -- the plan (P01-T04/T05) pins these 13
# files' SHA-256 up front, taken from the files this repo actually ships. A test built
# on this dict (tests/test_benchmark_golden_requests.py::test_golden_files_pinned)
# fails loudly if a golden is ever silently edited, added or removed, closing the gap
# `assert_golden` leaves: it happily accepts *any* existing golden's bytes.
GOLDEN_SHA256: Dict[str, str] = {
    "anthropic_extra_tools": "d19ea22cbacf9f103d8c30f7609f37bea9574eb6fe4c1d3954206266e0cb2de3",
    "anthropic_none": "10231c03bd7a487d4d6329f0955a39aa75bb3f4fa7e50094636b465750720f9b",
    "anthropic_rag": "0229f194ccbfe8685919c06bb69bf0a5559fb892b3c1c204957954598d9b86fc",
    "anthropic_wiki": "7c46e3fae4117760d67140ec834e70537d098b08c333ad69b389c1e60b7b8135",
    "ollama_extra_tools": "68c633a11f6d094263e33250eb38fe34d7163b5d03f5f38ef8614a31af97b3bf",
    "ollama_none": "4281275674c78b95afc991d14c765ce53f78f67792addb9409a306b9ef2905bf",
    "ollama_rag": "dfeef7056c9270c6b0f1ad25c1ec22bc04189c0ab4f9b6c5a061e98afb859365",
    "ollama_rescue": "72ee3a874f45fd689dfe3e42816605e51b74f5d24339a88e8223b243b8e7cf39",
    "ollama_wiki": "8e148565149946b9a52d3eadbc42356c24c22a8b971cfe17b329b14c65289c89",
    "openrouter_vllm_extra_tools": "451c42066875289ffafeb702b9d7593f4bf0c5a8b7dd72eb8262673192ff851a",
    "openrouter_vllm_none": "ecfaee2bded1d5eb2e8f9b4c272c55cbf86e4e93dd37bd53c9e1e23a68813af1",
    "openrouter_vllm_rag": "da74e77f6ab3c5ee7d1ce5dde258c52e3000ebae8f9e6b44f09d4087cdcaed53",
    "openrouter_vllm_wiki": "cc1db9c3dd573c5c4bc8cadbd0019f7af473b51ca82e67d288c66f507fab3e28",
}


def golden_file_sha256(name: str) -> str:
    return hashlib.sha256((GOLDEN_DIR / f"{name}.json").read_bytes()).hexdigest()


TASK_PROMPT = "Load 1ubq.pdb, show it as NewCartoon, and take a snapshot to check the view."
RESCUE_PROMPT = "Load 1ubq.pdb."
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
)

# One benchmark config per provider (the "none" arm).
PROVIDER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "anthropic": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5",
        "api_key": "sk-ant-golden",
    },
    "openrouter_vllm": {
        "provider": "vllm",
        "model": "Qwen/Qwen2.5-72B-Instruct-AWQ",
        "base_url": "http://localhost:8000/v1",
        "api_key": "sk-local-anything",
    },
    "ollama": {
        "provider": "ollama",
        "model": "qwen3.8:27b",
        "base_url": "http://127.0.0.1:11435",
    },
}
COMMON_CONFIG: Dict[str, Any] = {
    "agent_name": "vmd_ai",
    "eval_mode": "mcp",
    "experiment_number": "golden",
    "enable_rag": False,
    "enable_wiki": False,
    "loop_timeout": 120,
    "vmd_backend": "vmd_python",
}

# (tool_use id, tool name, input) per scripted turn; ids are ignored by Ollama.
_TURNS: List[Tuple[str, List[Tuple[str, str, Dict[str, Any]]]]] = [
    (
        "I'll load the structure and set the style.",
        [
            ("toolu_golden_1", "run_vmd_command",
             {"command": "mol new 1ubq.pdb", "rationale": "load the structure"}),
            ("toolu_golden_2", "run_vmd_command",
             {"command": "mol modstyle 0 0 NewCartoonX"}),
        ],
    ),
    (
        "The style name was wrong; checking the view.",
        [("toolu_golden_3", "capture_vmd_snapshot", {"purpose": "check the cartoon"})],
    ),
    ("1ubq is loaded and shown as NewCartoon.", []),
]
_RESCUE_TURNS: List[Tuple[str, List[Tuple[str, str, Dict[str, Any]]]]] = [
    (
        'I will run this: {"name": "run_vmd_command", '
        '"arguments": {"command": "mol new 1ubq.pdb"}}',
        [],
    ),
    ("Loaded 1ubq.", []),
]

_OK_RESULT = {"ok": True, "output": "Info) Using plugin pdb for structure file 1ubq.pdb\n0",
              "error": ""}
_ERROR_RESULT = {"ok": False, "output": "",
                 "error": "Unknown representation style 'NewCartoonX'"}
_SNAPSHOT_RESULT = {"ok": True, "output": "Snapshot rendered (check the cartoon).",
                    "error": "", "image_b64": TINY_PNG_B64, "image_mime": "image/png"}
DEFAULT_RESULTS: List[Dict[str, Any]] = [_OK_RESULT, _ERROR_RESULT, _SNAPSHOT_RESULT]
RESCUE_RESULTS: List[Dict[str, Any]] = [_OK_RESULT]


class RecordingUrlopen:
    """Fake ``urllib.request.urlopen``: records each request, serves canned bodies."""

    def __init__(self, responses: List[bytes]) -> None:
        self._responses = list(responses)
        self.requests: List[Dict[str, Any]] = []

    def __call__(self, req: Any, timeout: Optional[float] = None, **_kw: Any) -> io.BytesIO:
        data = req.data or b""
        self.requests.append({
            "url": req.full_url,
            "method": req.get_method(),
            "headers": dict(sorted(req.header_items())),
            "body_text": data.decode("utf-8"),
        })
        if not self._responses:
            raise AssertionError(
                f"unexpected request #{len(self.requests)} to {req.full_url}"
            )
        return io.BytesIO(self._responses.pop(0))

    @property
    def unconsumed(self) -> int:
        return len(self._responses)


class ScriptedBridge:
    """Strict six-keyword bridge that answers tool calls from a fixed list."""

    def __init__(self, results: Optional[List[Dict[str, Any]]] = None) -> None:
        self._results = copy.deepcopy(DEFAULT_RESULTS if results is None else results)
        self.calls: List[Dict[str, Any]] = []

    def reset(self) -> None:
        return None

    def close(self) -> None:
        return None

    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input,
                     session_queue, cancel_event) -> Dict[str, Any]:
        self.calls.append({"tool_call_id": tool_call_id, "tool_name": tool_name,
                           "tool_input": dict(tool_input or {})})
        if not self._results:
            raise AssertionError(f"no scripted result left for {tool_name}")
        return self._results.pop(0)


def _sse(events: List[Dict[str, Any]], done: bool = False) -> bytes:
    body = b"".join(b"data: " + json.dumps(e).encode("utf-8") + b"\n\n" for e in events)
    return body + (b"data: [DONE]\n\n" if done else b"")


def _anthropic_turn(text: str, calls: List[Tuple[str, str, Dict[str, Any]]]) -> bytes:
    events: List[Dict[str, Any]] = [
        {"type": "message_start", "message": {"id": "msg_golden", "role": "assistant"}},
    ]
    index = 0
    if text:
        events += [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": text}},
            {"type": "content_block_stop", "index": 0},
        ]
        index = 1
    for call_id, name, tool_input in calls:
        events += [
            {"type": "content_block_start", "index": index,
             "content_block": {"type": "tool_use", "id": call_id, "name": name, "input": {}}},
            {"type": "content_block_delta", "index": index,
             "delta": {"type": "input_json_delta", "partial_json": json.dumps(tool_input)}},
            {"type": "content_block_stop", "index": index},
        ]
        index += 1
    events += [
        {"type": "message_delta",
         "delta": {"stop_reason": "tool_use" if calls else "end_turn"}},
        {"type": "message_stop"},
    ]
    return _sse(events)


def _openai_turn(text: str, calls: List[Tuple[str, str, Dict[str, Any]]]) -> bytes:
    chunks: List[Dict[str, Any]] = []
    if text:
        chunks.append({"choices": [{"index": 0,
                                    "delta": {"role": "assistant", "content": text}}]})
    for i, (call_id, name, tool_input) in enumerate(calls):
        chunks.append({"choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": i, "id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(tool_input)},
        }]}}]})
    chunks.append({"choices": [{"index": 0, "delta": {},
                                "finish_reason": "tool_calls" if calls else "stop"}]})
    return _sse(chunks, done=True)


def _ollama_turn(text: str, calls: List[Tuple[str, str, Dict[str, Any]]]) -> bytes:
    lines: List[Dict[str, Any]] = []
    if text:
        lines.append({"model": "golden", "done": False,
                      "message": {"role": "assistant", "content": text}})
    final: Dict[str, Any] = {"role": "assistant", "content": ""}
    if calls:
        final["tool_calls"] = [{"function": {"name": name, "arguments": tool_input}}
                               for _call_id, name, tool_input in calls]
    lines.append({"model": "golden", "done": True, "done_reason": "stop", "message": final})
    return b"".join(json.dumps(line).encode("utf-8") + b"\n" for line in lines)


_TURN_BUILDERS = {
    "anthropic": _anthropic_turn,
    "openrouter_vllm": _openai_turn,
    "ollama": _ollama_turn,
}


def scripted_responses(provider: str, *, rescue: bool = False) -> List[bytes]:
    """Response bodies for the scripted run (3 turns, or 2 for the rescue run)."""
    if rescue and provider != "ollama":
        raise ValueError("the rescued-turn script is Ollama-only")
    build = _TURN_BUILDERS[provider]
    return [build(text, calls) for text, calls in (_RESCUE_TURNS if rescue else _TURNS)]


ARMS: Tuple[str, ...] = ("none", "rag", "wiki", "extra_tools")


class StubDocsSearch:
    """Replaces vmd_ai_runtime.docs_search.DocsSearch for the rag arm."""

    is_available = True

    def __init__(self, index_dir: Optional[str] = None) -> None:
        self.index_dir = index_dir

    def search(self, query: str, k: int = 5, scope: str = "all") -> Dict[str, Any]:
        raise AssertionError("the golden script never calls search_docs")


def benchmark_config(provider: str, arm: str, tmp_path: Path) -> Dict[str, Any]:
    """The adapter config for one (provider, arm) cell of the S7 matrix."""
    if provider not in PROVIDER_CONFIGS:
        raise ValueError(f"unknown provider {provider!r}")
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}")
    config = dict(COMMON_CONFIG, **PROVIDER_CONFIGS[provider])
    if arm == "rag":
        config["enable_rag"] = True
    elif arm == "wiki":
        config.update(enable_wiki=True,
                      wiki_root=str(tmp_path / "wiki"),
                      wiki_raw_root=str(tmp_path / "raw"))
    elif arm == "extra_tools":
        config["enable_semantic_tools"] = True
    return config


def import_adapter() -> Any:
    install_fake_framework()
    if str(SCIVIS_DIR) not in sys.path:
        sys.path.insert(0, str(SCIVIS_DIR))
    import vmd_ai_agent  # registers "vmd_ai" with the (fake) framework

    return vmd_ai_agent


def build_benchmark_agent(config: Dict[str, Any]) -> Any:
    """A VmdAiAgent after ``asyncio.run(agent.setup())`` (vmd_backend 'vmd_python')."""
    adapter = import_adapter()
    cfg = dict(config)
    cfg["vmd_backend"] = "vmd_python"
    agent = adapter.VmdAiAgent(cfg)
    with contextlib.ExitStack() as stack:
        if cfg.get("enable_rag"):
            stack.enter_context(
                mock.patch("vmd_ai_runtime.docs_search.DocsSearch", StubDocsSearch)
            )
        asyncio.run(agent.setup())
    return agent


# S7: the benchmark's SCORED outputs, not just the wire requests -- result.response
# feeds the answer scorer and metadata["tcl_log"] becomes the scored <case>.tcl. Values
# verified by running the scripted 3-turn script for every (provider, arm) cell in
# ARMS x PROVIDERS: identical across all of them, since only the tool schema on offer
# (not the scripted conversation) varies by arm.
NONE_ARM_RESPONSE = "1ubq is loaded and shown as NewCartoon."
NONE_ARM_TCL_LOG: List[Dict[str, Any]] = [
    {"cmd": "mol new 1ubq.pdb", "ok": True, "err": ""},
    {"cmd": "mol modstyle 0 0 NewCartoonX", "ok": False,
     "err": "Unknown representation style 'NewCartoonX'"},
]


def drive_benchmark_run(agent: Any, provider: str, *, rescue: bool = False) -> List[Dict[str, Any]]:
    """Run one scripted task through ``agent.run_task``; return the recorded requests."""
    recorder = RecordingUrlopen(scripted_responses(provider, rescue=rescue))
    agent._bridge = ScriptedBridge(RESCUE_RESULTS if rescue else DEFAULT_RESULTS)
    with tempfile.TemporaryDirectory(prefix="vmdai_golden_") as work:
        task = {"working_dir": work, "case_dir": work, "case_name": "golden", "timeout": 60}
        with mock.patch("urllib.request.urlopen", recorder):
            result = asyncio.run(
                agent.run_task(RESCUE_PROMPT if rescue else TASK_PROMPT, task)
            )
    assert result.success, result.error
    assert recorder.unconsumed == 0, f"{recorder.unconsumed} scripted responses unused"
    assert agent._bridge._results == [], "scripted tool results left unused"
    if not rescue:
        assert result.response == NONE_ARM_RESPONSE, (
            f"scored response changed for {provider}: {result.response!r}"
        )
        assert result.metadata["tcl_log"] == NONE_ARM_TCL_LOG, (
            f"scored tcl_log changed for {provider}: {result.metadata['tcl_log']!r}"
        )
    return recorder.requests


def _pretty(body_text: str) -> List[str]:
    try:
        return json.dumps(json.loads(body_text), indent=1, ensure_ascii=False).splitlines()
    except ValueError:
        return body_text.splitlines()


def _first_difference(expected: str, actual: str) -> int:
    for i, (a, b) in enumerate(zip(expected, actual)):
        if a != b:
            return i
    return min(len(expected), len(actual))


def _diff_request(i: int, expected: Dict[str, Any], actual: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    for key in ("url", "method"):
        if expected[key] != actual[key]:
            problems.append(f"request {i} {key}: expected {expected[key]!r}, got {actual[key]!r}")
    if expected["headers"] != actual["headers"]:
        keys = sorted(set(expected["headers"]) | set(actual["headers"]))
        for key in keys:
            want, got = expected["headers"].get(key), actual["headers"].get(key)
            if want != got:
                problems.append(f"request {i} header {key}: expected {want!r}, got {got!r}")
    want_body, got_body = expected["body_text"], actual["body_text"]
    if want_body != got_body:
        at = _first_difference(want_body, got_body)
        problems.append(
            f"request {i} body_text: first difference at char {at}: "
            f"expected ...{want_body[max(0, at - 40):at + 40]!r}... "
            f"got ...{got_body[max(0, at - 40):at + 40]!r}..."
        )
        pretty_want, pretty_got = _pretty(want_body), _pretty(got_body)
        if pretty_want == pretty_got:
            problems.append(
                f"request {i} body_text: the bodies parse to equal JSON; the bytes differ "
                "(json.dumps key order or separators changed)"
            )
        else:
            diff = difflib.unified_diff(pretty_want, pretty_got, "golden", "actual",
                                        n=2, lineterm="")
            problems.extend(list(diff)[:60])
    return problems


def assert_golden(name: str, requests: List[Dict[str, Any]]) -> None:
    """Compare ``requests`` with tests/fixtures/golden_requests/<name>.json byte-for-byte.

    A missing golden is written only when CHATVMD_UPDATE_GOLDENS=1; an
    existing one is never rewritten (S7 goldens are captured once, in M0).
    """
    path = GOLDEN_DIR / f"{name}.json"
    if not path.exists():
        if os.environ.get(UPDATE_ENV) == "1":
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            payload = {"name": name, "requests": requests}
            path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
            return
        raise AssertionError(
            f"missing S7 golden {path}; capture it once with {UPDATE_ENV}=1 "
            "(existing S7 goldens are never regenerated)"
        )
    expected = json.loads(path.read_text(encoding="utf-8"))["requests"]
    problems: List[str] = []
    if len(expected) != len(requests):
        problems.append(f"request count: expected {len(expected)}, got {len(requests)}")
    for i, (want, got) in enumerate(zip(expected, requests)):
        problems.extend(_diff_request(i, want, got))
    if problems:
        raise AssertionError(f"S7 golden mismatch for {name} ({path}):\n" + "\n".join(problems))
