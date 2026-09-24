# Act 3 demo run sheet — vmdbench reproducibility + scoring

**What Diego should take away:** there's a working evaluation harness that drives
real headless VMD, reads the molecular scene back programmatically, checks
machine-verifiable assertions, and proves the workflow reproduces. This is the
*measuring instrument* for "LLM-nativeness" — validated against reference
solutions before any model score is trusted.

> Honesty anchor: the numbers below are **oracle (reference) solutions = the
> upper bound**, not a model's score. That's the point of this stage — validate
> the verifier first. Say this out loud; it's a strength, not a weakness.

---

## 0. One-time setup (do this once, before the demo)

From the repo root (`vmd_ai/`):

```bash
# Real structure fixture (CDK2 kinase + ATP, 2510 atoms)
cp cdk2_v2_replay/1HCK.pdb vmdbench/fixtures/1hck.pdb

pip install pyyaml          # bench dependency

# VMD must be runnable. If `vmd` is on PATH, nothing to do. Otherwise point the
# bench straight at the app binary (Apple Silicon shown):
export VMDBENCH_VMD_BIN=/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64
```

---

## 1. Generate the real figure + score it  (the live beat)

```bash
python -m vmdbench.cli score-oracle \
  vmdbench/tasks/viz/viz_kinase_tube_001.yaml \
  vmdbench/oracles/viz_kinase_tube_001.tcl \
  --workdir demo_kinase_out \
  --timeout 600
```

This loads real CDK2 (2510 atoms), builds a protein **Tube** backbone + ATP
licorice, sets a white background, renders `demo_kinase_out/out.tga`, reads the
scene back, and prints scored JSON (`gate`, per-assertion pass/fail,
`replay_clean`).

> **Why Tube, not NewCartoon?** `NewCartoon` triggers VMD's STRIDE
> secondary-structure step, which **deadlocks** on a real few-hundred-residue
> chain in headless mode (it hung past 1200s here). `Tube` needs no secondary
> structure, renders in seconds, and still reads as a real protein. The
> `viz_kinase_cartoon_001` card is kept for machines where STRIDE behaves.

### If even Tube stalls — pinpoint it (≈30s)

```bash
/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64 \
    -dispdev text -eofexit -e probe_stride.tcl
```

Watch the `>>>` checkpoints. Reaching **CKPT3** means Tube renders fine (it just
wrote `/tmp/probe_tube.tga`); a stall right after CKPT3 with no CKPT4 confirms
the STRIDE hang. If it stalls before **CKPT2**, rendering itself is the problem,
not STRIDE — tell me and we change the render path.

```bash
# Pretty PNG for slides (sips is built into macOS — no install)
sips -s format png demo_kinase_out/out.tga --out demo_kinase_out/out.png
open demo_kinase_out/out.png
```

**Run this once before the demo** so you've seen the figure and the green gate.
That rehearsal is the whole confidence fix.

---

## 2. Show reproducibility  (the headline claim)

- The exact Tcl VMD executed is saved at `demo_kinase_out/__vb_run.tcl`.
- `replay_clean: true` means: re-running that Tcl in a fresh headless VMD
  reproduces the identical asserted scene — a session becomes a script anyone
  can re-run to get the same figure **and** the same verified state.
- Optional second exhibit: `report_out/REPORT.md` — the same machinery scoring
  the fixture suite (4/4, with the per-assertion tables).

---

## 3. Talk track (roughly what to say)

1. "This is the project's evaluation harness. A task is declarative — a prompt
   plus machine-checkable assertions about the resulting molecular scene."
2. "I run a solution through real headless VMD, read the scene back
   programmatically, and check each assertion. Here it loaded CDK2, built the
   cartoon + ATP licorice, set white background, rendered — all green."
3. "`replay_clean` proves the workflow reproduces deterministically."
4. **Pivot (say this):** "These are *reference* solutions — the upper bound. I
   validated the measuring instrument before trusting any model number. The next
   run drops Claude, and a cheaper local model, into the same harness on the
   raw-Tcl vs typed-tools tracks. That's the real experiment — and the
   cost/local-model comparison rides on exactly this."

---

## 4. Pre-empt the questions  (so they land as anticipated, not caught out)

| Likely question | Honest answer |
|---|---|
| Is `mini.pdb` a real molecule? | No — an 8-atom synthetic fixture for fast, hermetic verifier checks. This kinase task (1HCK) is the real-structure version. |
| Did the model do this, or a reference solution? | Reference/oracle — the upper bound, and it proves the verifier is satisfiable. Model-in-the-loop is the next build step. |
| Why is everything 1.00? | The oracle hits its own targets on easy tasks. The point right now is the *harness*, not the score; interesting numbers come with a real model + harder tasks. |
| Does headless VMD match interactive VMD? | Validated on these tasks. Rendering uses `render TachyonInternal` (`render snapshot` produces an invalid stub headless). |

---

## 5. Rate-limit / safety fallback

- **Act 3 needs no API at all** — it's pure local VMD — so the HTTP 429 rate
  limits that hit the wiki test cannot touch it. That's *why* it's the safe demo.
- If even VMD misbehaves live: show the pre-generated `demo_kinase_out/out.png`,
  the saved JSON, and `report_out/REPORT.md`. Nothing has to run live.

---

## What this maps to (the six LLM-nativeness dimensions)

This task exercises **actionability** (valid actions executed), **reproducibility**
(`replay_clean` + Tcl export), and **semantic grounding** (protein / ligand
selections). Observability, recovery, and workflow-efficiency come online with
the model-in-the-loop runs — the next stage.

## Files used

- Card:   `vmdbench/tasks/viz/viz_kinase_cartoon_001.yaml`
- Oracle: `vmdbench/oracles/viz_kinase_cartoon_001.tcl`
- Fixture (after step 0): `vmdbench/fixtures/1hck.pdb`
