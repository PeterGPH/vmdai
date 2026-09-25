"""Snapshot of the opt-in live-test gates, taken once at import time.

tests/conftest.py imports this module before any fixture runs, so the
values reflect the shell that launched pytest.  The autouse ``_hermetic``
fixture then clears every ``VMD_AI_*`` variable for each test; live tests
read their gates only through the ``live_env`` fixture, which returns
``LIVE_ENV``.
"""
from __future__ import annotations

import os
from typing import Dict, Tuple

LIVE_GATES: Tuple[str, ...] = (
    "VMD_AI_LIVE_OLLAMA",
    "VMD_AI_LIVE_MODEL",
    "VMD_AI_VMD_BIN",
    "VMD_AI_TCLSH",
    "VMD_AI_TCL_TM",
    "VMD_AI_TK_LIB",
)

LIVE_ENV: Dict[str, str] = {
    name: os.environ[name] for name in LIVE_GATES if os.environ.get(name)
}
