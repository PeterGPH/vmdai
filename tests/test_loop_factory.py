"""P02-T10: a fresh loop per request, the claude_loop compat setter and a real session lock (§3 app.py)."""
from __future__ import annotations

import threading
import time

from helpers.runtime_fixture import make_app, rpc, start_tokenless_session, wait_idle
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, RunContext

DEFAULT_MODEL = "anthropic/claude-sonnet-4.6"  # DEFAULT_SETTINGS["model"]


class FakeLoop(ClaudeToolLoop):
    """A ClaudeToolLoop whose _call returns one text turn and records what it saw."""

    def __init__(self, release=None):
        super().__init__(provider_name="openrouter", api_key="sk-or-test", model=DEFAULT_MODEL)
        self.release = release
        self.seen_ctx = []
        self.seen_recorders = []

    def run(self, *args, **kwargs):
        self.seen_ctx.append(kwargs.get("ctx"))
        return super().run(*args, **kwargs)

    def _call(self, messages, system_prompt, on_text, should_cancel):
        self.seen_recorders.append(self.recorder)
        if self.release is not None:
            self.release.wait(5)
        on_text("done")
        return "done", []


def _send(app, session, text="hi", **extra):
    return rpc(app, "chat.send", dict(text=text, **extra), session=session)


def _spy_runs(monkeypatch):
    """Record the loop object behind every run() call; _call answers at once."""
    used = []
    original = ClaudeToolLoop.run

    def spy(self, *args, **kwargs):
        used.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ClaudeToolLoop, "run", spy)
    monkeypatch.setattr(ClaudeToolLoop, "_call",
                        lambda self, messages, system_prompt, on_text, should_cancel: ("done", []))
    return used


def test_concurrent_send_conflict(tmp_path):
    release = threading.Event()

    def slow_factory(profile):
        time.sleep(0.1)  # widen the window between the conflict check and the start
        return FakeLoop(release=release)

    app = make_app(tmp_path, loop_factory=slow_factory)
    session = start_tokenless_session(app, cwd=str(tmp_path))
    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait()
        results.append(_send(app, session))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    release.set()
    wait_idle(app, session["session_id"])
    started = [r for r in results if "result" in r]
    conflicts = [r for r in results if r.get("error", {}).get("code") == "REQUEST_CONFLICT"]
    assert (len(started), len(conflicts)) == (1, 1), results


def test_per_request_loop_gets_wiki_store(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    app = make_app(tmp_path, provider_mode="openrouter", enable_wiki=True,
                   wiki_root=str(tmp_path / "wiki"), wiki_raw_root=str(tmp_path / "raw"))
    assert app.wiki_store is not None
    used = _spy_runs(monkeypatch)
    session = start_tokenless_session(app, cwd=str(tmp_path))
    assert "result" in _send(app, session, model="other/model")
    wait_idle(app, session["session_id"])
    assert len(used) == 1
    assert used[0].model == "other/model"
    assert used[0].wiki_store is app.wiki_store  # the old model override dropped it


def test_recorder_not_shared(tmp_path):
    built = []

    def factory(profile):
        loop = FakeLoop()
        built.append(loop)
        return loop

    app = make_app(tmp_path, loop_factory=factory)
    cwd_a, cwd_b = tmp_path / "a", tmp_path / "b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    for cwd in (cwd_a, cwd_b):
        session = start_tokenless_session(app, cwd=str(cwd))
        assert "result" in _send(app, session)
        wait_idle(app, session["session_id"])
    ran = [loop for loop in built if loop.seen_recorders]
    assert len(ran) == 2 and ran[0] is not ran[1]
    rec_a, rec_b = ran[0].seen_recorders[0], ran[1].seen_recorders[0]
    assert rec_a is not rec_b
    assert rec_a.runs_root == cwd_a.resolve() / ".vmdai_runs"
    assert rec_b.runs_root == cwd_b.resolve() / ".vmdai_runs"


def test_assigned_claude_loop_used(tmp_path):
    app = make_app(tmp_path)  # mock provider: no loop of its own
    assert app.claude_loop is None
    assert app.has_agent_loop() is False
    fake = FakeLoop()
    app.claude_loop = fake
    assert app.claude_loop is fake
    assert app.has_agent_loop() is True
    session = start_tokenless_session(app, cwd=str(tmp_path))
    assert session["agent_loop"] is True
    sent = _send(app, session)["result"]
    wait_idle(app, session["session_id"])
    ctx, = fake.seen_ctx
    assert isinstance(ctx, RunContext)
    assert (ctx.request_id, ctx.chat_id) == (sent["request_id"], session["chat_id"])
    assert fake.recorder is None  # the shared loop never keeps a request's recorder


def test_provider_set_does_not_assign_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    app = make_app(tmp_path)
    fake = FakeLoop()
    app.claude_loop = fake
    session = start_tokenless_session(app, cwd=str(tmp_path))
    resp = rpc(app, "provider.set", {"provider": "openrouter", "model": DEFAULT_MODEL},
               session=session)
    assert resp["result"]["agent_loop"] is True
    assert app.claude_loop is None  # provider.set never installs a shared loop
    used = _spy_runs(monkeypatch)
    for _ in range(2):
        assert "result" in _send(app, session)
        wait_idle(app, session["session_id"])
    assert len(used) == 2
    assert used[0] is not used[1]
    assert all(loop is not fake for loop in used)
    assert fake.seen_ctx == [] and fake.recorder is None
