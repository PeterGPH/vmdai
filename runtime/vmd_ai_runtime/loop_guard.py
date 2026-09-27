"""
loop_guard.py - stop a request when the model repeats one call (spec C4).

Adapted (not ported) from PyMolAI's ``modules/pymol/ai/doom_loop_detector.py``.
That file's command-family rule keys on the tool name for every tool except
``run_pymol_command``, so it would fire after any three ``run_vmd_command``
calls; round 1 keeps only the exact-repeat triggers:

  (a) the same signature with ``ok: false`` 3 times in a row;
  (b) the same signature with ``ok: true`` and the same first 200 characters
      of output 4 times in a row (``capture_vmd_snapshot`` is exempt from b).

The first trigger returns ``"nudge"``; the streak is NOT reset, so the next
identical call returns ``"stop"``. A call with a different signature resets
the streak. Stdlib-only and Python 3.9-compatible.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

FAILURE_LIMIT = 3
SUCCESS_LIMIT = 4
SNAPSHOT_TOOL = "capture_vmd_snapshot"

NUDGE_TEXT_TEMPLATE = (
    "Loop check: this exact call has now run {n} times with the same result. "
    "Do not repeat it; change the command, or stop and explain the problem to the user."
)

_WS_RUN = re.compile(r"\s+")


def signature(tool_name: str, tool_input: Dict[str, Any],
              result: Dict[str, Any]) -> Tuple[str, str, bool, str]:
    """(tool name, canonical input without rationale, ok, first 200 chars of error)."""
    data = dict(tool_input or {})
    data.pop("rationale", None)
    command = data.get("command")
    if isinstance(command, str):
        data["command"] = _WS_RUN.sub(" ", command).strip()
    canonical = json.dumps(data, sort_keys=True, default=str)
    ok = bool((result or {}).get("ok", False))
    error = str((result or {}).get("error") or "")[:200]
    return (str(tool_name or ""), canonical, ok, error)


class LoopGuard:
    """Observe every tool result of one request; say when to nudge or stop."""

    def __init__(self) -> None:
        self._last: Optional[Tuple[Tuple[str, str, bool, str], str]] = None
        self._streak = 0
        self._nudged = False

    @property
    def streak(self) -> int:
        return self._streak

    def observe(self, tool_name: str, tool_input: Dict[str, Any],
                result: Dict[str, Any]) -> Optional[str]:
        """Record one result. Returns None, ``"nudge"`` or ``"stop"``."""
        sig = signature(tool_name, tool_input, result)
        output = str((result or {}).get("output") or "")[:200] if sig[2] else ""
        key = (sig, output)
        if key == self._last:
            self._streak += 1
        else:
            self._last = key
            self._streak = 1
            self._nudged = False
        if sig[2]:
            if sig[0] == SNAPSHOT_TOOL:
                return None
            limit = SUCCESS_LIMIT
        else:
            limit = FAILURE_LIMIT
        if self._streak < limit:
            return None
        if not self._nudged:
            self._nudged = True
            return "nudge"
        return "stop"
