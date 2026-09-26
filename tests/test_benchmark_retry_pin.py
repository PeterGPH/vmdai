"""S7 retry pin (spec §2a): with options=None the loop keeps today's retry policy.

Every provider goes through _stream_request.  URLError is retried 5 times with
waits 2, 4, 8, 16, 30 s; HTTP 429/500/502/503/529 are retried 5 times, honouring
Retry-After, else 2, 4, 8, 16, 32 s; any other HTTP status is not retried.
The conftest records the waits instead of sleeping (fixture ``sleep_calls``).
"""
from __future__ import annotations

import email.message
import io
import threading
import urllib.error
from typing import Callable, Optional
from unittest import mock

import pytest

from vmd_ai_runtime.claude_loop import ClaudeLoopError, ClaudeToolLoop

PROVIDERS = {
    "anthropic-direct": ("sk-ant-pin", "claude-sonnet-4-5"),
    "openrouter": ("sk-or-pin", "pin/model"),
    "ollama": ("http://127.0.0.1:9", "llama3.1"),
}


class _NoToolBridge:
    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input,
                     session_queue, cancel_event):
        raise AssertionError("the pin never reaches a tool call")


class _Raiser:
    """Fake urlopen that raises a fresh exception on every call."""

    def __init__(self, make_exc: Callable[[], Exception]) -> None:
        self.make_exc = make_exc
        self.calls = 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        raise self.make_exc()


def _http_error(code: int, retry_after: Optional[str] = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    body = io.BytesIO(b'{"error": {"message": "pinned failure"}}')
    return urllib.error.HTTPError("http://pin.test/", code, "pinned", headers, body)


def _run_loop(provider: str) -> None:
    api_key, model = PROVIDERS[provider]
    loop = ClaudeToolLoop(provider_name=provider, api_key=api_key, model=model)
    loop.run(
        prompt="hi",
        system_prompt="sys",
        tool_bridge=_NoToolBridge(),
        session_id="pin",
        session_queue=None,
        cancel_event=threading.Event(),
        on_chunk=lambda s: None,
    )


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_urlerror_retries_five_times(provider, sleep_calls):
    raiser = _Raiser(lambda: urllib.error.URLError("Connection refused"))
    with mock.patch("urllib.request.urlopen", raiser):
        with pytest.raises(ClaudeLoopError, match="network error"):
            _run_loop(provider)
    assert raiser.calls == 6
    assert sleep_calls == [2.0, 4.0, 8.0, 16.0, 30.0]


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_http_429_backoff_without_retry_after(provider, sleep_calls):
    raiser = _Raiser(lambda: _http_error(429))
    with mock.patch("urllib.request.urlopen", raiser):
        with pytest.raises(ClaudeLoopError, match="HTTP 429: pinned failure"):
            _run_loop(provider)
    assert raiser.calls == 6
    assert sleep_calls == [2.0, 4.0, 8.0, 16.0, 32.0]


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_http_503_honours_retry_after(provider, sleep_calls):
    raiser = _Raiser(lambda: _http_error(503, retry_after="7"))
    with mock.patch("urllib.request.urlopen", raiser):
        with pytest.raises(ClaudeLoopError, match="HTTP 503: pinned failure"):
            _run_loop(provider)
    assert raiser.calls == 6
    assert sleep_calls == [7.0] * 5


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_http_400_not_retried(provider, sleep_calls):
    raiser = _Raiser(lambda: _http_error(400))
    with mock.patch("urllib.request.urlopen", raiser):
        with pytest.raises(ClaudeLoopError, match="HTTP 400: pinned failure"):
            _run_loop(provider)
    assert raiser.calls == 1
    assert sleep_calls == []


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
@pytest.mark.parametrize(
    "code,retry_after,waits",
    [(429, "7", [7.0] * 5), (503, None, [2.0, 4.0, 8.0, 16.0, 32.0])],
    ids=["429-retry-after", "503-no-retry-after"],
)
def test_http_retry_after_other_combinations(provider, code, retry_after, waits, sleep_calls):
    """Spec §2a pins 429 *and* 503 with and without Retry-After: the two other cells."""
    raiser = _Raiser(lambda: _http_error(code, retry_after=retry_after))
    with mock.patch("urllib.request.urlopen", raiser):
        with pytest.raises(ClaudeLoopError, match=f"HTTP {code}: pinned failure"):
            _run_loop(provider)
    assert raiser.calls == 6
    assert sleep_calls == waits
