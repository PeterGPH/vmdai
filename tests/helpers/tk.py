"""Tk tests under tclsh 8.6 with VMD.app's Tk (spec §6 "Tk golden transcripts").

The prelude loads Tk the way docs/design/round1/tools/vmdtk_run.tcl does:
``set ::tk_library …/Tk.framework/Versions/8.6/Resources/Scripts`` and then
``load …/Tk.framework/Versions/8.6/Tk Tk``. ``VMD_AI_TK_LIB`` (from the
live_env snapshot) names another Tk shared library to load instead; Tk then
finds its own script library. Aqua has no DISPLAY, so whether Tk works is
decided by a probe subprocess that must load Tk and exit within 10 s; without
a GUI login session (ssh, launchd, CI) it fails and every Tk test skips.
Tests take no screenshots. Goldens live in tests/fixtures/tk/<name>.txt and
are rewritten only when CHATVMD_UPDATE_GOLDENS=1.
"""
from __future__ import annotations

import functools
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

import pytest

from helpers.live import LIVE_ENV
from helpers.tcl import REPO, TclTestResult, find_tclsh, run_tcltest, tcl_skip_reason, tcl_word

VMD_TK_FRAMEWORK = "/Applications/VMD.app/Contents/Frameworks/Tk.framework/Versions/8.6"
GOLDEN_DIR = REPO / "tests" / "fixtures" / "tk"
PROBE_TIMEOUT_S = 10


def tk_prelude() -> str:
    """Tcl that loads Tk into a plain tclsh and hides the root window."""
    override = LIVE_ENV.get("VMD_AI_TK_LIB")
    if override:
        lines = [f"load {tcl_word(override)} Tk"]
    else:
        lines = [
            f"set ::tk_library {tcl_word(VMD_TK_FRAMEWORK + '/Resources/Scripts')}",
            f"load {tcl_word(VMD_TK_FRAMEWORK + '/Tk')} Tk",
        ]
    lines.append("wm withdraw .")
    return "".join(line + "\n" for line in lines)


@functools.lru_cache(maxsize=None)
def tk_skip_reason() -> Optional[str]:
    """Why Tk tests can't run here, or None when they can."""
    reason = tcl_skip_reason()
    if reason is not None:
        return reason
    library = LIVE_ENV.get("VMD_AI_TK_LIB") or VMD_TK_FRAMEWORK + "/Tk"
    if not Path(library).exists():
        return f"no Tk library at {library}: install VMD.app or set VMD_AI_TK_LIB"
    with tempfile.TemporaryDirectory(prefix="vmdai_tk_") as tmp:
        probe = os.path.join(tmp, "probe.tcl")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write(tk_prelude() + "exit 0\n")
        try:
            proc = subprocess.run([find_tclsh(), probe], capture_output=True, text=True,
                                  timeout=PROBE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return f"Tk did not load within {PROBE_TIMEOUT_S} s (no GUI session?)"
    if proc.returncode != 0:
        return f"Tk could not be loaded (no GUI session?): {proc.stderr.strip()[-200:]}"
    return None


def run_tk_test(test_file: str, *, env: Optional[Dict[str, str]] = None,
                timeout: int = 120) -> TclTestResult:
    """run_tcltest with Tk loaded first; skips when Tk is unavailable."""
    reason = tk_skip_reason()
    if reason is not None:
        pytest.skip(reason)
    return run_tcltest(test_file, env=env, timeout=timeout, prelude=tk_prelude())


def update_goldens() -> bool:
    return os.environ.get("CHATVMD_UPDATE_GOLDENS") == "1"


def golden_path(name: str) -> Path:
    return GOLDEN_DIR / f"{name}.txt"
