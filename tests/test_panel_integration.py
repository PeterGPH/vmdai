"""P09-T09: the real plugin, attached to a scripted runtime, driven through the panel.

Closes M2 (§8): S2 on the assembled panel, and Tk goldens for it. The driver
(tests/tcl/panel_driver.tcl) sends two prompts through the composer, then
opens a new chat and resumes the first one; the resumed view must equal the
live one (§2c Persistence: replay through vm::apply).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

import pytest

from helpers import tcl, tk
from helpers.scripted_runtime import ScriptedLoopFactory, serve_runtime

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "tests" / "tcl" / "panel_driver.tcl"
PROMPT_1 = "Load the demo structure and tell me how many atoms it has"
PROMPT_2 = "Set a white background and take a snapshot"
ANSWER_1 = "The structure has 42 atoms."
ANSWER_2 = "Done: the background command failed once, then the snapshot was taken."


def _tool(call_id: str, name: str, **tool_input: str) -> Dict[str, object]:
    return {"id": call_id, "name": name, "input": tool_input}


# One entry per model turn, served in order across both requests (03_conversation
# shape: prose, a command that succeeds, a failing then recovered command, a
# snapshot and a final answer). `color` is not a command in tclsh, so tc_2 fails.
SCRIPT = [
    ("I'll count the atoms.", [_tool("tc_1", "run_vmd_command", command='set n 42\nputs "atoms: $n"',
                                     rationale="Count atoms")]),
    (ANSWER_1, []),
    ("", [_tool("tc_2", "run_vmd_command", command="color Display Background white",
                rationale="White background")]),
    ("That command is not available here; retrying.",
     [_tool("tc_3", "run_vmd_command", command="puts recovered", rationale="Retry")]),
    ("", [_tool("tc_4", "capture_vmd_snapshot", purpose="Check the view")]),
    (ANSWER_2, []),
]

_CACHE: Dict[str, Dict[str, str]] = {}


def _numbered(pattern: str, label: str, text: str) -> str:
    seen: Dict[str, str] = {}
    return re.sub(pattern, lambda m: seen.setdefault(m.group(0), f"<{label}{len(seen) + 1}>"), text)


def normalise(text: str, tmp: Path) -> str:
    """Replace what differs between runs: paths, ids, call keys, widget and image names, times."""
    for root in {str(tmp.resolve()), str(tmp)}:
        text = text.replace(root, "<TMP>")
    text = _numbered(r"chat_[0-9a-f]{12}", "CHAT", text)
    text = _numbered(r"req_[0-9a-f]+", "REQ", text)
    text = _numbered(r"\b[0-9a-f]{12}\b", "KEY", text)
    text = re.sub(r"\.vmd_ai[\w.]*", "<W>", text)
    text = re.sub(r"\bimage\d+\b", "<IMG>", text)
    text = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AP]M)?\b", "<TIME>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\s?(?:ms|s)\b", "<DUR>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\s?(?:KB|MB)\b", "<SIZE>", text)
    return text


def _run(tmp: Path) -> Dict[str, str]:
    reason = tk.tk_skip_reason() or tcl.tcl_skip_reason(needs_http=True, needs_json=True)
    if reason:
        pytest.skip(reason)
    home = tmp / "home"
    work = tmp / "proj"
    out = tmp / "out"
    # tests/conftest.py's autouse _hermetic fixture already creates tmp/"home"
    # (and points os.environ["HOME"] at it) before this fixture runs; reuse
    # that empty directory instead of failing on it.
    home.mkdir(exist_ok=True)
    work.mkdir()
    runtime = serve_runtime(home, ScriptedLoopFactory(SCRIPT))
    try:
        env = {
            "HOME": str(home),
            "VMD_AI_ATTACH": f"127.0.0.1:{runtime.port}",
            "PANEL_OUT": str(out),
            "PANEL_WORKDIR": str(work),
            "PANEL_PROMPT_1": PROMPT_1,
            "PANEL_PROMPT_2": PROMPT_2,
        }
        proc = tcl.run_tcl(tk.tk_prelude() + DRIVER.read_text(encoding="utf-8"),
                           needs_http=True, needs_json=True, env=env, timeout=120)
    finally:
        runtime.stop()
    error = out / "error.txt"
    assert not error.exists(), error.read_text(encoding="utf-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return {name: normalise((out / f"{name}.txt").read_text(encoding="utf-8"), tmp)
            for name in ("live", "replay")}


@pytest.fixture
def dumps(tmp_path):
    # Function scope keeps the hermetic conftest (HOME, keyring) active;
    # the driver runs once per session.
    if "dumps" not in _CACHE:
        _CACHE["dumps"] = _run(tmp_path)
    return _CACHE["dumps"]


def _check_golden(name: str, text: str) -> None:
    path = tk.golden_path(name)
    if tk.update_goldens():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    assert path.exists(), f"{path} is missing: run with CHATVMD_UPDATE_GOLDENS=1 and review it"
    assert text == path.read_text(encoding="utf-8")


def test_live_equals_golden(dumps):
    live = dumps["live"]
    for expected in (PROMPT_1, PROMPT_2, ANSWER_1, ANSWER_2, "recovered"):
        assert expected in live
    assert live.count(PROMPT_1) == 1 and live.count(ANSWER_2) == 1
    assert "tunnel" not in live
    _check_golden("panel_03_conversation", live)


def test_resume_replay_matches_live(dumps):
    assert dumps["replay"] == dumps["live"]
    _check_golden("panel_resume_replay", dumps["replay"])
