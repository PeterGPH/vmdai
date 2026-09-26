"""P02-T06: transport flags in _stream_request (§2a rows, §5 429/5xx, 401/403, billing, 404)."""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request

import pytest

from helpers.fake_provider import FakeUrlopen, StatusRecorder, http_error, run_loop
from vmd_ai_runtime import claude_loop
from vmd_ai_runtime.claude_loop import (
    ClaudeLoopError,
    ClaudeToolLoop,
    LoopOptions,
    ModelNotFoundError,
    ProviderAuthError,
    ProviderBillingError,
    RunCancelled,
    _classify_http_error,
    _stream_request,
)

URL = "https://api.anthropic.com/v1/messages"


def _req():
    return urllib.request.Request(URL, data=b"{}", method="POST",
                                  headers={"Content-Type": "application/json"})


def _refused():
    return urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))


def _serve(monkeypatch, *items):
    fake = FakeUrlopen(list(items))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def test_options_none_identical(monkeypatch, sleep_calls):
    for kwargs in ({}, {"opts": None, "should_cancel": None, "on_meta": None}):
        fake = _serve(monkeypatch, *[_refused() for _ in range(6)])
        del sleep_calls[:]
        with pytest.raises(ClaudeLoopError) as info:
            _stream_request(_req(), 10, **kwargs)
        assert type(info.value) is ClaudeLoopError
        assert str(info.value).startswith("network error:")
        assert sleep_calls == [2.0, 4.0, 8.0, 16.0, 30.0]
        assert [r["timeout"] for r in fake.requests] == [10] * 6


def test_connect_retries_zero_single_attempt(monkeypatch, sleep_calls):
    fake = _serve(monkeypatch, _refused(), _refused())
    with pytest.raises(ClaudeLoopError, match="network error"):
        _stream_request(_req(), 10, opts=LoopOptions(connect_retries=0))
    assert len(fake.requests) == 1
    assert sleep_calls == []
    fake = _serve(monkeypatch, _refused(), _refused(), _refused())
    with pytest.raises(ClaudeLoopError):
        _stream_request(_req(), 10, opts=LoopOptions(connect_retries=1))
    assert len(fake.requests) == 2
    assert sleep_calls == [2.0]


def test_retry_status_meta(monkeypatch, sleep_calls):
    _serve(monkeypatch, http_error(URL, 429, {"error": {"message": "slow down"}}, {"Retry-After": "3"}), b"ok")
    seen = []
    resp = _stream_request(_req(), 10, opts=LoopOptions(), on_meta=seen.append)
    assert resp.read() == b"ok"
    assert seen == [{"kind": "status", "phase": "retrying", "attempt": 1, "max_attempts": 5,
                     "wait_s": 3.0, "http_status": 429, "message": "Rate limited"}]
    assert sleep_calls == [3.0]


def test_cancel_during_backoff_raises_quickly(monkeypatch):
    # Direct: Stop already pressed, a 60 s Retry-After raises at once.
    cancel = threading.Event()
    cancel.set()
    _serve(monkeypatch, http_error(URL, 503, {"error": {"message": "busy"}}, {"Retry-After": "60"}))
    with pytest.raises(RunCancelled):
        _stream_request(_req(), 10, opts=LoopOptions(cancellable_backoff=True),
                        should_cancel=cancel.is_set)

    # Through run(): Stop lands during the backoff; the run ends at once, cancelled.
    cancel = threading.Event()
    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        if len(slept) == 3:
            cancel.set()

    monkeypatch.setattr(claude_loop, "_sleep", fake_sleep)
    fake = _serve(monkeypatch, http_error(URL, 429, {"error": {"message": "slow down"}}, {"Retry-After": "60"}))
    recorder = StatusRecorder()
    loop = ClaudeToolLoop("anthropic-direct", "sk-ant-test", "claude-sonnet-4-5",
                          recorder=recorder, options=LoopOptions(cancellable_backoff=True))
    started = time.monotonic()
    assert run_loop(loop, cancel_event=cancel) == ""
    assert time.monotonic() - started < 1.0
    assert recorder.status == "cancelled"
    assert slept == [0.1, 0.1, 0.1]  # 3 slices of a 60 s wait, not 600
    assert len(fake.chat_requests) == 1


def test_classify_401_403_auth(monkeypatch):
    for code in (401, 403):
        _serve(monkeypatch, http_error(URL, code, {"error": {"type": "authentication_error",
                                                            "message": "invalid x-api-key"}}))
        with pytest.raises(ProviderAuthError) as info:
            _stream_request(_req(), 10, opts=LoopOptions(classify_errors=True))
        assert info.value.code == "auth" and info.value.http_status == code
        assert str(info.value) == f"API error HTTP {code}: invalid x-api-key"
        assert info.value.hint


def test_classify_402_and_credit_balance_billing(monkeypatch):
    cases = [
        (402, {"error": {"message": "Insufficient credits"}}),
        (400, {"error": {"type": "invalid_request_error",
                         "message": "Your credit balance is too low to access the Anthropic API."}}),
    ]
    for code, body in cases:
        _serve(monkeypatch, http_error(URL, code, body))
        with pytest.raises(ProviderBillingError) as info:
            _stream_request(_req(), 10, opts=LoopOptions(classify_errors=True))
        assert info.value.code == "billing" and info.value.http_status == code


def test_classify_404_model_not_found(monkeypatch):
    _serve(monkeypatch, http_error("http://ollama.test/api/chat", 404, {"error": "model 'qwen9' not found"}))
    with pytest.raises(ModelNotFoundError) as info:
        _stream_request(_req(), 10, opts=LoopOptions(classify_errors=True))
    assert info.value.code == "model_not_found"
    assert str(info.value) == "API error HTTP 404: model 'qwen9' not found"
    other = _classify_http_error(500, "boom")
    assert type(other) is ClaudeLoopError and other.code == "other" and other.http_status == 500


def test_unclassified_without_flag(monkeypatch):
    for opts in (None, LoopOptions()):
        _serve(monkeypatch, http_error(URL, 401, {"error": {"message": "invalid x-api-key"}}))
        with pytest.raises(ClaudeLoopError) as info:
            _stream_request(_req(), 10, opts=opts)
        assert type(info.value) is ClaudeLoopError
        assert info.value.code == "other"
        assert str(info.value) == "API error HTTP 401: invalid x-api-key"


def test_first_byte_timeout_used(monkeypatch):
    fake = _serve(monkeypatch, b"a", b"b", b"c")
    _stream_request(_req(), 90, opts=LoopOptions(first_byte_timeout_s=120.0))
    _stream_request(_req(), 90, opts=LoopOptions())
    _stream_request(_req(), 90)
    assert [r["timeout"] for r in fake.requests] == [120.0, 90, 90]
