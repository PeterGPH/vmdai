"""C5: full tool output on disk, head/tail cut for the model."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest import mock

from helpers.bridge_harness import CHAT_ID, SESSION_ID, BridgeCall, make_bridge, make_session
from helpers.fake_provider import SpyBridge, run_loop, scripted_call, tool_use
from vmd_ai_runtime import tool_bridge as tb
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, RunContext
from vmd_ai_runtime.conversation import stub_tool_result_text
from vmd_ai_runtime.events import EventQueue


def _run(bridge, output, **extra):
    call = BridgeCall(bridge)
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    params = {"call_key": call.call_key, "ok": True, "output": output, "error": ""}
    params.update(extra)
    bridge.post_result(SESSION_ID, params)
    return call.join()


def test_20000_lines_saved_and_cut(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    full = "\n".join("residue %05d rmsf %.3f" % (i, i * 0.001) for i in range(20000))
    result = _run(bridge, full)
    path = session.chat_dir / "outputs" / "k00000000001.txt"
    assert path.read_bytes() == full.encode("utf-8")
    assert result["output_path"] == str(path)
    assert result["output_bytes"] == len(full.encode("utf-8"))
    assert result["truncated"] is True
    text = result["output"]
    note = tb.truncation_note(20000, len(full.encode("utf-8")), str(path), False)
    assert note in text
    assert len(text) <= tb.MODEL_OUTPUT_CAP + len(note) + 2
    assert text.startswith("residue 00000 rmsf 0.000\n")
    assert text.endswith("residue 19999 rmsf 19.999")
    assert note.startswith("[output truncated: 20000 lines, ")
    assert ("Full text: %s. Don't print it again: compute what you need (measure, a narrower "
            "selection), or read a slice of that file with Tcl.]" % path) in note


def test_under_6000_no_file(tmp_path):
    session = make_session(tmp_path)
    result = _run(make_bridge(session), "y" * 6000)
    assert result["output"] == "y" * 6000
    assert result["output_path"] is None
    assert result["output_bytes"] == 6000
    assert result["truncated"] is False
    assert not (session.chat_dir / "outputs").exists()


def test_200kb_single_line(tmp_path):
    session = make_session(tmp_path)
    one_line = "{1.0 2.0 3.0}" * 16000
    result = _run(make_bridge(session), one_line)
    note = tb.truncation_note(1, len(one_line.encode("utf-8")), result["output_path"], False)
    assert note in result["output"]
    assert len(result["output"]) <= tb.MODEL_OUTPUT_CAP + len(note) + 2
    assert result["output"].startswith("{1.0 2.0 3.0}")
    assert result["output"].endswith("3.0}")
    assert Path(result["output_path"]).read_text() == one_line
    nospace = "x" * 200_000
    assert tb.cut_for_model(nospace, note="NOTE") == "x" * 3000 + "\nNOTE\n" + "x" * 2500
    undecodable = "a\udc80" * 5000
    bad = _run(make_bridge(make_session(tmp_path / "b")), undecodable)
    assert Path(bad["output_path"]).read_bytes().count(b"?") == 5000
    bad["output"].encode("utf-8")  # the model's copy is valid UTF-8


def test_cut_for_model_boundaries():
    text = "\n".join("line %04d" % i for i in range(2000))
    cut = tb.cut_for_model(text, note="N")
    head, tail = cut.split("\nN\n")
    assert len(head) <= 3000 and len(tail) <= 2500
    assert text.startswith(head) and text.endswith(tail)
    assert head.endswith(tuple("0123456789")) and tail.startswith("line ")
    assert tb.cut_for_model("short", note="N") == "short"


def test_executor_truncated_note(tmp_path):
    session = make_session(tmp_path)
    posted = "z" * 1_048_576 + "\n[executor limit: output cut at 1 MB]"
    result = _run(make_bridge(session), posted, truncated=True)
    path = session.chat_dir / "outputs" / "k00000000001.txt"
    assert "Saved text (cut at 1 MB in VMD): %s." % path in result["output"]
    assert "Full text:" not in result["output"]
    assert result["truncated"] is True


def test_late_results_cut_too(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session, cancel_grace_s=0.1)
    seen = []
    bridge.on_late_result = lambda sid, key, info: seen.append(info)
    call = BridgeCall(bridge)
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    call.cancel.set()
    assert call.join()["executed"] == "unknown"
    big = "\n".join(str(i) for i in range(20000))
    bridge.post_result(SESSION_ID, {"call_key": call.call_key, "ok": True, "output": big, "error": ""})
    assert len(seen) == 1
    info = seen[0]
    assert info["output_path"] == str(session.chat_dir / "outputs" / "k00000000001.txt")
    assert len(info["output"]) < 7000 and info["truncated"] is True


def test_tokenless_output_cut_when_chat_known(tmp_path):
    session = make_session(tmp_path, authenticated=False)
    bridge = make_bridge(session)
    call = BridgeCall(bridge, timeout=3)
    call.tool_start()
    bridge.resolve("tc_1", {"ok": True, "output": "w\n" * 5000, "error": ""})
    result = call.join()
    assert result["output_path"] == str(session.chat_dir / "outputs" / "k00000000001.txt")
    assert result["truncated"] is True


def test_compaction_stub_keeps_path(tmp_path):
    session = make_session(tmp_path)
    full = "\n".join("frame %d rmsd %.2f" % (i, i / 100.0) for i in range(20000))
    result = _run(make_bridge(session), full)
    stub = stub_tool_result_text(result["output"])
    assert result["output_path"] in stub.rstrip().splitlines()[-1]
    assert len(stub) < 1000


def test_tool_finished_carries_output_path(tmp_path):
    # C5 test: tool.finished carries output_path and output_bytes (plan 02's
    # _tool_finished_meta copies them from the bridge result).
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    queue = EventQueue()
    full = "\n".join("residue %05d" % i for i in range(20000))

    def _plugin():
        # Stand-in executor: pick up the tool_start, ack it, post the output.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            starts = [e for e in queue.poll(0, 50)["events"] if e["role"] == "tool_start"]
            if starts:
                key = starts[0]["metadata"]["call_key"]
                bridge.ack(SESSION_ID, key)
                bridge.post_result(SESSION_ID, {"call_key": key, "ok": True, "output": full, "error": ""})
                return
            time.sleep(0.01)

    threading.Thread(target=_plugin, daemon=True).start()
    turns = iter([
        ("", [{"type": "tool_use", "id": "t1", "name": "run_vmd_command",
               "input": {"command": "puts $rmsf"}}]),
        ("done", []),
    ])
    events = []
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m",
                          options=LoopOptions())
    with mock.patch.object(ClaudeToolLoop, "_call",
                           new=lambda self, m, s, on_text, should_cancel: next(turns)):
        loop.run(prompt="p", system_prompt="s", tool_bridge=bridge, session_id=SESSION_ID,
                 session_queue=queue, cancel_event=threading.Event(), on_chunk=lambda t: None,
                 ctx=RunContext(request_id="req_000000000001", chat_id=CHAT_ID,
                                on_event=events.append))
    finished = [e["metadata"] for e in events
                if (e.get("metadata") or {}).get("kind") == "tool.finished"][0]
    path = session.chat_dir / "outputs" / ("%s.txt" % finished["call_key"])
    assert finished["output_path"] == str(path)
    assert finished["output_bytes"] == len(full.encode("utf-8"))
    assert finished["truncated"] is True
    assert "Full text: %s." % path in finished["output"]


def test_options_none_benchmark_bridge_output_over_6000_unchanged():
    """Carry-forward (plan 01's final review): with options=None and a
    benchmark-style bridge (SpyBridge, a stand-in for the six-keyword
    SubprocessVmdBridge with no call_key/chat_dir concept), tool output over
    6000 characters reaches the model exactly as today: the C5 cut lives only
    in VmdToolBridge, gated on a known chat_dir, which this bridge never has.
    """
    big_output = "residue rmsf line\n" * 2000  # well over MODEL_OUTPUT_CAP
    assert len(big_output) > tb.MODEL_OUTPUT_CAP
    bridge = SpyBridge([{"ok": True, "output": big_output, "error": ""}])
    seen = []
    loop = ClaudeToolLoop("openrouter", "sk-or-test", "test/model", options=None)
    loop._call = scripted_call([
        ("", [tool_use("t1", "run_vmd_command", command="puts $rmsf")]),
        ("done", []),
    ], seen=seen)
    run_loop(loop, bridge=bridge)
    # seen[1] is the messages the second turn saw, ending with the tool
    # result message built from the bridge's raw (uncut) output.
    tool_result_message = seen[1][-1]
    assert tool_result_message["role"] == "user"
    block = tool_result_message["content"][0]
    assert block["type"] == "tool_result"
    assert block["content"] == big_output
    assert "output truncated" not in block["content"]
    assert "Full text:" not in block["content"]
