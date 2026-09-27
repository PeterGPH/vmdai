"""P03-T10: in-run compaction behind LoopOptions.compact_in_run (§2b, C5)."""
from __future__ import annotations

import copy
import json
import math
import threading

from helpers.app_driver import InstantBridge, ScriptedLoop, tool_use
from helpers.conversation_data import (
    assistant_tools,
    image_block,
    snapshot_result,
    tiny_png,
    tool_results,
    user,
)
from vmd_ai_runtime import conversation
from vmd_ai_runtime.claude_loop import LoopOptions, RunContext, _vmd_tools

SYSTEM = "You are a test."
OUTPUT = "r" * 2000
NOTE = ("[output truncated: 9000 lines, 80 KB. Full text: /x/outputs/k2.txt. "
        "Don't print it again: read a slice of that file with Tcl.]")


def _script(rounds):
    return [("", [tool_use("tc_%d" % i, "measure rmsf %d" % i)]) for i in range(rounds)] + [("All done.", [])]


def _budgeted_loop(target_budget, rounds):
    """An Ollama-named ScriptedLoop whose run budget is about ``target_budget`` chars."""
    tools_chars = len(json.dumps(_vmd_tools(include_search_docs=False, include_wiki=False)))
    num_ctx = 4096 + math.ceil((target_budget + len(SYSTEM) + tools_chars) / conversation.CHARS_PER_TOKEN)
    return ScriptedLoop(_script(rounds), provider_name="ollama", api_key="http://127.0.0.1:9", model="m",
                        options=LoopOptions(num_ctx=num_ctx, compact_in_run=True))


def _run(loop):
    events, out = [], []
    loop.run(prompt="compute RMSF per residue", system_prompt=SYSTEM,
             tool_bridge=InstantBridge(lambda tool_input: OUTPUT), session_id="sess_t",
             session_queue=None, cancel_event=threading.Event(), on_chunk=lambda text: None,
             ctx=RunContext(request_id="req_t", chat_id="chat_000000000000",
                            on_event=events.append, messages_out=out))
    return events, out


def _near_full(events):
    return [e for e in events
            if (e.get("metadata") or {}).get("kind") == "status"
            and e["metadata"].get("phase") == "context_near_full"]


def _result_texts(messages):
    return [b["content"] for m in messages if isinstance(m.get("content"), list)
            for b in m["content"] if b.get("type") == "tool_result"]


def test_status_context_near_full_once_at_90():
    loop = _budgeted_loop(9000, rounds=8)
    events, _out = _run(loop)
    assert len(_near_full(events)) == 1
    assert loop.last_compactions >= 1
    loop.script = _script(8)                  # a second request warns again, once
    events, _out = _run(loop)
    assert len(_near_full(events)) == 1


def test_compacted_copy_at_100_keeps_last_two_rounds_and_newest_image():
    loop = ScriptedLoop([], provider_name="ollama", api_key="http://127.0.0.1:9", model="m",
                        options=LoopOptions(num_ctx=32768, compact_in_run=True))
    old_png, new_png = tiny_png(4, 4), tiny_png(5, 5)
    messages = [
        user("go"),
        assistant_tools("", ("k0", "capture_vmd_snapshot", {})), snapshot_result("k0", old_png),
        assistant_tools("", ("k1", "capture_vmd_snapshot", {})), snapshot_result("k1", new_png),
        assistant_tools("", ("k2", "run_vmd_command", {"command": "a"})), tool_results(("k2", True, "x" * 3000 + "\n" + NOTE)),
        assistant_tools("", ("k3", "run_vmd_command", {"command": "b"})), tool_results(("k3", True, "y" * 3000)),
        assistant_tools("", ("k4", "run_vmd_command", {"command": "c"})), tool_results(("k4", True, "z" * 3000)),
    ]
    frozen = copy.deepcopy(messages)
    loop._run_budget = 5000
    loop._context_warned = True               # no run() in progress, so no status event
    compacted, did_compact = loop._compact_for_call(messages)
    assert did_compact is True and loop.last_compactions == 1
    assert messages == frozen                 # the in-run list is never modified
    k0, k1, k2, k3, k4 = [b for m in compacted if isinstance(m.get("content"), list)
                          for b in m["content"] if b.get("type") == "tool_result"]
    assert k0["content"][1]["type"] == "text" and "earlier snapshot" in k0["content"][1]["text"]
    assert k1["content"][1] == image_block(new_png)            # the newest image stays
    assert k2["content"].startswith("x" * 300) and k2["content"].endswith("\n" + NOTE)
    assert len(k2["content"]) < 700                            # C5: the stub keeps output_path
    assert k3["content"] == "y" * 3000 and k4["content"] == "z" * 3000
    loop._run_budget = 10 ** 6
    same, did_compact = loop._compact_for_call(messages)
    assert same is messages and did_compact is False


def test_messages_and_messages_out_keep_full_bodies():
    loop = _budgeted_loop(9000, rounds=8)
    _events, out = _run(loop)
    stored = _result_texts(out)
    assert len(stored) == 8 and all(text == OUTPUT for text in stored)
    compacted = [i for i, call in enumerate(loop.calls) if any(len(t) < len(OUTPUT) for t in _result_texts(call))]
    assert compacted and loop.last_compactions == len(compacted)
    for call in loop.calls:
        assert all(text == OUTPUT for text in _result_texts(call)[-2:])
    assert all(text == OUTPUT for call in loop.calls[:compacted[0]] for text in _result_texts(call))


def test_off_when_options_none():
    loop = ScriptedLoop(_script(8), provider_name="ollama", api_key="http://127.0.0.1:9", model="m")
    events, _out = _run(loop)
    assert _near_full(events) == []
    assert loop.last_compactions == 0 and loop._run_budget is None
    assert all(text == OUTPUT for call in loop.calls for text in _result_texts(call))
