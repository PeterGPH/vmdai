"""
subprocess_vmd_bridge.py — headless VMD tool bridge backed by your *native*
VMD.app, driven as a persistent ``vmd -dispdev text`` process **through a
pseudo-terminal (pty)**.

Why a pty: VMD is an interactive Tcl/Tk console app. When its stdin/stdout are
plain pipes (not a terminal) it block-buffers stdout and may not read stdin as a
console — so a naive pipe driver hangs. A pty makes VMD behave exactly as it
does in a real terminal: it reads "typed" commands and line-buffers output.
(Unix/macOS only — which is your platform.)

No new install: uses the VMD binary you already have. Because it is full VMD,
``render TachyonInternal`` works, so snapshots are real images.

Interface (duck-typed stand-in for the runtime's VmdToolBridge):

    execute_tool(tool_name=..., tool_input=..., cancel_event=..., **_) -> {ok, output, error}
    reset()    # clear molecules between tasks
    close()    # terminate the VMD process

Per tool call we wrap the model's Tcl in ``catch`` (so a Tcl error never breaks
the stream), print sentinel markers, and read the pty until the DONE marker.
``puts`` output lands before the markers, so the model still sees what it printed.
"""
from __future__ import annotations

import base64
import contextlib
import os
import pty
import select
import shutil
import subprocess
import tempfile
import termios
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_RC = "@@VMDAI_RC@@"
_MB = "@@VMDAI_MSG_BEGIN@@"
_ME = "@@VMDAI_MSG_END@@"
_DONE = "@@VMDAI_DONE@@"
_PROMPT = "vmd >"
_MAX_TOOL_OUTPUT_CHARS = 6000   # cap tool_result size so verbose VMD output can't flood context


class _VmdTimeout(RuntimeError):
    pass


def _has_scripts(d: str) -> bool:
    return (Path(d) / "scripts" / "vmd" / "atomselmacros.dat").exists()


def _resolve_vmd(vmd_bin: Optional[str]) -> Tuple[str, Optional[str]]:
    """Return (binary, VMDDIR-or-None). Explicit override -> PATH binary with
    scripts alongside -> macOS app bundle (with injected VMDDIR)."""
    cand = vmd_bin or os.environ.get("VMD_AI_VMD_BIN") or os.environ.get("VMDBENCH_VMD_BIN")
    if cand:
        if not Path(cand).exists():
            raise RuntimeError(f"VMD binary {cand!r} does not exist")
        parent = str(Path(cand).parent)
        return cand, (parent if _has_scripts(parent) else None)

    onpath = shutil.which(vmd_bin or "vmd")
    if onpath and _has_scripts(str(Path(onpath).parent)):
        return onpath, None

    app = Path("/Applications/VMD.app/Contents/vmd")
    if app.exists():
        for b in sorted(app.glob("vmd_MACOSX*")):
            if os.access(b, os.X_OK):
                return str(b), str(app)
    if onpath:
        return onpath, None
    raise RuntimeError(
        "No VMD binary found. Set VMD_AI_VMD_BIN to your vmd_MACOSXARM64 "
        "(e.g. /Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64)."
    )


class SubprocessVmdBridge:
    def __init__(self, vmd_bin: Optional[str] = None, timeout: int = 120):
        self._bin, self._vmddir = _resolve_vmd(vmd_bin)
        self._timeout = int(timeout)
        self._proc: Optional[subprocess.Popen] = None
        self._master_fd: Optional[int] = None
        self._buf = b""
        self._imbalance_streak = 0        # consecutive brace-imbalance rejections (anti-thrash)
        self._series = {}                 # per-task named per-frame series for vmd_compute

    # ------------------------------------------------------------- lifecycle
    def _start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        master_fd, slave_fd = pty.openpty()
        # Disable echo on the slave so the commands we write aren't echoed back
        # into the output stream we read.
        with contextlib.suppress(Exception):
            attrs = termios.tcgetattr(slave_fd)
            attrs[3] = attrs[3] & ~termios.ECHO          # lflags &= ~ECHO
            termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

        env = dict(os.environ)
        if self._vmddir:
            env["VMDDIR"] = self._vmddir

        self._proc = subprocess.Popen(
            [self._bin, "-dispdev", "text"],
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            env=env, close_fds=True,
        )
        os.close(slave_fd)
        self._master_fd = master_fd
        self._buf = b""
        # Consume the startup banner via the protocol; fail fast if mis-set.
        self._exec_wrapped("set __vbai_ready 1", timeout=min(self._timeout, 45))

    def reset(self) -> None:
        self._start()
        self._exec_wrapped("foreach __m [molinfo list] { mol delete $__m }",
                           timeout=self._timeout)
        with contextlib.suppress(Exception):
            self._exec_wrapped("display resetview", timeout=30)
        self._series = {}

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            with contextlib.suppress(Exception):
                os.write(self._master_fd, b"quit\n")
            with contextlib.suppress(Exception):
                self._proc.wait(timeout=5)
            with contextlib.suppress(Exception):
                self._proc.kill()
        if self._master_fd is not None:
            with contextlib.suppress(Exception):
                os.close(self._master_fd)
        self._master_fd = None
        self._proc = None

    # ------------------------------------------------------------ tool entry
    def execute_tool(self, *, tool_name: str = "", tool_input: Optional[Dict[str, Any]] = None,
                     cancel_event: Optional[Any] = None, **_: Any) -> Dict[str, Any]:
        tool_input = tool_input or {}
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            return {"ok": False, "output": "", "error": "cancelled"}
        try:
            self._start()
            if tool_name == "run_vmd_command":
                return self._run_tcl(str(tool_input.get("command") or ""))
            if tool_name == "capture_vmd_snapshot":
                return self._snapshot(str(tool_input.get("purpose") or ""),
                                      tool_input.get("save_path"))
            if tool_name == "vmd_measure":
                return self._measure(tool_input)
            if tool_name == "vmd_traj_measure":
                return self._traj_measure(tool_input)
            if tool_name == "vmd_traj_series":
                return self._traj_series(tool_input)
            if tool_name == "vmd_compute":
                return self._compute(tool_input)
            if tool_name == "vmd_represent":
                return self._represent(tool_input)
            return {"ok": False, "output": "", "error": f"unsupported tool {tool_name!r}"}
        except _VmdTimeout as exc:
            self.close()  # restart fresh on the next call
            return {"ok": False, "output": "", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "output": "", "error": str(exc)}

    # -------------------------------------------------------------- internals
    def _run_tcl(self, command: str) -> Dict[str, Any]:
        command = command.strip()
        if not command:
            return {"ok": False, "output": "", "error": "empty command"}
        # Reject syntactically incomplete Tcl (unbalanced braces/brackets/quotes) BEFORE
        # sending it — otherwise the interpreter waits for more input and the bridge hangs
        # until timeout (the recurring `{x y z]` / mismatched-bracket failure).
        imb = _imbalance(command)
        if imb:
            # Track consecutive rejections: a weak model can thrash the same unbalanced loop for
            # its whole budget (the 2erl meansasa=None failure — ~12 identical rejections, no
            # answer). After the 2nd strike, redirect it to the tool that authors the loop itself.
            self._imbalance_streak = getattr(self, "_imbalance_streak", 0) + 1
            err = (f"incomplete Tcl — {imb}. NOT executed (an unbalanced command hangs the "
                   "interpreter). Resend the ENTIRE command on one line with every {} and [] "
                   "matched — e.g. a whole loop `for {set i 0} {$i<$n} {incr i} { ... }` in one call.")
            if self._imbalance_streak >= 2:
                err += (" You have hit this repeatedly — STOP hand-writing this loop and call "
                        "vmd_traj_measure (over-all-frames) or vmd_measure (single value) instead; "
                        "they run the correct, brace-balanced Tcl for you.")
            return {"ok": False, "output": "", "error": err}
        self._imbalance_streak = 0            # a well-formed command clears the streak
        printed, rc, msg = self._exec_wrapped(command, timeout=self._timeout)
        printed = _strip_noise(printed)
        if rc == 0:
            parts = [p for p in (printed.rstrip("\n"), msg.strip()) if p.strip()]
            return {"ok": True, "output": _truncate("\n".join(parts) or "(command ok, no output)"), "error": ""}
        return {"ok": False, "output": _truncate(printed.rstrip("\n")), "error": _truncate(msg.strip()) or "Tcl error"}

    def _snapshot(self, purpose: str, save_path: Optional[str] = None) -> Dict[str, Any]:
        out = os.path.join(tempfile.gettempdir(),
                           f"vmdai_snap_{os.getpid()}_{int(time.time() * 1000)}.tga")
        with contextlib.suppress(Exception):
            if os.path.exists(out):
                os.unlink(out)
        _printed, _rc, msg = self._exec_wrapped(
            "display update\nrender TachyonInternal {" + out + "}", timeout=self._timeout
        )
        result: Dict[str, Any] = {"ok": True, "error": ""}
        if os.path.isfile(out) and os.path.getsize(out) > 1000:
            png = _to_png_bytes(out)
            if png:
                result["image_b64"] = base64.b64encode(png).decode()
                result["image_mime"] = "image/png"   # Anthropic rejects image/x-tga
                note = f"Snapshot rendered ({purpose or 'viewport'})."
                if save_path:
                    saved = _persist_image(png, str(save_path))
                    note += f" Saved to {saved}." if saved else f" (FAILED to save to {save_path})."
                result["output"] = note
            else:
                result["output"] = (f"Snapshot rendered to {out}, but TGA->PNG conversion "
                                    "was unavailable (pip install pillow).")
            with contextlib.suppress(Exception):
                os.unlink(out)
        else:
            result["output"] = "Snapshot attempted; no image produced. " + (msg.strip() or "")
        return result

    # ---- semantic tools: the harness writes the correct Tcl so the model can't ----
    _METRIC_TCL = {
        "rgyr":      ('set __s [atomselect top "{sel}"]; set __v [measure rgyr $__s]; $__s delete', True),
        "sasa":      ('set __s [atomselect top "{sel}"]; set __v [measure sasa 1.4 $__s]; $__s delete', True),
        "natoms":    ('set __v [molinfo top get numatoms]', False),
        "nresidues": ('set __s [atomselect top "{sel}"]; set __v [llength [lsort -unique [$__s get residue]]]; $__s delete', True),
        "ca_dist":   ('set __s [atomselect top "{sel} and name CA"]; set __i [$__s get index]; $__s delete; '
                      'set __v [measure bond [list [lindex $__i 0] [lindex $__i end]]]', True),
        "rmsd_self": ('set __s [atomselect top "{sel}"]; set __v [measure rmsd $__s $__s]; $__s delete', True),
    }

    def _measure(self, ti: Dict[str, Any]) -> Dict[str, Any]:
        metric = str(ti.get("metric") or "").strip()
        sel = str(ti.get("selection") or "protein").strip()
        if metric not in self._METRIC_TCL:
            return {"ok": False, "output": "",
                    "error": f"unknown metric {metric!r}; choose from {sorted(self._METRIC_TCL)}"}
        body, uses_sel = self._METRIC_TCL[metric]
        tcl = (body.format(sel=sel) if uses_sel else body) + '\nputs "VMDAI_VALUE=$__v"'
        res = self._run_tcl(tcl)
        res["tcl"] = tcl                    # record the executed Tcl for the reproducible transcript
        if not res.get("ok"):
            return res
        import re as _re
        val = None
        for line in str(res.get("output") or "").splitlines():
            m = _re.search(r"VMDAI_VALUE=\s*([-+0-9.eE]+)", line)
            if m:
                val = m.group(1)
        if val is None:
            return {"ok": False, "output": res.get("output", ""), "error": "could not read measured value"}
        note = f"{metric}({sel}) = {val}"
        save = ti.get("save_path")
        if save:
            try:
                p = os.path.abspath(str(save))
                os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
                with open(p, "w") as fh:
                    fh.write(str(val) + "\n")
                note += f"  (written to {p})"
            except Exception as exc:  # noqa: BLE001
                note += f"  (FAILED to write {save}: {exc})"
        return {"ok": True, "output": note, "error": "", "value": val, "tcl": tcl}

    # ---- trajectory semantic tool: harness authors the frame-loop Tcl (brace-heavy, so it
    # would be corrupted if the MODEL had to emit it through the tool-call transport). The
    # bodies mirror gold_oracle_traj.tcl exactly. `@SEL@` is substituted via str.replace (NOT
    # .format — Tcl is full of literal {}). Each body sets $__v; the loader prefix loads a fresh
    # structure+trajectory so a failed model load (the `nframes=0` bug) can't happen either.
    _TRAJ_TCL = {
        "nframes":  'set __v [molinfo top get numframes]',
        "meanrg":   ('set __p [atomselect top "@SEL@"]; set __n [molinfo top get numframes]; set __g 0.0; '
                     'for {set __i 0} {$__i < $__n} {incr __i} { $__p frame $__i; set __g [expr {$__g + [measure rgyr $__p]}] }; '
                     'set __v [expr {$__g / $__n}]; $__p delete'),
        "meansasa": ('set __p [atomselect top "@SEL@"]; set __n [molinfo top get numframes]; set __sa 0.0; '
                     'for {set __i 0} {$__i < $__n} {incr __i} { $__p frame $__i; set __sa [expr {$__sa + [measure sasa 1.4 $__p]}] }; '
                     'set __v [expr {$__sa / $__n}]; $__p delete'),
        "meanrmsd": ('set __ca [atomselect top "@SEL@ and name CA"]; set __ref [atomselect top "@SEL@ and name CA" frame 0]; '
                     'set __all [atomselect top all]; set __n [molinfo top get numframes]; set __r 0.0; '
                     'for {set __i 0} {$__i < $__n} {incr __i} { $__ca frame $__i; $__all frame $__i; $__all move [measure fit $__ca $__ref]; '
                     'set __r [expr {$__r + [measure rmsd $__ca $__ref]}] }; '
                     'set __v [expr {$__r / $__n}]; $__ca delete; $__ref delete; $__all delete'),
        "mean_rmsf": ('set __ca [atomselect top "@SEL@ and name CA"]; set __ref [atomselect top "@SEL@ and name CA" frame 0]; '
                      'set __all [atomselect top all]; set __n [molinfo top get numframes]; '
                      'for {set __i 0} {$__i < $__n} {incr __i} { $__ca frame $__i; $__all frame $__i; $__all move [measure fit $__ca $__ref] }; '
                      'set __f [measure rmsf $__ca]; set __sm 0.0; foreach __x $__f { set __sm [expr {$__sm + $__x}] }; '
                      'set __v [expr {$__sm / [llength $__f]}]; $__ca delete; $__ref delete; $__all delete'),
    }

    def _traj_measure(self, ti: Dict[str, Any]) -> Dict[str, Any]:
        metric = str(ti.get("metric") or "").strip()
        sel = str(ti.get("selection") or "protein").strip()
        struct = str(ti.get("structure") or "").strip()
        traj = str(ti.get("trajectory") or "").strip()
        if metric not in self._TRAJ_TCL:
            return {"ok": False, "output": "",
                    "error": f"unknown metric {metric!r}; choose from {sorted(self._TRAJ_TCL)}"}
        if not struct or not traj:
            return {"ok": False, "output": "", "error": "vmd_traj_measure needs both 'structure' and 'trajectory' paths"}
        if not os.path.exists(struct) or not os.path.exists(traj):
            return {"ok": False, "output": "", "error": f"file not found: structure={struct!r} trajectory={traj!r}"}
        body = self._TRAJ_TCL[metric].replace("@SEL@", sel)
        # fresh load (own molecule) + the metric body + emit — all harness-authored, always balanced.
        tcl = (f'mol new "{struct}" waitfor all\n'
               f'mol addfile "{traj}" waitfor all\n'
               f'{body}\nputs "VMDAI_VALUE=$__v"')
        res = self._run_tcl(tcl)
        res["tcl"] = tcl                    # record the executed Tcl for the reproducible transcript
        if not res.get("ok"):
            return res
        import re as _re
        val = None
        for line in str(res.get("output") or "").splitlines():
            m = _re.search(r"VMDAI_VALUE=\s*([-+0-9.eE]+)", line)
            if m:
                val = m.group(1)
        if val is None:
            return {"ok": False, "output": res.get("output", ""), "error": "could not read measured value"}
        note = f"{metric}({sel}) over trajectory = {val}"
        save = ti.get("save_path")
        if save:
            try:
                p = os.path.abspath(str(save))
                os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
                with open(p, "w") as fh:
                    fh.write(str(val) + "\n")
                note += f"  (written to {p})"
            except Exception as exc:  # noqa: BLE001
                note += f"  (FAILED to write {save}: {exc})"
        return {"ok": True, "output": note, "error": "", "value": val, "tcl": tcl}

    # ---- per-frame series tool: fetches the RAW per-frame values so the model can reduce
    # them freely with vmd_compute (max/min/std/argmin/...) instead of being limited to the
    # fixed reductions baked into _TRAJ_TCL. Selections mirror gold_oracle_traj_hard.tcl EXACTLY
    # (protein for rgyr/sasa; protein and name CA aligned to frame 0 for rmsd/rmsf) so that a
    # reduction over the fetched series equals the corresponding hard-gold value.
    _SERIES_TCL = {
        "rgyr": ('set __p [atomselect top "protein"]; set __n [molinfo top get numframes]; '
                 'for {set __i 0} {$__i < $__n} {incr __i} { $__p frame $__i; '
                 'puts "VMDAI_SERIES [measure rgyr $__p]" }; $__p delete; puts "VMDAI_SERIES_N $__n"'),
        "sasa": ('set __p [atomselect top "protein"]; set __n [molinfo top get numframes]; '
                 'for {set __i 0} {$__i < $__n} {incr __i} { $__p frame $__i; '
                 'puts "VMDAI_SERIES [measure sasa 1.4 $__p]" }; $__p delete; puts "VMDAI_SERIES_N $__n"'),
        "rmsd_to_frame0": (
            'set __ca [atomselect top "protein and name CA"]; set __ref [atomselect top "protein and name CA" frame 0]; '
            'set __all [atomselect top all]; set __n [molinfo top get numframes]; '
            'for {set __i 0} {$__i < $__n} {incr __i} { $__ca frame $__i; $__all frame $__i; '
            '$__all move [measure fit $__ca $__ref]; puts "VMDAI_SERIES [measure rmsd $__ca $__ref]" }; '
            '$__ca delete; $__ref delete; $__all delete; puts "VMDAI_SERIES_N $__n"'),
        "rmsf_per_residue": (
            'set __ca [atomselect top "protein and name CA"]; set __ref [atomselect top "protein and name CA" frame 0]; '
            'set __all [atomselect top all]; set __n [molinfo top get numframes]; '
            'for {set __i 0} {$__i < $__n} {incr __i} { $__ca frame $__i; $__all frame $__i; '
            '$__all move [measure fit $__ca $__ref] }; '
            'set __rf [measure rmsf $__ca]; foreach __x $__rf { puts "VMDAI_SERIES $__x" }; '
            'puts "VMDAI_SERIES_N [llength $__rf]"; $__ca delete; $__ref delete; $__all delete'),
    }
    _SERIES_NAME = {"rgyr": "rgyr", "sasa": "sasa", "rmsd_to_frame0": "rmsd", "rmsf_per_residue": "rmsf"}

    def _traj_series(self, ti: Dict[str, Any]) -> Dict[str, Any]:
        quantity = str(ti.get("quantity") or "").strip()
        struct = str(ti.get("structure") or "").strip()
        traj = str(ti.get("trajectory") or "").strip()
        if quantity not in self._SERIES_TCL:
            return {"ok": False, "output": "", "error": f"unknown quantity {quantity!r}; choose from {sorted(self._SERIES_TCL)}"}
        if not struct or not traj:
            return {"ok": False, "output": "", "error": "vmd_traj_series needs both 'structure' and 'trajectory' paths"}
        if not os.path.exists(struct) or not os.path.exists(traj):
            return {"ok": False, "output": "", "error": f"file not found: structure={struct!r} trajectory={traj!r}"}
        tcl = (f'mol new "{struct}" waitfor all\n'
               f'mol addfile "{traj}" waitfor all\n'
               f'{self._SERIES_TCL[quantity]}')
        res = self._run_tcl(tcl)
        res["tcl"] = tcl
        if not res.get("ok"):
            return res
        import re as _re
        vals = []
        expected = None
        for line in str(res.get("output") or "").splitlines():
            mn = _re.search(r"VMDAI_SERIES_N\s+(\d+)", line)
            if mn:
                expected = int(mn.group(1)); continue
            m = _re.search(r"VMDAI_SERIES\s+([-+0-9.eE]+)", line)
            if m:
                try: vals.append(float(m.group(1)))
                except ValueError: pass
        if not vals:
            return {"ok": False, "output": res.get("output", ""), "error": "no series values emitted"}
        if expected is None or len(vals) != expected:
            return {"ok": False, "output": "",
                     "error": f"series truncated/incomplete: got {len(vals)} values, expected {expected} "
                              f"(VMD output may exceed the {_MAX_TOOL_OUTPUT_CHARS}-char cap for a large structure/trajectory)"}
        name = self._SERIES_NAME[quantity]
        self._series[name] = vals
        preview = [round(v, 3) for v in vals[:5]]
        note = f"series '{name}' ({quantity}) fetched: {len(vals)} values, preview {preview}. Reduce it with vmd_compute, e.g. vmd_compute(\"max({name})\")."
        return {"ok": True, "output": note, "error": "", "name": name, "n": len(vals), "preview": preview, "tcl": tcl}

    def _compute(self, ti: Dict[str, Any]) -> Dict[str, Any]:
        expr = str(ti.get("expression") or "").strip()
        if not self._series:
            return {"ok": False, "output": "", "error": "no series bound yet; call vmd_traj_series first", "expr": expr}
        import sys as _sys, os.path as _op
        _d = _op.dirname(_op.abspath(__file__))
        if _d not in _sys.path:
            _sys.path.insert(0, _d)
        from safe_eval import safe_eval, ComputeError
        try:
            val = safe_eval(expr, self._series)
        except ComputeError as exc:
            return {"ok": False, "output": "", "error": f"vmd_compute: {exc}", "expr": expr}
        return {"ok": True, "output": f"{expr} = {val}", "error": "", "value": val, "expr": expr}

    _STYLES = {"licorice", "newcartoon", "cartoon", "vdw", "cpk", "lines", "newribbons",
               "ribbons", "tube", "trace", "surf", "quicksurf", "points", "bonds", "dynamicbonds"}
    _COLORS = {"name", "element", "charge", "resname", "restype", "resid", "chain",
               "structure", "beta", "occupancy", "index", "colorid", "mass", "type"}

    def _represent(self, ti: Dict[str, Any]) -> Dict[str, Any]:
        style = str(ti.get("style") or "").strip()
        color = str(ti.get("color") or "").strip()
        sel = str(ti.get("selection") or "protein").strip()
        if not style or style.split()[0].lower() not in self._STYLES:
            return {"ok": False, "output": "", "error": f"unknown style {style!r}"}
        cmds = [f"mol modstyle 0 top {style}", f'mol modselect 0 top "{sel}"']
        if color:
            if color.split()[0].lower() not in self._COLORS:
                return {"ok": False, "output": "", "error": f"unknown color {color!r}"}
            cmds.append(f"mol modcolor 0 top {color}")
        joined = "\n".join(cmds)
        res = self._run_tcl(joined)
        res["tcl"] = joined
        if res.get("ok"):
            res["output"] = f'rep 0: style={style}, color={color or "unchanged"}, selection="{sel}"'
        return res

    def _exec_wrapped(self, command: str, timeout: int) -> Tuple[str, int, str]:
        """Run `command` inside catch{}, return (printed_stdout, rc, result_or_error)."""
        script = (
            "set __vbrc [catch {\n" + command + "\n} __vbmsg]\n"
            f'puts "{_RC} $__vbrc"\n'
            f'puts "{_MB}"\nputs $__vbmsg\nputs "{_ME}"\n'
            f'puts "{_DONE}"\nflush stdout\n'
        )
        lines = self._send_and_read(script, timeout)
        printed: List[str] = []
        msg_lines: List[str] = []
        rc = 0
        seen_rc = False
        in_msg = False
        for raw in lines:
            s = _strip_prompt(raw)
            if _RC in s:
                seen_rc = True
                with contextlib.suppress(Exception):
                    rc = int(s.split(_RC, 1)[1].strip().split()[0])
                continue
            if _MB in s:
                in_msg = True
                continue
            if _ME in s:
                in_msg = False
                continue
            if in_msg:
                msg_lines.append(s)
            elif not seen_rc:
                printed.append(s)
        return "\n".join(printed), rc, "\n".join(msg_lines)

    def _send_and_read(self, script: str, timeout: int) -> List[str]:
        if self._master_fd is None:
            raise _VmdTimeout("VMD pty not open")
        os.write(self._master_fd, script.encode("utf-8"))
        out: List[str] = []
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise _VmdTimeout(f"VMD command timed out after {timeout}s")
            ready, _, _ = select.select([self._master_fd], [], [], min(remaining, 1.0))
            if not ready:
                if self._proc is not None and self._proc.poll() is not None:
                    raise _VmdTimeout("VMD process exited unexpectedly")
                continue
            try:
                chunk = os.read(self._master_fd, 65536)
            except OSError:
                raise _VmdTimeout("VMD pty closed (process exited?)")
            if not chunk:
                raise _VmdTimeout("VMD pty reached EOF")
            self._buf += chunk
            while b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                s = line.decode("utf-8", "replace").rstrip("\r")
                if _DONE in s:
                    return out
                out.append(s)


def _strip_prompt(line: str) -> str:
    s = line
    # VMD prints "vmd >" as its prompt and a bare "?" as the *continuation* prompt
    # for each line of a multi-line (braced) command. With echo disabled these
    # prompts still leak into the stream we read, e.g. "? ? ? ? Info) ...". Strip a
    # leading run of either so the model sees clean output (and doesn't waste its
    # small context, or misread the noise as an error).
    while True:
        t = s.lstrip()
        if t.startswith(_PROMPT):
            s = t[len(_PROMPT):]
        elif t[:1] == "?" and (len(t) == 1 or t[1:2].isspace()):
            s = t[1:]
        else:
            break
    return s


def _to_png_bytes(path: str) -> Optional[bytes]:
    """Convert a rendered TGA to PNG bytes. Anthropic only accepts
    png/jpeg/gif/webp, so raw TGA must be converted before it goes back to the
    model. Prefer the runtime's converter (no hard PIL dep), then Pillow."""
    try:
        from vmd_ai_runtime.image_utils import read_image_as_png_bytes
        data = read_image_as_png_bytes(path)
        if data:
            return data
    except Exception:
        pass
    try:
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.open(path).save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _truncate(s: str) -> str:
    """Cap a tool_result so one verbose VMD dump (file read, $sel get, per-atom
    loop) can't flood the model's context — that text is resent every turn."""
    if len(s) <= _MAX_TOOL_OUTPUT_CHARS:
        return s
    return (s[:_MAX_TOOL_OUTPUT_CHARS]
            + f"\n…[truncated {len(s) - _MAX_TOOL_OUTPUT_CHARS} more chars — do not dump "
              "per-atom/coordinate data or raw files; use selections + summary values]")


def _persist_image(png_bytes: bytes, save_path: str) -> Optional[str]:
    """Write a rendered image to save_path (relative -> CWD = the case working dir).
    Honors the requested extension (.png default; .jpg/.tga/.bmp via Pillow if present)."""
    try:
        dest = os.path.abspath(save_path)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        ext = os.path.splitext(dest)[1].lower()
        if ext in (".jpg", ".jpeg", ".tga", ".bmp"):
            try:
                import io
                from PIL import Image
                Image.open(io.BytesIO(png_bytes)).convert("RGB").save(dest)
                return dest
            except Exception:
                pass  # fall through to a raw PNG write under whatever name was asked
        with open(dest, "wb") as fh:
            fh.write(png_bytes)
        return dest
    except Exception:
        return None


def _strip_noise(text: str) -> str:
    """Drop VMD's chattiest startup/info lines so the model sees signal."""
    keep = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("Info) ") and ("Multithreading" in s or "plugin" in s or s.endswith("...")):
            continue
        keep.append(ln)
    return "\n".join(keep)


def _tcl_is_complete(cmd: str) -> bool:
    """True if ``cmd`` is syntactically complete (braces + brackets balanced). Pure-Python,
    no Tcl interpreter — a tkinter Tcl interp is thread-affine and aborts the process when
    torn down from the wrong thread (the agent runs in a worker thread). The brace/bracket
    balance catches the unbalanced-bracket hangs (the recurring `{x y z]` failure), which is
    the whole point of the check."""
    return _balanced(cmd)


def _balanced(s: str) -> bool:
    return _imbalance(s) is None


def _imbalance(s: str):
    """None if the command's braces/brackets are balanced; otherwise a short, agent-actionable
    description of the FIRST mismatch. Tracks double-quote state so `{}`/`[]` *inside* a Tcl
    string (e.g. `puts "done]"`) are not miscounted — those were false-rejected before."""
    brace = brack = 0
    esc = inq = False
    for ch in s:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            inq = not inq
            continue
        if inq:
            continue
        if ch == "{":
            brace += 1
        elif ch == "}":
            brace -= 1
        elif ch == "[":
            brack += 1
        elif ch == "]":
            brack -= 1
        if brace < 0:
            return "an extra '}' with no matching '{' (delete it, or add the missing '{')"
        if brack < 0:
            return "an extra ']' with no matching '[' — a common slip is `{x y z]` which should be `{x y z}`"
    if brace > 0:
        return f"{brace} unclosed '{{' — close the loop/expr body before sending"
    if brack > 0:
        return f"{brack} unclosed '[' — every command substitution needs its ']' (e.g. `[measure rgyr $s]`)"
    return None
