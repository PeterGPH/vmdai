# Hard/Reasoning Tier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a de-saturated "hard" tier to the ATLAS-traj benchmark where the prompt hides the formulation (metric/formula/VMD command) and asks for *composed* observables the semantic tool cannot answer in one call, with determinate gold.

**Architecture:** A new gold oracle (`gold_oracle_traj_hard.tcl`) emits composed observables (std / max / range / argmin / delta / ratio) built from the same per-frame Rg/SASA/RMSD/RMSF series the easy oracle uses. A new catalog module (`hard_metrics.py`) holds the recipe-stripped prompts + tolerances. `run_atlas_traj.py` gains a `--hard` switch that swaps in the hard metrics, prompt-builder, and oracle — the easy path is untouched. Tests: pure-Python catalog/prompt checks + a live VMD oracle test cross-validated against MDAnalysis for the Rg-derived quantities.

**Tech Stack:** Python 3 (stdlib + asyncio), Tcl (VMD `-dispdev text`), MDAnalysis 2.9 (test-only cross-check), pytest/unittest (`vmdbench/tests`) and runnable-`main` tests (`integrations/scivisagentbench`).

## Global Constraints

- Run all commands from `vmd_ai/` (so `python -m vmdbench…` and relative fixture paths resolve).
- VMD binary resolves via `VMD_AI_VMD_BIN` env / `--vmd` flag / config `vmd_bin`. Known paths: Mac dev `/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64`; server `/software/vmd-1.9.3/bin/vmd`.
- The `none`/hard runs need no GPU for VMD — prefix benchmark launches with `CUDA_VISIBLE_DEVICES=-1` on the shared box so VMD stays CPU-only.
- Gold is emitted as `GOLD <key> <value>` lines and parsed by `re.match(r"\s*GOLD\s+(\S+)\s+(\S+)", line)`; keep that exact shape.
- The main loop unpacks each metrics-dict value as a 3-tuple `(phrase, tol, scored)`; the hard catalog MUST keep that shape.
- ATLAS fixtures are CC-BY-NC 4.0 — do **not** commit new `fixtures/*`. Live tests SKIP when fixtures/VMD are absent.
- Do **not** sync `config_arm_*.json` to the server (they carry host-specific `vmd_bin`).
- Branch: `vmdbench-design`. End every commit message with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Spec: `docs/superpowers/specs/2026-07-10-hard-reasoning-tier-design.md`.

## File Structure

- **Create** `integrations/scivisagentbench/gold_oracle_traj_hard.tcl` — hard-tier gold oracle (composed observables + reference means).
- **Create** `integrations/scivisagentbench/hard_metrics.py` — `HARD_METRICS`, `HARD_INTENT`, `build_hard_prompt()`.
- **Create** `integrations/scivisagentbench/calibrate_hard.py` — `recommend_tol()` + a CLI that runs the oracle over fixtures and prints recommended tolerances.
- **Create** `integrations/scivisagentbench/test_hard_metrics.py` — runnable-`main` pure tests (prompt-stripping, catalog integrity, oracle key-parity, `select_mode`, `recommend_tol`).
- **Create** `vmdbench/tests/test_hard_oracle.py` — live VMD oracle test + MDAnalysis cross-check (skips without VMD/fixtures/MDAnalysis).
- **Modify** `integrations/scivisagentbench/run_atlas_traj.py` — add `HARD_ORACLE`, `select_mode()`, an `oracle=` param on `compute_gold`/`load_gold`, and a `--hard` flag; route the loop/scoreboard through the selected metrics/prompt-builder.
- **Modify** `integrations/scivisagentbench/precompute_gold_traj.py` — add `--hard` (use the hard oracle + hard keys).
- **Modify** `integrations/scivisagentbench/run_atlas_parallel.sh` — add a `HARD` env knob (passes `--hard`, uses a `_hard.json` gold cache).

---

### Task 1: Hard gold oracle + live cross-validated test

**Files:**
- Create: `integrations/scivisagentbench/gold_oracle_traj_hard.tcl`
- Test: `vmdbench/tests/test_hard_oracle.py`

**Interfaces:**
- Produces: a VMD `-e` script that, given env `GOLD_STRUCT` (pdb) + `GOLD_TRAJ` (dcd), prints `GOLD <key> <value>` lines for keys: `nframes rg_std rmsd_max sasa_range rmsf_max rg_argmin_frame rg_delta rg_ratio rg_frac_above_mean` **plus** reference keys `meanrg meanrmsd mean_rmsf rg_first rg_last rg_min`.

- [ ] **Step 1: Write the failing live test**

Create `vmdbench/tests/test_hard_oracle.py`:

```python
"""Live cross-validation of gold_oracle_traj_hard.tcl: run the hard oracle under real VMD on a
committed ATLAS fixture, assert (a) all scored keys are emitted, (b) physical invariant relations
hold, and (c) the Rg-derived quantities match an INDEPENDENT MDAnalysis computation. Skips (never
fails) when VMD, the fixture, or MDAnalysis is absent, so a plain checkout stays green.
"""
from __future__ import annotations
import os, re, subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORACLE = ROOT / "integrations" / "scivisagentbench" / "gold_oracle_traj_hard.tcl"
FIX = ROOT / "vmdbench" / "fixtures"
PDB, DCD = FIX / "2erl_A.pdb", FIX / "2erl_A_R1_s25.dcd"
VMD = os.environ.get("VMD_AI_VMD_BIN", "/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64")
SCORED = ("rg_std", "rmsd_max", "sasa_range", "rmsf_max", "rg_argmin_frame", "rg_delta", "rg_ratio")


def _run_oracle():
    env = dict(os.environ, GOLD_STRUCT=str(PDB), GOLD_TRAJ=str(DCD))
    out = subprocess.run([VMD, "-dispdev", "text", "-e", str(ORACLE)], env=env,
                         capture_output=True, text=True, timeout=600).stdout
    g = {}
    for line in out.splitlines():
        m = re.match(r"\s*GOLD\s+(\S+)\s+(\S+)", line)
        if m:
            try: g[m.group(1)] = float(m.group(2))
            except ValueError: pass
    return g


class HardOracleLiveTests(unittest.TestCase):
    def setUp(self):
        if not Path(VMD).exists():
            self.skipTest(f"VMD not found at {VMD} (set VMD_AI_VMD_BIN)")
        if not (PDB.exists() and DCD.exists()):
            self.skipTest(f"ATLAS fixture 2erl_A absent (CC-BY-NC; run scripts/make_atlas_cards.py)")
        self.g = _run_oracle()

    def test_all_scored_keys_emitted(self):
        missing = [k for k in SCORED if k not in self.g]
        self.assertFalse(missing, f"oracle did not emit {missing}; got {sorted(self.g)}")

    def test_invariant_relations(self):
        g = self.g
        n = g["nframes"]
        self.assertGreaterEqual(g["rg_std"], 0.0)
        self.assertGreaterEqual(g["sasa_range"], 0.0)
        self.assertGreaterEqual(g["rmsd_max"], g["meanrmsd"] - 1e-6)   # max >= mean
        self.assertGreaterEqual(g["rmsf_max"], g["mean_rmsf"] - 1e-6)
        self.assertTrue(0 <= g["rg_argmin_frame"] <= n - 1)
        self.assertEqual(g["rg_argmin_frame"], round(g["rg_argmin_frame"]))  # integer
        self.assertAlmostEqual(g["rg_delta"], g["rg_last"] - g["rg_first"], places=4)
        self.assertAlmostEqual(g["rg_ratio"], g["rg_last"] / g["rg_first"], places=4)
        self.assertLessEqual(g["rg_min"], g["meanrg"] + 1e-6)

    def test_rg_quantities_match_mdanalysis(self):
        try:
            import numpy as np
            import MDAnalysis as mda
        except ImportError:
            self.skipTest("MDAnalysis not installed")
        u = mda.Universe(str(PDB), str(DCD))
        prot = u.select_atoms("protein")
        rgs = np.array([prot.radius_of_gyration() for _ in u.trajectory])
        g = self.g
        self.assertAlmostEqual(g["rg_std"], float(rgs.std()), delta=0.05)          # population std
        self.assertAlmostEqual(g["rg_delta"], float(rgs[-1] - rgs[0]), delta=0.05)
        self.assertAlmostEqual(g["rg_ratio"], float(rgs[-1] / rgs[0]), delta=0.01)
        self.assertEqual(int(g["rg_argmin_frame"]), int(rgs.argmin()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest vmdbench/tests/test_hard_oracle.py -q`
Expected: FAIL — the oracle file does not exist yet, so `_run_oracle()` returns `{}` and `test_all_scored_keys_emitted` fails on `KeyError`/missing keys (or the subprocess errors). (If VMD/fixture are absent it SKIPS — run this on the Mac dev box where both exist.)

- [ ] **Step 3: Write the oracle**

Create `integrations/scivisagentbench/gold_oracle_traj_hard.tcl`:

```tcl
# gold_oracle_traj_hard.tcl — HARD-tier trajectory gold oracle.
# Env: GOLD_STRUCT (.pdb), GOLD_TRAJ (.dcd/.xtc). Emits GOLD <key> <value> for COMPOSED
# observables that have no single VMD command (std / max / range / argmin / delta / ratio),
# plus reference means (meanrg/meanrmsd/mean_rmsf) and rg_first/rg_last/rg_min for self-checking.
# rg_std is the POPULATION std (÷n); rg_argmin_frame is 0-based; rg_frac_above_mean uses strict >.
proc emit {k v} { puts "GOLD $k $v" }

if {![info exists env(GOLD_STRUCT)] || ![info exists env(GOLD_TRAJ)]} {
    puts "GOLD_ERROR missing GOLD_STRUCT / GOLD_TRAJ env"; quit
}
set pdb  $env(GOLD_STRUCT)
set traj $env(GOLD_TRAJ)
if {![file exists $pdb] || ![file exists $traj]} {
    puts "GOLD_ERROR file-not-found '$pdb' or '$traj'"; quit
}

mol new $pdb waitfor all
mol addfile $traj waitfor all
set n [molinfo top get numframes]
emit nframes $n

# ---- Rg + SASA per-frame series (both rigid-motion invariant) ----
if {[catch {
    set prot [atomselect top "protein"]
    set rgs {}; set sasas {}
    for {set i 0} {$i < $n} {incr i} {
        $prot frame $i
        lappend rgs   [measure rgyr $prot]
        lappend sasas [measure sasa 1.4 $prot]
    }
    set sum 0.0; foreach x $rgs { set sum [expr {$sum + $x}] }
    set mean [expr {$sum / $n}]
    emit meanrg $mean
    set ss 0.0; foreach x $rgs { set d [expr {$x - $mean}]; set ss [expr {$ss + $d*$d}] }
    emit rg_std [expr {sqrt($ss / $n)}]
    set rgf [lindex $rgs 0]; set rgl [lindex $rgs end]
    emit rg_first $rgf
    emit rg_last  $rgl
    emit rg_delta [expr {$rgl - $rgf}]
    emit rg_ratio [expr {$rgl / $rgf}]
    set minv $rgf; set argmin 0
    for {set i 1} {$i < $n} {incr i} {
        set v [lindex $rgs $i]
        if {$v < $minv} { set minv $v; set argmin $i }
    }
    emit rg_min $minv
    emit rg_argmin_frame $argmin
    set cnt 0; foreach x $rgs { if {$x > $mean} { incr cnt } }
    emit rg_frac_above_mean [expr {double($cnt) / $n}]
    set smin [lindex $sasas 0]; set smax $smin
    foreach x $sasas { if {$x < $smin} {set smin $x}; if {$x > $smax} {set smax $x} }
    emit sasa_range [expr {$smax - $smin}]
} err]} { puts "GOLD_ERROR rg_sasa $err" }

# ---- aligned Calpha RMSD-to-frame0 (mean + max) + per-residue RMSF (max) ----
if {[catch {
    set ca  [atomselect top "protein and name CA"]
    set ref [atomselect top "protein and name CA" frame 0]
    set all [atomselect top "all"]
    set rsum 0.0; set rmax 0.0
    for {set i 0} {$i < $n} {incr i} {
        $ca frame $i; $all frame $i
        $all move [measure fit $ca $ref]
        set r [measure rmsd $ca $ref]
        set rsum [expr {$rsum + $r}]
        if {$r > $rmax} { set rmax $r }
    }
    emit meanrmsd [expr {$rsum / $n}]
    emit rmsd_max $rmax
    set rmsf [measure rmsf $ca]
    set fsum 0.0; set fmax 0.0
    foreach v $rmsf { set fsum [expr {$fsum + $v}]; if {$v > $fmax} {set fmax $v} }
    emit mean_rmsf [expr {$fsum / [llength $rmsf]}]
    emit rmsf_max  $fmax
} err]} { puts "GOLD_ERROR rmsd_rmsf $err" }

quit
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_hard_oracle.py -q`
Expected: PASS (3 tests) on a box with VMD + the `2erl_A` fixture + MDAnalysis.

- [ ] **Step 5: Commit**

```bash
git add integrations/scivisagentbench/gold_oracle_traj_hard.tcl vmdbench/tests/test_hard_oracle.py
git commit -m "feat(vmdbench): hard-tier gold oracle (composed observables) + live MDAnalysis cross-check

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Hard task catalog + prompt builder

**Files:**
- Create: `integrations/scivisagentbench/hard_metrics.py`
- Test: `integrations/scivisagentbench/test_hard_metrics.py`

**Interfaces:**
- Produces: `HARD_METRICS: dict[str, tuple[str, float, bool]]` (key → `(question, tol, scored)`); `HARD_INTENT: dict[str, str]`; `build_hard_prompt(pdb, dcd, question, answer_path) -> str`.
- Consumes (in the test): the emitted keys of `gold_oracle_traj_hard.tcl` (Task 1).

- [ ] **Step 1: Write the failing test**

Create `integrations/scivisagentbench/test_hard_metrics.py`:

```python
#!/usr/bin/env python3
"""test_hard_metrics.py — pure tests for the HARD-tier catalog + prompt builder (no VMD).
Run: python integrations/scivisagentbench/test_hard_metrics.py
"""
import re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hard_metrics import HARD_METRICS, HARD_INTENT, build_hard_prompt  # noqa: E402

GIVEAWAYS = ("rgyr", "gyration", "measure", "numframes", "rmsf", "rmsd", "sasa",
             "solvent-accessible", "radius of")


def check(cond, label, fails):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    return fails + (0 if cond else 1)


def main():
    fails = 0
    # 1. prompt strips every giveaway but keeps the plumbing
    p = build_hard_prompt("/x/a.pdb", "/x/a.dcd", HARD_METRICS["rg_std"][0], "/x/o.txt")
    low = p.lower()
    for tok in GIVEAWAYS:
        fails = check(tok not in low, f"prompt omits giveaway '{tok}'", fails)
    for plumb in ('mol new "/x/a.pdb"', 'mol addfile "/x/a.dcd"', 'open "/x/o.txt"'):
        fails = check(plumb in p, f"prompt keeps plumbing '{plumb}'", fails)

    # 2. every question string (not just rg_std) is giveaway-free
    for key, (question, tol, scored) in HARD_METRICS.items():
        ql = question.lower()
        bad = [t for t in GIVEAWAYS if t in ql]
        fails = check(not bad, f"question '{key}' giveaway-free (found {bad})", fails)
        fails = check(isinstance(tol, (int, float)) and tol > 0, f"'{key}' tol>0", fails)
        fails = check(scored is True, f"'{key}' scored", fails)

    # 3. catalog <-> intent parity + oracle key parity
    fails = check(set(HARD_METRICS) == set(HARD_INTENT), "HARD_METRICS/HARD_INTENT keys match", fails)
    oracle = (HERE / "gold_oracle_traj_hard.tcl").read_text()
    emitted = set(re.findall(r"emit\s+(\w+)", oracle))
    missing = set(HARD_METRICS) - emitted
    fails = check(not missing, f"oracle emits every scored key (missing {missing})", fails)

    print("ALL GOOD" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python integrations/scivisagentbench/test_hard_metrics.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'hard_metrics'`.

- [ ] **Step 3: Write the catalog module**

Create `integrations/scivisagentbench/hard_metrics.py`:

```python
#!/usr/bin/env python3
"""hard_metrics.py — the HARD/reasoning tier catalog for `run_atlas_traj.py --hard`.

Each task HIDES the formulation: the prompt states a scientific goal in plain language (no metric
name, no formula, no VMD command) and asks for a COMPOSED observable the semantic tool cannot
answer in one call. Gold is a single determinate number from gold_oracle_traj_hard.tcl.
Spec: docs/superpowers/specs/2026-07-10-hard-reasoning-tier-design.md

Tolerances below are provisional-WIDE so the harness runs; tighten with calibrate_hard.py before
the real eval. Values are (question incl. unit, absolute tolerance, scored?) to match the 3-tuple
the run_atlas_traj main loop unpacks.
"""
HARD_METRICS = {
    "rg_std": (
        "Proteins breathe: their overall size fluctuates as they move. How much does this "
        "protein's overall size fluctuate over the whole trajectory? Report a single number in "
        "Angstroms.", 0.30, True),
    "rmsd_max": (
        "Over the trajectory, how far does the backbone get from the starting structure at its "
        "most-deviated point? Report that largest deviation as a single number in Angstroms.",
        1.5, True),
    "sasa_range": (
        "The protein's exposed surface area changes frame to frame. How large is the swing "
        "between its most-exposed and least-exposed frames? Report a single number in square "
        "Angstroms.", 1500.0, True),
    "rmsf_max": (
        "Some residues move much more than others. How mobile is the single most mobile residue "
        "over the trajectory? Report a single number in Angstroms.", 1.0, True),
    "rg_argmin_frame": (
        "At which frame of the trajectory is the protein at its most compact? Report the frame "
        "index as a single integer (the first frame is 0).", 0.5, True),
    "rg_delta": (
        "Comparing the last frame to the first, how much larger or smaller is the protein's "
        "overall size? Report a single signed number in Angstroms (negative if it shrank).",
        1.5, True),
    "rg_ratio": (
        "By what factor does the protein's overall size change from the first frame to the last? "
        "Report a single dimensionless number (1.0 means no change).", 0.15, True),
}

# intended_quantity per key — the spec-adequacy annotation (spec §8). Used by tests + calibration.
HARD_INTENT = {
    "rg_std": "population standard deviation of per-frame radius of gyration (protein), Angstrom",
    "rmsd_max": "maximum over frames of aligned Calpha RMSD-to-frame-0, Angstrom",
    "sasa_range": "max(SASA) - min(SASA) over frames (protein, measure sasa 1.4), Angstrom^2",
    "rmsf_max": "maximum per-residue Calpha RMSF over the trajectory, Angstrom",
    "rg_argmin_frame": "0-based frame index minimizing radius of gyration",
    "rg_delta": "Rg(last) - Rg(first), signed, Angstrom",
    "rg_ratio": "Rg(last) / Rg(first), dimensionless",
}


def build_hard_prompt(pdb, dcd, question, answer_path):
    """Recipe-stripped prompt: keep ONLY the mechanical plumbing (load + write); the reasoning
    (which metric / formula / VMD command) is withheld on purpose — that IS the task."""
    return (
        "You are controlling VMD headlessly through the run_vmd_command tool (Tcl).\n"
        "Load this structure and its trajectory:\n"
        f'    mol new "{pdb}" waitfor all\n'
        f'    mol addfile "{dcd}" waitfor all\n'
        f"{question}\n"
        "Report a single number and write ONLY that value (digits only, no words) to this exact "
        "file:\n"
        f'    set f [open "{answer_path}" w]; puts $f $value; close $f\n'
        "Finish in as few commands as possible."
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python integrations/scivisagentbench/test_hard_metrics.py`
Expected: PASS — prints `ALL GOOD`.

- [ ] **Step 5: Commit**

```bash
git add integrations/scivisagentbench/hard_metrics.py integrations/scivisagentbench/test_hard_metrics.py
git commit -m "feat(vmdbench): hard-tier task catalog + recipe-stripped prompt builder

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Wire `--hard` into run_atlas_traj.py

**Files:**
- Modify: `integrations/scivisagentbench/run_atlas_traj.py`
- Test: `integrations/scivisagentbench/test_hard_metrics.py` (append a `select_mode` case)

**Interfaces:**
- Produces: `HARD_ORACLE: Path`; `select_mode(hard: bool) -> (metrics, prompt_builder, oracle)`; `compute_gold(vmd, pdb, dcd, oracle=ORACLE)`; `load_gold(pairs, vmd, cache_path=None, oracle=ORACLE)`; a `--hard` CLI flag.
- Consumes: `HARD_METRICS`, `build_hard_prompt` from `hard_metrics` (Task 2); `HARD_ORACLE` file (Task 1).

- [ ] **Step 1: Write the failing test (append to test_hard_metrics.py)**

Add this function to `integrations/scivisagentbench/test_hard_metrics.py`, and call it from `main()` (add `fails += test_select_mode()` before the summary print):

```python
def test_select_mode():
    import run_atlas_traj as R
    fails = 0
    m_e, b_e, o_e = R.select_mode(False)
    fails = check(m_e is R.METRICS and b_e is R.build_prompt, "easy mode -> METRICS/build_prompt", fails)
    fails = check(o_e == R.ORACLE, "easy mode -> easy oracle", fails)
    m_h, b_h, o_h = R.select_mode(True)
    fails = check(set(m_h) == set(R_hard_keys()), "hard mode -> HARD_METRICS", fails)
    fails = check(str(o_h).endswith("gold_oracle_traj_hard.tcl"), "hard mode -> hard oracle", fails)
    return fails


def R_hard_keys():
    from hard_metrics import HARD_METRICS
    return set(HARD_METRICS)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python integrations/scivisagentbench/test_hard_metrics.py`
Expected: FAIL — `AttributeError: module 'run_atlas_traj' has no attribute 'select_mode'`.

- [ ] **Step 3: Edit run_atlas_traj.py**

3a. Add `HARD_ORACLE` after the `ORACLE` line (currently line 18):

```python
ORACLE = HERE / "gold_oracle_traj.tcl"
HARD_ORACLE = HERE / "gold_oracle_traj_hard.tcl"
```

3b. Parameterize `compute_gold` — change its signature and the oracle it runs:

```python
def compute_gold(vmd, pdb, dcd, oracle=ORACLE):
    env = dict(os.environ, GOLD_STRUCT=pdb, GOLD_TRAJ=dcd)
    try:
        out = subprocess.run([vmd, "-dispdev", "text", "-e", str(oracle)], env=env,
                             capture_output=True, text=True, timeout=600).stdout
```

(only the `def` line and `str(ORACLE)` → `str(oracle)` change; the rest of the function is unchanged.)

3c. Add `select_mode` immediately after `build_prompt` (after its closing `)` near line 64):

```python
def select_mode(hard):
    """Return (metrics, prompt_builder, oracle) for the easy or hard tier. Pure — unit-tested."""
    if hard:
        from hard_metrics import HARD_METRICS, build_hard_prompt
        return HARD_METRICS, build_hard_prompt, HARD_ORACLE
    return METRICS, build_prompt, ORACLE
```

3d. Parameterize `load_gold` — signature + the `compute_gold` call inside it:

```python
def load_gold(pairs, vmd, cache_path=None, oracle=ORACLE):
```

and change the miss branch call (currently `g, err = compute_gold(vmd, pdb, dcd)`):

```python
            g, err = compute_gold(vmd, pdb, dcd, oracle=oracle)
```

3e. In `run_arm`, right after `config = json.load(open(args.config))` (line 120), select the mode:

```python
    config = json.load(open(args.config))
    metrics, prompt_builder, oracle = select_mode(getattr(args, "hard", False))
```

3f. Route gold, the loop, and the scoreboard through the selection. Change the gold call (line 128):

```python
    gold = load_gold(pairs, os.path.expanduser(args.vmd), args.gold_cache, oracle=oracle)
```

Change the metric loop header (line 140) and the prompt build (line 144):

```python
                for mkey, (phrase, tol, scored) in metrics.items():
```
```python
                    prompt = prompt_builder(pdb, dcd, phrase, ans_path)
```

Change the scoreboard loop header (line 174):

```python
    for m, (_, _, sc) in metrics.items():
```

3g. Add the `--hard` flag in `main()` after the `--gold-cache` argument (after line 204):

```python
    ap.add_argument("--hard", action="store_true",
                    help="use the HARD/reasoning tier (hard_metrics + gold_oracle_traj_hard.tcl)")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python integrations/scivisagentbench/test_hard_metrics.py`
Expected: PASS — `ALL GOOD` (now includes the select_mode checks).

Also confirm the easy path still parses:
Run: `python integrations/scivisagentbench/run_atlas_traj.py --help`
Expected: exit 0, help text lists `--hard`.

- [ ] **Step 5: Commit**

```bash
git add integrations/scivisagentbench/run_atlas_traj.py integrations/scivisagentbench/test_hard_metrics.py
git commit -m "feat(vmdbench): --hard switch in run_atlas_traj (select_mode + oracle param)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Hard-gold precompute + parallel-runner knob

**Files:**
- Modify: `integrations/scivisagentbench/precompute_gold_traj.py`
- Modify: `integrations/scivisagentbench/run_atlas_parallel.sh`

**Interfaces:**
- Consumes: `HARD_ORACLE`, `compute_gold(..., oracle=)` (Task 3); `HARD_METRICS` (Task 2).
- Produces: `precompute_gold_traj.py --hard` writing a hard gold cache; a `HARD=1` env knob on `run_atlas_parallel.sh`.

- [ ] **Step 1: Edit precompute_gold_traj.py**

Change the import (line 14) to also pull the hard oracle + metrics:

```python
from run_atlas_traj import pairs_in, compute_gold, DEFAULT_VMD, METRICS, HARD_ORACLE, ORACLE  # noqa: E402
from hard_metrics import HARD_METRICS  # noqa: E402
```

Add a `--hard` arg (after the `--out` line, line 21):

```python
    ap.add_argument("--hard", action="store_true", help="precompute HARD-tier gold")
```

Select the oracle + required keys right after `args = ap.parse_args()` (line 22):

```python
    args = ap.parse_args()
    oracle = HARD_ORACLE if args.hard else ORACLE
    need = set(HARD_METRICS) if args.hard else set(METRICS)
```

Then delete the old `need = set(METRICS)` line (line 28) and pass the oracle into the call (line 31):

```python
        g, err = compute_gold(os.path.expanduser(args.vmd), pdb, dcd, oracle=oracle)
```

- [ ] **Step 2: Verify precompute parses and (with VMD) writes hard keys**

Run: `python integrations/scivisagentbench/precompute_gold_traj.py --hard --help`
Expected: exit 0, help lists `--hard`.

With VMD + fixtures present, a real precompute over the committed fixtures:
Run:
```bash
CUDA_VISIBLE_DEVICES=-1 python integrations/scivisagentbench/precompute_gold_traj.py --hard \
  --fixtures-dir vmdbench/fixtures --vmd "$VMD_AI_VMD_BIN" \
  --out /tmp/hard_gold_smoke.json
python3 -c "import json; d=json.load(open('/tmp/hard_gold_smoke.json')); k=next(iter(d)); print(k, sorted(d[k]))"
```
Expected: the printed key list contains `rg_std rmsd_max sasa_range rmsf_max rg_argmin_frame rg_delta rg_ratio`.

- [ ] **Step 3: Edit run_atlas_parallel.sh — add the HARD knob**

3a. Insert the HARD knob **immediately BEFORE** the `GOLD_CACHE="${GOLD_CACHE:-…}"` default line (line 25) — it must seed the hard cache path first, because the default line's `:-` won't override an already-set value:

```bash
HARD="${HARD:-}"                                   # HARD=1 -> hard/reasoning tier
if [ -n "$HARD" ] && [ -z "${GOLD_CACHE:-}" ]; then
  GOLD_CACHE="$HARNESS/gold_cache_$(basename "$FIXDIR")_hard.json"
fi
```

(The existing `GOLD_CACHE="${GOLD_CACHE:-$HARNESS/gold_cache_$(basename "$FIXDIR").json}"` line then stays as-is and becomes a no-op when HARD seeded it.)

3b. In the precompute block, pass `--hard` when set (change the `python "$HARNESS/precompute_gold_traj.py" …` line, line 49):

```bash
  python "$HARNESS/precompute_gold_traj.py" ${HARD:+--hard} --fixtures-dir "$FIXDIR" --vmd "$VMD" --out "$GOLD_CACHE" \
```

3c. In the arm-launch loop, pass `--hard` to the run (append to the `--gold-cache "$GOLD_CACHE"` line, line 64):

```bash
    --gold-cache "$GOLD_CACHE" ${HARD:+--hard} > "$log" 2>&1 &
```

- [ ] **Step 4: Verify the shell still parses**

Run: `bash -n integrations/scivisagentbench/run_atlas_parallel.sh`
Expected: exit 0 (no syntax error).

- [ ] **Step 5: Commit**

```bash
git add integrations/scivisagentbench/precompute_gold_traj.py integrations/scivisagentbench/run_atlas_parallel.sh
git commit -m "feat(vmdbench): HARD=1 knob for the atlas sweep + --hard precompute

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Calibrate the tolerances

**Files:**
- Create: `integrations/scivisagentbench/calibrate_hard.py`
- Test: `integrations/scivisagentbench/test_hard_metrics.py` (append a `recommend_tol` case)
- Modify: `integrations/scivisagentbench/hard_metrics.py` (set the calibrated tolerances)

**Interfaces:**
- Produces: `recommend_tol(values, frac=0.03, floor=0.0) -> float` (pure); a CLI that runs the hard oracle over a fixtures dir and prints, per key, the value distribution + a recommended tolerance.

- [ ] **Step 1: Write the failing test (append to test_hard_metrics.py)**

Add to `test_hard_metrics.py`, and call `fails += test_recommend_tol()` in `main()`:

```python
def test_recommend_tol():
    from calibrate_hard import recommend_tol
    fails = 0
    # 3% of the median (11.0) = 0.33, above the floor -> 0.33
    fails = check(abs(recommend_tol([10.0, 11.0, 12.0], frac=0.03, floor=0.1) - 0.33) < 1e-9,
                  "recommend_tol scales with median", fails)
    # floor dominates when the fraction is tiny
    fails = check(recommend_tol([10.0, 11.0, 12.0], frac=0.0, floor=0.5) == 0.5,
                  "recommend_tol respects the floor", fails)
    fails = check(recommend_tol([], floor=0.7) == 0.7, "recommend_tol handles empty -> floor", fails)
    return fails
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python integrations/scivisagentbench/test_hard_metrics.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'calibrate_hard'`.

- [ ] **Step 3: Write calibrate_hard.py**

Create `integrations/scivisagentbench/calibrate_hard.py`:

```python
#!/usr/bin/env python3
"""calibrate_hard.py — derive HARD-tier tolerances from the oracle (never hand-typed).

Runs gold_oracle_traj_hard.tcl over every fixture pair, collects each scored key's gold values
across chains, and prints the distribution + a recommended absolute tolerance. Copy the
recommended values into hard_metrics.py, then re-run to confirm. Determinism is enforced
separately by replay_clean; this only sizes the accept band.

  python integrations/scivisagentbench/calibrate_hard.py --fixtures-dir vmdbench/fixtures \
      --vmd "$VMD_AI_VMD_BIN"
"""
import argparse, os, sys, statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_atlas_traj import pairs_in, compute_gold, DEFAULT_VMD, HARD_ORACLE  # noqa: E402
from hard_metrics import HARD_METRICS  # noqa: E402

# per-key floor: the smallest tolerance that still absorbs VMD jitter + definitional variants.
# rg_argmin_frame is an exact integer (band 0.5); the rest floor at a physically negligible error.
FLOORS = {"rg_std": 0.02, "rmsd_max": 0.05, "sasa_range": 30.0, "rmsf_max": 0.05,
          "rg_argmin_frame": 0.5, "rg_delta": 0.05, "rg_ratio": 0.005}


def recommend_tol(values, frac=0.03, floor=0.0):
    """A tolerance = max(floor, frac * median(|value|)). Empty -> floor."""
    if not values:
        return floor
    med = statistics.median(abs(v) for v in values)
    return max(floor, frac * med)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures-dir", default=str(HERE / "atlas_fixtures"))
    ap.add_argument("--vmd", default=DEFAULT_VMD)
    ap.add_argument("--frac", type=float, default=0.03, help="tol as fraction of median magnitude")
    args = ap.parse_args()

    pairs = pairs_in(args.fixtures_dir)
    if not pairs:
        print(f"no fixture pairs in {args.fixtures_dir}"); return 1
    cols = {k: [] for k in HARD_METRICS}
    for name, pdb, dcd in pairs:
        g, err = compute_gold(os.path.expanduser(args.vmd), pdb, dcd, oracle=HARD_ORACLE)
        if not g:
            print(f"  {name}: FAILED {err}"); continue
        for k in cols:
            if k in g:
                cols[k].append(g[k])
    print(f"\n{'key':18}{'n':>4}{'min':>12}{'median':>12}{'max':>12}{'recommend_tol':>16}")
    for k in HARD_METRICS:
        vs = cols[k]
        if not vs:
            print(f"{k:18}{0:>4}{'-':>12}{'-':>12}{'-':>12}{'-':>16}"); continue
        tol = recommend_tol(vs, frac=args.frac, floor=FLOORS.get(k, 0.0))
        print(f"{k:18}{len(vs):>4}{min(vs):>12.3f}{statistics.median(vs):>12.3f}"
              f"{max(vs):>12.3f}{tol:>16.3f}")
    print("\ncopy each recommend_tol into HARD_METRICS[...] tol, then re-run the oracle test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python integrations/scivisagentbench/test_hard_metrics.py`
Expected: PASS — `ALL GOOD`.

- [ ] **Step 5: Run calibration and set the tolerances**

On a box with VMD + the fixtures:
```bash
CUDA_VISIBLE_DEVICES=-1 python integrations/scivisagentbench/calibrate_hard.py \
  --fixtures-dir vmdbench/fixtures --vmd "$VMD_AI_VMD_BIN"
```
Read the `recommend_tol` column and set each `HARD_METRICS[key]` tolerance in `hard_metrics.py` to that value (leave `rg_argmin_frame` at `0.5`). This replaces the provisional-wide tolerances.

- [ ] **Step 6: Commit**

```bash
git add integrations/scivisagentbench/calibrate_hard.py integrations/scivisagentbench/hard_metrics.py integrations/scivisagentbench/test_hard_metrics.py
git commit -m "feat(vmdbench): hard-tier tolerance calibration (oracle-derived bands)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: End-to-end smoke + the sweep

**Files:** none created — this validates the assembled pipeline and records how to run it.

**Interfaces:** Consumes everything above.

- [ ] **Step 1: Local gold+prompt smoke (no model needed)**

Confirm the hard path assembles a prompt + gold without an LLM:
```bash
CUDA_VISIBLE_DEVICES=-1 python3 - <<'PY'
import os, sys; sys.path.insert(0, "integrations/scivisagentbench")
from run_atlas_traj import select_mode, load_gold, pairs_in, DEFAULT_VMD
metrics, build, oracle = select_mode(True)
vmd = os.environ.get("VMD_AI_VMD_BIN", DEFAULT_VMD)
pairs = pairs_in("vmdbench/fixtures")[:1]
gold = load_gold(pairs, vmd, None, oracle=oracle)
name = pairs[0][0]
print("gold keys:", sorted(gold[name]))
print(build(pairs[0][1], pairs[0][2], metrics["rg_std"][0], "/tmp/a.txt")[:200])
PY
```
Expected: `gold keys` includes the 7 scored keys; the printed prompt names no metric/command.

- [ ] **Step 2: Full pytest + runnable tests green**

Run:
```bash
python -m pytest vmdbench/tests -q
python integrations/scivisagentbench/test_hard_metrics.py
```
Expected: pytest passes (hard-oracle test runs where VMD+fixtures exist, else skips); `test_hard_metrics.py` prints `ALL GOOD`.

- [ ] **Step 3: Run the hard sweep on the server (needs vLLM + a model)**

With a model served at `http://localhost:8000/v1` and the `config_arm_{none,toolssoft,tools}.json` present:
```bash
CUDA_VISIBLE_DEVICES=-1 HARD=1 RUN=hard_qwen7b SEEDS=3 \
  bash integrations/scivisagentbench/run_atlas_parallel.sh none toolssoft tools
```
This precomputes hard gold once (`gold_cache_<fix>_hard.json`), runs the three arms, and writes `test_results/atlas_traj/{none,toolssoft,tools}_hard_qwen7b/summary.json`.

- [ ] **Step 4: Fill the eval table in the report**

Score with the same one-liner used for the easy tier (glob the hard tags), then add a "hard tier" row to `docs/crossmodel_tool_results.html` beside the easy row. Expected shape: hard-tier tool arm ≪ 100%, and the `none → tool` lift smaller than on the easy tier (the tool cannot supply the formulation).

- [ ] **Step 5: Commit the report update**

```bash
git add docs/crossmodel_tool_results.html
git commit -m "docs: hard-tier results row (formulation gap)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **TDD reality for the oracle (Task 1):** the oracle is Tcl, so its "unit test" is the live VMD test. Run Task 1 on the Mac dev box (VMD at `/Applications/VMD.app/...`, MDAnalysis installed, the `2erl_A` fixture present) so the red→green cycle is real; on a checkout without those it SKIPS.
- **Determinism (`replay_clean`):** not re-implemented here — the existing gold cache + the fact that gold is deterministic covers it. `rg_argmin_frame` is the one at risk; if the live test's MDAnalysis-vs-VMD argmin ever disagrees, that fixture has a near-tie minimum — drop `rg_argmin_frame` for it (or pick a different smoke fixture) per spec §6.
- **Do not** commit new ATLAS fixtures or `config_arm_*.json`.
