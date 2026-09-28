"""Final-fix I2 (plan-09 final-review.md): Settings reloads cleanly after a
real runtime restart while it's open, instead of showing the old session's
AUTH_FAILED.

Unlike tests/tcl/test_bridge_v2.tcl's v2-settings_after_restart (a fake
transport with no sessions), this drives the real plugin against a real
in-process RuntimeApp: killing and restarting it exercises the actual
session/token handshake that I2's bug depended on. The two RuntimeApps
share one SettingsStore (like a real ~/.vmdai/settings.json surviving a
crash), so the active profile ("qwen") is still there once the plugin
recovers.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from helpers import tcl, tk
from helpers.scripted_runtime import ScriptedLoopFactory, serve_runtime
from vmd_ai_runtime.settings_store import SettingsStore

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "tests" / "tcl" / "panel_restart_driver.tcl"

QWEN_PROFILE = {"provider": "ollama", "base_url": "http://127.0.0.1:9", "model": "m", "options": {}}

_CACHE: Dict[str, Dict[str, Any]] = {}


def _run(tmp: Path) -> Dict[str, Any]:
    reason = tk.tk_skip_reason() or tcl.tcl_skip_reason(needs_http=True, needs_json=True)
    if reason:
        pytest.skip(reason)
    # tests/conftest.py's autouse _hermetic fixture already creates tmp/"home"
    # (and points os.environ["HOME"] at it) before this fixture runs; SettingsStore()
    # below reads/writes it through that same HOME.
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    work = tmp / "proj"
    work.mkdir()
    sync = tmp / "sync"
    sync.mkdir()
    out = tmp / "out.json"

    store = SettingsStore()
    store.save_profile("qwen", QWEN_PROFILE, activate=True)

    factory = ScriptedLoopFactory([("Loaded.", [])])
    # Both RuntimeApps this RunningRuntime builds (before and after the
    # restart) share `store`, so the profile a real ~/.vmdai/settings.json
    # would keep across a crash is still there once the plugin recovers.
    runtime = serve_runtime(home, factory, settings_store=store)
    env = {
        "HOME": str(home),
        "VMD_AI_ATTACH": f"127.0.0.1:{runtime.port}",
        "PANEL_RESTART_OUT": str(out),
        "PANEL_RESTART_SYNC": str(sync),
        "PANEL_RESTART_WORKDIR": str(work),
    }
    done: Dict[str, Any] = {}

    def run() -> None:
        done["proc"] = tcl.run_tcl(tk.tk_prelude() + DRIVER.read_text(encoding="utf-8"),
                                   needs_http=True, needs_json=True, env=env, timeout=90)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 30
        while not (sync / "ready_for_restart").exists():
            assert worker.is_alive() and time.monotonic() < deadline, done
            time.sleep(0.02)
        runtime.stop()
        time.sleep(3.0)
        runtime.restart_same_port()
        (sync / "restarted").touch()
        worker.join(timeout=100)
    finally:
        runtime.stop()
    proc = done["proc"]
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    assert "error" not in data, data.get("error")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return {"data": data, "runtime": runtime}


@pytest.fixture
def result(tmp_path):
    # Function scope keeps the hermetic conftest (HOME, keyring) active;
    # the driver and its runtime run once per module (cached across tests).
    if "result" not in _CACHE:
        _CACHE["result"] = _run(tmp_path)
    return _CACHE["result"]


def test_settings_profile_survives_restart(result):
    assert result["data"]["profile"] == "qwen"


def test_settings_footer_has_no_stale_session_error(result):
    assert "invalid session" not in result["data"]["footer_msg"]


def test_settings_key_rows_are_not_unknown(result):
    assert not result["data"]["src_anthropic"].startswith("Unknown")
    assert not result["data"]["src_openrouter"].startswith("Unknown")


def test_settings_not_stuck_saving(result):
    assert result["data"]["saving"] is False


def test_runtime_restarted_exactly_once(result):
    assert len(result["runtime"].apps) == 2
