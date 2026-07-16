# Workbench Write-Answer + Guided Errors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give `vmd_compute` an optional `save_path` that writes its computed value straight to the answer file (killing the 53% transcription-fumble class), plus a guided unbound-series error, and tell the model to use it.

**Architecture:** `_compute` in the bridge gains `save_path` (mirrors `_traj_measure`'s save block) and enriches the unbound-series error with the `vmd_traj_series(quantity=...)` call to make. `VMD_COMPUTE_SCHEMA` advertises `save_path`; `workbench_directive` instructs the model to record its final answer via `save_path` (not `run_vmd_command`). No scorer/gold change.

**Tech Stack:** Python 3 (stdlib), runnable-`main` tests in `integrations/scivisagentbench`.

## Global Constraints

- No scorer/gold change — the harness still parses the answer file for the nearest float to gold. `save_path` writes `str(value)+"\n"` exactly like `_traj_measure` does.
- `save_path` is OPTIONAL — omitting it leaves `_compute` behavior unchanged (back-compatible; canned/none/easy arms unaffected).
- Quantities stay BARE (no gloss of what they measure) — do not leak the formulation. Only the *unbound-series* error names the `vmd_traj_series(quantity=...)` fetch call (that's tool-usage help, not answer help).
- Spec: `docs/superpowers/specs/2026-07-16-workbench-write-answer-design.md`.
- Run from vmd_ai/. Branch vmdbench-design. Commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

- **Modify** `integrations/scivisagentbench/subprocess_vmd_bridge.py` — `_NAME_QUANTITY` map; `_compute` gains `save_path` + guided error.
- **Create** `integrations/scivisagentbench/test_compute_save.py` — pure test (no VMD) of the write + guided error.
- **Modify** `integrations/scivisagentbench/vmd_ai_agent.py` — `VMD_COMPUTE_SCHEMA` gains `save_path`.
- **Modify** `integrations/scivisagentbench/tool_prompts.py` — `workbench_directive` write-the-answer instruction.
- **Modify** `integrations/scivisagentbench/test_workbench_wiring.py` — assert the directive mentions `save_path` (and stays giveaway-free).

---

### Task 1: bridge `_compute` — save_path + guided unbound-series error

**Files:**
- Modify: `integrations/scivisagentbench/subprocess_vmd_bridge.py`
- Test: `integrations/scivisagentbench/test_compute_save.py`

**Interfaces:**
- Produces: `_compute(ti)` honors `ti["save_path"]` (writes `str(value)+"\n"`) and returns a guided error when the expression names an unbound series. Return shape unchanged (`{ok, output, error, value, expr}`).

- [ ] **Step 1: Write the failing test**

Create `integrations/scivisagentbench/test_compute_save.py`:

```python
#!/usr/bin/env python3
"""test_compute_save.py — pure test of vmd_compute's save_path write + guided unbound-series error.
Drives the bridge's _compute directly (no VMD spawn — _compute is pure safe_eval + file write).
Run: python integrations/scivisagentbench/test_compute_save.py
"""
import os, sys, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from subprocess_vmd_bridge import SubprocessVmdBridge  # noqa: E402


def check(cond, label, fails):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    return fails + (0 if cond else 1)


def main():
    fails = 0
    b = SubprocessVmdBridge(vmd_bin="/bin/echo")   # constructs w/o VMD; _compute never spawns
    b._series = {"rgyr": [10.0, 11.0, 12.0, 9.0], "rmsd": [0.0, 1.0, 3.0, 2.0]}

    with tempfile.TemporaryDirectory() as d:
        ans = os.path.join(d, "sub", "answer.txt")   # nested dir exercises makedirs
        r = b._compute({"expression": "max(rmsd)", "save_path": ans})
        fails = check(r["ok"] and r["value"] == 3.0, "compute returns value", fails)
        fails = check(os.path.exists(ans) and open(ans).read().strip() == "3.0",
                      "save_path writes the exact computed value", fails)
        fails = check("written to" in r["output"], "note records the write", fails)

    r = b._compute({"expression": "max(rgyr)"})   # no save_path -> no file, unchanged
    fails = check(r["ok"] and r["value"] == 12.0, "no save_path still returns the value", fails)

    b._series = {"rgyr": [10.0, 11.0]}             # rmsd NOT bound
    r = b._compute({"expression": "max(rmsd)"})
    fails = check(not r["ok"], "unbound series -> ok False", fails)
    fails = check("rmsd_to_frame0" in r["error"] and "vmd_traj_series" in r["error"],
                  "unbound-series error names the fetch call + quantity", fails)

    print("ALL GOOD" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python integrations/scivisagentbench/test_compute_save.py`
Expected: FAIL — the current `_compute` ignores `save_path` (no file written) and its unbound-series error is safe_eval's raw "unknown name" (no `rmsd_to_frame0`/`vmd_traj_series` hint).

- [ ] **Step 3: Edit subprocess_vmd_bridge.py**

3a. Add the reverse map right after `_SERIES_NAME` (the line
`_SERIES_NAME = {"rgyr": "rgyr", "sasa": "sasa", "rmsd_to_frame0": "rmsd", "rmsf_per_residue": "rmsf"}`):

```python
    _NAME_QUANTITY = {v: k for k, v in _SERIES_NAME.items()}   # short name -> vmd_traj_series quantity
```

3b. Replace the whole `_compute` method with:

```python
    def _compute(self, ti: Dict[str, Any]) -> Dict[str, Any]:
        expr = str(ti.get("expression") or "").strip()
        save_path = ti.get("save_path")
        if not self._series:
            return {"ok": False, "output": "",
                    "error": "vmd_compute: no series bound yet — call vmd_traj_series(quantity=...) first",
                    "expr": expr}
        import sys as _sys, os.path as _op
        _d = _op.dirname(_op.abspath(__file__))
        if _d not in _sys.path:
            _sys.path.insert(0, _d)
        from safe_eval import safe_eval, ComputeError
        try:
            val = safe_eval(expr, self._series)
        except ComputeError as exc:
            import re as _re
            msg = str(exc)
            m = _re.search(r"unknown name '([^']+)'", msg)
            if m and m.group(1) in self._NAME_QUANTITY:
                nm = m.group(1)
                msg = (f"series '{nm}' not bound — fetch it first with "
                       f"vmd_traj_series(quantity='{self._NAME_QUANTITY[nm]}'). "
                       f"Currently bound: {sorted(self._series)}")
            return {"ok": False, "output": "", "error": f"vmd_compute: {msg}", "expr": expr}
        note = f"{expr} = {val}"
        if save_path:
            try:
                p = os.path.abspath(str(save_path))
                os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
                with open(p, "w") as fh:
                    fh.write(str(val) + "\n")
                note += f"  (written to {p})"
            except Exception as exc:  # noqa: BLE001
                note += f"  (FAILED to write {save_path}: {exc})"
        return {"ok": True, "output": note, "error": "", "value": val, "expr": expr}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python integrations/scivisagentbench/test_compute_save.py`
Expected: PASS — `ALL GOOD`.

Also confirm no regression:
Run: `python integrations/scivisagentbench/test_safe_eval.py && python -m pytest vmdbench/tests -q`
Expected: `ALL GOOD`; suite passes.

- [ ] **Step 5: Commit**

```bash
git add integrations/scivisagentbench/subprocess_vmd_bridge.py integrations/scivisagentbench/test_compute_save.py
git commit -m "feat(vmdbench): vmd_compute save_path + guided unbound-series error

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: agent wiring — schema `save_path` + directive

**Files:**
- Modify: `integrations/scivisagentbench/vmd_ai_agent.py`
- Modify: `integrations/scivisagentbench/tool_prompts.py`
- Test: `integrations/scivisagentbench/test_workbench_wiring.py`

**Interfaces:**
- Consumes: `_compute`'s `save_path` (Task 1).
- Produces: `VMD_COMPUTE_SCHEMA` advertises `save_path`; `workbench_directive` instructs its use.

- [ ] **Step 1: Add the failing assertion to `test_workbench_wiring.py`**

In `integrations/scivisagentbench/test_workbench_wiring.py`, add to the directive checks (near where it asserts the directive names both tools) — a check that the directive tells the model to use `save_path`:

```python
    fails = check("save_path" in d, "directive tells the model to record via save_path", fails)
```
(Keep the existing giveaway-free assertions — the new directive text must still contain none of the scored formulas.)

- [ ] **Step 2: Run it to verify it fails**

Run: `python integrations/scivisagentbench/test_workbench_wiring.py`
Expected: FAIL — the current directive has no `save_path`.

- [ ] **Step 3a: Add `save_path` to `VMD_COMPUTE_SCHEMA`** (`vmd_ai_agent.py`)

In `VMD_COMPUTE_SCHEMA`'s `properties`, after the `expression` property, add:

```python
            "save_path": {"type": "string",
                          "description": "absolute path of the task's output file — pass it to record "
                                         "your FINAL answer; the tool writes the computed value exactly, "
                                         "so do not re-type the number yourself"},
```
(Leave `"required": ["expression"]` unchanged — `save_path` is optional.)

- [ ] **Step 3b: Update `WORKBENCH_DIRECTIVE`** (`tool_prompts.py`)

Replace the final sentence of `WORKBENCH_DIRECTIVE` — currently
`"Write the final number to the requested file with run_vmd_command."` — with:

```python
    "To RECORD your final answer, call vmd_compute again with save_path set to the exact output "
    "file named in the task (e.g. vmd_compute(\"max(rmsd)\", save_path=\"/…/answer.txt\")) — the "
    "tool writes the computed value for you. Do NOT re-type the number or write the file yourself "
    "with run_vmd_command; that is where wrong answers creep in."
```
(The `median(rgyr)`/`std(sasa)` examples stay — they are non-scored. No scored formula may appear.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python integrations/scivisagentbench/test_workbench_wiring.py`
Expected: PASS — `ALL GOOD` (directive mentions `save_path`, still giveaway-free).

Confirm no regression:
Run: `python integrations/scivisagentbench/test_safe_eval.py && python integrations/scivisagentbench/test_compute_save.py && python -m pytest vmdbench/tests -q`
Expected: all `ALL GOOD`; suite passes.

- [ ] **Step 5: Commit**

```bash
git add integrations/scivisagentbench/vmd_ai_agent.py integrations/scivisagentbench/tool_prompts.py integrations/scivisagentbench/test_workbench_wiring.py
git commit -m "feat(vmdbench): advertise vmd_compute save_path + directive to record via it

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **`_compute` never spawns VMD** — it is pure `safe_eval` + optional file write, so the Task 1 test drives it directly with a hand-set `self._series` and a dummy `vmd_bin="/bin/echo"` (constructs anywhere, no VMD needed).
- **Do not** gloss the quantity names in the schema/directive (no "rgyr = size") — only the unbound-series *error* names the fetch call. Keeping quantities bare is what preserves the reasoning test.
- The `_NAME_QUANTITY` class-attr comprehension references `_SERIES_NAME` only in its *iterable* (`.items()`), which is evaluated in class scope — this is valid Python (unlike referencing a class attr in a comprehension *body*).
- After both tasks, re-sync and re-run the 14B workbench arm (CONC=2) — the "tool-right/agent-wrong" class should collapse and correctness rise toward ~55%.
