"""C3: structured model-facing failure text (result_format) and executed status."""
from __future__ import annotations

import threading
from unittest import mock

from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, RunContext, _build_tool_result_block
from vmd_ai_runtime.events import EventQueue

ERROR_INFO = 'invalid command name "bogus"\n    while executing\n"bogus"'
FAILED = {
    "ok": False, "output": "", "executed": "yes", "error": 'invalid command name "bogus"',
    "statements": {"total": 4, "applied": 2,
                   "failed": {"index": 3, "text": "bogus", "error_info": ERROR_INFO}},
}
PRECHECK = {
    "ok": False, "output": "", "executed": "no",
    "error": "Nothing was run: statement 2 of 2 is incomplete (unbalanced braces, brackets or quotes)",
    "statements": {"total": 2, "applied": 0,
                   "failed": {"index": 2, "text": "foreach a {1 2} {", "error_info": ""}},
}


def _text(result, fmt="structured"):
    return _build_tool_result_block("call_k1", result, False, result_format=fmt)["content"]


def test_structured_runtime_error_text():
    block = _build_tool_result_block("call_k1", FAILED, False, result_format="structured")
    assert block["is_error"] is True
    assert block["content"] == (
        "Failed at statement 3 of 4: `bogus`\n"
        'Error: invalid command name "bogus"\n'
        + ERROR_INFO + "\n"
        "Statements 1–2 were applied and are still in effect; do not re-run them."
    )


def test_structured_applied_counts_wording():
    one = dict(FAILED, statements={"total": 3, "applied": 1,
                                   "failed": {"index": 2, "text": "bogus", "error_info": ""}})
    assert _text(one).endswith("Statement 1 was applied and is still in effect; do not re-run it.")
    none = dict(FAILED, statements={"total": 2, "applied": 0,
                                    "failed": {"index": 1, "text": "bogus", "error_info": ""}})
    assert _text(none).endswith("No statements were applied.")
    assert "Output before the error:\n12 atoms" in _text(dict(FAILED, output="12 atoms"))


def test_precheck_text():
    block = _build_tool_result_block("call_k2", PRECHECK, False, result_format="structured")
    assert block["content"] == (
        "Nothing was run: statement 2 of 2 is incomplete (unbalanced braces, brackets or quotes)\n"
        "Incomplete statement: `foreach a {1 2} {`"
    )
    assert block["is_error"] is True


def test_not_executed_texts():
    assert _text({"ok": False, "executed": "no", "error": "cancelled"}) == "not executed: request stopped"
    assert _text({"ok": False, "executed": "no", "error": "not executed: loop guard"}) == "not executed: loop guard"
    assert _text({"ok": False, "executed": "no",
                  "error": "VMD did not pick up the command (no reply within 45 s)."}) == (
        "not executed: VMD did not pick up the command (no reply within 45 s).")
    assert _text({"ok": False, "executed": "unknown",
                  "error": "stopped while running; outcome unknown"}) == "stopped while running; outcome unknown"
    blocked = {"ok": False, "executed": "no", "error": "Not run: this would close the user's VMD session.",
               "blocked": [{"id": "cmd_quit", "word": "exit", "text": "exit"}]}
    assert _text(blocked) == "Not run: this would close the user's VMD session."


def test_legacy_unchanged():
    assert _text(FAILED, "legacy") == 'Error: invalid command name "bogus"'
    assert _build_tool_result_block("c", FAILED, False)["content"] == 'Error: invalid command name "bogus"'
    assert _build_tool_result_block("c", {"ok": True, "output": ""}, False)["content"] == "Command executed successfully."
    assert _build_tool_result_block("c", {"ok": False}, False)["content"] == "Command failed with unknown error."
    assert _build_tool_result_block("c", {"ok": False, "executed": "no", "error": "cancelled"}, False)["content"] == "Error: cancelled"


def test_structured_success_same_as_legacy():
    ok = {"ok": True, "output": "0 1 2", "executed": "yes",
          "statements": {"total": 1, "applied": 1, "failed": None}}
    assert _build_tool_result_block("c", ok, False, result_format="structured") == _build_tool_result_block("c", ok, False)


class _PrecheckBridge:
    """Strict six keywords; returns the executor's C3 pre-check refusal."""

    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input, session_queue, cancel_event):
        return dict(PRECHECK)


def test_executed_no_survives_to_tool_result_and_finished():
    turns = iter([
        ("", [{"type": "tool_use", "id": "t1", "name": "run_vmd_command",
               "input": {"command": "mol list\nforeach a {1 2} {"}}]),
        ("I will fix the braces.", []),
    ])
    events, out = [], []
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m",
                          options=LoopOptions(result_format="structured"))
    with mock.patch.object(ClaudeToolLoop, "_call",
                           new=lambda self, m, s, on_text, should_cancel: next(turns)):
        loop.run(prompt="loop", system_prompt="s", tool_bridge=_PrecheckBridge(), session_id="s",
                 session_queue=EventQueue(), cancel_event=threading.Event(), on_chunk=lambda t: None,
                 ctx=RunContext(request_id="req_000000000001", chat_id="chat_0123456789ab",
                                on_event=events.append, messages_out=out))
    finished = [e for e in events if (e.get("metadata") or {}).get("kind") == "tool.finished"]
    assert finished[0]["metadata"]["executed"] == "no"
    results = [b for msg in out if msg["role"] == "user" and isinstance(msg["content"], list)
               for b in msg["content"] if b.get("type") == "tool_result"]
    assert results[0]["content"].startswith("Nothing was run: statement 2 of 2 is incomplete")
    assert "Incomplete statement: `foreach a {1 2} {`" in results[0]["content"]


def test_options_none_keeps_legacy_failure_text():
    """Carry-forward: with options=None (S7 benchmark bridges), _result_format()
    stays 'legacy' and the model-facing failure text is exactly today's text
    (unaffected by C3). The benchmark HTTP request bodies themselves — which
    embed this same text for a run_vmd_command error — are pinned byte-for-byte
    by tests/test_benchmark_golden_requests.py's golden-hash guard.
    """
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m")
    assert loop.options is None
    assert loop._result_format() == "legacy"
    block = _build_tool_result_block("c", FAILED, False, result_format=loop._result_format())
    assert block["content"] == 'Error: invalid command name "bogus"'
    assert block == _build_tool_result_block("c", FAILED, False)
