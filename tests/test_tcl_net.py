"""net.tcl: escaper, typed params, async call, after-0 delivery, epoch, S8 (P06-T03).

Runs tests/tcl/test_net.tcl against two FakeRpcServers (ASCII and UTF-8
replies) and checks the request bytes on the Python side.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List

import pytest

from helpers.fake_rpc_server import FakeRpcServer, Recorded, Reply
from helpers.tcl import REPO, TclTestResult, module_result, module_run, run_tcl, run_tcltest, tcl_word

TCL_FILE = REPO / "tests" / "tcl" / "test_net.tcl"
TOTAL = 14  # every case except the http 2.9.5-only net-s8-1
ARROW = "".join(map(chr, (0xC5, 0x2192, 0xB0)))  # the S8 text


def handler(method: str, params: Dict[str, Any], headers: Dict[str, str]) -> Any:
    if method in ("echo", "session.start"):
        return {"result": params}
    if method == "fail.rpc":
        return {"error": {"code": "NO_MODEL", "message": "No model configured",
                          "data": {"action": "open_settings"}}}
    if method == "fail.403":
        body = json.dumps({"jsonrpc": "2.0", "id": None,
                           "error": {"code": "FORBIDDEN", "message": "forbidden", "data": {}}})
        return Reply(body.encode("ascii"), status=403)
    if method == "fail.garbage":
        return Reply(b"<html>not json</html>", content_type="text/html")
    if method == "slow":
        return Reply(b'{"jsonrpc":"2.0","id":"x","result":{}}', delay_s=1.5)
    if method == "slow.short":
        return Reply(b'{"jsonrpc":"2.0","id":"x","result":{}}', delay_s=0.3)
    return {"error": {"code": "METHOD_NOT_FOUND", "message": method, "data": {}}}


@dataclass
class NetRun:
    result: TclTestResult
    ascii_requests: List[Recorded]
    utf8_requests: List[Recorded]


def _run(**kw: Any) -> NetRun:
    with FakeRpcServer(handler) as plain, FakeRpcServer(handler, ensure_ascii=False) as utf8:
        env = {"VMDAI_FAKE_URL": plain.base_url, "VMDAI_FAKE_UTF8_URL": utf8.base_url}
        result = run_tcltest(str(TCL_FILE), env=env, **kw)
        return NetRun(result, list(plain.requests), list(utf8.requests))


@module_run
def _module_run(tmp_path_factory) -> NetRun:
    return _run()


@pytest.fixture(scope="module")
def net_run(request) -> NetRun:
    return module_result(request)


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(net_run):
    assert (net_run.result.passed, net_run.result.failed) == (TOTAL, 0), net_run.result.output


ROUND_TRIP = [
    "",
    "plain ascii",
    'quote " backslash \\ slash /',
    "".join(chr(i) for i in range(32)) + "\x7f",
    "".join(map(chr, (0xC5, 0x2192, 0xB0, 0x20, 0x2014, 0x20, 0x63, 0x61, 0x66, 0xE9))),
    "".join(map(chr, (0x2028, 0x2029, 0xFEFF))),
    "{braces} [brackets] $dollar",
    "\\u0041 is not an escape here",
    "x" * 5000 + chr(0xE9),
]


def _tcl_literal(s: str) -> str:
    return '"' + "".join(f"\\u{ord(c):04x}" for c in s) + '"'


def test_escaper_round_trip_python_json():
    lines = [
        f"source {tcl_word(str(REPO / 'plugin' / 'config.tcl'))}",
        f"source {tcl_word(str(REPO / 'plugin' / 'sched.tcl'))}",
        f"source {tcl_word(str(REPO / 'plugin' / 'net.tcl'))}",
    ]
    for s in ROUND_TRIP:
        lit = _tcl_literal(s)
        lines.append(f"puts [::vmdai::net::json_string {lit}]")
        lines.append(f"puts [::vmdai::config::_json_quote {lit}]")
    proc = run_tcl("\n".join(lines) + "\n")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.splitlines()
    assert len(out) == 2 * len(ROUND_TRIP)
    for i, s in enumerate(ROUND_TRIP):
        net_line, config_line = out[2 * i], out[2 * i + 1]
        assert net_line.isascii(), net_line[:80]
        assert json.loads(net_line) == s
        assert config_line == net_line


def test_typed_params(net_run):
    _assert_passed(net_run.result, ["net-typed-1", "net-typed-2", "net-typed-3",
                                    "net-call-1", "net-call-2"])
    typed = [r for r in net_run.ascii_requests if r.params.get("session_id") == "sess_typed"]
    assert len(typed) == 1
    request = typed[0]
    assert request.params == {"session_id": "sess_typed", "name": 'a"b\\c\n', "n": 42,
                              "flag": True, "obj": {"k": [1, 2]}}
    assert request.body.isascii()
    headers = {k.lower(): v for k, v in request.headers.items()}
    assert headers["x-session-token"] == "tok_typed"
    assert headers["content-type"] == "application/json"
    assert re.fullmatch(r"127\.0\.0\.1:\d+", headers["host"])
    assert "origin" not in headers
    start = [r for r in net_run.ascii_requests if r.method == "session.start"]
    assert len(start) == 1 and "session_id" not in start[0].params
    assert "x-session-token" not in {k.lower() for k in start[0].headers}


def test_reply_forms(net_run):
    _assert_passed(net_run.result, ["net-call-3", "net-call-4", "net-sync-1", "net-get-1", "net-get-2"])


def test_stale_epoch_dropped_token_cleaned(net_run):
    _assert_passed(net_run.result, ["net-epoch-1"])


def test_throwing_handler_logged_pump_continues(net_run):
    _assert_passed(net_run.result, ["net-deliver-1"])


def test_escaper_speed(net_run):
    _assert_passed(net_run.result, ["net-escape-1", "net-escape-2"])


def test_s8_unicode_round_trip_http_295():
    prelude = "package require tcltest 2\n::tcltest::configure -match net-s8-*\n"
    run = _run(needs_http=True, prelude=prelude)
    assert (run.result.passed, run.result.failed) == (1, 0), run.result.output
    for request in run.ascii_requests + run.utf8_requests:
        assert request.body.isascii()
        assert request.params == {"text": ARROW}
