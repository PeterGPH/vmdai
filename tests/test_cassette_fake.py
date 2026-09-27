"""P04-T07: the cassette replay fake, the recorder's privacy rules and the
committed cassette set (spec C9)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

import pytest

from helpers.cassette import CASSETTE_DIR, CassetteError, load_cassette, play
from helpers.provider_fakes import FakeResponse

REPO = Path(__file__).resolve().parents[1]
EXPECTED = {
    ("ollama", "plain_answer"): False,
    ("ollama", "tool_call"): False,
    ("ollama", "thinking_tool_call"): False,
    ("ollama", "vision_turn"): False,
    ("ollama", "truncated_tool_call"): False,
    ("ollama", "model_not_found"): False,
    ("ollama", "version_ps"): False,
    ("ollama", "think_unsupported"): True,
    ("ollama", "rescue_json"): True,
    ("openai-compatible", "reasoning_usage"): True,
    ("anthropic-direct", "usage_error"): True,
}


def cassette(*exchanges: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "meta": {"recorded_at": "2026-09-24T00:00:00Z", "provider": "ollama",
                 "server_version": "0.12.0", "model": "m", "model_digest": None,
                 "synthetic": True},
        "exchanges": list(exchanges),
    }


def exchange(method: str, path: str, *, status: int = 200, lines=("{}",),
             content_type: str = "application/json") -> Dict[str, Any]:
    return {"method": method, "path": path, "request_sha256": "", "status": status,
            "content_type": content_type, "body_lines": list(lines)}


def post(url: str, data: bytes = b"{}") -> urllib.request.Request:
    return urllib.request.Request(url, data=data, method="POST")


def test_serves_in_order():
    cas = cassette(
        exchange("GET", "/api/version", lines=['{"version":"0.12.0"}']),
        exchange("POST", "/api/chat", lines=['{"a":1}', '{"b":2}'], content_type="application/x-ndjson"),
    )
    with play(cas) as player:
        with urllib.request.urlopen("http://ollama.test/api/version", timeout=2) as resp:
            assert json.loads(resp.read()) == {"version": "0.12.0"}
        with urllib.request.urlopen(post("http://ollama.test/api/chat", b'{"model":"m"}'), timeout=2) as resp:
            assert list(resp) == [b'{"a":1}\n', b'{"b":2}\n']
    assert [r["path"] for r in player.requests] == ["/api/version", "/api/chat"]
    assert player.requests[1]["body"] == {"model": "m"}


def test_method_path_mismatch_fails():
    with pytest.raises(CassetteError, match="expected GET /api/version, got POST /api/chat"):
        with play(cassette(exchange("GET", "/api/version"))):
            urllib.request.urlopen(post("http://ollama.test/api/chat"), timeout=2)


def test_mismatch_swallowed_by_product_code_still_fails():
    with pytest.raises(CassetteError, match="expected GET /api/version, got GET /api/ps"):
        with play(cassette(exchange("GET", "/api/version"))):
            try:
                urllib.request.urlopen("http://ollama.test/api/ps", timeout=2)
            except Exception:
                pass


def test_extra_request_fails():
    with pytest.raises(CassetteError, match="extra request GET /api/version"):
        with play(cassette(exchange("GET", "/api/version"))):
            urllib.request.urlopen("http://ollama.test/api/version", timeout=2)
            urllib.request.urlopen("http://ollama.test/api/version", timeout=2)


def test_unconsumed_fails_at_teardown():
    with pytest.raises(CassetteError, match=r"1 exchange\(s\) left unconsumed; next is GET /api/ps"):
        with play(cassette(exchange("GET", "/api/version"), exchange("GET", "/api/ps"))):
            urllib.request.urlopen("http://ollama.test/api/version", timeout=2)


def test_4xx_raises_httperror_with_body():
    cas = cassette(exchange("POST", "/api/chat", status=404,
                            lines=['{"error":"model \\"x\\" not found"}']))
    with play(cas):
        with pytest.raises(urllib.error.HTTPError) as info:
            urllib.request.urlopen(post("http://ollama.test/api/chat"), timeout=2)
    assert info.value.code == 404
    assert json.loads(info.value.read()) == {"error": 'model "x" not found'}


def _recorder_module():
    spec = importlib.util.spec_from_file_location("record_cassettes", REPO / "scripts" / "record_cassettes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_auth_headers_recorded():
    module = _recorder_module()

    def inner(req, timeout=None, **kwargs):
        return FakeResponse(req.full_url, 200, "application/json",
                            b'{"echo":"http://127.0.0.1:11435/api/tags"}')

    recorder = module.Recorder(inner, base_url="http://127.0.0.1:11435")
    req = urllib.request.Request(
        "http://127.0.0.1:11435/api/chat", data=b'{"model":"m"}', method="POST",
        headers={"Authorization": "Bearer sk-secret-123", "x-api-key": "sk-ant-secret-456"},
    )
    recorder.urlopen(req, timeout=2).read()
    dumped = json.dumps(recorder.exchanges)
    for needle in ("Authorization", "authorization", "x-api-key", "X-api-key",
                   "sk-secret-123", "sk-ant-secret-456", "127.0.0.1:11435"):
        assert needle not in dumped
    assert "http://ollama.test/api/tags" in dumped
    assert recorder.exchanges[0]["request_sha256"] == hashlib.sha256(b'{"model":"m"}').hexdigest()
    for path in sorted(CASSETTE_DIR.rglob("*.json")):
        text = path.read_text(encoding="utf-8").lower()
        for needle in ("authorization", "x-api-key", "sk-ant-", "bearer "):
            assert needle not in text, f"{path} contains {needle!r}"


def test_synthesize_is_reproducible(tmp_path):
    module = _recorder_module()
    module.synthesize(tmp_path)
    for (provider, name), synthetic in EXPECTED.items():
        if synthetic:
            written = (tmp_path / provider / f"{name}.json").read_text(encoding="utf-8")
            committed = (CASSETTE_DIR / provider / f"{name}.json").read_text(encoding="utf-8")
            assert written == committed, f"{provider}/{name}.json differs from --synthesize output"


def test_committed_cassettes_valid():
    found = {(p.parent.name, p.stem) for p in CASSETTE_DIR.rglob("*.json")}
    assert found == set(EXPECTED)
    for (provider, name), synthetic in EXPECTED.items():
        data = load_cassette(provider, name)
        assert data["meta"]["synthetic"] is synthetic
        assert data["meta"]["provider"] == provider
        assert data["exchanges"], f"{provider}/{name} has no exchanges"
