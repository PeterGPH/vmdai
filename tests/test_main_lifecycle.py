"""P02-T04: main.py lifecycle: --port 0, --announce, --watch-stdin, shutdown thread (§2d, §2e, S4)."""
from __future__ import annotations

import http.server
import json
import os
import select
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "runtime" / "main.py"
READY = "VMDAI_READY "


def _env(extra=None):
    # The hermetic conftest already cleared VMD_AI_*/ANTHROPIC_*/... and set a temp HOME.
    env = dict(os.environ)
    # An empty settings.json in the temp HOME keeps the runtime's first-run
    # probe (plan 03) away from the real ports 11435/11434 (§6).
    settings = Path(env["HOME"]) / ".vmdai" / "settings.json"
    if not settings.exists():
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text('{"version": 1, "active": null, "profiles": {}}\n', encoding="utf-8")
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env.update(extra or {})
    return env


def _cmd(tmp_path, *args, store=None, log=None):
    return [sys.executable, "-u", str(MAIN), "--port", "0",
            "--store-dir", str(store or tmp_path / "chats"),
            "--log-file", str(log or tmp_path / "logs" / "runtime.log"),
            "--disable-wiki", *args]


def _spawn(tmp_path, *args, env_extra=None, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE):
    return subprocess.Popen(_cmd(tmp_path, *args), stdin=stdin, stdout=subprocess.PIPE,
                            stderr=stderr, env=_env(env_extra), cwd=str(tmp_path))


def _readline(proc, timeout=20.0):
    """One stdout line, read straight from the fd (so communicate() still works later)."""
    fd = proc.stdout.fileno()
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            continue
        char = os.read(fd, 1)
        if not char:
            break
        buf += char
        if char == b"\n":
            break
    return buf.decode("utf-8", "replace")


def _ready(proc):
    line = _readline(proc)
    assert line.startswith(READY), f"expected the READY line, got {line!r}"
    return json.loads(line[len(READY):])


def _rpc(port, method, params, token=""):
    body = json.dumps({"jsonrpc": "2.0", "id": "1", "method": method, "params": params}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/rpc", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Session-Token": token},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _exit_seconds(proc, sig=signal.SIGTERM):
    started = time.monotonic()
    proc.send_signal(sig)
    proc.wait(timeout=10)
    return time.monotonic() - started


def _stop(proc):
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=5)


def _token_files():
    return sorted((Path(os.environ["HOME"]) / ".vmdai" / "run").glob("runtime-*.json"))


def _wait_token_file(proc, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        files = _token_files()
        if files:
            return files[0]
        if proc.poll() is not None:
            raise AssertionError(f"the runtime exited with code {proc.returncode} before writing its token file")
        time.sleep(0.05)
    raise AssertionError("the token file never appeared")


def test_help_exits_zero():
    proc = subprocess.run([sys.executable, str(MAIN), "--help"], capture_output=True,
                          text=True, env=_env(), timeout=30)
    assert proc.returncode == 0
    for flag in ("--port", "--announce", "--watch-stdin", "--log-file"):
        assert flag in proc.stdout


def test_announce_prints_ready_first_line(tmp_path):
    proc = _spawn(tmp_path, "--announce")
    try:
        info = _ready(proc)
        assert set(info) == {"port", "pid", "version", "protocol", "launch_token"}
        assert info["pid"] == proc.pid and info["port"] > 0
        assert info["version"] == "0.3.0" and info["protocol"] == 2
        assert len(info["launch_token"]) == 32 and int(info["launch_token"], 16) >= 0
        assert _token_files() == []  # under --announce the token is only in READY
    finally:
        _stop(proc)


def test_health_after_ready(tmp_path):
    proc = _spawn(tmp_path, "--announce")
    try:
        info = _ready(proc)
        with urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/health", timeout=5) as resp:
            assert json.loads(resp.read()) == {"ok": True, "pid": proc.pid,
                                               "version": "0.3.0", "protocol": 2}
        refused = _rpc(info["port"], "session.start", {"cwd": str(tmp_path)})
        assert refused["error"]["code"] == "AUTH_REQUIRED"
        started = _rpc(info["port"], "session.start",
                       {"cwd": str(tmp_path), "launch_token": info["launch_token"]})
        assert started["result"]["event_protocol"] == 1
    finally:
        _stop(proc)


def test_runtime_shutdown_rpc_exits_within_2s(tmp_path):
    proc = _spawn(tmp_path, "--announce")
    try:
        info = _ready(proc)
        started = time.monotonic()
        reply = _rpc(info["port"], "runtime.shutdown", {"launch_token": info["launch_token"]})
        assert reply["result"] == {"ok": True}
        proc.wait(timeout=10)
        assert time.monotonic() - started < 2.0
        assert proc.returncode == 0
    finally:
        _stop(proc)


def test_sigterm_exits_within_2s(tmp_path):
    """S4: SIGTERM exits within 2 s (the old handler deadlocked)."""
    proc = _spawn(tmp_path, "--announce")
    try:
        _ready(proc)
        assert _exit_seconds(proc) < 2.0
        assert proc.returncode == 0
    finally:
        _stop(proc)

    # A second signal can re-enter _start_shutdown on the main thread while
    # the first handler still holds the lock; it must return, not deadlock.
    import importlib.util
    spec = importlib.util.spec_from_file_location("vmdai_runtime_main_under_test", MAIN)
    runtime_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime_main)

    class _Server:
        def shutdown(self):
            pass

    server, nested = _Server(), []

    def first_handler():
        with runtime_main._SHUTDOWN_LOCK:
            nested.append(runtime_main._start_shutdown(server))

    thread = threading.Thread(target=first_handler, daemon=True)
    thread.start()
    thread.join(2.0)
    assert nested and nested[0] is runtime_main._start_shutdown(server)


def test_sigterm_during_active_request_exits_within_2s(tmp_path):
    # A listener that accepts and never answers: the worker blocks in urlopen.
    silent = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    silent.bind(("127.0.0.1", 0))
    silent.listen(4)
    accepted = threading.Event()
    held = []

    def _accept():
        try:
            conn, _ = silent.accept()
        except OSError:
            return
        held.append(conn)
        accepted.set()

    threading.Thread(target=_accept, daemon=True).start()
    host = f"http://127.0.0.1:{silent.getsockname()[1]}"
    # Without --announce a tokenless session may use the env provider.
    proc = _spawn(tmp_path, stderr=subprocess.DEVNULL, env_extra={
        "VMD_AI_PROVIDER": "ollama",
        "VMD_AI_OLLAMA_MODEL": "qwen3.8:27b",
        "VMD_AI_OLLAMA_HOST": host,
    })
    try:
        port = json.loads(_wait_token_file(proc).read_text())["port"]
        start = _rpc(port, "session.start", {"cwd": str(tmp_path)})["result"]
        assert start["agent_loop"] is True
        sent = _rpc(port, "chat.send", {"session_id": start["session_id"], "text": "hi"},
                    token=start["session_token"])
        assert "request_id" in sent["result"]
        assert accepted.wait(5), "the worker never reached the provider"
        assert _exit_seconds(proc) < 2.0
    finally:
        _stop(proc)
        for conn in held:
            conn.close()
        silent.close()


class _OllamaToolCall(http.server.BaseHTTPRequestHandler):
    """A fake Ollama whose /api/chat answers with one run_vmd_command call."""

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        call = {"function": {"name": "run_vmd_command", "arguments": {"command": "puts hi"}}}
        lines = [
            {"message": {"role": "assistant", "content": "", "tool_calls": [call]}, "done": False},
            {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
        ]
        body = b"".join(json.dumps(line).encode("utf-8") + b"\n" for line in lines)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


def test_sigterm_during_tool_wait_exits_within_2s(tmp_path):
    # The model asks for a VMD command and no plugin ever answers, so the
    # worker blocks in VmdToolBridge.execute_tool (the 45 s pickup wait).
    fake = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OllamaToolCall)
    threading.Thread(target=fake.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    proc = _spawn(tmp_path, stderr=subprocess.DEVNULL, env_extra={
        "VMD_AI_PROVIDER": "ollama",
        "VMD_AI_OLLAMA_MODEL": "qwen3.8:27b",
        "VMD_AI_OLLAMA_HOST": f"http://127.0.0.1:{fake.server_port}",
    })
    try:
        port = json.loads(_wait_token_file(proc).read_text())["port"]
        start = _rpc(port, "session.start", {"cwd": str(tmp_path)})["result"]
        sid, token = start["session_id"], start["session_token"]
        sent = _rpc(port, "chat.send", {"session_id": sid, "text": "hi"}, token=token)
        assert "request_id" in sent["result"]
        roles, deadline = [], time.monotonic() + 5
        while "tool_start" not in roles and time.monotonic() < deadline:
            polled = _rpc(port, "chat.events.poll", {"session_id": sid, "after_seq": 0}, token=token)
            roles = [event["role"] for event in polled["result"]["events"]]
            time.sleep(0.05)
        assert "tool_start" in roles, "the worker never reached the tool wait"
        assert _exit_seconds(proc) < 2.0
    finally:
        _stop(proc)
        fake.shutdown()
        fake.server_close()


def test_stdin_eof_exits_within_2s(tmp_path):
    proc = _spawn(tmp_path, "--announce", "--watch-stdin", stdin=subprocess.PIPE)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = _spawn(other_dir, "--announce", stdin=subprocess.PIPE)
    try:
        _ready(proc)
        _ready(other)
        # Without --watch-stdin, EOF on stdin is ignored. Close other's stdin
        # first so its 0.5 s check overlaps proc's exit instead of following it.
        other.stdin.close()
        other_closed = time.monotonic()
        started = time.monotonic()
        proc.stdin.close()
        proc.wait(timeout=10)
        assert time.monotonic() - started < 2.0
        assert proc.returncode == 0
        time.sleep(max(0.0, 0.5 - (time.monotonic() - other_closed)))
        assert time.monotonic() - other_closed >= 0.5
        assert other.poll() is None
    finally:
        _stop(proc)
        _stop(other)


def test_no_announce_writes_token_file_0600_and_removes_on_exit(tmp_path):
    proc = _spawn(tmp_path, stderr=subprocess.DEVNULL)
    try:
        path = _wait_token_file(proc)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        data = json.loads(path.read_text())
        assert set(data) == {"port", "pid", "token", "protocol"}
        assert data["pid"] == proc.pid and data["protocol"] == 2 and len(data["token"]) == 32
        assert path.name == f"runtime-{data['port']}.json"
        started = _rpc(data["port"], "session.start", {"cwd": str(tmp_path)})
        assert "session_id" in started["result"]  # tokenless is fine without --announce
        assert _exit_seconds(proc) < 2.0
        assert not path.exists()
        # No READY line (nor any other stdout) without --announce, over the
        # runtime's whole life rather than a 0.5 s window after the token file.
        assert proc.stdout.read() == b""
    finally:
        _stop(proc)


def test_announce_keeps_stderr_clean(tmp_path):
    proc = _spawn(tmp_path, "--announce")
    try:
        info = _ready(proc)
        bad = _rpc(info["port"], "no.such.method", {})
        assert bad["error"]["code"] == "METHOD_NOT_FOUND"  # the app logs a warning
        _exit_seconds(proc)
        rest, err = proc.communicate(timeout=5)
    finally:
        _stop(proc)
    assert rest == b""
    assert err == b""
    log = (tmp_path / "logs" / "runtime.log").read_text(encoding="utf-8")
    assert "rpc error method=no.such.method" in log
    assert "runtime stopped" in log


def test_startup_traceback_reaches_merged_pipe(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    cases = (
        # Fails after logging is configured: the store dir cannot be created.
        _cmd(tmp_path, "--announce", store=blocker / "chats"),
        # Fails before logging is configured: the log dir cannot be created.
        _cmd(tmp_path, "--announce", log=blocker / "logs" / "runtime.log"),
    )
    for cmd in cases:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, env=_env(), timeout=30)
        out = proc.stdout.decode("utf-8", "replace")
        assert proc.returncode != 0
        assert "Traceback (most recent call last)" in out
        assert "VMDAI_READY" not in out
    assert "runtime failed to start" in (tmp_path / "logs" / "runtime.log").read_text()
