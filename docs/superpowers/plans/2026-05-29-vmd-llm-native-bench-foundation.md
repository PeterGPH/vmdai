# VMD-LLM-Native Bench — Foundation (Plan 1 of 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the LLM-free core of VMD-LLM-Native Bench: load a declarative task card, replay a reference Tcl solution in live headless VMD, parse the result into a canonical `SceneState`, evaluate the closed assertion vocabulary, and emit a gated + 6-dimension + composite score — proven end-to-end on three task cards.

**Architecture:** A runtime-agnostic Python package `vmd_ai/vmdbench/` (Approach B from the design spec). This plan implements the layers below the system-under-test adapter: `spec/` (task cards, assertions, dimensions), `env/` (canonical `SceneState` + a `HeadlessVMDEnv` that drives `vmd -dispdev text`), `adapters/oracle_tcl.py` (reference-solution runner, the verifier's upper bound), `verify/` (assertion evaluators + runner), and `score/` (gated composite). The ChatVMD adapter, typed-tool track, `get_scene_state` observation, recovery fault-injection, factorial harness, and reporting are Plans 2–4.

**Tech Stack:** Python 3 (stdlib only: `dataclasses`, `subprocess`, `re`, `json`, `pathlib`, `unittest`), `PyYAML` for card parsing, and VMD **1.9.4a57** (`vmd -dispdev text -eofexit -e <script.tcl>`). Tests are stdlib `unittest.TestCase` (matching the repo convention in `vmd_ai/tests/`), run via `pytest`.

---

## Conventions used in every task

- **Working directory for all commands:** `/Users/pinhaogu/Documents/GitHub/PyMolAI/vmd_ai` (referred to below as `$VMDAI`). All test/commit paths are relative to it.
- **Test import shim** (matches `vmd_ai/tests/test_protocol.py`): every test file starts with
  ```python
  from __future__ import annotations
  import sys, unittest
  from pathlib import Path
  ROOT = Path(__file__).resolve().parents[2]   # .../vmd_ai  (parents: [0]=tests, [1]=vmdbench, [2]=vmd_ai)
  if str(ROOT) not in sys.path:
      sys.path.insert(0, str(ROOT))
  ```
  then `from vmdbench.<module> import ...`.
- **Run a single test:** `python -m pytest vmdbench/tests/<file>.py -v`
- **VMD requirement:** these tests launch real VMD. If `command -v vmd` fails, stop and install VMD first — the live tasks (T3, T9, T11) cannot pass without it.
- **Commits:** all on the current `vmdbench-design` branch. Conventional-commit style (`feat(vmdbench): ...`). Co-author trailer per repo policy.

---

## File map (created by this plan)

```
vmd_ai/vmdbench/
├── __init__.py
├── VERSION                       # pins supported VMD version string
├── README.md
├── cli.py                        # `python -m vmdbench.cli score-oracle <card> <oracle.tcl>`
├── spec/
│   ├── __init__.py
│   ├── dimensions.py             # Dimension enum + DEFAULT_WEIGHTS + KIND_DIMENSIONS
│   ├── assertions.py             # assertion validation + evaluator registry + custom_check hook
│   └── task_card.py              # TaskCard dataclass + YAML load + validate
├── env/
│   ├── __init__.py
│   ├── scene_state.py            # Molecule/Representation/Display/SceneState + parse_probe_lines
│   └── headless_vmd.py           # HeadlessVMDEnv: wrap Tcl, run vmd, parse → SceneState
├── adapters/
│   ├── __init__.py
│   └── oracle_tcl.py             # run a reference .tcl through HeadlessVMDEnv
├── verify/
│   ├── __init__.py
│   ├── checks.py                 # state-assertion evaluators
│   └── runner.py                 # replay tcl + evaluate card → VerifyResult
├── score/
│   ├── __init__.py
│   └── scorer.py                 # gate → per-dim subscore → composite
├── fixtures/
│   └── mini.pdb                   # hermetic test structure (protein+nucleic+water), committed
├── tasks/
│   ├── viz/viz_protein_dna_001.yaml
│   ├── select/select_water_count_001.yaml
│   └── traj/traj_render_001.yaml
├── oracles/
│   ├── viz_protein_dna_001.tcl
│   ├── select_water_count_001.tcl
│   └── traj_render_001.tcl
└── tests/
    ├── __init__.py
    ├── fixtures.py               # write_mini_pdb()
    ├── test_smoke.py
    ├── test_dimensions.py
    ├── test_scene_state.py
    ├── test_headless_vmd.py      # LIVE
    ├── test_assertions.py
    ├── test_task_card.py
    ├── test_cards_load.py
    ├── test_checks.py
    ├── test_runner.py            # LIVE
    ├── test_scorer.py
    └── test_cli.py               # LIVE
```

---

## Task 0: Scaffold package, pin VMD, smoke test, test fixture

**Files:**
- Create: `vmdbench/__init__.py`, `vmdbench/VERSION`, and empty `__init__.py` in `spec/ env/ adapters/ verify/ score/ tests/`
- Create: `vmdbench/tests/fixtures.py`
- Create: `vmdbench/tests/test_smoke.py`

- [ ] **Step 1: Create the package skeleton**

```bash
cd /Users/pinhaogu/Documents/GitHub/PyMolAI/vmd_ai
mkdir -p vmdbench/spec vmdbench/env vmdbench/adapters vmdbench/verify vmdbench/score vmdbench/tasks/viz vmdbench/tasks/select vmdbench/tasks/traj vmdbench/oracles vmdbench/tests
for d in vmdbench vmdbench/spec vmdbench/env vmdbench/adapters vmdbench/verify vmdbench/score vmdbench/tests; do touch "$d/__init__.py"; done
printf 'vmd_min_version = "1.9.4a57"\n' > vmdbench/VERSION
```

- [ ] **Step 2: Write the fixture generator** (`vmdbench/tests/fixtures.py`)

A correctly-column-formatted minimal PDB with protein (ALA), water (HOH ×2), and nucleic (DA) atoms, so the `protein`/`water`/`nucleic` VMD selection macros are all non-empty. Written programmatically to guarantee fixed-width columns.

```python
from __future__ import annotations
from pathlib import Path

# (record, serial, name, resname, chain, resseq, x, y, z, element)
_ATOMS = [
    ("ATOM", 1, "N",   "ALA", "A", 1, 0.000, 0.000, 0.000, "N"),
    ("ATOM", 2, "CA",  "ALA", "A", 1, 1.458, 0.000, 0.000, "C"),
    ("ATOM", 3, "C",   "ALA", "A", 1, 2.009, 1.420, 0.000, "C"),
    ("ATOM", 4, "O",   "ALA", "A", 1, 1.251, 2.390, 0.000, "O"),
    ("ATOM", 5, "CB",  "ALA", "A", 1, 1.988,-0.773, 1.199, "C"),
    ("ATOM", 6, "P",   "DA",  "B", 1, 8.000, 0.000, 0.000, "P"),
    ("ATOM", 7, "C1'", "DA",  "B", 1, 9.200, 1.000, 0.000, "C"),
    ("HETATM",8, "O",   "HOH", "W", 1, 5.000, 5.000, 0.000, "O"),
    ("HETATM",9, "O",   "HOH", "W", 2, 6.000, 5.000, 0.000, "O"),
]

def write_mini_pdb(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for rec, serial, name, resname, chain, resseq, x, y, z, elem in _ATOMS:
        # PDB atom-name justification: 4-char names start in col 13; <4-char names get a leading space.
        nm = name if len(name) >= 4 else f" {name:<3}"
        lines.append(
            f"{rec:<6}{serial:>5} {nm:<4}{'':1}{resname:>3} {chain:1}{resseq:>4}{'':4}"
            f"{x:8.3f}{y:8.3f}{z:8.3f}{1.00:6.2f}{0.00:6.2f}{'':10}{elem:>2}"
        )
    lines.append("END")
    path.write_text("\n".join(lines) + "\n")
    return path

EXPECTED_NUMATOMS = len(_ATOMS)  # 9
```

- [ ] **Step 3: Write the smoke test** (`vmdbench/tests/test_smoke.py`)

```python
from __future__ import annotations
import sys, unittest, shutil, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.tests.fixtures import write_mini_pdb, EXPECTED_NUMATOMS


class SmokeTests(unittest.TestCase):
    def test_vmd_present(self):
        self.assertIsNotNone(shutil.which("vmd"), "vmd must be on PATH for the bench")

    def test_vmd_loads_fixture_headless(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = write_mini_pdb(Path(d) / "mini.pdb")
            script = Path(d) / "probe.tcl"
            script.write_text(
                f'mol new "{pdb}" waitfor all\n'
                'puts "PROBE> numatoms=[molinfo top get numatoms]"\n'
                'quit\n'
            )
            out = subprocess.run(
                ["vmd", "-dispdev", "text", "-eofexit", "-e", str(script)],
                capture_output=True, text=True, timeout=120,
            )
            self.assertIn(f"PROBE> numatoms={EXPECTED_NUMATOMS}", out.stdout,
                          msg=f"stdout was:\n{out.stdout}\nstderr:\n{out.stderr}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the smoke test**

Run: `python -m pytest vmdbench/tests/test_smoke.py -v`
Expected: both tests PASS. If `test_vmd_loads_fixture_headless` reports a different `numatoms`, the fixture columns are off — fix `write_mini_pdb` until VMD reports `9`.

- [ ] **Step 5: Commit**

```bash
git add vmdbench/__init__.py vmdbench/VERSION vmdbench/*/__init__.py vmdbench/tests/__init__.py vmdbench/tests/fixtures.py vmdbench/tests/test_smoke.py
git commit -m "feat(vmdbench): scaffold package + headless VMD smoke test + fixture" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 1: Dimensions, weights, and the kind→dimension map

**Files:**
- Create: `vmdbench/spec/dimensions.py`
- Test: `vmdbench/tests/test_dimensions.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.dimensions import Dimension, DEFAULT_WEIGHTS, KIND_DIMENSIONS


class DimensionTests(unittest.TestCase):
    def test_six_dimensions(self):
        self.assertEqual(len(list(Dimension)), 6)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(DEFAULT_WEIGHTS.values()), 1.0, places=6)
        self.assertEqual(set(DEFAULT_WEIGHTS), set(Dimension))

    def test_kind_map_uses_valid_dimensions(self):
        for kind, dims in KIND_DIMENSIONS.items():
            self.assertTrue(dims, f"{kind} maps to no dimension")
            for d in dims:
                self.assertIsInstance(d, Dimension)

    def test_known_kind_mapping(self):
        self.assertIn(Dimension.SEMANTIC_GROUNDING, KIND_DIMENSIONS["selection_count"])
        self.assertIn(Dimension.ACTIONABILITY, KIND_DIMENSIONS["representation_exists"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_dimensions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vmdbench.spec.dimensions'`

- [ ] **Step 3: Write the implementation** (`vmdbench/spec/dimensions.py`)

```python
from __future__ import annotations
from enum import Enum


class Dimension(str, Enum):
    OBSERVABILITY = "observability"
    ACTIONABILITY = "actionability"
    SEMANTIC_GROUNDING = "semantic_grounding"
    VERIFICATION_RECOVERY = "verification_recovery"
    REPRODUCIBILITY = "reproducibility"
    WORKFLOW_EFFICIENCY = "workflow_efficiency"


DEFAULT_WEIGHTS: dict[Dimension, float] = {d: 1.0 / len(Dimension) for d in Dimension}

# Which dimension each state-assertion kind contributes to. Observability and
# workflow_efficiency are driven by episode metrics (Plans 2+), not single assertions.
KIND_DIMENSIONS: dict[str, list[Dimension]] = {
    "molecule_loaded":        [Dimension.ACTIONABILITY],
    "representation_exists":  [Dimension.ACTIONABILITY],
    "representation_count":   [Dimension.ACTIONABILITY],
    "display_property":       [Dimension.ACTIONABILITY],
    "file_rendered":          [Dimension.ACTIONABILITY],
    "frames_loaded":          [Dimension.ACTIONABILITY],
    "camera_changed":         [Dimension.ACTIONABILITY],
    "file_exists":            [Dimension.REPRODUCIBILITY],
    "selection_count":        [Dimension.SEMANTIC_GROUNDING],
    "selection_visible":      [Dimension.SEMANTIC_GROUNDING],
    "distinct_chain_colors":  [Dimension.SEMANTIC_GROUNDING],
    "no_runtime_errors":      [Dimension.VERIFICATION_RECOVERY],
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_dimensions.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add vmdbench/spec/dimensions.py vmdbench/tests/test_dimensions.py
git commit -m "feat(vmdbench): add LLM-nativeness dimensions, weights, kind map" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Canonical `SceneState` + PROBE-line parser

**Files:**
- Create: `vmdbench/env/scene_state.py`
- Test: `vmdbench/tests/test_scene_state.py`

This task is pure data + parsing (no VMD). It parses the `PROBE> key=value` lines (format verified against VMD 1.9.4a57) into a `SceneState`.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.env.scene_state import SceneState, parse_probe_lines

SAMPLE = """\
Info) startup junk ignored
PROBE> mol_list=0
PROBE> mol_top=0
PROBE> mol0_name=mini.pdb
PROBE> mol0_filename=/tmp/mini.pdb
PROBE> mol0_filetype=pdb
PROBE> mol0_numatoms=9
PROBE> mol0_numframes=1
PROBE> mol0_frame=0
PROBE> mol0_numreps=2
PROBE> rep0_0_style=NewCartoon 0.300000 12.000000 4.500000 0
PROBE> rep0_0_selection=protein
PROBE> rep0_0_color=Chain
PROBE> rep0_0_material=Opaque
PROBE> rep0_0_visible=1
PROBE> rep0_1_style=VDW 1.000000 12.000000
PROBE> rep0_1_selection=water
PROBE> rep0_1_color=ColorID 1
PROBE> rep0_1_material=Opaque
PROBE> rep0_1_visible=0
PROBE> display_background=white
PROBE> display_projection=Orthographic
PROBE> axes_location=Off
PROBE> view_center={3.9 2.6 1.5}
PROBE> view_rotate_matrix={{1 0 0 0} {0 1 0 0} {0 0 1 0} {0 0 0 1}}
PROBE> view_scale_matrix={{0.13 0 0 0} {0 0.13 0 0} {0 0 0.13 0} {0 0 0 1}}
PROBE> sel0_count=2
PROBE> sel1_error=atomselect: cannot parse selection text: resname (
ERROR) Could not read file /nonexistent.pdb
"""


class SceneStateParseTests(unittest.TestCase):
    def setUp(self):
        self.scene = parse_probe_lines(SAMPLE, selection_texts=["water", "resname ("])

    def test_molecule_parsed(self):
        self.assertEqual(len(self.scene.molecules), 1)
        m = self.scene.molecules[0]
        self.assertEqual(m.id, 0)
        self.assertEqual(m.num_atoms, 9)
        self.assertEqual(m.num_frames, 1)
        self.assertEqual(m.name, "mini.pdb")

    def test_reps_parsed(self):
        self.assertEqual(len(self.scene.representations), 2)
        r0 = self.scene.representations[0]
        self.assertEqual(r0.style_name, "NewCartoon")
        self.assertEqual(r0.selection, "protein")
        self.assertEqual(r0.color, "Chain")
        self.assertTrue(r0.visible)
        self.assertFalse(self.scene.representations[1].visible)

    def test_display_parsed(self):
        self.assertEqual(self.scene.display.background, "white")
        self.assertEqual(self.scene.display.projection, "Orthographic")
        self.assertEqual(self.scene.display.axes, "Off")

    def test_selection_counts(self):
        self.assertEqual(self.scene.selections["water"], 2)
        self.assertNotIn("resname (", self.scene.selections)  # errored selection omitted

    def test_errors_collected(self):
        joined = " ".join(self.scene.errors)
        self.assertIn("Could not read file", joined)
        self.assertIn("cannot parse selection text", joined)

    def test_camera_changed_default_false(self):
        # identity rotate + this scale is the loaded default; helper reports not-changed
        self.assertFalse(self.scene.camera_changed())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_scene_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vmdbench.env.scene_state'`

- [ ] **Step 3: Write the implementation** (`vmdbench/env/scene_state.py`)

```python
from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict

_PROBE = re.compile(r"^PROBE>\s*(?P<key>[^=]+)=(?P<val>.*)$")
_MOL = re.compile(r"^mol(?P<id>\d+)_(?P<attr>name|filename|filetype|numatoms|numframes|frame|numreps)$")
_REP = re.compile(r"^rep(?P<mol>\d+)_(?P<rep>\d+)_(?P<attr>style|selection|color|material|visible)$")
_SEL = re.compile(r"^sel(?P<idx>\d+)_(?P<attr>count|error)$")

_IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


@dataclass
class Molecule:
    id: int
    name: str = ""
    filename: str = ""
    filetype: str = ""
    num_atoms: int = 0
    num_frames: int = 0
    cur_frame: int = 0


@dataclass
class Representation:
    mol_id: int
    rep_id: int
    style: str = ""        # full style string incl. params, e.g. "NewCartoon 0.3 ..."
    selection: str = ""
    color: str = ""        # coloring method, e.g. "Chain" or "ColorID 1"
    material: str = ""
    visible: bool = True

    @property
    def style_name(self) -> str:
        return self.style.split()[0] if self.style else ""


@dataclass
class Display:
    background: str = ""
    projection: str = ""
    axes: str = ""


@dataclass
class SceneState:
    molecules: list[Molecule] = field(default_factory=list)
    representations: list[Representation] = field(default_factory=list)
    selections: dict[str, int] = field(default_factory=dict)
    display: Display = field(default_factory=Display)
    camera: dict = field(default_factory=dict)   # {"center":[...], "rotate_matrix":[[...]], "scale_matrix":[[...]]}
    rendered_images: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def reps_for(self, selection: str) -> list[Representation]:
        return [r for r in self.representations if r.selection == selection]

    def camera_changed(self) -> bool:
        rot = self.camera.get("rotate_matrix")
        return rot is not None and rot != _IDENTITY


def _parse_tcl_matrix(s: str) -> list:
    """Parse VMD brace nesting like '{{1 0 0 0} {0 1 0 0}}' or '{3.9 2.6 1.5}' into nested float lists."""
    s = s.strip()
    if s.startswith("{{"):
        rows = re.findall(r"\{([^{}]*)\}", s)
        return [[float(x) for x in row.split()] for row in rows]
    inner = s.strip("{}")
    return [float(x) for x in inner.split()] if inner else []


def parse_probe_lines(stdout: str, selection_texts: list[str] | None = None) -> SceneState:
    selection_texts = selection_texts or []
    scene = SceneState()
    mols: dict[int, Molecule] = {}
    reps: dict[tuple[int, int], Representation] = {}

    for line in stdout.splitlines():
        line = line.rstrip()
        if line.startswith("ERROR)"):
            scene.errors.append(line[len("ERROR)"):].strip())
            continue
        m = _PROBE.match(line)
        if not m:
            continue
        key, val = m.group("key").strip(), m.group("val").strip()

        if key == "body_error":
            scene.errors.append(val)
            continue
        mm = _MOL.match(key)
        if mm:
            mol = mols.setdefault(int(mm["id"]), Molecule(id=int(mm["id"])))
            attr = mm["attr"]
            if attr == "name": mol.name = val
            elif attr == "filename": mol.filename = val
            elif attr == "filetype": mol.filetype = val
            elif attr == "numatoms": mol.num_atoms = int(val or 0)
            elif attr == "numframes": mol.num_frames = int(val or 0)
            elif attr == "frame": mol.cur_frame = int(val or 0)
            continue
        rm = _REP.match(key)
        if rm:
            rk = (int(rm["mol"]), int(rm["rep"]))
            rep = reps.setdefault(rk, Representation(mol_id=rk[0], rep_id=rk[1]))
            attr = rm["attr"]
            if attr == "style": rep.style = val
            elif attr == "selection": rep.selection = val
            elif attr == "color": rep.color = val
            elif attr == "material": rep.material = val
            elif attr == "visible": rep.visible = (val.strip() == "1")
            continue
        sm = _SEL.match(key)
        if sm:
            idx = int(sm["idx"])
            text = selection_texts[idx] if idx < len(selection_texts) else f"sel{idx}"
            if sm["attr"] == "count":
                scene.selections[text] = int(val or 0)
            else:  # error
                scene.errors.append(val)
            continue
        if key == "display_background": scene.display.background = val
        elif key == "display_projection": scene.display.projection = val
        elif key == "axes_location": scene.display.axes = val
        elif key == "view_center": scene.camera["center"] = _parse_tcl_matrix(val)
        elif key == "view_rotate_matrix": scene.camera["rotate_matrix"] = _parse_tcl_matrix(val)
        elif key == "view_scale_matrix": scene.camera["scale_matrix"] = _parse_tcl_matrix(val)

    scene.molecules = [mols[k] for k in sorted(mols)]
    scene.representations = [reps[k] for k in sorted(reps)]
    return scene
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_scene_state.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add vmdbench/env/scene_state.py vmdbench/tests/test_scene_state.py
git commit -m "feat(vmdbench): canonical SceneState + PROBE-line parser" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `HeadlessVMDEnv` — run Tcl in live VMD, return `SceneState`

**Files:**
- Create: `vmdbench/env/headless_vmd.py`
- Test: `vmdbench/tests/test_headless_vmd.py` (LIVE — launches VMD)

The env wraps a Tcl body in: an introspection proc (verified idioms), a `catch` around the body (so a runtime error is recorded but introspection still runs), a guarded introspection call over all loaded molecules + the requested selections, and `quit`. It runs `vmd -dispdev text -eofexit -e <script>` in a chosen workdir and parses stdout.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
import sys, unittest, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.env.headless_vmd import HeadlessVMDEnv
from vmdbench.tests.fixtures import write_mini_pdb, EXPECTED_NUMATOMS


class HeadlessVMDTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.pdb = write_mini_pdb(self.work / "mini.pdb")
        self.env = HeadlessVMDEnv()

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_and_introspect(self):
        body = (
            'mol new "mini.pdb" waitfor all\n'
            'mol modstyle 0 0 NewCartoon\n'
            'mol modselect 0 0 protein\n'
            'mol modcolor 0 0 Chain\n'
        )
        res = self.env.run(body, workdir=self.work, selection_texts=["water", "protein"])
        self.assertEqual(res.returncode, 0)
        self.assertEqual(len(res.scene.molecules), 1)
        self.assertEqual(res.scene.molecules[0].num_atoms, EXPECTED_NUMATOMS)
        self.assertEqual(res.scene.representations[0].style_name, "NewCartoon")
        self.assertEqual(res.scene.representations[0].selection, "protein")
        self.assertEqual(res.scene.selections["water"], 2)
        self.assertGreater(res.scene.selections["protein"], 0)
        self.assertEqual(res.scene.errors, [])

    def test_runtime_error_recorded_but_introspection_runs(self):
        body = (
            'mol new "mini.pdb" waitfor all\n'
            'mol new "/nonexistent/path/nope.pdb" waitfor all\n'  # raises, caught
        )
        res = self.env.run(body, workdir=self.work, selection_texts=[])
        self.assertTrue(any("nope.pdb" in e or "Unable to load" in e or "Could not read" in e
                            for e in res.scene.errors), res.scene.errors)
        self.assertEqual(len(res.scene.molecules), 1)  # first load survived; bad load left no orphan

    def test_tachyon_render_produces_real_file(self):
        body = (
            'mol new "mini.pdb" waitfor all\n'
            'render TachyonInternal out.tga\n'
        )
        res = self.env.run(body, workdir=self.work, selection_texts=[])
        out = self.work / "out.tga"
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 1000)  # real render, not the 18-byte snapshot stub


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_headless_vmd.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vmdbench.env.headless_vmd'`

- [ ] **Step 3: Write the implementation** (`vmdbench/env/headless_vmd.py`)

```python
from __future__ import annotations
import shutil, subprocess, tempfile
from dataclasses import dataclass
from pathlib import Path

from vmdbench.env.scene_state import SceneState, parse_probe_lines

# Introspection idioms verified against VMD 1.9.4a57 (macOS, -dispdev text).
_INTROSPECT_PROC = r"""
proc __vb_introspect {sels} {
    set mols [molinfo list]
    puts "PROBE> mol_list=$mols"
    if {[llength $mols] == 0} { return }
    puts "PROBE> mol_top=[molinfo top]"
    foreach m $mols {
        puts "PROBE> mol${m}_name=[molinfo $m get name]"
        puts "PROBE> mol${m}_filename=[lindex [molinfo $m get filename] 0]"
        puts "PROBE> mol${m}_filetype=[lindex [molinfo $m get filetype] 0]"
        puts "PROBE> mol${m}_numatoms=[molinfo $m get numatoms]"
        puts "PROBE> mol${m}_numframes=[molinfo $m get numframes]"
        puts "PROBE> mol${m}_frame=[molinfo $m get frame]"
        set nreps [molinfo $m get numreps]
        puts "PROBE> mol${m}_numreps=$nreps"
        for {set i 0} {$i < $nreps} {incr i} {
            set f [molinfo $m get "{rep $i} {selection $i} {color $i} {material $i}"]
            puts "PROBE> rep${m}_${i}_style=[lindex $f 0]"
            puts "PROBE> rep${m}_${i}_selection=[lindex $f 1]"
            puts "PROBE> rep${m}_${i}_color=[lindex $f 2]"
            puts "PROBE> rep${m}_${i}_material=[lindex $f 3]"
            puts "PROBE> rep${m}_${i}_visible=[mol showrep $m $i]"
        }
    }
    puts "PROBE> display_background=[color Display Background]"
    puts "PROBE> display_projection=[display get projection]"
    puts "PROBE> axes_location=[axes location]"
    set top [molinfo top]
    puts "PROBE> view_center=[molinfo $top get center]"
    puts "PROBE> view_rotate_matrix=[molinfo $top get rotate_matrix]"
    puts "PROBE> view_scale_matrix=[molinfo $top get scale_matrix]"
    set i 0
    foreach st $sels {
        if {[catch {set s [atomselect $top $st]; set n [$s num]; $s delete} e]} {
            puts "PROBE> sel${i}_error=$e"
        } else {
            puts "PROBE> sel${i}_count=$n"
        }
        incr i
    }
}
"""


@dataclass
class VmdRunResult:
    scene: SceneState
    stdout: str
    stderr: str
    returncode: int


def _tcl_list(items: list[str]) -> str:
    # VMD selections rarely contain braces; wrap each in braces. Document the limitation.
    return "[list " + " ".join("{" + s + "}" for s in items) + "]"


class HeadlessVMDEnv:
    def __init__(self, vmd_bin: str = "vmd", timeout_s: int = 180):
        if shutil.which(vmd_bin) is None:
            raise RuntimeError(f"VMD binary '{vmd_bin}' not found on PATH")
        self.vmd_bin = vmd_bin
        self.timeout_s = timeout_s

    def _wrap(self, body: str, selection_texts: list[str]) -> str:
        sels = _tcl_list(selection_texts)
        return (
            _INTROSPECT_PROC
            + f"\nset __vb_sels {sels}\n"
            + "if {[catch {\n" + body + "\n} __vb_err]} { puts \"PROBE> body_error=$__vb_err\" }\n"
            + "__vb_introspect $__vb_sels\n"
            + "quit\n"
        )

    def run(self, body: str, workdir: Path, selection_texts: list[str] | None = None) -> VmdRunResult:
        selection_texts = selection_texts or []
        workdir = Path(workdir)
        script = workdir / "__vb_run.tcl"
        script.write_text(self._wrap(body, selection_texts))
        proc = subprocess.run(
            [self.vmd_bin, "-dispdev", "text", "-eofexit", "-e", str(script)],
            cwd=str(workdir), capture_output=True, text=True, timeout=self.timeout_s,
        )
        scene = parse_probe_lines(proc.stdout, selection_texts=selection_texts)
        return VmdRunResult(scene=scene, stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_headless_vmd.py -v`
Expected: PASS (3 tests). If `test_load_and_introspect` shows an empty `errors` assertion failing because a benign `Warning)`-driven line leaked in, inspect `res.stdout` — only lines starting `ERROR)` or `body_error` should populate `errors`; adjust the parser only if a genuine error pattern was missed.

- [ ] **Step 5: Commit**

```bash
git add vmdbench/env/headless_vmd.py vmdbench/tests/test_headless_vmd.py
git commit -m "feat(vmdbench): HeadlessVMDEnv runs Tcl in live VMD and parses SceneState" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Assertion vocabulary — validation, registry, `custom_check` hook

**Files:**
- Create: `vmdbench/spec/assertions.py`
- Test: `vmdbench/tests/test_assertions.py`

This defines the **closed set** of assertion kinds, validates an assertion's shape, and provides the `custom_check` escape hatch via a registry of reviewed functions. (Evaluation logic lives in `verify/checks.py`, Task 7 — this task is the contract.)

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.assertions import (
    KNOWN_KINDS, validate_assertion, AssertionError as VBAssertionError,
    register_custom_check, CUSTOM_CHECKS,
)


class AssertionContractTests(unittest.TestCase):
    def test_known_kinds_closed_set(self):
        for k in ["molecule_loaded", "representation_exists", "selection_count",
                  "selection_visible", "display_property", "file_rendered",
                  "no_runtime_errors", "distinct_chain_colors", "frames_loaded",
                  "camera_changed", "file_exists", "representation_count", "custom_check"]:
            self.assertIn(k, KNOWN_KINDS)

    def test_validate_good_assertion(self):
        validate_assertion({"kind": "representation_exists",
                            "where": {"selection": "protein", "style": "NewCartoon"}})

    def test_unknown_kind_rejected(self):
        with self.assertRaises(VBAssertionError):
            validate_assertion({"kind": "make_it_pretty", "where": {}})

    def test_missing_where_rejected(self):
        with self.assertRaises(VBAssertionError):
            validate_assertion({"kind": "representation_exists"})

    def test_custom_check_requires_registered_ref(self):
        with self.assertRaises(VBAssertionError):
            validate_assertion({"kind": "custom_check", "where": {"ref": "not_registered"}})
        register_custom_check("my_reviewed_check", lambda scene, ctx, where: True)
        validate_assertion({"kind": "custom_check", "where": {"ref": "my_reviewed_check"}})
        self.assertIn("my_reviewed_check", CUSTOM_CHECKS)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_assertions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vmdbench.spec.assertions'`

- [ ] **Step 3: Write the implementation** (`vmdbench/spec/assertions.py`)

```python
from __future__ import annotations
from typing import Callable

from vmdbench.spec.dimensions import KIND_DIMENSIONS


class AssertionError(Exception):
    """Raised when a task-card assertion is malformed (distinct from builtins.AssertionError)."""


# Closed set: state-assertion kinds (KIND_DIMENSIONS) + the custom_check escape hatch.
KNOWN_KINDS: frozenset[str] = frozenset(set(KIND_DIMENSIONS) | {"custom_check"})

# Registry of reviewed custom-check functions: name -> fn(scene, ctx, where) -> bool
CUSTOM_CHECKS: dict[str, Callable] = {}


def register_custom_check(name: str, fn: Callable) -> None:
    CUSTOM_CHECKS[name] = fn


def validate_assertion(a: dict) -> None:
    if not isinstance(a, dict):
        raise AssertionError(f"assertion must be a mapping, got {type(a).__name__}")
    kind = a.get("kind")
    if kind not in KNOWN_KINDS:
        raise AssertionError(f"unknown assertion kind: {kind!r}; allowed: {sorted(KNOWN_KINDS)}")
    if "where" not in a or not isinstance(a["where"], dict):
        raise AssertionError(f"assertion {kind!r} missing 'where' mapping")
    if kind == "custom_check":
        ref = a["where"].get("ref")
        if ref not in CUSTOM_CHECKS:
            raise AssertionError(
                f"custom_check ref {ref!r} not registered; register it via register_custom_check()"
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_assertions.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add vmdbench/spec/assertions.py vmdbench/tests/test_assertions.py
git commit -m "feat(vmdbench): closed assertion vocabulary + custom_check registry" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `TaskCard` — load + validate YAML cards

**Files:**
- Create: `vmdbench/spec/task_card.py`
- Test: `vmdbench/tests/test_task_card.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
import sys, unittest, tempfile, textwrap
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.task_card import TaskCard, load_card, CardError

GOOD = textwrap.dedent("""\
    task_id: viz_demo_001
    category: visualization
    bucket: synthesis
    difficulty: easy
    dimensions: [actionability, semantic_grounding]
    initial_state:
      files: [fixtures/mini.pdb]
      pdb: MINI
      molecules_loaded: false
    allowed_interface: [raw_tcl]
    user_prompt: Load and show protein as cartoon.
    verify:
      required:
        - {kind: molecule_loaded, where: {pdb: MINI}}
        - {kind: representation_exists, where: {selection: protein, style: NewCartoon}}
      optional:
        - {kind: no_runtime_errors, where: {}}
    reproducibility:
      exports: [tcl]
      replay_clean: true
""")


class TaskCardTests(unittest.TestCase):
    def _write(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / "card.yaml"
        p.write_text(text)
        return p

    def test_load_good_card(self):
        card = load_card(self._write(GOOD))
        self.assertEqual(card.task_id, "viz_demo_001")
        self.assertEqual(card.category, "visualization")
        self.assertEqual(len(card.required), 2)
        self.assertEqual(len(card.optional), 1)
        self.assertEqual([d.value for d in card.dimensions], ["actionability", "semantic_grounding"])

    def test_unknown_assertion_kind_rejected(self):
        bad = GOOD.replace("kind: molecule_loaded", "kind: bogus_kind")
        with self.assertRaises(CardError):
            load_card(self._write(bad))

    def test_missing_required_field_rejected(self):
        bad = GOOD.replace("task_id: viz_demo_001\n", "")
        with self.assertRaises(CardError):
            load_card(self._write(bad))

    def test_selection_texts_collected(self):
        card = load_card(self._write(GOOD))
        self.assertEqual(card.selection_texts(), [])  # no selection_count/visible in this card


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_task_card.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vmdbench.spec.task_card'`

- [ ] **Step 3: Write the implementation** (`vmdbench/spec/task_card.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from vmdbench.spec.assertions import validate_assertion, AssertionError as VBAssertionError
from vmdbench.spec.dimensions import Dimension

_REQUIRED_FIELDS = ["task_id", "category", "user_prompt", "verify"]
_SELECTION_KINDS = {"selection_count", "selection_visible"}


class CardError(Exception):
    pass


@dataclass
class TaskCard:
    task_id: str
    category: str
    user_prompt: str
    bucket: str = ""
    difficulty: str = "easy"
    dimensions: list[Dimension] = field(default_factory=list)
    initial_state: dict = field(default_factory=dict)
    allowed_interface: list[str] = field(default_factory=lambda: ["raw_tcl"])
    required: list[dict] = field(default_factory=list)
    optional: list[dict] = field(default_factory=list)
    observe: dict = field(default_factory=dict)
    reproducibility: dict = field(default_factory=dict)
    human_review: dict = field(default_factory=dict)
    source_path: str = ""

    def selection_texts(self) -> list[str]:
        out: list[str] = []
        for a in self.required + self.optional:
            if a.get("kind") in _SELECTION_KINDS:
                sel = a.get("where", {}).get("selection")
                if sel and sel not in out:
                    out.append(sel)
        return out


def load_card(path: str | Path) -> TaskCard:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise CardError(f"{path}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise CardError(f"{path}: card must be a YAML mapping")

    for f in _REQUIRED_FIELDS:
        if f not in data:
            raise CardError(f"{path}: missing required field '{f}'")

    verify = data["verify"] or {}
    required = verify.get("required", []) or []
    optional = verify.get("optional", []) or []
    if not required:
        raise CardError(f"{path}: verify.required must contain at least one assertion")

    for a in required + optional:
        try:
            validate_assertion(a)
        except VBAssertionError as e:
            raise CardError(f"{path}: {e}") from e

    dims = []
    for d in data.get("dimensions", []) or []:
        try:
            dims.append(Dimension(d))
        except ValueError as e:
            raise CardError(f"{path}: unknown dimension {d!r}") from e

    return TaskCard(
        task_id=data["task_id"],
        category=data["category"],
        user_prompt=data["user_prompt"],
        bucket=data.get("bucket", ""),
        difficulty=data.get("difficulty", "easy"),
        dimensions=dims,
        initial_state=data.get("initial_state", {}) or {},
        allowed_interface=data.get("allowed_interface", ["raw_tcl"]),
        required=required,
        optional=optional,
        observe=data.get("observe", {}) or {},
        reproducibility=data.get("reproducibility", {}) or {},
        human_review=data.get("human_review", {}) or {},
        source_path=str(path),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_task_card.py -v`
Expected: PASS (4 tests). If `import yaml` fails, install it: `python -m pip install pyyaml`.

- [ ] **Step 5: Commit**

```bash
git add vmdbench/spec/task_card.py vmdbench/tests/test_task_card.py
git commit -m "feat(vmdbench): TaskCard loader with assertion + dimension validation" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Three exemplar task cards + a load-all test

**Files:**
- Create: `vmdbench/fixtures/mini.pdb`
- Create: `vmdbench/tasks/viz/viz_protein_dna_001.yaml`
- Create: `vmdbench/tasks/select/select_water_count_001.yaml`
- Create: `vmdbench/tasks/traj/traj_render_001.yaml`
- Test: `vmdbench/tests/test_cards_load.py`

These three cards exercise three categories and all the Plan-1 assertion kinds. They run against the committed `mini.pdb` fixture so they are hermetic (no network). Each card's `initial_state.files` lists fixture paths **relative to `vmdbench/fixtures/`**; `prepare_workdir` (Task 8) copies them into the run workdir by basename, so oracle Tcl can `mol new mini.pdb`.

- [ ] **Step 1: Materialize the committed fixture PDB**

```bash
cd /Users/pinhaogu/Documents/GitHub/PyMolAI/vmd_ai
python -c "from vmdbench.tests.fixtures import write_mini_pdb; write_mini_pdb('vmdbench/fixtures/mini.pdb')"
```
(Creates `vmdbench/fixtures/mini.pdb`. Verify it has 9 ATOM/HETATM lines + END.)

- [ ] **Step 2: Write `viz/viz_protein_dna_001.yaml`**

```yaml
task_id: viz_protein_dna_001
category: visualization
bucket: synthesis
difficulty: easy
dimensions: [actionability, semantic_grounding, reproducibility]
initial_state:
  files: [mini.pdb]
  molecules_loaded: false
allowed_interface: [raw_tcl]
user_prompt: >
  Load the structure, show protein as NewCartoon, nucleic as Licorice, color
  protein by chain, hide water, set a white background, render to out.tga.
verify:
  required:
    - {kind: molecule_loaded,       where: {}}
    - {kind: representation_exists, where: {selection: protein, style: NewCartoon}}
    - {kind: representation_exists, where: {selection: nucleic, style: Licorice}}
    - {kind: selection_visible,     where: {selection: water}, visible: false}
    - {kind: display_property,      where: {bg_color: white}}
    - {kind: file_rendered,         where: {path: out.tga, must_be_image: true, min_bytes: 1000}}
  optional:
    - {kind: distinct_chain_colors, where: {min_distinct: 2}}
    - {kind: no_runtime_errors,     where: {}}
reproducibility:
  exports: [tcl]
  replay_clean: true
```

- [ ] **Step 3: Write `select/select_water_count_001.yaml`**

```yaml
task_id: select_water_count_001
category: selection
bucket: lookup
difficulty: easy
dimensions: [semantic_grounding]
initial_state:
  files: [mini.pdb]
  molecules_loaded: false
allowed_interface: [raw_tcl]
user_prompt: Load the structure (the gold water count is regenerated from the oracle).
verify:
  required:
    - {kind: molecule_loaded, where: {}}
    - {kind: selection_count, where: {selection: water, expect: 2}}
    - {kind: selection_count, where: {selection: protein, min: 1}}
  optional:
    - {kind: no_runtime_errors, where: {}}
```

- [ ] **Step 4: Write `traj/traj_render_001.yaml`**

```yaml
task_id: traj_render_001
category: trajectory
bucket: operational
difficulty: easy
dimensions: [actionability, reproducibility]
initial_state:
  files: [mini.pdb]
  molecules_loaded: false
allowed_interface: [raw_tcl]
user_prompt: Load the structure and render a publication image with white background to out.tga.
verify:
  required:
    - {kind: molecule_loaded,  where: {}}
    - {kind: frames_loaded,    where: {min: 1}}
    - {kind: display_property, where: {bg_color: white}}
    - {kind: file_rendered,    where: {path: out.tga, must_be_image: true, min_bytes: 1000}}
  optional:
    - {kind: no_runtime_errors, where: {}}
reproducibility:
  exports: [tcl]
  replay_clean: true
```

- [ ] **Step 5: Write the load-all test** (`vmdbench/tests/test_cards_load.py`)

```python
from __future__ import annotations
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.task_card import load_card

TASKS_DIR = ROOT / "vmdbench" / "tasks"


class CardsLoadTests(unittest.TestCase):
    def test_all_cards_load_and_validate(self):
        cards = list(TASKS_DIR.rglob("*.yaml"))
        self.assertGreaterEqual(len(cards), 3)
        ids = []
        for p in cards:
            card = load_card(p)
            ids.append(card.task_id)
        self.assertEqual(len(ids), len(set(ids)), f"duplicate task_ids: {ids}")

    def test_select_card_collects_selection_texts(self):
        card = load_card(TASKS_DIR / "select" / "select_water_count_001.yaml")
        self.assertEqual(set(card.selection_texts()), {"water", "protein"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: Run the test**

Run: `python -m pytest vmdbench/tests/test_cards_load.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add vmdbench/fixtures vmdbench/tasks vmdbench/tests/test_cards_load.py
git commit -m "feat(vmdbench): three exemplar task cards + committed fixture" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Assertion evaluators (`verify/checks.py`)

**Files:**
- Create: `vmdbench/verify/checks.py`
- Test: `vmdbench/tests/test_checks.py`

Each evaluator takes `(where: dict, scene: SceneState, ctx: CheckContext)` and returns a `CheckResult(passed, observed)`. `ctx` carries the run workdir (for file checks) and the assertion's top-level fields (e.g. `visible`). Evaluators are registered by kind.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
import sys, unittest, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.env.scene_state import SceneState, Molecule, Representation, Display
from vmdbench.verify.checks import evaluate, CheckContext


def _scene():
    return SceneState(
        molecules=[Molecule(id=0, name="mini.pdb", num_atoms=9, num_frames=1)],
        representations=[
            Representation(mol_id=0, rep_id=0, style="NewCartoon 0.3", selection="protein", color="Chain", visible=True),
            Representation(mol_id=0, rep_id=1, style="VDW 1.0", selection="water", color="ColorID 1", visible=False),
        ],
        selections={"water": 2, "protein": 5},
        display=Display(background="white", projection="Orthographic", axes="Off"),
        camera={"rotate_matrix": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]},
        errors=[],
    )


class ChecksTests(unittest.TestCase):
    def setUp(self):
        self.scene = _scene()
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = CheckContext(workdir=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def _ev(self, a):
        return evaluate(a, self.scene, self.ctx)

    def test_molecule_loaded(self):
        self.assertTrue(self._ev({"kind": "molecule_loaded", "where": {}}).passed)

    def test_representation_exists_match_and_miss(self):
        self.assertTrue(self._ev({"kind": "representation_exists",
                                  "where": {"selection": "protein", "style": "NewCartoon"}}).passed)
        self.assertFalse(self._ev({"kind": "representation_exists",
                                   "where": {"selection": "protein", "style": "VDW"}}).passed)

    def test_selection_visible_false(self):
        self.assertTrue(self._ev({"kind": "selection_visible",
                                  "where": {"selection": "water"}, "visible": False}).passed)

    def test_selection_count_expect(self):
        self.assertTrue(self._ev({"kind": "selection_count", "where": {"selection": "water", "expect": 2}}).passed)
        self.assertFalse(self._ev({"kind": "selection_count", "where": {"selection": "water", "expect": 3}}).passed)
        self.assertTrue(self._ev({"kind": "selection_count", "where": {"selection": "protein", "min": 1}}).passed)

    def test_display_property(self):
        self.assertTrue(self._ev({"kind": "display_property", "where": {"bg_color": "white"}}).passed)
        self.assertFalse(self._ev({"kind": "display_property", "where": {"bg_color": "black"}}).passed)

    def test_distinct_chain_colors(self):
        self.assertTrue(self._ev({"kind": "distinct_chain_colors", "where": {"min_distinct": 2}}).passed)

    def test_no_runtime_errors(self):
        self.assertTrue(self._ev({"kind": "no_runtime_errors", "where": {}}).passed)
        self.scene.errors.append("boom")
        self.assertFalse(self._ev({"kind": "no_runtime_errors", "where": {}}).passed)

    def test_frames_loaded(self):
        self.assertTrue(self._ev({"kind": "frames_loaded", "where": {"min": 1}}).passed)

    def test_file_rendered(self):
        target = self.ctx.workdir / "out.tga"
        target.write_bytes(b"\x00" * 2048)
        self.assertTrue(self._ev({"kind": "file_rendered",
                                  "where": {"path": "out.tga", "min_bytes": 1000}}).passed)
        self.assertFalse(self._ev({"kind": "file_rendered",
                                   "where": {"path": "missing.tga", "min_bytes": 1000}}).passed)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_checks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vmdbench.verify.checks'`

- [ ] **Step 3: Write the implementation** (`vmdbench/verify/checks.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from vmdbench.env.scene_state import SceneState
from vmdbench.spec.assertions import CUSTOM_CHECKS


@dataclass
class CheckContext:
    workdir: Path


@dataclass
class CheckResult:
    kind: str
    passed: bool
    observed: Any = None
    where: dict = field(default_factory=dict)


_EVALUATORS: dict[str, Callable[[dict, SceneState, CheckContext, dict], CheckResult]] = {}


def _register(kind):
    def deco(fn):
        _EVALUATORS[kind] = fn
        return fn
    return deco


def evaluate(assertion: dict, scene: SceneState, ctx: CheckContext) -> CheckResult:
    kind = assertion["kind"]
    where = assertion.get("where", {})
    fn = _EVALUATORS.get(kind)
    if fn is None:
        raise KeyError(f"no evaluator for assertion kind {kind!r}")
    return fn(where, scene, ctx, assertion)


@_register("molecule_loaded")
def _molecule_loaded(where, scene, ctx, a):
    if not scene.molecules:
        return CheckResult("molecule_loaded", False, observed=0, where=where)
    pdb = where.get("pdb")
    if pdb:
        ok = any(pdb.lower() in (m.name or "").lower() or pdb.lower() in (m.filename or "").lower()
                 for m in scene.molecules)
        return CheckResult("molecule_loaded", ok, observed=[m.name for m in scene.molecules], where=where)
    return CheckResult("molecule_loaded", True, observed=len(scene.molecules), where=where)


@_register("representation_exists")
def _rep_exists(where, scene, ctx, a):
    sel = where.get("selection")
    style = where.get("style")
    color = where.get("color")
    material = where.get("material")
    want_vis = where.get("visible")
    matches = []
    for r in scene.representations:
        if sel is not None and r.selection != sel: continue
        if style is not None and r.style_name != style: continue
        if color is not None and color.lower() not in r.color.lower(): continue
        if material is not None and r.material != material: continue
        if want_vis is not None and r.visible != bool(want_vis): continue
        matches.append((r.selection, r.style_name, r.color))
    return CheckResult("representation_exists", bool(matches), observed=matches or
                       [(r.selection, r.style_name) for r in scene.representations], where=where)


@_register("representation_count")
def _rep_count(where, scene, ctx, a):
    n = len(scene.representations)
    ok = True
    if "min" in where: ok = ok and n >= where["min"]
    if "max" in where: ok = ok and n <= where["max"]
    if "expect" in where: ok = ok and n == where["expect"]
    return CheckResult("representation_count", ok, observed=n, where=where)


@_register("selection_visible")
def _sel_visible(where, scene, ctx, a):
    sel = where["selection"]
    want = bool(a.get("visible", True))
    shown = any(r.selection == sel and r.visible for r in scene.representations)
    return CheckResult("selection_visible", shown == want, observed=shown, where=where)


@_register("selection_count")
def _sel_count(where, scene, ctx, a):
    sel = where["selection"]
    if sel not in scene.selections:
        return CheckResult("selection_count", False, observed=f"selection {sel!r} not evaluated", where=where)
    n = scene.selections[sel]
    ok = True
    if "expect" in where: ok = ok and n == where["expect"]
    if "min" in where: ok = ok and n >= where["min"]
    if "max" in where: ok = ok and n <= where["max"]
    if where.get("nonempty"): ok = ok and n > 0
    return CheckResult("selection_count", ok, observed=n, where=where)


@_register("display_property")
def _display(where, scene, ctx, a):
    ok = True
    if "bg_color" in where: ok = ok and scene.display.background.lower() == where["bg_color"].lower()
    if "projection" in where: ok = ok and scene.display.projection.lower() == where["projection"].lower()
    if "axes" in where: ok = ok and scene.display.axes.lower() == where["axes"].lower()
    return CheckResult("display_property", ok,
                       observed={"bg": scene.display.background, "proj": scene.display.projection,
                                 "axes": scene.display.axes}, where=where)


@_register("frames_loaded")
def _frames(where, scene, ctx, a):
    n = max((m.num_frames for m in scene.molecules), default=0)
    ok = True
    if "min" in where: ok = ok and n >= where["min"]
    if "max" in where: ok = ok and n <= where["max"]
    return CheckResult("frames_loaded", ok, observed=n, where=where)


@_register("camera_changed")
def _camera(where, scene, ctx, a):
    changed = scene.camera_changed()
    want = where.get("from_default", True)
    return CheckResult("camera_changed", changed == bool(want), observed=changed, where=where)


@_register("distinct_chain_colors")
def _distinct_colors(where, scene, ctx, a):
    min_distinct = where.get("min_distinct", 2)
    by_chain = any(r.color.lower() == "chain" for r in scene.representations)
    distinct = len({r.color for r in scene.representations if r.visible})
    ok = by_chain or distinct >= min_distinct
    return CheckResult("distinct_chain_colors", ok, observed={"by_chain": by_chain, "distinct": distinct}, where=where)


@_register("no_runtime_errors")
def _no_errors(where, scene, ctx, a):
    return CheckResult("no_runtime_errors", not scene.errors, observed=scene.errors, where=where)


def _is_image(path: Path) -> bool:
    try:
        head = path.read_bytes()[:8]
    except OSError:
        return False
    # TGA has no strong magic; accept PNG magic, or non-trivial TGA (footer/size handled by min_bytes).
    if head.startswith(b"\x89PNG"): return True
    return path.suffix.lower() in {".tga", ".png", ".ppm", ".bmp"}


@_register("file_rendered")
def _file_rendered(where, scene, ctx, a):
    path = ctx.workdir / where["path"]
    min_bytes = where.get("min_bytes", 1000)
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    ok = exists and size >= min_bytes
    if where.get("must_be_image"):
        ok = ok and _is_image(path)
    return CheckResult("file_rendered", ok, observed={"exists": exists, "size": size}, where=where)


@_register("file_exists")
def _file_exists(where, scene, ctx, a):
    path = ctx.workdir / where["path"]
    return CheckResult("file_exists", path.exists(), observed=path.exists(), where=where)


@_register("custom_check")
def _custom(where, scene, ctx, a):
    fn = CUSTOM_CHECKS[where["ref"]]
    return CheckResult("custom_check", bool(fn(scene, ctx, where)), observed=where.get("ref"), where=where)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_checks.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add vmdbench/verify/checks.py vmdbench/tests/test_checks.py
git commit -m "feat(vmdbench): state-assertion evaluators" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Oracle adapter + three reference Tcl solutions

**Files:**
- Create: `vmdbench/adapters/oracle_tcl.py`
- Create: `vmdbench/oracles/viz_protein_dna_001.tcl`
- Create: `vmdbench/oracles/select_water_count_001.tcl`
- Create: `vmdbench/oracles/traj_render_001.tcl`
- Test: `vmdbench/tests/test_runner.py` covers these live in Task 9; this task adds a focused oracle test below.
- Test: `vmdbench/tests/test_oracle.py` (LIVE)

The oracle adapter prepares a run workdir (copies `initial_state.files` from the card's directory into it so relative paths resolve), then runs the reference Tcl through `HeadlessVMDEnv`. Reference Tcl uses **`render TachyonInternal`** (verified to work headless).

- [ ] **Step 1: Write the three reference Tcl files**

`vmdbench/oracles/viz_protein_dna_001.tcl`:
```tcl
mol new mini.pdb waitfor all
# rep 0: protein cartoon, colored by chain
mol modstyle 0 0 NewCartoon
mol modselect 0 0 protein
mol modcolor 0 0 Chain
# rep 1: nucleic licorice
mol addrep 0
mol modstyle 1 0 Licorice
mol modselect 1 0 nucleic
# rep 2: water, hidden
mol addrep 0
mol modselect 2 0 water
mol showrep 0 2 off
color Display Background white
render TachyonInternal out.tga
```

`vmdbench/oracles/select_water_count_001.tcl`:
```tcl
mol new mini.pdb waitfor all
```

`vmdbench/oracles/traj_render_001.tcl`:
```tcl
mol new mini.pdb waitfor all
color Display Background white
render TachyonInternal out.tga
```

- [ ] **Step 2: Write the oracle adapter** (`vmdbench/adapters/oracle_tcl.py`)

```python
from __future__ import annotations
import shutil
from dataclasses import dataclass
from pathlib import Path

from vmdbench.env.headless_vmd import HeadlessVMDEnv, VmdRunResult
from vmdbench.spec.task_card import TaskCard

# Fixture root: vmdbench/fixtures (parents[1] of vmdbench/adapters/oracle_tcl.py = vmdbench).
FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"


@dataclass
class OracleRun:
    result: VmdRunResult
    workdir: Path
    tcl: str


def prepare_workdir(card: TaskCard, dest: Path, fixtures_root: Path | None = None) -> Path:
    """Copy the card's initial_state files (relative to fixtures_root) into a run workdir by basename."""
    fixtures_root = Path(fixtures_root or FIXTURES_ROOT)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for rel in card.initial_state.get("files", []) or []:
        src = (fixtures_root / rel).resolve()
        shutil.copy2(src, dest / Path(rel).name)
    return dest


def run_oracle(card: TaskCard, oracle_tcl_path: str | Path, workdir: Path,
               env: HeadlessVMDEnv | None = None) -> OracleRun:
    env = env or HeadlessVMDEnv()
    prepare_workdir(card, workdir)
    tcl = Path(oracle_tcl_path).read_text()
    res = env.run(tcl, workdir=workdir, selection_texts=card.selection_texts())
    return OracleRun(result=res, workdir=Path(workdir), tcl=tcl)
```

- [ ] **Step 3: Write the live oracle test** (`vmdbench/tests/test_oracle.py`)

```python
from __future__ import annotations
import sys, unittest, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.task_card import load_card
from vmdbench.adapters.oracle_tcl import run_oracle

TASKS = ROOT / "vmdbench" / "tasks"
ORACLES = ROOT / "vmdbench" / "oracles"


class OracleLiveTests(unittest.TestCase):
    def test_select_oracle_reports_gold_counts(self):
        card = load_card(TASKS / "select" / "select_water_count_001.yaml")
        with tempfile.TemporaryDirectory() as d:
            run = run_oracle(card, ORACLES / "select_water_count_001.tcl", Path(d))
            self.assertEqual(run.result.scene.selections["water"], 2)
            self.assertGreater(run.result.scene.selections["protein"], 0)
            self.assertEqual(run.result.scene.errors, [])

    def test_viz_oracle_builds_reps_and_renders(self):
        card = load_card(TASKS / "viz" / "viz_protein_dna_001.yaml")
        with tempfile.TemporaryDirectory() as d:
            run = run_oracle(card, ORACLES / "viz_protein_dna_001.tcl", Path(d))
            scene = run.result.scene
            styles = {r.style_name for r in scene.representations}
            self.assertIn("NewCartoon", styles)
            self.assertIn("Licorice", styles)
            self.assertEqual(scene.display.background, "white")
            self.assertTrue((run.workdir / "out.tga").exists())
            self.assertGreater((run.workdir / "out.tga").stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the live oracle test**

Run: `python -m pytest vmdbench/tests/test_oracle.py -v`
Expected: PASS (2 tests). If `water` count differs from 2, the fixture changed — regenerate gold by reading the oracle's reported count and updating the `select` card's `expect` (gold counts are oracle-derived, never hand-typed). If `Licorice`/`NewCartoon` missing, inspect `run.result.stdout` for the `rep*_style` PROBE lines.

- [ ] **Step 5: Commit**

```bash
git add vmdbench/adapters/oracle_tcl.py vmdbench/oracles vmdbench/tests/test_oracle.py
git commit -m "feat(vmdbench): oracle adapter + reference Tcl solutions (TachyonInternal render)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Verify runner — replay + evaluate a card → `VerifyResult`

**Files:**
- Create: `vmdbench/verify/runner.py`
- Test: `vmdbench/tests/test_runner.py` (LIVE)

The runner takes a card + a Tcl transcript (here, the oracle Tcl), runs it through `HeadlessVMDEnv` in a workdir prepared from the card's fixtures, evaluates every required and optional assertion, and returns a `VerifyResult` with the gate.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
import sys, unittest, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.task_card import load_card
from vmdbench.verify.runner import verify_card

TASKS = ROOT / "vmdbench" / "tasks"
ORACLES = ROOT / "vmdbench" / "oracles"


class RunnerLiveTests(unittest.TestCase):
    def _verify(self, card_rel, oracle_rel):
        card = load_card(TASKS / card_rel)
        tcl = (ORACLES / oracle_rel).read_text()
        with tempfile.TemporaryDirectory() as d:
            return verify_card(card, tcl, Path(d))

    def test_viz_oracle_passes_gate(self):
        res = self._verify("viz/viz_protein_dna_001.yaml", "viz_protein_dna_001.tcl")
        failed = [r.kind for r in res.required if not r.passed]
        self.assertTrue(res.gate, f"oracle should satisfy verifier; failed: {failed}\nobserved: "
                                  f"{[(r.kind, r.observed) for r in res.required]}")

    def test_select_oracle_passes_gate(self):
        res = self._verify("select/select_water_count_001.yaml", "select_water_count_001.tcl")
        self.assertTrue(res.gate, [(r.kind, r.observed) for r in res.required])

    def test_traj_oracle_passes_gate(self):
        res = self._verify("traj/traj_render_001.yaml", "traj_render_001.tcl")
        self.assertTrue(res.gate, [(r.kind, r.observed) for r in res.required])

    def test_empty_transcript_fails_gate(self):
        card = load_card(TASKS / "viz/viz_protein_dna_001.yaml")
        with tempfile.TemporaryDirectory() as d:
            res = verify_card(card, "# does nothing\n", Path(d))
        self.assertFalse(res.gate)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vmdbench.verify.runner'`

- [ ] **Step 3: Write the implementation** (`vmdbench/verify/runner.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

from vmdbench.adapters.oracle_tcl import prepare_workdir
from vmdbench.env.headless_vmd import HeadlessVMDEnv
from vmdbench.env.scene_state import SceneState
from vmdbench.spec.task_card import TaskCard
from vmdbench.verify.checks import CheckContext, CheckResult, evaluate


@dataclass
class VerifyResult:
    task_id: str
    gate: bool
    required: list[CheckResult] = field(default_factory=list)
    optional: list[CheckResult] = field(default_factory=list)
    scene: SceneState | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def cr(r): return {"kind": r.kind, "passed": r.passed, "observed": r.observed, "where": r.where}
        return {
            "task_id": self.task_id, "gate": self.gate,
            "required": [cr(r) for r in self.required],
            "optional": [cr(r) for r in self.optional],
            "errors": self.errors,
        }


def verify_card(card: TaskCard, tcl_transcript: str, workdir: Path,
                env: HeadlessVMDEnv | None = None) -> VerifyResult:
    env = env or HeadlessVMDEnv()
    workdir = Path(workdir)
    prepare_workdir(card, workdir)
    run = env.run(tcl_transcript, workdir=workdir, selection_texts=card.selection_texts())
    ctx = CheckContext(workdir=workdir)

    required = [evaluate(a, run.scene, ctx) for a in card.required]
    optional = [evaluate(a, run.scene, ctx) for a in card.optional]
    gate = all(r.passed for r in required)
    return VerifyResult(
        task_id=card.task_id, gate=gate, required=required, optional=optional,
        scene=run.scene, errors=run.scene.errors,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_runner.py -v`
Expected: PASS (4 tests). The three oracle gates passing proves the verifier is satisfiable; the empty transcript failing proves it discriminates. If a required check fails for an oracle, read the printed `observed` list — it tells you exactly which assertion and what VMD reported, then fix the oracle Tcl (not the verifier) until the gate passes.

- [ ] **Step 5: Commit**

```bash
git add vmdbench/verify/runner.py vmdbench/tests/test_runner.py
git commit -m "feat(vmdbench): verify runner replays transcript and gates on assertions" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Scorer — gate → per-dimension subscore → composite

**Files:**
- Create: `vmdbench/score/scorer.py`
- Test: `vmdbench/tests/test_scorer.py`

Implements the spec formula. For Plan 1, dimension subscores come from state-assertion pass-rates bucketed by `KIND_DIMENSIONS`, plus a reproducibility signal (`exports_ok`, `replay_clean`) passed in. `observability` and `workflow_efficiency` require episode metrics (Plans 2+); when a card lists them but no episode metrics are supplied, the scorer marks them `not_evaluated` and **excludes them from the composite** (surfacing the omission rather than scoring 0 silently).

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.dimensions import Dimension
from vmdbench.verify.checks import CheckResult
from vmdbench.verify.runner import VerifyResult
from vmdbench.score.scorer import score_task


def _vr(gate, required, optional):
    return VerifyResult(task_id="t", gate=gate,
                        required=[CheckResult(k, p, where=w) for (k, p, w) in required],
                        optional=[CheckResult(k, p, where=w) for (k, p, w) in optional])


class ScorerTests(unittest.TestCase):
    def test_gate_zero_zeros_gated_dims(self):
        vr = _vr(False,
                 [("representation_exists", False, {}), ("selection_count", True, {})],
                 [])
        s = score_task(vr, dimensions=[Dimension.ACTIONABILITY, Dimension.SEMANTIC_GROUNDING])
        self.assertFalse(s.solved)
        self.assertEqual(s.dim_scores[Dimension.ACTIONABILITY], 0.0)
        self.assertEqual(s.dim_scores[Dimension.SEMANTIC_GROUNDING], 0.0)
        self.assertEqual(s.composite, 0.0)

    def test_full_pass_scores_one(self):
        vr = _vr(True,
                 [("representation_exists", True, {}), ("selection_count", True, {})],
                 [("no_runtime_errors", True, {})])
        s = score_task(vr, dimensions=[Dimension.ACTIONABILITY, Dimension.SEMANTIC_GROUNDING,
                                       Dimension.VERIFICATION_RECOVERY])
        self.assertTrue(s.solved)
        self.assertEqual(s.dim_scores[Dimension.ACTIONABILITY], 1.0)
        self.assertEqual(s.dim_scores[Dimension.SEMANTIC_GROUNDING], 1.0)
        self.assertAlmostEqual(s.composite, 1.0, places=6)

    def test_reproducibility_signal(self):
        vr = _vr(True, [("molecule_loaded", True, {})], [])
        s = score_task(vr, dimensions=[Dimension.REPRODUCIBILITY],
                       repro_signals={"exports_ok": True, "replay_clean": True})
        self.assertEqual(s.dim_scores[Dimension.REPRODUCIBILITY], 1.0)

    def test_unevaluable_dim_excluded_from_composite(self):
        vr = _vr(True, [("representation_exists", True, {})], [])
        s = score_task(vr, dimensions=[Dimension.ACTIONABILITY, Dimension.OBSERVABILITY])
        self.assertIn(Dimension.OBSERVABILITY, s.not_evaluated)
        self.assertAlmostEqual(s.composite, 1.0, places=6)  # only actionability counts


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_scorer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vmdbench.score.scorer'`

- [ ] **Step 3: Write the implementation** (`vmdbench/score/scorer.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field

from vmdbench.spec.dimensions import Dimension, DEFAULT_WEIGHTS, KIND_DIMENSIONS
from vmdbench.verify.runner import VerifyResult

# Dimensions that cannot be scored from state assertions alone in Plan 1.
_EPISODE_ONLY = {Dimension.OBSERVABILITY, Dimension.WORKFLOW_EFFICIENCY}


@dataclass
class TaskScore:
    task_id: str
    solved: bool
    dim_scores: dict[Dimension, float] = field(default_factory=dict)
    not_evaluated: list[Dimension] = field(default_factory=list)
    composite: float = 0.0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "solved": self.solved,
            "dim_scores": {d.value: v for d, v in self.dim_scores.items()},
            "not_evaluated": [d.value for d in self.not_evaluated],
            "composite": self.composite,
        }


def _passrate(results, dim: Dimension) -> float | None:
    relevant = [r for r in results if dim in KIND_DIMENSIONS.get(r.kind, [])]
    if not relevant:
        return None
    return sum(1 for r in relevant if r.passed) / len(relevant)


def score_task(vr: VerifyResult, dimensions: list[Dimension],
               repro_signals: dict | None = None,
               episode_metrics: dict | None = None,
               weights: dict[Dimension, float] | None = None) -> TaskScore:
    weights = weights or DEFAULT_WEIGHTS
    all_checks = list(vr.required) + list(vr.optional)
    score = TaskScore(task_id=vr.task_id, solved=vr.gate)

    for d in dimensions:
        raw: float | None
        if d == Dimension.REPRODUCIBILITY and repro_signals is not None:
            raw = 1.0 if (repro_signals.get("exports_ok") and repro_signals.get("replay_clean")) else 0.0
        elif d in _EPISODE_ONLY:
            raw = (episode_metrics or {}).get(d.value)  # None unless supplied (Plans 2+)
        else:
            raw = _passrate(all_checks, d)

        if raw is None:
            score.not_evaluated.append(d)
            continue
        score.dim_scores[d] = (raw if vr.gate else 0.0)

    in_play = {d: w for d, w in weights.items() if d in score.dim_scores}
    total_w = sum(in_play.values())
    if total_w > 0:
        score.composite = sum(score.dim_scores[d] * w for d, w in in_play.items()) / total_w
    return score
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_scorer.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add vmdbench/score/scorer.py vmdbench/tests/test_scorer.py
git commit -m "feat(vmdbench): gated composite + per-dimension scorer" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: CLI — `score-oracle` end-to-end + replay-clean check

**Files:**
- Create: `vmdbench/cli.py`
- Test: `vmdbench/tests/test_cli.py` (LIVE)

The CLI ties the pipeline together: load card → run oracle → verify → replay-clean check → score → print JSON. `replay_clean` runs the transcript a second time and confirms the gate still passes and the asserted scene fields match (the reproducibility hard-signal).

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
import sys, unittest, tempfile, json, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TASKS = ROOT / "vmdbench" / "tasks"
ORACLES = ROOT / "vmdbench" / "oracles"


class CliLiveTests(unittest.TestCase):
    def test_score_oracle_emits_json_with_solved_true(self):
        with tempfile.TemporaryDirectory() as d:
            out = subprocess.run(
                [sys.executable, "-m", "vmdbench.cli", "score-oracle",
                 str(TASKS / "viz/viz_protein_dna_001.yaml"),
                 str(ORACLES / "viz_protein_dna_001.tcl"),
                 "--workdir", d],
                cwd=str(ROOT), capture_output=True, text=True, timeout=300,
            )
            self.assertEqual(out.returncode, 0, out.stderr)
            payload = json.loads(out.stdout)
            self.assertTrue(payload["verify"]["gate"])
            self.assertTrue(payload["score"]["solved"])
            self.assertTrue(payload["replay_clean"])
            self.assertGreater(payload["score"]["composite"], 0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vmdbench/tests/test_cli.py -v`
Expected: FAIL — `No module named vmdbench.cli` (the subprocess returns non-zero / empty stdout)

- [ ] **Step 3: Write the implementation** (`vmdbench/cli.py`)

```python
from __future__ import annotations
import argparse, json, sys, tempfile
from pathlib import Path

from vmdbench.env.headless_vmd import HeadlessVMDEnv
from vmdbench.spec.task_card import load_card
from vmdbench.verify.runner import verify_card
from vmdbench.score.scorer import score_task


def _scene_fingerprint(scene) -> tuple:
    reps = tuple(sorted((r.selection, r.style_name, r.visible) for r in scene.representations))
    sels = tuple(sorted(scene.selections.items()))
    return (len(scene.molecules), reps, sels, scene.display.background, scene.display.projection)


def _replay_clean(card, tcl, env) -> bool:
    fps = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as d:
            res = verify_card(card, tcl, Path(d), env=env)
            if not res.gate:
                return False
            fps.append(_scene_fingerprint(res.scene))
    return fps[0] == fps[1]


def cmd_score_oracle(args) -> int:
    card = load_card(args.card)
    tcl = Path(args.oracle).read_text()
    env = HeadlessVMDEnv()
    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp())

    verify = verify_card(card, tcl, workdir, env=env)
    exports_ok = "tcl" in (card.reproducibility.get("exports", []) or [])  # oracle IS reusable tcl
    replay_clean = _replay_clean(card, tcl, env) if card.reproducibility.get("replay_clean") else None
    score = score_task(
        verify, dimensions=card.dimensions,
        repro_signals={"exports_ok": exports_ok, "replay_clean": bool(replay_clean)}
                      if card.reproducibility else None,
    )
    payload = {
        "task_id": card.task_id,
        "verify": verify.to_dict(),
        "score": score.to_dict(),
        "replay_clean": replay_clean,
    }
    print(json.dumps(payload, indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="vmdbench")
    sub = p.add_subparsers(dest="cmd", required=True)
    so = sub.add_parser("score-oracle", help="run a reference Tcl against a card and score it")
    so.add_argument("card")
    so.add_argument("oracle")
    so.add_argument("--workdir", default=None)
    so.set_defaults(func=cmd_score_oracle)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vmdbench/tests/test_cli.py -v`
Expected: PASS (1 test). Also run it by hand to see the output:
`python -m vmdbench.cli score-oracle vmdbench/tasks/viz/viz_protein_dna_001.yaml vmdbench/oracles/viz_protein_dna_001.tcl`

- [ ] **Step 5: Commit**

```bash
git add vmdbench/cli.py vmdbench/tests/test_cli.py
git commit -m "feat(vmdbench): score-oracle CLI with replay-clean reproducibility check" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: README + full-suite green + foundation wrap

**Files:**
- Create: `vmdbench/README.md`
- Test: full `vmdbench/tests` suite

- [ ] **Step 1: Write `vmdbench/README.md`**

```markdown
# VMD-LLM-Native Bench (`vmdbench`)

Measures how *LLM-native* VMD operation is: can an LLM understand the scene,
choose valid actions, verify the result, recover, and export a reproducible workflow.
Design spec: `../docs/superpowers/specs/2026-05-29-vmd-llm-native-bench-design.md`.

## Status: Plan 1 (Foundation) — LLM-free core
- `spec/`    task cards, closed assertion vocabulary, the 6 dimensions
- `env/`     canonical SceneState + HeadlessVMDEnv (drives `vmd -dispdev text`)
- `adapters/oracle_tcl.py`  reference-solution runner (verifier upper bound)
- `verify/`  assertion evaluators + runner (gate)
- `score/`   gated composite + per-dimension subscores
- `tasks/` + `oracles/`  three exemplar cards with reference solutions

## Requirements
- VMD on PATH (developed against 1.9.4a57; see `VERSION`)
- `pip install pyyaml`

## Run the bench on a reference solution
```
python -m vmdbench.cli score-oracle tasks/viz/viz_protein_dna_001.yaml oracles/viz_protein_dna_001.tcl
```

## Run the tests
```
python -m pytest vmdbench/tests -v
```

## Headless rendering note
`render snapshot` does NOT work in `-dispdev text` (produces an invalid stub).
Use `render TachyonInternal <file>`; the `file_rendered` assertion expects a real
(>1 KB) image.

## Not yet implemented (Plans 2–4)
- ChatVMD adapter (live LLM runs, raw-Tcl track), `harness/` factorial, provenance/version-pinning, 429 isolation
- Typed-tool track + `get_scene_state` observation; observability & workflow-efficiency scoring
- Recovery track (fault injection); `report/` leaderboard + radar; full ~40–50 task dataset
```

- [ ] **Step 2: Run the entire suite**

Run: `python -m pytest vmdbench/tests -v`
Expected: ALL tests PASS across `test_smoke, test_dimensions, test_scene_state, test_headless_vmd, test_assertions, test_task_card, test_cards_load, test_checks, test_oracle, test_runner, test_scorer, test_cli`.

- [ ] **Step 3: Confirm no stray working-tree breakage**

Run: `git -C /Users/pinhaogu/Documents/GitHub/PyMolAI status --short`
Expected: only `vmdbench/` additions staged/committed; pre-existing unrelated changes (`.gitignore`, `claude_sdk_loop.py`, etc.) untouched.

- [ ] **Step 4: Commit**

```bash
git add vmdbench/README.md
git commit -m "docs(vmdbench): foundation README + headless render note" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Plans 2–4 (outline — to be written after Plan 1 lands)

- **Plan 2 — ChatVMD adapter + harness:** `env/base.py` (`VMDEnv` ABC + `Action` types), `adapters/chatvmd.py` (wrap `ClaudeToolLoop`/`VmdToolBridge`, raw-Tcl track), `harness/run.py` + `matrix.py` (tasks × models × configs × seeds), `harness/provenance.py` on top of `RunRecorder` (model-version + seed + VMD-version pinning, **HTTP-429 isolation**). Episode log enables `tool_used`, `self_observed_before_done`, `grounded_claims`, and workflow-efficiency metrics → fills the observability & workflow_efficiency dimensions stubbed in Task 10.
- **Plan 3 — LLM-native surfaces:** typed-tool track (`Typed` actions: `load_structure`, `create_representation`, `select_atoms`, `align_trajectory`, `render_snapshot`, `export_script`), normalized `get_scene_state` observation for all providers, recovery track (`env/faults.py`: `missing_file`, `wrong_resname`, `empty_selection`, `invalid_molid`, `bad_rep_style`; 0/partial/full scoring), `verify/tier0_idioms.py` (reuse `scripts/rag_ab_batch.py` `IDIOM_PATTERNS` as non-gating signal).
- **Plan 4 — Reporting + publishable hardening:** `report/leaderboard.py` (composite ranking) + `report/profile.py` (6-dim radar, raw-Tcl vs typed-tools delta, solved-rate, infra-error rate), `score/aggregate.py` (wrap `scripts/aggregate_seeds.py`), `verify/human_review.py` (image+rubric export), and porting the full 14 `rag_wiki_suite_v1` prompts + expanding to ~40–50 tasks across the 6×difficulty grid.
```
