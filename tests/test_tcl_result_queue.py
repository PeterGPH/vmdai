"""net::post_result: retry until accepted, epoch change, duplicates (P06-T04; §2d, §5)."""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, List

import pytest

from helpers.fake_rpc_server import FakeRpcServer, Recorded, Reply
from helpers.tcl import REPO, TclTestResult, run_tcltest

TCL_FILE = REPO / "tests" / "tcl" / "test_result_queue.tcl"
TOTAL = 5

ACCEPTED = {"accepted": True, "late": False, "duplicate": False}
UNAVAILABLE = Reply(b"Service Unavailable", status=503, content_type="text/plain")


class QueueHandler:
    """Replies by call_key: k_retry fails twice, k_dup is a duplicate,
    k_unknown is TOOL_CALL_UNKNOWN, k_auth is AUTH_FAILED, k_never always 503."""

    def __init__(self) -> None:
        self.seen: Dict[str, int] = {}
        self.lock = threading.Lock()

    def __call__(self, method: str, params: Dict[str, Any], headers: Dict[str, str]) -> Any:
        key = str(params.get("call_key", ""))
        with self.lock:
            self.seen[key] = self.seen.get(key, 0) + 1
            count = self.seen[key]
        if method != "tool.command_result":
            return {"error": {"code": "METHOD_NOT_FOUND", "message": method, "data": {}}}
        if key == "k_retry":
            return UNAVAILABLE if count <= 2 else {"result": ACCEPTED}
        if key == "k_dup":
            return {"result": {"accepted": True, "late": False, "duplicate": True}}
        if key == "k_unknown":
            return {"error": {"code": "TOOL_CALL_UNKNOWN", "message": "unknown call_key", "data": {}}}
        if key == "k_auth":
            return {"error": {"code": "AUTH_FAILED", "message": "session token mismatch", "data": {}}}
        return UNAVAILABLE


@dataclass
class QueueRun:
    result: TclTestResult
    requests: List[Recorded]
    seen: Dict[str, int]


@pytest.fixture(scope="module")
def queue_run() -> QueueRun:
    handler = QueueHandler()
    with FakeRpcServer(handler) as server:
        result = run_tcltest(str(TCL_FILE), env={"VMDAI_FAKE_URL": server.base_url})
        return QueueRun(result, list(server.requests), dict(handler.seen))


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(queue_run):
    assert (queue_run.result.passed, queue_run.result.failed) == (TOTAL, 0), queue_run.result.output


def test_retries_until_accepted(queue_run):
    _assert_passed(queue_run.result, ["rq-retry-1"])
    assert queue_run.seen["k_retry"] == 3
    posted = [r for r in queue_run.requests if r.params.get("call_key") == "k_retry"]
    assert posted[0].params == {"session_id": "sess_rq", "call_key": "k_retry", "ok": True,
                                "output": "done", "executed": "yes",
                                "statements_total": 1, "statements_applied": 1}
    assert len({json.loads(r.body)["id"] for r in posted}) == 3  # a fresh JSON-RPC id per attempt


def test_epoch_change_stops(queue_run):
    _assert_passed(queue_run.result, ["rq-once-1", "rq-epoch-1"])
    assert queue_run.seen["k_auth"] == 2


def test_duplicate_counts_as_accepted(queue_run):
    _assert_passed(queue_run.result, ["rq-dup-1"])
    assert queue_run.seen["k_dup"] == 1


def test_permanent_error_dropped(queue_run):
    _assert_passed(queue_run.result, ["rq-unknown-1"])
    assert queue_run.seen["k_unknown"] == 1
