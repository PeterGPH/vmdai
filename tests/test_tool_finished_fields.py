"""P07-T03: tool.finished display fields (C1, C3, C5) and the late tool.finished (§2d)."""
from __future__ import annotations

import json
import threading

from helpers.app_driver import call, make_token_app, result, send, wait_idle
from helpers.events_v2 import (FakePlugin, MetaScriptedLoop, ProductBridge, ScriptTurn, of_kind,
                               poll_all, product_options, product_result, run_cmd, start_v2, tool_block)
from vmd_ai_runtime.claude_loop import _tool_finished_meta

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
BLOCKED = [{"id": "cmd_exec", "word": "exec", "text": "exec ls"}]
FAILED_STATEMENT = {"index": 3, "text": "bogus",
                    "error_info": 'invalid command name "bogus"\n    while executing\n"bogus"'}
IMAGE = {"path": "/w/chats/chat_000000000001/images/k.png",
         "thumb_path": "/w/chats/chat_000000000001/images/k_thumb.png", "width": 847, "height": 1024,
         "src_width": 1280, "src_height": 1547, "renderer": "TachyonInternal"}
CUT = ("0\n1\n[output truncated: 20000 lines, 107 KB. Full text: /w/chats/chat_000000000001/outputs/k.txt. "
       "Don't print it again: compute what you need (measure, a narrower selection), or read a slice "
       "of that file with Tcl.]\n19999")


def test_fields_blocked_statements_output_path_image_saved_path(tmp_path):
    results = [
        product_result(ok=False, executed="no", blocked=BLOCKED,
                       error="Not run: `exec` is never run by ChatVMD. If the user needs it, show the command "
                             "in a tcl code block so they can copy it and run it in the VMD console themselves."),
        product_result(ok=False, error='invalid command name "bogus"', applied_text="mol new a.pdb\nmol delrep 0 top\n",
                       statements={"total": 4, "applied": 2, "failed": FAILED_STATEMENT}),
        product_result(output=CUT, truncated=True, output_bytes=108889,
                       output_path="/w/chats/chat_000000000001/outputs/k.txt"),
        product_result(image=IMAGE, saved_path="/w/fig1.png", image_b64=TINY_PNG_B64, image_mime="image/png"),
    ]
    app = make_token_app(tmp_path)
    app.claude_loop = MetaScriptedLoop([
        ScriptTurn(tool_blocks=[
            run_cmd("tc_1", "exec ls"),
            run_cmd("tc_2", "mol new a.pdb\nmol delrep 0 top\nbogus\nputs x"),
            run_cmd("tc_3", "puts [$sel get {x y z}]"),
            tool_block("tc_4", "capture_vmd_snapshot", purpose="final figure", save_path="fig1.png"),
        ]),
        ScriptTurn(text="Done."),
    ], options=product_options(supports_vision=False))
    app.tool_bridge = ProductBridge(results)
    session = start_v2(app, tmp_path)
    result(send(app, session, "four steps"))
    wait_idle(app, session)
    events = poll_all(app, session)
    blocked, failed, cut, snap = of_kind(events, "tool.finished")
    assert (blocked["ok"], blocked["executed"], blocked["blocked"]) == (False, "no", BLOCKED)
    assert blocked["error"].startswith("Not run: `exec` is never run by ChatVMD.")
    assert (failed["ok"], failed["executed"], failed["statements"]) == (
        False, "yes", {"total": 4, "applied": 2, "failed": FAILED_STATEMENT})
    assert (cut["output"], cut["truncated"], cut["output_path"], cut["output_bytes"]) == (
        CUT, True, "/w/chats/chat_000000000001/outputs/k.txt", 108889)
    assert (snap["image"], snap["saved_path"], snap["tool_name"]) == (IMAGE, "/w/fig1.png", "capture_vmd_snapshot")
    for meta in (blocked, failed, cut):
        assert meta["image"] is None and meta["saved_path"] is None
    assert [m["late"] for m in (blocked, failed, cut, snap)] == [False] * 4
    assert TINY_PNG_B64 not in json.dumps(events)        # base64 never reaches a display event


def test_tool_finished_meta_late_flag():
    meta = _tool_finished_meta("k00000000001", "run_vmd_command", "tcl", product_result(output="x"), 12.4, late=True)
    assert (meta["late"], meta["duration_ms"], meta["output"], meta["output_bytes"]) == (True, 12, "x", 1)
    assert _tool_finished_meta("k00000000001", "run_vmd_command", "tcl", product_result(), 0.0)["late"] is False


def _held_run(tmp_path, monkeypatch, script):
    app = make_token_app(tmp_path)                        # the real VmdToolBridge
    monkeypatch.setattr(app, "_tool_timeouts", lambda: (None, 0.1))   # cancel_grace_s 0.1 s
    app.claude_loop = MetaScriptedLoop(script)
    return app, start_v2(app, tmp_path)


def _index(events, predicate):
    return [i for i, e in enumerate(events) if predicate(e["metadata"] or {})]


def test_late_after_finished(tmp_path, monkeypatch):
    app, session = _held_run(tmp_path, monkeypatch, [ScriptTurn(tool_blocks=[run_cmd("tc_1", "long_job")])])
    with FakePlugin(app, session, answer=lambda meta: None) as plugin:
        first = result(send(app, session, "run the long job"))
        key, = plugin.wait_held()
        result(call(app, "chat.cancel", {}, session))
        wait_idle(app, session)
        reply = plugin.post(key, ok=True, output="3 atoms", statements_total=1, statements_applied=1)
        again = plugin.post(key, ok=True, output="3 atoms", statements_total=1, statements_applied=1)
    events = poll_all(app, session)
    assert reply == {"accepted": True, "late": True, "duplicate": False}
    assert again["duplicate"] is True
    finished = of_kind(events, "tool.finished")
    assert [(m["call_key"], m["executed"], m["late"]) for m in finished] == [
        (key, "unknown", False), (key, "yes", True)]           # one row update, not two
    late = finished[1]
    assert (late["request_id"], late["ok"], late["output"], late["tool_name"], late["executor"], late["v"]) == (
        first["request_id"], True, "3 atoms", "run_vmd_command", "tcl", 2)
    assert late["statements"] == {"total": 1, "applied": 1, "failed": None}
    assert of_kind(events, "request.finished")[0]["status"] == "cancelled"
    end, = _index(events, lambda m: m.get("kind") == "request.finished")
    late_at, = _index(events, lambda m: m.get("late") is True)
    assert late_at > end


def test_late_after_next_request(tmp_path, monkeypatch):
    """Review focus 2: the late row update lands while the next request is running."""
    gate = threading.Event()
    app, session = _held_run(tmp_path, monkeypatch, [
        ScriptTurn(tool_blocks=[run_cmd("tc_1", "long_job")]),
        ScriptTurn(text="Second answer.", before=lambda: gate.wait(5)),
    ])
    with FakePlugin(app, session, answer=lambda meta: None) as plugin:
        first = result(send(app, session, "run the long job"))
        key, = plugin.wait_held()
        result(call(app, "chat.cancel", {}, session))
        wait_idle(app, session)
        second = result(send(app, session, "and now?"))
        plugin.wait_for(lambda e: (e["metadata"] or {}).get("kind") == "turn.started"
                        and e["metadata"].get("request_id") == second["request_id"])
        reply = plugin.post(key, ok=True, output="3 atoms")
        gate.set()
        wait_idle(app, session)
    events = poll_all(app, session)
    assert reply == {"accepted": True, "late": True, "duplicate": False}
    late, = [m for m in of_kind(events, "tool.finished") if m["late"]]
    assert (late["call_key"], late["request_id"], late["output"]) == (key, first["request_id"], "3 atoms")
    started2, = _index(events, lambda m: m.get("kind") == "request.started" and m["request_id"] == second["request_id"])
    finished2, = _index(events, lambda m: m.get("kind") == "request.finished" and m["request_id"] == second["request_id"])
    late_at, = _index(events, lambda m: m.get("late") is True)
    assert started2 < late_at < finished2
    assert of_kind(events, "request.finished")[1]["status"] == "complete"
