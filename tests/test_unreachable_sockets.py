"""S6: an unreachable Ollama fails within 3 s with a case-specific hint.

Real sockets on 127.0.0.1:0 cover the three spec 2f cases: a closed port
(tunnel down), accept-then-close (tunnel up, remote Ollama down) and a
listener that never answers (stale tunnel). Each runs cold and warm; warm
means /api/version was answered, and cached by provider_catalog, just before
the listener changed behaviour, so only the never-cached /api/ps can notice.
Time runs from run() start to the raise.
"""
from __future__ import annotations

import socket
import threading
import time
import urllib.request
from typing import Any, Callable, Iterator, List, Tuple

import pytest

from helpers.provider_fakes import DIGEST, FakeHttp, ndjson, patch_urlopen, run_loop
from vmd_ai_runtime import provider_catalog
from vmd_ai_runtime.claude_loop import (
    ClaudeLoopError,
    ClaudeToolLoop,
    LoopOptions,
    ModelNotFoundError,
    ProviderUnreachableError,
    _ps_entry,
    _stream_ollama,
    _stream_request,
)

MODEL = "qwen3.8:27b"
BASE = "http://ollama.test"
CHAT_OK = ndjson([
    {"message": {"role": "assistant", "content": "ok"}},
    {"done": True, "done_reason": "stop"},
])


class Listener:
    """A TCP listener on 127.0.0.1:0 whose behaviour can be switched:
    'ok' answers /api/version and /api/ps, 'close' accepts and closes at once,
    'hang' reads the request and never answers."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.paths: List[str] = []
        self._held: List[socket.socket] = []
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self._sock.settimeout(0.05)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if self.mode == "close":
                conn.close()
                continue
            path = self._read_path(conn)
            self.paths.append(path)
            if self.mode == "hang":
                self._held.append(conn)
            else:
                self._answer(conn, path)

    @staticmethod
    def _read_path(conn: socket.socket) -> str:
        conn.settimeout(2.0)
        data = b""
        try:
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
        except OSError:
            pass
        parts = data.split(b" ", 2)
        return parts[1].decode("ascii", "replace") if len(parts) > 1 else ""

    @staticmethod
    def _answer(conn: socket.socket, path: str) -> None:
        body = b'{"version":"0.12.0"}' if path == "/api/version" else b'{"models":[]}'
        head = (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Content-Length: %d\r\nConnection: close\r\n\r\n" % len(body)
        )
        try:
            conn.sendall(head + body)
        finally:
            conn.close()

    def close_port(self) -> None:
        self._stop.set()
        self._sock.close()
        self._thread.join(timeout=1.0)

    def close(self) -> None:
        self.close_port()
        for conn in self._held:
            conn.close()


@pytest.fixture
def listeners() -> Iterator[Callable[[str], Listener]]:
    made: List[Listener] = []

    def make(mode: str) -> Listener:
        listener = Listener(mode)
        made.append(listener)
        return listener

    yield make
    for listener in made:
        listener.close()


def closed_port_url() -> str:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return f"http://127.0.0.1:{port}"


def product_options(base_url: str, model: str = MODEL) -> LoopOptions:
    return LoopOptions.product({"provider": "ollama", "base_url": base_url, "model": model, "options": {}})


def run_until_raise(base_url: str) -> Tuple[ProviderUnreachableError, float]:
    loop = ClaudeToolLoop(provider_name="ollama", api_key=base_url, model=MODEL,
                          options=product_options(base_url))
    started = time.monotonic()
    with pytest.raises(ProviderUnreachableError) as info:
        run_loop(loop)
    return info.value, time.monotonic() - started


def prime_version_cache(base_url: str) -> None:
    assert provider_catalog.ollama_version(base_url, timeout=2.0) == "0.12.0"


def test_closed_port_cold_and_warm(listeners):
    cold = closed_port_url()
    exc, elapsed = run_until_raise(cold)
    assert elapsed < 3.0
    assert exc.code == "unreachable"
    assert exc.hint == provider_catalog.unreachable_hint(cold, "refused")
    assert "Is the SSH tunnel up?" in exc.hint

    warm = listeners("ok")
    prime_version_cache(warm.base_url)
    warm.close_port()
    exc, elapsed = run_until_raise(warm.base_url)
    assert elapsed < 3.0
    assert exc.hint == provider_catalog.unreachable_hint(warm.base_url, "refused")


def test_accept_then_close_cold_and_warm(listeners):
    cold = listeners("close")
    exc, elapsed = run_until_raise(cold.base_url)
    assert elapsed < 3.0
    assert exc.code == "unreachable"
    assert exc.hint == provider_catalog.unreachable_hint(cold.base_url, "reset")
    assert "ollama serve" in exc.hint

    warm = listeners("ok")
    prime_version_cache(warm.base_url)
    warm.mode = "close"
    exc, elapsed = run_until_raise(warm.base_url)
    assert elapsed < 3.0
    assert exc.hint == provider_catalog.unreachable_hint(warm.base_url, "reset")


def test_never_answering_cold_and_warm(listeners):
    # Each case waits out the real 2 s timeout, so the cold case runs on a
    # thread while the warm one runs here. Each is timed on its own and has
    # its own listener and base_url (the version cache is per base_url).
    cold = listeners("hang")
    cold_outcome: List[Any] = []

    def run_cold() -> None:
        try:
            cold_outcome.append(run_until_raise(cold.base_url))
        except BaseException as failure:  # noqa: BLE001 - re-raised below
            cold_outcome.append(failure)

    cold_thread = threading.Thread(target=run_cold, daemon=True)
    cold_thread.start()

    warm = listeners("ok")
    prime_version_cache(warm.base_url)
    warm.mode = "hang"
    warm_exc, warm_elapsed = run_until_raise(warm.base_url)

    cold_thread.join(timeout=30)
    assert len(cold_outcome) == 1, "the cold case did not finish"
    if isinstance(cold_outcome[0], BaseException):
        raise cold_outcome[0]
    exc, elapsed = cold_outcome[0]
    assert 1.5 < elapsed < 3.0
    assert exc.code == "unreachable"
    assert exc.hint == provider_catalog.unreachable_hint(cold.base_url, "timeout")
    assert "stale" in exc.hint
    assert cold.paths == ["/api/version"]

    exc, elapsed = warm_exc, warm_elapsed
    assert 1.5 < elapsed < 3.0
    assert exc.hint == provider_catalog.unreachable_hint(warm.base_url, "timeout")
    # /api/version came from the cache; the never-cached /api/ps timed out.
    assert warm.paths == ["/api/version", "/api/ps"]


def test_reset_on_first_read_is_unreachable_without_preflight(listeners):
    listener = listeners("close")
    opts = LoopOptions(connect_retries=0, classify_unreachable=True)
    with pytest.raises(ProviderUnreachableError) as info:
        _stream_ollama(
            messages=[{"role": "user", "content": "hi"}], model=MODEL, system_prompt="",
            base_url=listener.base_url, timeout=5, on_text=lambda s: None,
            should_cancel=lambda: False, tools=[], on_meta=None, opts=opts,
        )
    assert info.value.hint == provider_catalog.unreachable_hint(listener.base_url, "reset")


def test_stream_request_refused_is_unreachable_with_flag():
    base = closed_port_url()
    req = urllib.request.Request(base + "/v1/chat/completions", data=b"{}", method="POST")
    with pytest.raises(ProviderUnreachableError) as info:
        _stream_request(req, 5, opts=LoopOptions(connect_retries=0, classify_unreachable=True))
    # _stream_request does not know the provider, so its hint is generic;
    # _stream_ollama replaces it with the Ollama wording (tests above).
    assert info.value.hint == f"Could not reach {base}. Check that the server is running."
    with pytest.raises(ClaudeLoopError) as plain:
        _stream_request(req, 5, opts=LoopOptions(connect_retries=0))
    assert type(plain.value) is ClaudeLoopError
    assert str(plain.value).startswith("network error:")


def _chat_fake(*, loaded: bool) -> FakeHttp:
    fake = FakeHttp().ollama_ok(MODEL, loaded=loaded)
    fake.add("/api/chat", CHAT_OK, content_type="application/x-ndjson")
    return fake


def _stream(fake: FakeHttp, on_meta) -> str:
    with patch_urlopen(fake):
        text, _blocks = _stream_ollama(
            messages=[{"role": "user", "content": "hi"}], model=MODEL, system_prompt="",
            base_url=BASE, timeout=30, on_text=lambda s: None, should_cancel=lambda: False,
            tools=[], on_meta=on_meta, opts=product_options(BASE),
        )
    return text


def test_loading_model_status_when_not_in_ps():
    fake = _chat_fake(loaded=False)
    text = _stream(fake, lambda item: fake.requests.append({"path": "<meta>", "item": item}))
    assert text == "ok"
    order = [
        r["path"] if r["path"] != "<meta>" else (r["item"].get("phase") or r["item"].get("kind"))
        for r in fake.requests
    ]
    assert order[:4] == ["/api/version", "/api/ps", "loading_model", "/api/chat"]
    status = next(r["item"] for r in fake.requests
                  if r["path"] == "<meta>" and r["item"].get("phase") == "loading_model")
    assert status == {"kind": "status", "phase": "loading_model", "message": f"Loading {MODEL}…"}


def test_model_digest_meta_from_ps():
    fake = _chat_fake(loaded=True)
    items: List[dict] = []
    _stream(fake, items.append)
    assert {"kind": "model_digest", "value": DIGEST} in items
    assert not any(i.get("phase") == "loading_model" for i in items)

    loop = ClaudeToolLoop(provider_name="ollama", api_key=BASE, model=MODEL,
                          options=product_options(BASE))
    assert loop.last_model_digest is None
    with patch_urlopen(fake):
        run_loop(loop)
    assert loop.last_model_digest == DIGEST


def test_ps_entry_matches_latest_tag():
    models = [{"name": "llama3.1:latest", "model": "llama3.1:latest", "digest": "d1"}]
    assert _ps_entry(models, "llama3.1")["digest"] == "d1"
    assert _ps_entry(models, "llama3.1:8b") is None
    assert _ps_entry([], "llama3.1") is None


def test_model_not_found_gets_pull_hint():
    fake = FakeHttp().ollama_ok("qwen9:1b", loaded=False)
    fake.add("/api/chat", {"error": "model \"qwen9:1b\" not found, try pulling it first"}, status=404)
    with patch_urlopen(fake):
        with pytest.raises(ModelNotFoundError) as info:
            _stream_ollama(
                messages=[{"role": "user", "content": "hi"}], model="qwen9:1b", system_prompt="",
                base_url=BASE, timeout=30, on_text=lambda s: None, should_cancel=lambda: False,
                tools=[], on_meta=None, opts=product_options(BASE, "qwen9:1b"),
            )
    assert info.value.code == "model_not_found"
    assert info.value.hint == "ollama pull qwen9:1b"
    assert "not found" in str(info.value)
    assert not isinstance(info.value, ProviderUnreachableError)


def test_preflight_non_ollama_reply_is_not_unreachable():
    """A port that answers, but not as Ollama (for example another web server),
    is an 'other' error, never one of the three unreachable hints."""
    fake = FakeHttp().add("/api/version", "<html>not ollama</html>", content_type="text/html")
    with patch_urlopen(fake):
        with pytest.raises(ClaudeLoopError) as info:
            _stream_ollama(
                messages=[{"role": "user", "content": "hi"}], model=MODEL, system_prompt="",
                base_url=BASE, timeout=30, on_text=lambda s: None, should_cancel=lambda: False,
                tools=[], on_meta=None, opts=product_options(BASE),
            )
    assert type(info.value) is ClaudeLoopError
    assert info.value.code == "other"
    assert str(info.value).startswith("Ollama preflight failed at 'http://ollama.test'")
    assert fake.paths() == ["/api/version"]
