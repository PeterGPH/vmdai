"""Direct contract test of tests/helpers/tk.py (moved from P06-T10's
tests/test_tk_ui_min.py when P09-T07 retired the M1 ui.tcl)."""
from __future__ import annotations

from helpers import tk
from helpers.tcl import REPO


def test_tk_helper_contract(monkeypatch):
    assert tk.golden_path("x") == REPO / "tests" / "fixtures" / "tk" / "x.txt"
    assert "load " in tk.tk_prelude() and " Tk\n" in tk.tk_prelude()
    assert tk.tk_prelude().endswith("wm withdraw .\n")
    monkeypatch.setenv("CHATVMD_UPDATE_GOLDENS", "1")
    assert tk.update_goldens() is True
    monkeypatch.delenv("CHATVMD_UPDATE_GOLDENS")
    assert tk.update_goldens() is False
