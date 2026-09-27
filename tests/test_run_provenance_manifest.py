"""C6: product run provenance in the recorder manifest."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from helpers.fake_http import FakeHTTP, anthropic_text, ollama_text, openai_text
from helpers.runtime_fixture import make_app, start_token_session
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, RunContext
from vmd_ai_runtime.constants import RUNTIME_VERSION
from vmd_ai_runtime.events import EventQueue
from vmd_ai_runtime.provider_catalog import strip_url_secrets
from vmd_ai_runtime.recorder import RunRecorder
from vmd_ai_runtime.settings_store import SettingsStore

TOKEN = "0123456789abcdef0123456789abcdef"
LEGACY_KEYS = {
    "task_id", "status", "prompt", "chat_id", "model", "cwd", "started_at",
    "last_activity_at", "turn_count", "successful_count", "failed_count",
    "snapshot_count", "ended_at",
}
VMD_ENV = {"vmd_version": "1.9.4a57", "arch": "MACOSXARM64",
           "tcl_patchlevel": "8.6.12", "tk_patchlevel": "8.6.12"}


class NullBridge:
    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input, session_queue, cancel_event):
        return {"ok": True, "output": "", "error": ""}


def _manifest(root: Path) -> dict:
    found = list((root / ".vmdai_runs").glob("*/manifest.json"))
    assert len(found) == 1, found
    return json.loads(found[0].read_text())


def _run(loop, fake, root, meta):
    loop.recorder = RunRecorder.for_cwd(root, meta=meta)
    ctx = RunContext(request_id="req_000000000001", chat_id="chat_0123456789ab")
    with mock.patch("urllib.request.urlopen", fake):
        loop.run(prompt="hi", system_prompt="s", tool_bridge=NullBridge(),
                 session_id="sess_0123456789ab", session_queue=EventQueue(),
                 cancel_event=threading.Event(), on_chunk=lambda t: None, ctx=ctx)
    return _manifest(root)


def _rpc(app, method, params, sess):
    body = {"jsonrpc": "2.0", "id": "t", "method": method,
            "params": dict(params, session_id=sess["session_id"])}
    return app.handle_rpc(body, session_token=sess["session_token"])


def _wait_idle(app, session_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = app.sessions.get(session_id)
        if state is not None and state.active_request is None:
            return
        time.sleep(0.02)
    raise AssertionError("request did not finish")


def test_existing_keys_unchanged_without_meta(tmp_path):
    rec = RunRecorder.for_cwd(tmp_path)
    tid = rec.start_task("x", chat_id="c", model="m", cwd="/w")
    rec.update_meta(model_digest="sha256:x", usage={"output_tokens": 1})
    rec.end_task()
    assert set(rec.read_manifest(tid)) == LEGACY_KEYS
    assert "# provider" not in rec.read_transcript(tid)


def test_digest_from_ps(tmp_path):
    ps = {"models": [{"name": "qwen3.8:27b", "model": "qwen3.8:27b", "digest": "c0ffee1234", "size": 1}]}
    fake = FakeHTTP([ollama_text("done")], ps=ps)
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="qwen3.8:27b",
                          options=LoopOptions(preflight=True, base_url="http://ollama.test"))
    m = _run(loop, fake, tmp_path, {"request_id": "req_000000000001"})
    assert m["provenance"]["model_digest"] == "c0ffee1234"
    assert m["usage"] == {"input_tokens_evaluated": 10, "output_tokens": 5}
    assert m["counts"] == {"tool_calls": 0, "rescued_calls": 0, "truncated_turns": 0, "compactions": 0}
    assert m["status"] == "complete"
    assert any(u.endswith("/api/ps") for u in fake.urls)


def test_digest_null_when_absent(tmp_path):
    fake = FakeHTTP([ollama_text("done")], ps={"models": []})
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="qwen3.8:27b",
                          options=LoopOptions(preflight=True, base_url="http://ollama.test"))
    m = _run(loop, fake, tmp_path, {"request_id": "req_000000000001"})
    assert m["provenance"]["model_digest"] is None


def test_usage_null_include_usage_off(tmp_path):
    fake = FakeHTTP([openai_text("done")])
    loop = ClaudeToolLoop(provider_name="openai-compatible", api_key="EMPTY", model="m",
                          options=LoopOptions(base_url="http://vllm.test/v1", include_usage=False))
    m = _run(loop, fake, tmp_path, {"request_id": "req_000000000001"})
    assert m["usage"] == {"input_tokens_evaluated": None, "output_tokens": None}
    assert m["provenance"]["model_digest"] is None
    assert "stream_options" not in fake.bodies[0]


@pytest.mark.parametrize("provider,api_key,model,reply", [
    ("anthropic-direct", "sk-ant-test", "claude-sonnet-4-5", anthropic_text),
    ("ollama", "http://ollama.test", "qwen3.8:27b", ollama_text),
])
def test_tools_sha256_matches_first_request(tmp_path, provider, api_key, model, reply):
    # The hash covers the tools list exactly as the provider's body carries it.
    app = make_app(tmp_path, launch_token=TOKEN)
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    state = app.sessions.get(sess["session_id"])
    loop = ClaudeToolLoop(provider_name=provider, api_key=api_key, model=model,
                          options=LoopOptions())
    meta = app._recorder_meta(state, loop, "req_000000000001")
    fake = FakeHTTP([reply("done")])
    m = _run(loop, fake, tmp_path / "w", meta)
    first_tools = fake.bodies[0]["tools"]
    canonical = hashlib.sha256(
        json.dumps(first_tools, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert m["provenance"]["tools_sha256"] == canonical


def test_system_prompt_sha_cwd_independent_wiki_dependent(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    other = tmp_path / "other"
    other.mkdir()
    a = start_token_session(app, TOKEN, cwd=str(tmp_path))
    b = start_token_session(app, TOKEN, cwd=str(other))
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m",
                          options=LoopOptions(base_url="http://ollama.test"))
    sha_a = app._recorder_meta(app.sessions.get(a["session_id"]), loop, "req_a")["system_prompt_sha256"]
    sha_b = app._recorder_meta(app.sessions.get(b["session_id"]), loop, "req_b")["system_prompt_sha256"]
    assert sha_a == sha_b and len(sha_a) == 64
    # C6: the hash covers exactly the prompt the request sends before its
    # <session> block (P04-T06), mode line included.
    full = app._system_prompt_for_request(app.sessions.get(a["session_id"]), loop)
    before_session = full[: full.index("\n\n<session>\n")]
    assert sha_a == hashlib.sha256(before_session.encode("utf-8")).hexdigest()
    loop.wiki_store = object()
    sha_wiki = app._recorder_meta(app.sessions.get(a["session_id"]), loop, "req_c")["system_prompt_sha256"]
    assert sha_wiki != sha_a


def test_base_url_secrets_stripped(tmp_path):
    assert strip_url_secrets("http://user:pw@127.0.0.1:11435/v1?key=x#frag") == "http://127.0.0.1:11435/v1"
    assert strip_url_secrets("https://openrouter.ai/api/v1") == "https://openrouter.ai/api/v1"
    assert strip_url_secrets("") == ""
    app = make_app(tmp_path, launch_token=TOKEN)
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    secret = "http://user:pw@127.0.0.1:11435?key=x"
    loop = ClaudeToolLoop(provider_name="ollama", api_key=secret, model="m",
                          options=LoopOptions(base_url=secret))
    meta = app._recorder_meta(app.sessions.get(sess["session_id"]), loop, "req_1")
    dumped = json.dumps(meta)
    assert "pw@" not in dumped and "key=x" not in dumped
    assert meta["base_url"] == "http://127.0.0.1:11435"
    assert meta["options"]["base_url"] == "http://127.0.0.1:11435"


def test_header_comment_lines(tmp_path):
    meta = {"request_id": "req_1", "profile": "qwen", "provider": "ollama",
            "base_url": "http://127.0.0.1:11435", "model": "qwen3.8:27b", "model_digest": None,
            "runtime_version": "0.3.0", "vmd_env": VMD_ENV, "options": {"num_ctx": 32768},
            "system_prompt_sha256": "a" * 64, "tools_sha256": "b" * 64}
    rec = RunRecorder.for_cwd(tmp_path, meta=meta)
    tid = rec.start_task("x")
    rec.update_meta(model_digest="sha256:abc")
    rec.end_task()
    head = rec.read_transcript(tid)
    assert "# provider   : ollama http://127.0.0.1:11435\n" in head
    assert "# runtime    : vmd_ai_runtime 0.3.0\n" in head
    assert "# vmd        : 1.9.4a57 MACOSXARM64 (Tcl 8.6.12, Tk 8.6.12)\n" in head
    assert "# provenance : see manifest.json\n" in head
    assert "sha256:abc" not in head, "the digest lives only in the manifest"


def test_update_meta_merges_and_mirrors_status(tmp_path):
    rec = RunRecorder.for_cwd(tmp_path, meta={"request_id": "req_1", "model_digest": None})
    tid = rec.start_task("x")
    rec.update_meta(model_digest="sha256:abc", usage={"output_tokens": 5}, counts={"tool_calls": 2})
    m = rec.read_manifest(tid)
    assert m["status"] == "active"
    assert m["provenance"] == {"request_id": "req_1", "model_digest": "sha256:abc"}
    assert m["usage"] == {"input_tokens_evaluated": None, "output_tokens": 5}
    assert m["counts"] == {"tool_calls": 2, "rescued_calls": 0, "truncated_turns": 0, "compactions": 0}
    rec.end_task("stuck")
    assert rec.read_manifest(tid)["status"] == "stuck"


def test_product_run_manifest_has_provenance(tmp_path):
    # make_app builds no SettingsStore (plan 03: only main.py passes one).
    app = make_app(tmp_path, launch_token=TOKEN, settings_store=SettingsStore())
    work = tmp_path / "work"
    work.mkdir()
    sess = start_token_session(app, TOKEN, cwd=str(work), vmd_env=VMD_ENV)
    app.settings_store.save_profile(
        "local", {"provider": "ollama", "base_url": "http://127.0.0.1:9", "model": "m"}, activate=True)
    secret = "http://user:pw@127.0.0.1:9?key=x"
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://127.0.0.1:9", model="m",
                          options=LoopOptions(base_url=secret))
    app.claude_loop = loop

    def fake_call(self, messages, system_prompt, on_text, should_cancel):
        on_text("done")
        return "done", []

    with mock.patch.object(ClaudeToolLoop, "_call", new=fake_call):
        resp = _rpc(app, "chat.send", {"text": "hello", "conversation_mode": "full"}, sess)
        assert "result" in resp, resp
        _wait_idle(app, sess["session_id"])
    m = _manifest(work)
    p = m["provenance"]
    assert p["request_id"] == resp["result"]["request_id"]
    assert p["profile"] == "local"
    assert (p["provider"], p["model"]) == ("ollama", "m")
    assert p["runtime_version"] == RUNTIME_VERSION
    assert p["vmd_env"] == VMD_ENV
    assert p["base_url"] == "http://127.0.0.1:9"
    assert len(p["system_prompt_sha256"]) == 64 and len(p["tools_sha256"]) == 64
    assert "pw@" not in json.dumps(m) and "key=x" not in json.dumps(m)
    assert m["status"] == "complete"
    transcript = next((work / ".vmdai_runs").glob("*/transcript.tcl")).read_text()
    assert "# provenance : see manifest.json" in transcript
