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
from typing import Any, Dict, Optional


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

_EMPTY_USAGE = {"input_tokens_evaluated": None, "output_tokens": None}
_EMPTY_COUNTS = {"tool_calls": 0, "rescued_calls": 0, "truncated_turns": 0, "compactions": 0}


def _utc_iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _slug(text: str, max_len: int = 40) -> str:
    s = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return s[:max_len] or "task"


def _tcl_word(s: str) -> str:
    """A single Tcl word that parses back to exactly ``s`` (M8: the old
    ``{...}`` wrapping produced invalid Tcl for a path containing an
    unbalanced brace). Brace-quoting is used whenever ``s`` has no brace at
    all — the common case, and what earlier transcripts already look like —
    since VMD 8.6's Tcl performs no substitution inside braces. Otherwise a
    backslash-escaped double-quoted word is used instead; braces need no
    escaping there, only the characters double-quoting itself is special
    about.
    """
    if "{" not in s and "}" not in s:
        return "{%s}" % s
    escaped = (
        s.replace("\\", "\\\\")
         .replace("\"", "\\\"")
         .replace("$", "\\$")
         .replace("[", "\\[")
         .replace("]", "\\]")
    )
    return "\"%s\"" % escaped


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

    def __init__(
        self,
        runs_root: Optional[Path | str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ):
        self.runs_root: Optional[Path] = (
            Path(runs_root) if runs_root is not None else None
        )
        self._current: Optional[_TaskState] = None
        # C6 product-run provenance. None keeps today's manifest exactly.
        self._meta: Optional[Dict[str, Any]] = None
        if meta is not None:
            self._meta = {
                "provenance": dict(meta),
                "usage": dict(_EMPTY_USAGE),
                "counts": dict(_EMPTY_COUNTS),
            }

    @classmethod
    def for_cwd(
        cls,
        cwd: Optional[str | Path] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "RunRecorder":
        """Build a recorder rooted at ``<cwd>/.vmdai_runs/``."""
        base = Path(cwd) if cwd is not None else Path(os.getcwd())
        return cls(base / cls.DEFAULT_DIR_NAME, meta=meta)

    def update_meta(self, **fields: Any) -> None:
        """Merge provenance fields; ``usage`` and ``counts`` update their keys.

        No-op when the recorder was built without ``meta``. Rewrites the
        manifest when a task is active, so a crash leaves the values of the
        last completed turn on disk.
        """
        if self._meta is None:
            return
        for key, value in fields.items():
            if key in ("usage", "counts"):
                merged = dict(self._meta[key])
                merged.update(dict(value or {}))
                self._meta[key] = merged
            else:
                self._meta["provenance"][key] = value
        if self._current is not None:
            self._flush_manifest(status="active")

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
        applied_text: Optional[str] = None,
        failed_index: Optional[int] = None,
        total: Optional[int] = None,
        error: Optional[str] = None,
    ) -> Optional[int]:
        """Record one ``run_vmd_command`` tool call.

        Returns the 1-based turn number on success, ``None`` if no task
        is active or the call failed (failed commands are counted in
        the manifest and never written as runnable Tcl).

        A partial failure (C3: ``ok=False`` with a non-empty
        ``applied_text``, the exact source of statements 1..applied)
        writes that applied prefix, which is still in effect in VMD,
        followed by a comment naming the failed statement and the
        unapplied rest commented out line by line. Without
        ``applied_text`` a failed call writes nothing, as before.
        """
        if self._current is None:
            return None
        self._current.turn_count += 1
        turn_n = self._current.turn_count
        self._current.last_activity_at = time.time()

        if not ok:
            self._current.failed_count += 1
            if applied_text:
                block = self._format_partial_block(
                    turn_n, command, rationale, duration_ms,
                    applied_text, failed_index, total, error,
                )
                with (self._current.dir / "transcript.tcl").open("a", encoding="utf-8") as f:
                    f.write(block)
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
        renderer: str = "snapshot",
        saved_path: Optional[str] = None,
    ) -> Optional[int]:
        """Record one ``capture_vmd_snapshot`` tool call.

        On success: save image_bytes to ``snapshots/turn_NNN.<ext>`` and
        emit a ``render <renderer> snapshots/turn_NNN.<ext>`` line to
        ``transcript.tcl`` so replay reproduces the image file. When the
        runtime also wrote a ``save_path`` deliverable, replay re-renders it
        with ``render <renderer> {<saved_path>}``. Returns the turn number.

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
        block = self._format_snapshot_block(
            turn_n, snap_name, purpose, duration_ms,
            renderer=renderer, saved_path=saved_path,
        )
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

    def _format_partial_block(
        self,
        turn_n: int,
        command: str,
        rationale: str,
        duration_ms: float,
        applied_text: str,
        failed_index: Optional[int],
        total: Optional[int],
        error: Optional[str],
    ) -> str:
        """C3: the applied prefix, then the failed/unapplied rest as comments
        (the same rule as the panel's Save .tcl export)."""
        ts = _utc_iso(time.time())
        first_error = (str(error or "").strip().splitlines() or ["error"])[0]
        idx = int(failed_index or 0)
        tot = int(total or 0)
        if idx and tot and idx < tot:
            span = f"statements {idx}–{tot} were not applied"
        elif idx:
            span = f"statement {idx} was not applied"
        else:
            span = "the rest was not applied"
        out: list[str] = []
        out.append("")
        out.append(f"# --- turn {turn_n:02d} | {ts} | {duration_ms:.0f}ms | partial ---")
        if rationale:
            for r_line in rationale.splitlines():
                out.append(f"# rationale : {r_line}")
        out.append("")
        out.append(applied_text.rstrip())
        out.append(f"# statement {idx} of {tot} failed ({first_error}); {span}:")
        rest = command[len(applied_text):] if command.startswith(applied_text) else command
        for r_line in rest.strip("\n").splitlines():
            # A trailing odd backslash would continue the comment onto the
            # next line; a following space stops that.
            if (len(r_line) - len(r_line.rstrip("\\"))) % 2 == 1:
                r_line += " "
            out.append(f"# {r_line}")
        out.append("")
        return "\n".join(out)

    def _format_snapshot_block(
        self,
        turn_n: int,
        snap_name: str,
        purpose: str,
        duration_ms: float,
        renderer: str = "snapshot",
        saved_path: Optional[str] = None,
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
        if saved_path:
            # A comment runs to end of line; collapse any embedded CR/LF so
            # a saved_path can never split it into unterminated Tcl source.
            comment_path = re.sub(r"\r\n|\r|\n", " ", saved_path)
            out.append(f"# save_path : {comment_path}")
        out.append("")
        out.append(f"render {renderer} snapshots/{snap_name}")
        if saved_path:
            out.append(f"render {renderer} {_tcl_word(saved_path)}")
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
            f"{self._provenance_header()}"
            f"#\n"
            f"# Successful commands, and the applied part of a partly failed one, "
            f"are recorded; this file is replayable:\n"
            f"#   vmd -e {s.task_id}/transcript.tcl\n"
            f"#   vmd -dispdev text -e {s.task_id}/transcript.tcl   (headless)\n"
        )
        (s.dir / "transcript.tcl").write_text(header, encoding="utf-8")

    def _provenance_header(self) -> str:
        """C6 header lines; empty without meta. The digest lives only in the
        manifest, because it may be unknown when the header is written."""
        if self._meta is None:
            return ""
        p = self._meta["provenance"]
        env = p.get("vmd_env") or {}
        vmd = " ".join(
            str(x) for x in (env.get("vmd_version"), env.get("arch")) if x
        ) or "unknown"
        tcl_tk = []
        if env.get("tcl_patchlevel"):
            tcl_tk.append(f"Tcl {env['tcl_patchlevel']}")
        if env.get("tk_patchlevel"):
            tcl_tk.append(f"Tk {env['tk_patchlevel']}")
        if tcl_tk:
            vmd += " (" + ", ".join(tcl_tk) + ")"
        provider = str(p.get("provider") or "")
        if p.get("base_url"):
            provider += f" {p['base_url']}"
        return (
            f"# provider   : {provider}\n"
            f"# runtime    : vmd_ai_runtime {p.get('runtime_version') or 'unknown'}\n"
            f"# vmd        : {vmd}\n"
            f"# provenance : see manifest.json\n"
        )

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
        if self._meta is not None:
            manifest["provenance"] = dict(self._meta["provenance"])
            manifest["usage"] = dict(self._meta["usage"])
            manifest["counts"] = dict(self._meta["counts"])
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
