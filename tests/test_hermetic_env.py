"""The hermetic base (spec §6, S9): env, HOME and keyring are isolated per test."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from helpers.live import LIVE_ENV, LIVE_GATES

REPO = Path(__file__).resolve().parents[1]
PREFIXES = ("VMD_AI_", "ANTHROPIC_", "OPENROUTER_", "OLLAMA_")
PROBE_MODEL = "probe-model-7f3c"


def _child_env(**extra: str) -> dict:
    env = dict(os.environ)
    env.update(extra)
    return env


def _run_child_pytest(*args: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=str(REPO),
        env=_child_env(**env),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_env_prefixes_cleared():
    leaked = sorted(k for k in os.environ if k.startswith(PREFIXES))
    assert leaked == []


def test_home_is_tmp(tmp_path):
    from vmd_ai_runtime.app import RuntimeApp

    home = tmp_path / "home"
    assert os.environ["HOME"] == str(home)
    assert Path.home() == home
    app = RuntimeApp()
    assert Path(app.store.root_dir) == home / ".vmdai" / "chats"
    assert app.wiki_store is not None
    assert app.wiki_store.wiki_root.is_relative_to(home.resolve())
    assert app.provider_name == "mock"


def test_keyring_is_isolated(fake_keyring_store):
    import keyring
    from vmd_ai_runtime.keys import KeyStore

    assert type(keyring.get_keyring()).__name__ == "StubBackend"
    assert fake_keyring_store == {}
    result = KeyStore().save("openrouter", "sk-or-hermetic")
    assert result.ok, result.message
    assert fake_keyring_store == {("vmd_ai", "openrouter_api_key"): "sk-or-hermetic"}


def test_live_env_captured_before_clearing():
    proc = _run_child_pytest(
        "tests/test_hermetic_env.py::test_live_env_probe",
        VMD_AI_LIVE_MODEL=PROBE_MODEL,
        CHATVMD_LIVE_PROBE="1",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout


def test_live_env_probe(live_env):
    """Always runs; test_live_env_captured_before_clearing also runs it in a child."""
    assert live_env is LIVE_ENV
    assert set(live_env) <= set(LIVE_GATES)
    for name in LIVE_GATES:
        assert name not in os.environ
    if os.environ.get("CHATVMD_LIVE_PROBE") == "1":
        assert live_env.get("VMD_AI_LIVE_MODEL") == PROBE_MODEL


def test_owner_shell_env_does_not_leak():
    proc = _run_child_pytest(
        "tests/test_provider_selection.py",
        VMD_AI_PROVIDER="anthropic-direct",
        ANTHROPIC_API_KEY="sk-ant-x",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "5 passed" in proc.stdout
