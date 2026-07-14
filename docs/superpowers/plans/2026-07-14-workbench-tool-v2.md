# v2 Workbench Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a composable "workbench" tool pair — `vmd_traj_series` (returns the raw per-frame series) + `vmd_compute` (safe-evaluates a free reduction expression the model writes) — as a new benchmark arm, so the hard tier tests the *reduction choice* (formulation) with the Tcl-syntax and arithmetic barriers removed.

**Architecture:** `vmd_traj_series` runs VMD once (like the existing `_traj_measure`) but emits the whole per-frame series and binds it under a short name in a per-task namespace on the bridge. `vmd_compute` is pure Python: it `safe_eval`s the model's expression (`max(rmsd)`, `std(rgyr)`, `rgyr[-1]-rgyr[0]`, …) over those bound numpy arrays through a strict `ast` allow-list. Wired into the agent via the same `extra_tools` + directive mechanism as `vmd_traj_measure`, toggled by a new `enable_workbench_tools` config flag, run as a `workbench` arm beside `none`/`tools`. Gold and scoring are unchanged (same hard tier).

**Tech Stack:** Python 3.12 (stdlib `ast` + numpy), Tcl (VMD `-dispdev text`), runnable-`main` tests in `integrations/scivisagentbench`, `unittest` live test in `vmdbench/tests`.

## Global Constraints

- Run all commands from `vmd_ai/`.
- Spec: `docs/superpowers/specs/2026-07-14-workbench-tool-v2-design.md`.
- `vmd_compute` MUST be a strict `ast` allow-list evaluator — never `eval()` on raw input. No `Attribute` access, no imports, no dunder names, no unbound names, no non-allow-listed calls. This is the security gate.
- Python is **3.12** on the server — do NOT reference `ast.Index` (removed in 3.12).
- `vmd_traj_series` mirrors `gold_oracle_traj_hard.tcl`'s selections/measures exactly (protein for rgyr/sasa; `protein and name CA` for rmsd/rmsf) so `vmd_compute("max(rmsd)")` == gold `rmsd_max`.
- `vmd_traj_series` returns a **≤5-value preview + length**, never the full array (keeps arithmetic in `vmd_compute`, not in-context).
- The series namespace is **per-task**: cleared in the bridge's `reset()`.
- Do NOT commit host-specific `config_arm_*.json` with Mac paths. The workbench arm config is created on the server from an existing arm config.
- Branch `vmdbench-design`. End every commit message with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

- **Create** `integrations/scivisagentbench/safe_eval.py` — the `ast` allow-list evaluator (`safe_eval`, `ComputeError`).
- **Create** `integrations/scivisagentbench/test_safe_eval.py` — exhaustive pure tests (allowed compute correctly; disallowed raise).
- **Modify** `integrations/scivisagentbench/subprocess_vmd_bridge.py` — `_SERIES_TCL`, `_traj_series`, `_compute`, dispatch, `self._series`, clear in `reset()`.
- **Create** `vmdbench/tests/test_workbench_series.py` — live: fetched-series reductions match the hard oracle.
- **Modify** `integrations/scivisagentbench/vmd_ai_agent.py` — `VMD_TRAJ_SERIES_SCHEMA`, `VMD_COMPUTE_SCHEMA`, advertise under `enable_workbench_tools`, append `workbench_directive`.
- **Modify** `integrations/scivisagentbench/tool_prompts.py` — `workbench_directive()`.
- **Modify** `integrations/scivisagentbench/transcript_util.py` — record `vmd_traj_series` (tcl) + `vmd_compute` (expression).
- **Create** `integrations/scivisagentbench/test_workbench_wiring.py` — pure: directive text is giveaway-free; schemas advertised under the flag; transcript entries for both tools.

---

### Task 1: safe_eval.py — the allow-list evaluator

**Files:**
- Create: `integrations/scivisagentbench/safe_eval.py`
- Test: `integrations/scivisagentbench/test_safe_eval.py`

**Interfaces:**
- Produces: `safe_eval(expression: str, namespace: dict[str, list|array]) -> float|int`; `ComputeError(ValueError)`.

- [ ] **Step 1: Write the failing test**

Create `integrations/scivisagentbench/test_safe_eval.py`:

```python
#!/usr/bin/env python3
"""test_safe_eval.py — the security gate for vmd_compute. Allowed expressions compute correctly;
everything outside the allow-list raises ComputeError. Pure — no VMD. Run:
  python integrations/scivisagentbench/test_safe_eval.py
"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from safe_eval import safe_eval, ComputeError  # noqa: E402

NS = {"rgyr": [10.0, 11.0, 12.0, 9.0], "rmsd": [0.0, 1.0, 3.0, 2.0], "sasa": [100.0, 250.0, 175.0]}

OK_CASES = [   # (expr, expected)
    ("max(rmsd)", 3.0), ("min(rgyr)", 9.0), ("mean(rgyr)", 10.5),
    ("ptp(sasa)", 150.0), ("argmin(rgyr)", 3), ("argmax(rmsd)", 2),
    ("rgyr[-1]-rgyr[0]", -1.0), ("rgyr[-1]/rgyr[0]", 0.9), ("rgyr[0]", 10.0),
    ("max(sasa)-min(sasa)", 150.0), ("abs(rgyr[-1]-rgyr[0])", 1.0),
    ("mean(rgyr > mean(rgyr))", 0.5),           # fraction above mean -> 2/4
    ("sum(rmsd)", 6.0),
]
BAD_CASES = [   # expressions that MUST raise ComputeError
    "__import__('os').system('id')", "().__class__.__bases__", "open('/etc/passwd')",
    "rgyr.__class__", "unknown_series", "lambda x: x", "[x for x in rgyr]",
    "rgyr.sum()", "exec('x=1')", "globals()", "max(rgyr).__reduce__",
    "", "   ", "1;2", "import os",
]


def approx(a, b): return abs(float(a) - float(b)) < 1e-9


def main():
    fails = 0
    for expr, want in OK_CASES:
        try:
            got = safe_eval(expr, NS)
            ok = approx(got, want) and type(got) in (int, float)
        except Exception as e:  # noqa: BLE001
            ok = False; got = f"RAISED {type(e).__name__}: {e}"
        print(f"  [{'PASS' if ok else 'FAIL'}] {expr!r} -> {got}" + ("" if ok else f"  (want {want})"))
        fails += not ok
    for expr in BAD_CASES:
        try:
            got = safe_eval(expr, NS); ok = False
        except ComputeError:
            ok = True; got = "ComputeError (correctly rejected)"
        except Exception as e:  # noqa: BLE001  wrong exception type is still a fail
            ok = False; got = f"WRONG EXC {type(e).__name__}: {e}"
        print(f"  [{'PASS' if ok else 'FAIL'}] reject {expr!r} -> {got}")
        fails += not ok
    print("ALL GOOD" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python integrations/scivisagentbench/test_safe_eval.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'safe_eval'`.

- [ ] **Step 3: Write safe_eval.py**

Create `integrations/scivisagentbench/safe_eval.py`:

```python
#!/usr/bin/env python3
"""safe_eval.py — a strict allow-list evaluator for vmd_compute (the v2 workbench).

The model writes a reduction expression over per-frame series it fetched with vmd_traj_series
(e.g. "max(rmsd)", "std(rgyr)", "rgyr[-1]-rgyr[0]", "mean(rgyr > mean(rgyr))"). This evaluates it
over numpy arrays through an ast allow-list — NEVER eval() on raw input. Anything outside the
allow-list raises ComputeError. Pure module (numpy only); unit-tested in test_safe_eval.py.
"""
import ast
import math
import numbers
import numpy as np


class ComputeError(ValueError):
    """The expression used something outside the allow-list, or failed to reduce to a number."""


_FUNCS = {
    "max": np.max, "min": np.min, "mean": np.mean, "std": np.std, "var": np.var,
    "median": np.median, "sum": np.sum, "abs": np.abs, "sqrt": np.sqrt,
    "ptp": np.ptp, "argmin": np.argmin, "argmax": np.argmax, "len": len,
}
_CONSTS = {"pi": math.pi, "e": math.e}

# every ast node type the evaluator permits; anything else -> ComputeError
_ALLOWED = (
    ast.Expression, ast.Constant, ast.Name, ast.Load,
    ast.BinOp, ast.UnaryOp, ast.Call, ast.Subscript, ast.Compare,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq,
)  # NB: no ast.Index (removed in 3.12); subscript slices are plain exprs on 3.9+


def _check(node, names):
    if not isinstance(node, _ALLOWED):
        raise ComputeError(f"disallowed expression element: {type(node).__name__}")
    if isinstance(node, ast.Name):
        if node.id.startswith("__"):
            raise ComputeError(f"disallowed name: {node.id!r}")
        if node.id not in names and node.id not in _CONSTS and node.id not in _FUNCS:
            raise ComputeError(f"unknown name {node.id!r}; bound series are {sorted(names)}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ComputeError("only these functions are allowed: " + ", ".join(sorted(_FUNCS)))
        if node.keywords:
            raise ComputeError("keyword arguments are not allowed")
    for child in ast.iter_child_nodes(node):
        _check(child, names)


def safe_eval(expression, namespace):
    """Evaluate `expression` over the bound series (each coerced to a float numpy array). Returns a
    python float (or int for argmin/argmax/len). Raises ComputeError on anything unsafe or on an
    expression that does not reduce to a single number."""
    if not isinstance(expression, str) or not expression.strip():
        raise ComputeError("empty expression")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ComputeError(f"syntax error: {exc.msg}")
    names = {k: np.asarray(v, dtype=float) for k, v in (namespace or {}).items()}
    _check(tree, set(names))
    env = {"__builtins__": {}, **_FUNCS, **_CONSTS, **names}
    try:
        val = eval(compile(tree, "<vmd_compute>", "eval"), env)   # ast pre-validated by _check
    except ComputeError:
        raise
    except Exception as exc:  # noqa: BLE001  numpy/math/zero-division etc.
        raise ComputeError(f"evaluation failed: {exc}")
    if isinstance(val, np.integer) or (isinstance(val, int) and not isinstance(val, bool)):
        return int(val)
    if isinstance(val, np.floating) or isinstance(val, numbers.Real):
        return float(val)
    raise ComputeError(f"expression did not reduce to a number (got {type(val).__name__})")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python integrations/scivisagentbench/test_safe_eval.py`
Expected: PASS — `ALL GOOD` (all OK_CASES compute, all BAD_CASES raise ComputeError).

- [ ] **Step 5: Commit**

```bash
git add integrations/scivisagentbench/safe_eval.py integrations/scivisagentbench/test_safe_eval.py
git commit -m "feat(vmdbench): safe_eval allow-list evaluator for vmd_compute

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: bridge — vmd_traj_series + vmd_compute

**Files:**
- Modify: `integrations/scivisagentbench/subprocess_vmd_bridge.py`
- Test: `vmdbench/tests/test_workbench_series.py`

**Interfaces:**
- Consumes: `safe_eval`, `ComputeError` (Task 1).
- Produces: `execute_tool` routes `"vmd_traj_series"` → `_traj_series(ti)` and `"vmd_compute"` → `_compute(ti)`; `self._series: dict[str,list]`. `_traj_series` returns `{ok, output, name, n, preview, tcl}`; `_compute` returns `{ok, output, value, expr}`.

- [ ] **Step 1: Write the failing live test**

Create `vmdbench/tests/test_workbench_series.py`:

```python
"""Live: the workbench's fetched per-frame series, reduced with the SAME reductions the hard gold
uses, equal the hard oracle's values. Confirms vmd_traj_series is gold-consistent and vmd_compute
reduces correctly end-to-end. Skips without VMD or the 2erl_A fixture.
"""
from __future__ import annotations
import os, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "integrations" / "scivisagentbench"
sys.path.insert(0, str(HARNESS))
FIX = ROOT / "vmdbench" / "fixtures"
PDB, DCD = FIX / "2erl_A.pdb", FIX / "2erl_A_R1_s25.dcd"
VMD = os.environ.get("VMD_AI_VMD_BIN", "/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64")


class WorkbenchSeriesLiveTests(unittest.TestCase):
    def setUp(self):
        if not Path(VMD).exists():
            self.skipTest(f"VMD not found at {VMD}")
        if not (PDB.exists() and DCD.exists()):
            self.skipTest("ATLAS fixture 2erl_A absent (CC-BY-NC)")
        from subprocess_vmd_bridge import SubprocessVmdBridge
        self.b = SubprocessVmdBridge(vmd_bin=VMD, timeout=600)

    def tearDown(self):
        try: self.b.close()
        except Exception: pass

    def _series(self, quantity):
        r = self.b.execute_tool(tool_name="vmd_traj_series",
                                tool_input={"quantity": quantity, "structure": str(PDB), "trajectory": str(DCD)})
        self.assertTrue(r.get("ok"), r.get("error"))
        return r

    def _compute(self, expr):
        r = self.b.execute_tool(tool_name="vmd_compute", tool_input={"expression": expr})
        self.assertTrue(r.get("ok"), r.get("error"))
        return r["value"]

    def test_series_reductions_match_hard_gold(self):
        # gold for 2erl_A (from gold_oracle_traj_hard.tcl / the committed hard cache)
        self._series("rmsd_to_frame0"); self._series("rgyr"); self._series("sasa"); self._series("rmsf_per_residue")
        self.assertAlmostEqual(self._compute("max(rmsd)"), 1.3697, delta=0.02)      # rmsd_max
        self.assertAlmostEqual(self._compute("ptp(sasa)"), 255.11, delta=1.0)       # sasa_range
        self.assertAlmostEqual(self._compute("rgyr[-1]-rgyr[0]"),
                               self._compute("rgyr[-1]") - self._compute("rgyr[0]"), delta=1e-6)
        self.assertEqual(int(self._compute("argmin(rgyr)")), int(self._compute("argmin(rgyr)")))
        self.assertGreaterEqual(self._compute("max(rmsf)"), self._compute("mean(rmsf)"))

    def test_preview_is_bounded_not_the_full_array(self):
        r = self._series("rgyr")
        self.assertLessEqual(len(r["preview"]), 5)
        self.assertGreater(r["n"], 5)         # 2erl_A has ~42 frames; preview must be a subset


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest vmdbench/tests/test_workbench_series.py -q`
Expected: FAIL — `unsupported tool 'vmd_traj_series'` (bridge doesn't route it yet). Run on the Mac dev box (VMD + fixture present) so it doesn't skip.

- [ ] **Step 3: Edit subprocess_vmd_bridge.py**

3a. In `__init__` (near line 90, after `self._imbalance_streak = 0`), add the per-task namespace:

```python
        self._imbalance_streak = 0        # consecutive brace-imbalance rejections (anti-thrash)
        self._series = {}                 # per-task named per-frame series for vmd_compute
```

3b. In `reset` (near line 119), clear it (add alongside whatever reset already does):

```python
        self._series = {}
```

3c. In `execute_tool`, add two routes right after the `vmd_traj_measure` route (line 158):

```python
            if tool_name == "vmd_traj_series":
                return self._traj_series(tool_input)
            if tool_name == "vmd_compute":
                return self._compute(tool_input)
```

3d. Add the series Tcl table + the two methods, right after `_traj_measure` (after its `return` near line 340). `@SEL@` mirrors the hard oracle's selections; each body emits one `VMDAI_SERIES <val>` line per frame (or per residue for rmsf):

```python
    _SERIES_TCL = {
        "rgyr": ('set __p [atomselect top "protein"]; set __n [molinfo top get numframes]; '
                 'for {set __i 0} {$__i < $__n} {incr __i} { $__p frame $__i; '
                 'puts "VMDAI_SERIES [measure rgyr $__p]" }; $__p delete'),
        "sasa": ('set __p [atomselect top "protein"]; set __n [molinfo top get numframes]; '
                 'for {set __i 0} {$__i < $__n} {incr __i} { $__p frame $__i; '
                 'puts "VMDAI_SERIES [measure sasa 1.4 $__p]" }; $__p delete'),
        "rmsd_to_frame0": (
            'set __ca [atomselect top "protein and name CA"]; set __ref [atomselect top "protein and name CA" frame 0]; '
            'set __all [atomselect top all]; set __n [molinfo top get numframes]; '
            'for {set __i 0} {$__i < $__n} {incr __i} { $__ca frame $__i; $__all frame $__i; '
            '$__all move [measure fit $__ca $__ref]; puts "VMDAI_SERIES [measure rmsd $__ca $__ref]" }; '
            '$__ca delete; $__ref delete; $__all delete'),
        "rmsf_per_residue": (
            'set __ca [atomselect top "protein and name CA"]; set __ref [atomselect top "protein and name CA" frame 0]; '
            'set __all [atomselect top all]; set __n [molinfo top get numframes]; '
            'for {set __i 0} {$__i < $__n} {incr __i} { $__ca frame $__i; $__all frame $__i; '
            '$__all move [measure fit $__ca $__ref] }; '
            'foreach __x [measure rmsf $__ca] { puts "VMDAI_SERIES $__x" }; $__ca delete; $__ref delete; $__all delete'),
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
        for line in str(res.get("output") or "").splitlines():
            m = _re.search(r"VMDAI_SERIES\s+([-+0-9.eE]+)", line)
            if m:
                try: vals.append(float(m.group(1)))
                except ValueError: pass
        if not vals:
            return {"ok": False, "output": res.get("output", ""), "error": "no series values emitted"}
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
        _sys.path.insert(0, _op.dirname(_op.abspath(__file__)))
        from safe_eval import safe_eval, ComputeError
        try:
            val = safe_eval(expr, self._series)
        except ComputeError as exc:
            return {"ok": False, "output": "", "error": f"vmd_compute: {exc}", "expr": expr}
        return {"ok": True, "output": f"{expr} = {val}", "error": "", "value": val, "expr": expr}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_workbench_series.py -q`
Expected: PASS (2 tests) on the Mac dev box.

Also confirm the safe-eval + full suites still pass:
Run: `python integrations/scivisagentbench/test_safe_eval.py && python -m pytest vmdbench/tests -q`
Expected: `ALL GOOD`; suite passes.

- [ ] **Step 5: Commit**

```bash
git add integrations/scivisagentbench/subprocess_vmd_bridge.py vmdbench/tests/test_workbench_series.py
git commit -m "feat(vmdbench): bridge vmd_traj_series + vmd_compute (per-frame series + safe reduce)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: agent wiring — schemas, directive, transcript

**Files:**
- Modify: `integrations/scivisagentbench/vmd_ai_agent.py`
- Modify: `integrations/scivisagentbench/tool_prompts.py`
- Modify: `integrations/scivisagentbench/transcript_util.py`
- Test: `integrations/scivisagentbench/test_workbench_wiring.py`

**Interfaces:**
- Consumes: the bridge tools (Task 2).
- Produces: `VMD_TRAJ_SERIES_SCHEMA`, `VMD_COMPUTE_SCHEMA` advertised when `config["enable_workbench_tools"]`; `workbench_directive(config)`; transcript entries for `vmd_traj_series`/`vmd_compute`.

- [ ] **Step 1: Write the failing test**

Create `integrations/scivisagentbench/test_workbench_wiring.py`:

```python
#!/usr/bin/env python3
"""test_workbench_wiring.py — pure checks for the workbench directive + transcript recording.
Run: python integrations/scivisagentbench/test_workbench_wiring.py
"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tool_prompts import workbench_directive  # noqa: E402
from transcript_util import semantic_tool_transcript_entry  # noqa: E402


def check(cond, label, fails):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    return fails + (0 if cond else 1)


def main():
    fails = 0
    d = workbench_directive({})
    # the directive explains the loop but must NOT hand over the reduction (no metric/formula giveaways)
    for tok in ("vmd_traj_series", "vmd_compute"):
        fails = check(tok in d, f"directive names {tok}", fails)
    for giveaway in ("mean", "maximum", "std", "average", "radius of gyration"):
        fails = check(giveaway.lower() not in d.lower(), f"directive omits giveaway '{giveaway}'", fails)

    # vmd_traj_series has tcl -> recorded; vmd_compute has an expr -> recorded
    s = semantic_tool_transcript_entry("vmd_traj_series",
            {"ok": True, "output": "series 'rmsd' fetched", "tcl": 'mol new "x"\nputs "VMDAI_SERIES 1.0"'})
    fails = check(s is not None and "via vmd_traj_series" in s["cmd"], "series call recorded", fails)
    c = semantic_tool_transcript_entry("vmd_compute",
            {"ok": True, "output": "max(rmsd) = 3.0", "expr": "max(rmsd)"})
    fails = check(c is not None and "max(rmsd)" in c["cmd"], "compute call recorded (expr)", fails)

    print("ALL GOOD" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python integrations/scivisagentbench/test_workbench_wiring.py`
Expected: FAIL — `ImportError: cannot import name 'workbench_directive'`.

- [ ] **Step 3a: Add `workbench_directive` to tool_prompts.py**

Append to `integrations/scivisagentbench/tool_prompts.py`:

```python
# workbench (v2): the tool returns the RAW per-frame series; the model chooses the reduction. The
# directive explains the loop but deliberately hands over NO metric name/formula — that is the test.
WORKBENCH_DIRECTIVE = (
    "\n\nTRAJECTORY WORKBENCH: you have two tools. vmd_traj_series(quantity, structure, trajectory) "
    "returns the raw PER-FRAME series for one observable (quantity ∈ rgyr, sasa, rmsd_to_frame0, "
    "rmsf_per_residue) and binds it to a short name (rgyr, sasa, rmsd, rmsf). vmd_compute(expression) "
    "then reduces the bound series with an expression YOU write — e.g. vmd_compute(\"max(rmsd)\"), "
    "\"rgyr[-1]-rgyr[0]\", \"argmin(rgyr)\", \"ptp(sasa)\". Available functions: max min mean std var "
    "median sum abs sqrt ptp argmin argmax len, plus indexing (series[0], series[-1]) and comparisons. "
    "Decide which quantity and which reduction the question calls for — the series is data, the "
    "reduction is your judgment. Write the final number to the requested file with run_vmd_command."
)


def workbench_directive(config):
    """Directive for the v2 workbench arm (config['enable_workbench_tools'])."""
    return WORKBENCH_DIRECTIVE
```

- [ ] **Step 3b: Record both tools in transcript_util.py**

In `integrations/scivisagentbench/transcript_util.py`, extend `SEMANTIC_TOOLS` and handle the `vmd_compute` (no tcl, has `expr`) case. Replace the current `SEMANTIC_TOOLS` line and the body of `semantic_tool_transcript_entry`:

```python
SEMANTIC_TOOLS = ("vmd_measure", "vmd_traj_measure", "vmd_represent", "vmd_traj_series", "vmd_compute")
```

and, inside `semantic_tool_transcript_entry`, before the existing `tcl = result.get("tcl")` block, add the compute special-case:

```python
    if name == "vmd_compute":                      # pure-python reduce: record the expression
        expr = result.get("expr")
        if not expr:
            return None
        note = str(result.get("output") or "").splitlines()[:1]
        cmd = f"# >>> via vmd_compute: {expr}" + (f"  # {note[0][:80]}" if note else "")
        return {"cmd": cmd, "ok": bool(result.get("ok")), "err": str(result.get("error") or "")}
```

(The rest of the function — the `tcl`-based path — now also serves `vmd_traj_series`, which carries `tcl`.)

- [ ] **Step 3c: Add schemas + advertise them in vmd_ai_agent.py**

After `VMD_REPRESENT_SCHEMA` (near line 87) add:

```python
VMD_TRAJ_SERIES_SCHEMA = {
    "name": "vmd_traj_series",
    "description": "Return the RAW per-frame series for one trajectory observable (no reduction "
                   "applied) and bind it to a short name for vmd_compute to reduce.",
    "input_schema": {
        "type": "object",
        "properties": {
            "quantity": {"type": "string",
                         "enum": ["rgyr", "sasa", "rmsd_to_frame0", "rmsf_per_residue"],
                         "description": "which per-frame observable to compute"},
            "structure": {"type": "string", "description": "absolute path to the .pdb topology"},
            "trajectory": {"type": "string", "description": "absolute path to the .dcd trajectory"},
        },
        "required": ["quantity", "structure", "trajectory"],
    },
}
VMD_COMPUTE_SCHEMA = {
    "name": "vmd_compute",
    "description": "Reduce the bound per-frame series to a single number with an expression you "
                   "write, e.g. \"max(rmsd)\", \"std(rgyr)\", \"rgyr[-1]-rgyr[0]\", \"argmin(rgyr)\".",
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {"type": "string",
                           "description": "math over bound series; funcs: max min mean std var median "
                                          "sum abs sqrt ptp argmin argmax len; indexing and comparisons OK"},
        },
        "required": ["expression"],
    },
}
```

Then in `setup` where semantic tools are advertised (near line 285), add the workbench branch. Insert directly after the `enable_semantic_tools` block:

```python
        if bool(self.config.get("enable_workbench_tools", False)):
            from tool_prompts import workbench_directive
            existing = list(getattr(self._loop, "extra_tools", []) or [])
            self._loop.extra_tools = existing + [VMD_TRAJ_SERIES_SCHEMA, VMD_COMPUTE_SCHEMA]
            self._system_prompt += workbench_directive(self.config)
            print("[vmd_ai] workbench tools enabled (vmd_traj_series + vmd_compute)")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python integrations/scivisagentbench/test_workbench_wiring.py`
Expected: PASS — `ALL GOOD`.

Confirm nothing else regressed:
Run: `python integrations/scivisagentbench/test_safe_eval.py && python -m pytest vmdbench/tests -q`
Expected: `ALL GOOD`; suite passes.

- [ ] **Step 5: Commit**

```bash
git add integrations/scivisagentbench/vmd_ai_agent.py integrations/scivisagentbench/tool_prompts.py integrations/scivisagentbench/transcript_util.py integrations/scivisagentbench/test_workbench_wiring.py
git commit -m "feat(vmdbench): advertise workbench tools + directive + transcript recording

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: arm config + end-to-end smoke + sweep

**Files:** none created in-repo (config is host-specific, made on the server). This validates the assembled arm and documents the run.

**Interfaces:** Consumes everything above.

- [ ] **Step 1: Create the workbench arm config on the server (host paths preserved)**

The workbench arm reuses an existing arm config's host paths and just flips the tool flags. On the server:
```bash
cd /data/server10/pinhao2/ML/PyMolAI/vmd_ai
python3 - <<'PY'
import json
base = json.load(open("integrations/scivisagentbench/config_arm_tools.json"))
base["enable_semantic_tools"] = False          # workbench replaces the v1 canned tool
base["enable_workbench_tools"] = True
base["experiment_number"] = "workbench_hard"
json.dump(base, open("integrations/scivisagentbench/config_arm_workbench.json", "w"), indent=2)
print("wrote config_arm_workbench.json  model=", base.get("model"), " vmd_bin=", base.get("vmd_bin"))
PY
```

- [ ] **Step 2: Local wiring smoke (no model needed)**

Confirm the flag advertises exactly the two workbench tools:
```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "integrations/scivisagentbench")
from vmd_ai_agent import VMD_TRAJ_SERIES_SCHEMA, VMD_COMPUTE_SCHEMA
from tool_prompts import workbench_directive
print("schemas:", VMD_TRAJ_SERIES_SCHEMA["name"], VMD_COMPUTE_SCHEMA["name"])
d = workbench_directive({})
print("directive giveaway-free:", not any(t in d.lower() for t in ("mean","maximum","std","average")))
PY
```
Expected: `schemas: vmd_traj_series vmd_compute` and `directive giveaway-free: True`.

- [ ] **Step 3: Run the workbench arm on the hard tier (server, needs vLLM)**

```bash
CUDA_VISIBLE_DEVICES=-1 HARD=1 RUN=hard_qwen14b_wb SEEDS=3 \
  FIXDIR=$PWD/integrations/scivisagentbench/atlas_fixtures \
  bash integrations/scivisagentbench/run_atlas_parallel.sh none tools workbench
```
This runs the baseline (`none`), the v1 canned tool (`tools`), and the new `workbench` arm on the same hard questions + gold. Expected: `workbench` scores **above** both `none` and `tools` on the max/range metrics, because the model can now fetch the series and reduce it correctly.

- [ ] **Step 4: Score + compare**

```bash
for t in none tools workbench; do
  python3 -c "import json,os; d='test_results/atlas_traj/${t}_hard_qwen14b_wb/summary.json'; \
  j=json.load(open(d)) if os.path.exists(d) else {}; \
  v=[x for x in j.values() if isinstance(x,dict) and x.get('ok') is not None]; \
  ok=sum(1 for x in v if x['ok'] is True); \
  print('${t}'.ljust(10), f'{ok}/{len(v)}', f'{100*ok/len(v):.1f}%' if v else '-')"
done
```
Expected shape: `workbench` > `tools` > `none` on correct%. If the workbench closes most of the formulation gap, the residual failures (via the transcript's recorded `vmd_compute` expressions) are genuine wrong-reduction choices — report those.

- [ ] **Step 5: Commit any report update**

```bash
git add docs/crossmodel_tool_results.html
git commit -m "docs: workbench arm results (series+compute vs canned tool)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **TDD reality:** Task 1 (safe_eval) and Task 3 (wiring) are pure — run anywhere. Task 2's live test needs the Mac dev box (VMD at `/Applications/VMD.app/...` + the `2erl_A` fixture); it SKIPS elsewhere.
- **Security first:** Task 1's BAD_CASES are the security gate — if any fails to raise `ComputeError`, stop and fix before Task 2. Add a case rather than weaken the check if a bypass is found.
- **Gold-consistency:** `_SERIES_TCL` selections/measures must stay byte-aligned with `gold_oracle_traj_hard.tcl` — if they drift, `max(rmsd)` won't equal gold `rmsd_max`. The Task 2 live test guards this.
- Do NOT commit `config_arm_workbench.json` (host paths).
