"""C1 enforcement in the product bridge (runtime/vmd_ai_runtime/tool_bridge.py)."""
from __future__ import annotations

import threading
from unittest import mock

from helpers.bridge_harness import SESSION_ID, BridgeCall, make_bridge, make_session
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, RunContext
from vmd_ai_runtime.events import EventQueue
from vmd_ai_runtime.recorder import RunRecorder

EXEC_MESSAGE = (
    "Not run: `exec` is never run by ChatVMD. If the user needs it, show the "
    "command in a tcl code block so they can copy it and run it in the VMD "
    "console themselves."
)


def test_blocked_never_queued(tmp_path):
    for authenticated in (True, False):
        bridge = make_bridge(make_session(tmp_path, authenticated=authenticated), pickup_timeout_s=0.3)
        call = BridgeCall(bridge, tool_input={"command": "set x [exec ls]"}, timeout=0.3)
        result = call.join(wait=2.0)
        assert call.queue.poll(0, 50)["events"] == [], "a blocked call must never reach VMD"
        assert result["executed"] == "no"
        assert result["blocked"][0]["id"] == "cmd_exec"


def test_blocked_result_shape(tmp_path):
    bridge = make_bridge(make_session(tmp_path), pickup_timeout_s=0.3)
    result = BridgeCall(bridge, tool_input={"command": "mol new a.pdb; exit"}).join()
    assert result["ok"] is False
    assert result["executed"] == "no"
    assert result["blocked"] == [{"id": "cmd_quit", "word": "exit", "text": "exit"}]
    assert result["error"] == "Not run: this would close the user's VMD session."
    exec_result = BridgeCall(bridge, tool_input={"command": "exec curl -O x.pdb"},
                             call_key="k0000000000e").join()
    assert exec_result["error"] == EXEC_MESSAGE
    assert exec_result["blocked"] == [{"id": "cmd_exec", "word": "exec", "text": "exec curl -O x.pdb"}]


def test_allowed_command_not_blocked(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    call = BridgeCall(bridge, tool_input={"command": 'puts "exit code"'})
    assert call.tool_start()["metadata"]["tool_input"]["command"] == 'puts "exit code"'
    call.cancel.set()
    assert call.join()["blocked"] is None


def test_recorder_untouched_when_blocked(tmp_path):
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m")
    loop.recorder = RunRecorder.for_cwd(tmp_path)
    tid = loop.recorder.start_task("blocked")
    blocked = {"ok": False, "output": "", "executed": "no", "error": EXEC_MESSAGE,
               "blocked": [{"id": "cmd_exec", "word": "exec", "text": "exec ls"}]}
    loop._recorder_record(tool_name="run_vmd_command", tool_input={"command": "exec ls"},
                          result=blocked, duration_ms=0.0)
    manifest = loop.recorder.read_manifest(tid)
    assert (manifest["turn_count"], manifest["failed_count"], manifest["successful_count"]) == (0, 0, 0)
    assert "exec ls" not in loop.recorder.read_transcript(tid)
    # M5 (final review): a blocked call never reached VMD, so it must not
    # count toward the C6 manifest's counts.tool_calls either.
    assert getattr(loop, "_prov_tool_calls", 0) == 0

    allowed = {"ok": True, "output": "0 1", "executed": "yes", "error": ""}
    loop._recorder_record(tool_name="run_vmd_command", tool_input={"command": "mol list"},
                          result=allowed, duration_ms=1.0)
    assert loop._prov_tool_calls == 1


def test_tool_started_and_finished_still_emitted(tmp_path):
    bridge = make_bridge(make_session(tmp_path), pickup_timeout_s=0.3)
    turns = iter([
        ("", [{"type": "tool_use", "id": "t1", "name": "run_vmd_command", "input": {"command": "exec ls"}}]),
        ("I cannot run shell commands.", []),
    ])
    events, out = [], []
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m",
                          options=LoopOptions(result_format="structured"))
    with mock.patch.object(ClaudeToolLoop, "_call",
                           new=lambda self, m, s, on_text, should_cancel: next(turns)):
        loop.run(prompt="list files", system_prompt="s", tool_bridge=bridge, session_id=SESSION_ID,
                 session_queue=EventQueue(), cancel_event=threading.Event(), on_chunk=lambda t: None,
                 ctx=RunContext(request_id="req_000000000001", chat_id="chat_0123456789ab",
                                on_event=events.append, messages_out=out))
    kinds = [(e.get("metadata") or {}).get("kind") for e in events]
    assert "tool.started" in kinds and "tool.finished" in kinds
    finished = [e for e in events if (e.get("metadata") or {}).get("kind") == "tool.finished"][0]["metadata"]
    assert finished["executed"] == "no"
    assert finished["blocked"] == [{"id": "cmd_exec", "word": "exec", "text": "exec ls"}]
    results = [b for msg in out if msg["role"] == "user" and isinstance(msg["content"], list)
               for b in msg["content"] if b.get("type") == "tool_result"]
    assert results and EXEC_MESSAGE in str(results[0]["content"])
