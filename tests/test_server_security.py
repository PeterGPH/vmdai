"""P02-T01: loopback Host/Origin checks, the /health payload and ASCII-only JSON (§2e, §2c, S11)."""
from __future__ import annotations

import json
import os
import socket
import threading
import urllib.request

import pytest

from vmd_ai_runtime.app import RuntimeApp
from vmd_ai_runtime.server import RpcHTTPServer, create_server

START = {"jsonrpc": "2.0", "id": "1", "method": "session.start", "params": {"cwd": "."}}


@pytest.fixture
def port(tmp_path):
    app = RuntimeApp(store_dir=str(tmp_path / "chats"), provider_mode="mock",
                     enable_rag=False, enable_wiki=False)
    server = create_server(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield int(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _raw(port, request):
    """Send one raw HTTP request and return (status, body bytes)."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(request)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
    head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
    return int(head.split(b" ", 2)[1]), body


def _get(port, host, extra=""):
    request = f"GET /health HTTP/1.1\r\nHost: {host}\r\n{extra}Connection: close\r\n\r\n"
    return _raw(port, request.encode("ascii"))


def _post(port, host, payload, extra=""):
    body = json.dumps(payload).encode("ascii")
    head = (f"POST /rpc HTTP/1.1\r\nHost: {host}\r\n{extra}"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n")
    return _raw(port, head.encode("ascii") + body)


def _assert_forbidden(status, body):
    assert status == 403
    assert json.loads(body)["error"]["code"] == "FORBIDDEN"


def test_foreign_host_rejected(port):
    _assert_forbidden(*_get(port, f"192.168.1.20:{port}"))
    _assert_forbidden(*_get(port, f"127.0.0.1:{port + 1}"))
    _assert_forbidden(*_post(port, f"10.0.0.1:{port}", START))


def test_dns_rebinding_host_rejected(port):
    # A rebinding page makes attacker.example resolve to 127.0.0.1, but the
    # browser still sends its own host name in Host.
    _assert_forbidden(*_get(port, f"attacker.example:{port}"))
    _assert_forbidden(*_post(port, f"attacker.example:{port}", START))


def test_origin_header_rejected(port):
    good = f"127.0.0.1:{port}"
    _assert_forbidden(*_post(port, good, START, extra="Origin: http://evil.example\r\n"))
    _assert_forbidden(*_post(port, good, START, extra="Origin: null\r\n"))
    _assert_forbidden(*_get(port, good, extra="Origin: http://127.0.0.1\r\n"))


def test_missing_host_rejected(port):
    # HTTP/1.0 allows a request with no Host header; the runtime must not.
    _assert_forbidden(*_raw(port, b"GET /health HTTP/1.0\r\n\r\n"))
    _assert_forbidden(*_raw(port, b"POST /rpc HTTP/1.0\r\nContent-Length: 2\r\n\r\n{}"))


def test_localhost_host_accepted_case_insensitive(port):
    for host in (f"127.0.0.1:{port}", f"localhost:{port}", f"LOCALHOST:{port}"):
        status, body = _get(port, host)
        assert status == 200, host
        assert json.loads(body)["ok"] is True
    status, body = _post(port, f"Localhost:{port}", START)
    assert status == 200
    assert "session_id" in json.loads(body)["result"]


def test_health_payload(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
        assert resp.headers["Content-Type"] == "application/json; charset=utf-8"
        payload = json.loads(resp.read())
    assert payload == {"ok": True, "pid": os.getpid(), "version": "0.3.0", "protocol": 2}


def test_ascii_wire(port):
    status, body = _post(port, f"127.0.0.1:{port}",
                         {"jsonrpc": "2.0", "id": "u", "method": "Å→°", "params": {}})
    assert status == 200
    assert all(byte < 0x80 for byte in body), body
    assert json.loads(body.decode("ascii"))["error"]["message"].endswith("Å→°")


def test_request_threads_do_not_block_exit():
    assert RpcHTTPServer.daemon_threads is True
    assert RpcHTTPServer.block_on_close is False
