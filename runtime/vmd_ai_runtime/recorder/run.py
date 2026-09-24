"""
run.py — the RunRecorder state machine.

Layout written under ``runs_root`` (typically ``<cwd>/.vmdai_runs/``):

    <task_id>/
        manifest.json     · prompt, status, counts, timestamps
        transcript.tcl    · runnable Tcl (only successful commands)
        snapshots/
            turn_03.png   · saved images, named by turn number

The recorder is intentionally *append-only* on disk: every successful
turn is flushed immediately so a VMD crash or kill-9 still leaves a
replayable partial transcript. The manifest is rewritten atomically
after each record() call so external watchers see consistent state.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------

class RunRecorderError(RuntimeError):
    """Raised on misconfiguration (no runs_root, bad task state, etc.)."""


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SAFE_EXT = ("png", "tga", "jpg", "jpeg")


def _utc_iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _slug(text: str, max_len: int = 40) -> str:
    s = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return s[:max_len] or "task"


def _atomic_write(path: Path, data: str) -> None:
    """Write ``data`` to ``path`` atomically (write-temp-then-rename).

    Necessary because external tools (or the user's editor) may read
    ``manifest.json`` while we're updating it. A partial write would
    surface as a JSON parse error mid-update.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


# ----------------------------------------------------------------------
# Internal task state
# ----------------------------------------------------------------------

@dataclass
class _TaskState:
    task_id: str
    dir: Path
    prompt: str
    model: str
    chat_id: str
    cwd: str
    started_at: float
    turn_count: int = 0
    successful_count: int = 0
    failed_count: int = 0
    snapshot_count: int = 0
    last_activity_at: float = 0.0


# ----------------------------------------------------------------------
# RunRecorder
# ----------------------------------------------------------------------

class RunRecorder:
    """Per-task transcript recorder.

    Lifecycle:
        rec = RunRecorder.for_cwd("/path/to/project")
        rec.start_task("visualize docked pose", chat_id="...", model="...")
        rec.record_vmd_command("mol new 1ubq.pdb", ok=True, duration_ms=42)
        rec.record_vmd_command("mol_color ResName", ok=False, ...)   # ignored
        rec.record_snapshot(ok=True, image_bytes=b"...", purpose="final")
        rec.end_task(status="complete")
    """

    DEFAULT_DIR_NAME = ".vmdai_runs"

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, runs_root: Optional[Path | str] = None):
        self.runs_root: Optional[Path] = (
            Path(runs_root) if runs_root is not None else None
        )
        self._current: Optional[_TaskState] = None

    @classmethod
    def for_cwd(cls, cwd: Optional[str | Path] = None) -> "RunRecorder":
        """Build a recorder rooted at ``<cwd>/.vmdai_runs/``."""
        base = Path(cwd) if cwd is not None else Path(os.getcwd())
        return cls(base / cls.DEFAULT_DIR_NAME)

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def current_task_id(self) -> Optional[str]:
        return self._current.task_id if self._current else None

    @property
    def current_task_dir(self) -> Optional[Path]:
        return self._current.dir if self._current else None

    @property
    def is_active(self) -> bool:
        return self._current is not None

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def start_task(
        self,
        prompt: str,
        *,
        chat_id: str = "",
        model: str = "",
        cwd: Optional[str] = None,
    ) -> str:
        """Begin a new task; supersede any active task (status='superseded').

        Returns the new task_id (string), which is also the directory
        name under ``runs_root``.
        """
        if self.runs_root is None:
            raise RunRecorderError(
                "RunRecorder has no runs_root; "
                "use RunRecorder.for_cwd(...) or pass runs_root=..."
            )
        if self._current is not None:
            self.end_task(status="superseded")

        t = time.time()
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(t))
        slug = _slug(prompt)
        suffix = uuid.uuid4().hex[:6]
        task_id = f"{stamp}-{suffix}_{slug}" if slug else f"{stamp}-{suffix}"
        task_dir = self.runs_root / task_id
        task_dir.mkdir(parents=True, exist_ok=False)
        (task_dir / "snapshots").mkdir(exist_ok=True)

        state = _TaskState(
            task_id=task_id,
            dir=task_dir,
            prompt=prompt or "",
            model=model,
            chat_id=chat_id,
            cwd=cwd or os.getcwd(),
            started_at=t,
            last_activity_at=t,
        )
        self._current = state

        # Initial files: transcript header + manifest.
        self._write_tcl_header()
        self._flush_manifest(status="active")
        return task_id

    def end_task(self, status: str = "complete") -> Optional[str]:
        """End the current task; rewrite manifest with the final status.

        Returns the ended task_id, or None if no task was active.
        Idempotent: calling twice in a row is a no-op on the second call.
        """
        if self._current is None:
            return None
        task_id = self._current.task_id
        self._flush_manifest(status=status, ended=True)
        self._current = None
        return task_id

    # ------------------------------------------------------------------
    # Recording — VMD Tcl command
    # ------------------------------------------------------------------

    def record_vmd_command(
        self,
        command: str,
        *,
        ok: bool,
        rationale: str = "",
        duration_ms: float = 0.0,
    ) -> Optional[int]:
        """Record one ``run_vmd_command`` tool call.

        Returns the 1-based turn number on success, ``None`` if no task
        is active or the call failed (failed commands are counted in
        the manifest but never written to transcript.tcl).
        """
        if self._current is None:
            return None
        self._current.turn_count += 1
        turn_n = self._current.turn_count
        self._current.last_activity_at = time.time()

        if not ok:
            self._current.failed_count += 1
            self._flush_manifest(status="active")
            return None

        self._current.successful_count += 1
        block = self._format_command_block(turn_n, command, rationale, duration_ms)
        with (self._current.dir / "transcript.tcl").open("a", encoding="utf-8") as f:
            f.write(block)
        self._flush_manifest(status="active")
        return turn_n

    # ------------------------------------------------------------------
    # Recording — snapshot
    # ------------------------------------------------------------------

    def record_snapshot(
        self,
        *,
        ok: bool,
        purpose: str = "",
        image_bytes: Optional[bytes] = None,
        image_ext: str = "png",
        duration_ms: float = 0.0,
    ) -> Optional[int]:
        """Record one ``capture_vmd_snapshot`` tool call.

        On success: save image_bytes to ``snapshots/turn_NN.<ext>`` and
        emit a ``render snapshot snapshots/turn_NN.<ext>`` line to
        ``transcript.tcl`` so replay reproduces the image file. Returns
        the turn number.

        On failure: count it and return None.
        """
        if self._current is None:
            return None
        self._current.turn_count += 1
        turn_n = self._current.turn_count
        self._current.last_activity_at = time.time()

        if not ok:
            self._current.failed_count += 1
            self._flush_manifest(status="active")
            return None

        ext = (image_ext or "png").lower().lstrip(".")
        if ext not in _SAFE_EXT:
            ext = "png"
        snap_name = f"turn_{turn_n:03d}.{ext}"

        if image_bytes is not None:
            (self._current.dir / "snapshots" / snap_name).write_bytes(image_bytes)

        self._current.successful_count += 1
        self._current.snapshot_count += 1
        block = self._format_snapshot_block(turn_n, snap_name, purpose, duration_ms)
        with (self._current.dir / "transcript.tcl").open("a", encoding="utf-8") as f:
            f.write(block)
        self._flush_manifest(status="active")
        return turn_n

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def _format_command_block(
        self,
        turn_n: int,
        command: str,
        rationale: str,
        duration_ms: float,
    ) -> str:
        ts = _utc_iso(time.time())
        # Header marker, comment rationale (multi-line safe), then the
        # raw Tcl. A trailing blank line keeps adjacent blocks readable.
        out: list[str] = []
        out.append("")
        out.append(f"# --- turn {turn_n:02d} | {ts} | {duration_ms:.0f}ms ---")
        if rationale:
            for r_line in rationale.splitlines():
                out.append(f"# rationale : {r_line}")
        out.append("")
        out.append(command.rstrip())
        out.append("")
        return "\n".join(out)

    def _format_snapshot_block(
        self,
        turn_n: int,
        snap_name: str,
        purpose: str,
        duration_ms: float,
    ) -> str:
        ts = _utc_iso(time.time())
        out: list[str] = []
        out.append("")
        out.append(
            f"# --- turn {turn_n:02d} | {ts} | {duration_ms:.0f}ms | snapshot ---"
        )
        if purpose:
            for p_line in purpose.splitlines():
                out.append(f"# purpose   : {p_line}")
        out.append(f"# saved to  : snapshots/{snap_name}")
        out.append("")
        out.append(f"render snapshot snapshots/{snap_name}")
        out.append("")
        return "\n".join(out)

    def _write_tcl_header(self) -> None:
        if self._current is None:
            return
        s = self._current
        prompt_one_line = " ".join(s.prompt.split())[:200]
        header = (
            f"# VMD AI transcript\n"
            f"# task_id    : {s.task_id}\n"
            f"# started_at : {_utc_iso(s.started_at)}\n"
            f"# chat_id    : {s.chat_id}\n"
            f"# model      : {s.model}\n"
            f"# cwd        : {s.cwd}\n"
            f"# prompt     : {prompt_one_line}\n"
            f"#\n"
            f"# Only successful commands are recorded; this file is replayable:\n"
            f"#   vmd -e {s.task_id}/transcript.tcl\n"
            f"#   vmd -dispdev text -e {s.task_id}/transcript.tcl   (headless)\n"
        )
        (s.dir / "transcript.tcl").write_text(header, encoding="utf-8")

    # ------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------

    def _flush_manifest(self, *, status: str, ended: bool = False) -> None:
        if self._current is None:
            return
        s = self._current
        manifest = {
            "task_id": s.task_id,
            "status": status,
            "prompt": s.prompt,
            "chat_id": s.chat_id,
            "model": s.model,
            "cwd": s.cwd,
            "started_at": _utc_iso(s.started_at),
            "last_activity_at": _utc_iso(s.last_activity_at),
            "turn_count": s.turn_count,
            "successful_count": s.successful_count,
            "failed_count": s.failed_count,
            "snapshot_count": s.snapshot_count,
        }
        if ended:
            manifest["ended_at"] = _utc_iso(time.time())
        _atomic_write(
            s.dir / "manifest.json",
            json.dumps(manifest, indent=2, sort_keys=True),
        )

    # ------------------------------------------------------------------
    # Convenience helpers (used by tests)
    # ------------------------------------------------------------------

    def read_transcript(self, task_id: str) -> str:
        """Return the full transcript.tcl content for ``task_id``."""
        if self.runs_root is None:
            raise RunRecorderError("RunRecorder has no runs_root")
        return (self.runs_root / task_id / "transcript.tcl").read_text(
            encoding="utf-8"
        )

    def read_manifest(self, task_id: str) -> dict:
        """Return the manifest dict for ``task_id``."""
        if self.runs_root is None:
            raise RunRecorderError("RunRecorder has no runs_root")
        return json.loads(
            (self.runs_root / task_id / "manifest.json").read_text(encoding="utf-8")
        )

    def list_tasks(self) -> list[str]:
        """Return all task_ids under ``runs_root``, oldest first."""
        if self.runs_root is None or not self.runs_root.exists():
            return []
        return sorted(p.name for p in self.runs_root.iterdir() if p.is_dir())
