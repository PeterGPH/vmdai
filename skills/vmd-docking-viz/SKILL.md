---
name: vmd-docking-viz
version: "1.0.0"
author: PyMolAI
tools:
  - run_vmd_command
  - capture_vmd_snapshot
requires:
  - python3
  - numpy
  - matplotlib
  - vmd
  - vmd-pdbqt-plugin    # optional — falls back to PDB loader on Apple Silicon
output:
  - "/tmp/docking_scene.tga"     # raw VMD render (TGA)
  - "/tmp/<figure>.png"          # 300 DPI raster figure
  - "/tmp/<figure>.svg"          # vector figure for editing
  - "/tmp/clashes.dat"           # optional steric-clash table
description: >
  Publication-quality molecular docking visualization in VMD. Use this skill whenever
  the user wants to visualize, analyze, or render docked ligand poses, protein-ligand
  binding sites, multi-pose ensembles, or scoring results from AutoDock Vina, AutoDock4,
  Smina, GNINA, Glide, GOLD, rDock, or any docking program that emits PDBQT, PDB,
  SDF, MOL2, or multi-model output. Triggers include: "show me the docked pose",
  "visualize binding site", "overlay poses", "interaction map", "render docking
  results", "binding pocket figure", "compare top poses", "color by score", "show
  hydrogen bonds with ligand", "make a paper figure of the docked complex". Also
  triggers for any request mentioning Vina, AutoDock, PDBQT, docked complex,
  binding pocket visualization, or pose comparison.
---

<example>
User: "Show me the top Vina pose docked into my receptor."
Skill action:
  1. Load receptor.pdbqt and vina_out.pdbqt as separate molecules via run_vmd_command.
  2. Parse REMARK VINA RESULT lines to extract affinity for each pose.
  3. Reset reps; render protein cartoon + pocket licorice + top-pose licorice.
  4. capture_vmd_snapshot → return PNG of the binding scene.
</example>

<example>
User: "Compare the top 5 docked poses and color them by Vina score."
Skill action:
  1. Load the multi-MODEL PDBQT (5 poses as frames of one molecule).
  2. Write per-frame Vina affinities into the User column for color-by-User.
  3. Add a Licorice rep colored by User; clamp scaleminmax to the score range.
  4. Use mol drawframes to render all 5 poses; capture_vmd_snapshot for the figure.
</example>

# VMD Docking Visualization Skill

Generate publication-quality figures and live VMD scenes for molecular docking
results. The pipeline has three phases: **load** docking output (receptor + one
or many poses), **dress** the scene with informative representations of the
binding pocket and ligand, then **render** either as a TGA/PNG snapshot from
the VMD viewport or as a matplotlib figure of derived quantitative data
(scores, RMSDs, interaction counts).

## When to use this skill vs vmd-ligand-pore-viz

- Use **this skill** for static binding-site analysis: AutoDock/Vina output,
  PDBQT files, multi-pose SDF/MOL2, scoring tables, ligand-receptor
  interaction maps, single-frame paper figures.
- Use **vmd-ligand-pore-viz** for trajectories: ligand permeation, time-series,
  ion channels, MD analysis.

If the user has both (docked starting pose followed by an MD trajectory of
that pose), use this skill for the "before" figure and the pore-viz skill for
the "during/after" plots.

## Tools

You drive a live VMD session through the vmd_ai runtime:

- `run_vmd_command` — execute Tcl in the running VMD process
- `capture_vmd_snapshot` — grab the current viewport as PNG (and view it)

The `scripts/` directory next to this SKILL.md ships reusable Tcl helpers you
can `source` instead of re-typing boilerplate. They are documented inline.

## Phase 1: Load docking output

### Recognize the input format

Ask if you are not sure, but the file extension is usually decisive:

| Extension | Source | Loader |
|---|---|---|
| `.pdbqt` | AutoDock / Vina / Smina / GNINA | `mol new ... type pdbqt` |
| `.pdb` (multi-MODEL) | Vina --out, AutoDock4, GOLD | `mol new ... type pdb waitfor all` |
| `.sdf` / `.mol2` | RDKit, OpenBabel, Glide, rDock | `mol new ... type {sdf,mol2}` |
| `.dlg` | AutoDock4 docking log | parse externally; load resulting PDB |

A single PDBQT or multi-MODEL PDB from Vina contains all top-N poses as
sequential frames in **one molecule**. The receptor is a separate file.

### Standard load: receptor + ligand poses

```tcl
# Receptor
set rec_id [mol new "receptor.pdbqt" type pdbqt waitfor all]
mol rename $rec_id "receptor"

# All poses as frames of one molecule
set lig_id [mol new "vina_out.pdbqt" type pdbqt waitfor all]
mol rename $lig_id "poses"

# Confirm pose count
set npose [molinfo $lig_id get numframes]
puts "Loaded $npose docked poses"
```

If the docking program wrote one file per pose (`pose_1.pdb`, `pose_2.pdb`,
...), load them as additional frames into a single molecule:

```tcl
set lig_id [mol new "pose_1.pdb" waitfor all]
foreach f [glob -nocomplain pose_*.pdb] {
    if {$f eq "pose_1.pdb"} { continue }
    mol addfile $f molid $lig_id waitfor all
}
mol rename $lig_id "poses"
```

### Parse Vina scores

Vina embeds the affinity (kcal/mol) and RMSD in REMARK lines of the PDBQT
output. Extract them programmatically — never hand-copy:

```tcl
proc vmdai::vina_scores {filename} {
    set scores {}
    set fh [open $filename r]
    while {[gets $fh line] >= 0} {
        if {[regexp {REMARK VINA RESULT:\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)} $line _ aff rmsd_lb rmsd_ub]} {
            lappend scores [list $aff $rmsd_lb $rmsd_ub]
        }
    }
    close $fh
    return $scores
}
```

For other docking programs the score is in a property block (`> <SCORE>` in
SDF, `@<TRIPOS>COMMENT` in MOL2, `<minimizedAffinity>` in GNINA SDF). Adjust
the regex accordingly.

## Phase 2: Dress the scene

### Reset to a clean slate

Always start from a known-good baseline. Bad initial reps are the single most
common reason that VMD figures look amateurish:

```tcl
# Drop every existing representation on receptor
set nrep [molinfo $rec_id get numreps]
for {set i [expr {$nrep - 1}]} {$i >= 0} {incr i -1} {
    mol delrep $i $rec_id
}
set nrep [molinfo $lig_id get numreps]
for {set i [expr {$nrep - 1}]} {$i >= 0} {incr i -1} {
    mol delrep $i $lig_id
}

# Display defaults
display projection Orthographic
display depthcue off
axes location Off
color Display Background white
```

### Receptor: cartoon + binding-pocket licorice

The pocket is whatever residue sits within ~5 angstrom of the ligand in the
top pose. Compute it dynamically rather than hard-coding residue IDs:

```tcl
animate goto 0 ;# top pose

# Whole protein, low-key cartoon
mol representation NewCartoon 0.3 12 4.5
mol color ColorID 8                 ;# light gray
mol selection "protein"
mol material AOChalky
mol addrep $rec_id

# Pocket residues as licorice, colored by atom type
set ligsel [atomselect $lig_id "all" frame 0]
set ligcoords [$ligsel get {x y z}]
$ligsel delete

set pocket_resids [list]
set near [atomselect $rec_id "protein and within 5 of (index [lsearch -all -inline -not [list] -1])" ]
# Above won't work cross-molecule; use measure contacts instead:
set lig_cur [atomselect $lig_id "all" frame 0]
set rec_all [atomselect $rec_id "protein"]
set contacts [measure contacts 5.0 $lig_cur $rec_all]
set rec_idx [lindex $contacts 1]
$lig_cur delete

if {[llength $rec_idx] > 0} {
    set near [atomselect $rec_id "index $rec_idx"]
    set pocket_resids [lsort -unique -integer [$near get resid]]
    $near delete
}
$rec_all delete

if {[llength $pocket_resids] > 0} {
    mol representation Licorice 0.25 12 12
    mol color Name
    mol selection "protein and resid $pocket_resids"
    mol material Opaque
    mol addrep $rec_id
}
```

Two cross-molecule details to watch:

- `within X of` selectors only work **inside the same molecule**. Use
  `measure contacts` to find atom contacts across molecules and convert the
  returned indices back into a selection string.
- `resid` in VMD is the original PDB residue number; `residue` is the
  zero-based internal index. They are not interchangeable.

### Ligand: top pose as licorice, alt poses as faded thin licorice

```tcl
# Top pose, prominent
mol representation Licorice 0.35 12 12
mol color Name
mol selection "all"
mol material Opaque
mol addrep $lig_id
mol drawframes $lig_id [expr {[molinfo $lig_id get numreps] - 1}] {0}

# Alt poses 1..N-1, thin and translucent
set npose [molinfo $lig_id get numframes]
if {$npose > 1} {
    mol representation Licorice 0.15 12 12
    mol color ColorID 7              ;# muted green
    mol selection "all"
    mol material Transparent
    mol addrep $lig_id
    set repidx [expr {[molinfo $lig_id get numreps] - 1}]
    set rest {}
    for {set f 1} {$f < $npose} {incr f} { lappend rest $f }
    mol drawframes $lig_id $repidx $rest
}
```

`mol drawframes` is the right way to show specific frames in a single
representation — far better than animating and rendering each one.

### Color by docking score (heatmap)

If the user wants the ensemble colored by Vina score, write the affinity into
the User column of each frame and color by `User`:

```tcl
proc vmdai::write_score_to_user {molid scores} {
    set sel [atomselect $molid "all"]
    set nf [molinfo $molid get numframes]
    for {set f 0} {$f < $nf} {incr f} {
        $sel frame $f
        set s [lindex $scores $f 0]
        if {$s eq ""} { set s 0.0 }
        $sel set user $s
    }
    $sel delete
}

vmdai::write_score_to_user $lig_id [vmdai::vina_scores "vina_out.pdbqt"]

# Then in the rep:
mol representation Licorice 0.25 12 12
mol color User
mol selection "all"
mol material Opaque
mol addrep $lig_id
mol scaleminmax $lig_id [expr {[molinfo $lig_id get numreps] - 1}] -12.0 -4.0
mol colupdate [expr {[molinfo $lig_id get numreps] - 1}] $lig_id 1
```

`mol scaleminmax` clamps the colour scale — set its range to match the actual
score range (Vina affinities are typically -12 to -4 kcal/mol).

### Surface for cavity context

A semi-transparent receptor surface highlights the pocket nicely. Restrict it
to the pocket vicinity to keep render times sane:

```tcl
mol representation Surf 1.4
mol color ColorID 6              ;# silver
mol selection "protein and same residue as (within 8 of (index [join $rec_idx])) "
mol material Transparent
mol addrep $rec_id
```

For very large receptors prefer `QuickSurf 1.0 0.5 1.0 1.0` — Surf with a
1.4-A probe on a multi-thousand-atom selection blocks the GUI for seconds.

## Phase 3: Render and analyze

### Camera and orientation

A figure with no consistent orientation looks sloppy. The helper
`vmdai::frame_scene` does the right thing automatically — it computes the
bounding sphere of the target selection and picks a scale that fits with
40% margin, then applies a small canonical rotation:

```tcl
vmdai::frame_scene $rec_id "protein" -padding 1.4 -rotate {-25 10}
```

If you want to roll your own — for instance to focus tightly on the
ligand-pocket region — use:

```tcl
set lig_cur [atomselect $lig_id "all" frame 0]
set com [measure center $lig_cur weight mass]
$lig_cur delete

display projection Orthographic
display resetview
molinfo $lig_id set center [list $com]
# scale by N: N>1 zooms IN, N<1 zooms OUT. For a small receptor like
# ubiquitin (~30 A) start with 0.6 and tune from there.
scale by 0.6
rotate y by -25
rotate x by 10
```

### Snapshot

```tcl
render snapshot "/tmp/docking_scene.tga"
# Or, higher quality (slower):
render TachyonInternal "/tmp/docking_scene.tga"
```

After rendering, **always** call `capture_vmd_snapshot` and look at it. If the
ligand is occluded, the scene rotates incorrectly, or the colors are
unreadable, iterate. Do not declare success without a verified snapshot.

### Quantitative figures (matplotlib)

Many docking analyses need a non-VMD plot too. Write a self-contained script
and execute it with `python3` in the shell. Mirror the publication style from
vmd-ligand-pore-viz:

- Arial 10pt, single-column 3.5x2.8 inches, 300 DPI
- Colorblind-safe palette: `["#0072B2","#D55E00","#009E73","#CC79A7","#F0E442","#56B4E9"]`
- Save both PNG (raster) and SVG (editable)
- Top and right spines off, axis line width 0.8

Three plots that come up over and over:

**1. Score-vs-rank bar chart** (the canonical Vina figure):

```python
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

scores = np.array([-9.4,-9.1,-8.8,-8.7,-8.5,-8.4,-8.2,-8.1,-7.9,-7.7])
ranks = np.arange(1, len(scores)+1)

fig, ax = plt.subplots(figsize=(3.5, 2.6))
ax.bar(ranks, scores, color="#0072B2", width=0.7)
ax.axhline(scores[0], ls="--", color="#D55E00", lw=0.8, label=f"Top: {scores[0]:.1f}")
ax.set_xlabel("Pose rank")
ax.set_ylabel("Vina affinity (kcal/mol)")
ax.set_xticks(ranks)
ax.invert_yaxis()      ;# more negative = better, plot pointing up
ax.legend(frameon=False, fontsize=8)
fig.savefig("/tmp/vina_scores.png", dpi=300, bbox_inches="tight")
fig.savefig("/tmp/vina_scores.svg", bbox_inches="tight")
```

**2. Pose RMSD matrix** (clustering check):

```python
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# rmsd_matrix shape (N, N), pre-computed via VMD measure rmsd
fig, ax = plt.subplots(figsize=(3.5, 3.2))
im = ax.imshow(rmsd_matrix, cmap="viridis", vmin=0, vmax=4.0)
ax.set_xlabel("Pose"); ax.set_ylabel("Pose")
cbar = fig.colorbar(im, ax=ax, shrink=0.85)
cbar.set_label(r"RMSD ($\AA$)")
fig.savefig("/tmp/pose_rmsd.png", dpi=300, bbox_inches="tight")
fig.savefig("/tmp/pose_rmsd.svg", bbox_inches="tight")
```

**3. Interaction-residue chart** (per-residue contacts, all poses):

```python
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# contacts[i, j] = 1 if pose i contacts residue j (residue 4-letter labels in resid_labels)
fig, ax = plt.subplots(figsize=(7.0, 3.0))
im = ax.imshow(contacts, aspect="auto", cmap="YlOrRd", origin="lower",
               vmin=0, vmax=1, interpolation="nearest")
ax.set_xticks(np.arange(len(resid_labels)))
ax.set_xticklabels(resid_labels, rotation=60, ha="right", fontsize=7)
ax.set_yticks(np.arange(len(poses)))
ax.set_yticklabels([f"P{p}" for p in poses], fontsize=7)
ax.set_xlabel("Pocket residue"); ax.set_ylabel("Pose")
fig.savefig("/tmp/pose_contacts.png", dpi=300, bbox_inches="tight")
fig.savefig("/tmp/pose_contacts.svg", bbox_inches="tight")
```

### Steric clash analysis

When a docked pose looks visibly wrong — atoms passing through the receptor,
ligand half-buried in a side chain — quantify it instead of eyeballing.
A "clash" is when two atoms are closer than the sum of their van der Waals
radii minus a tolerance (Probe / MolProbity convention: 0.4 A).

```tcl
set clashes [vmdai::pose_clashes $lig_id $rec_id 0.4]
puts [vmdai::pose_clash_summary $lig_id $rec_id 0.4]
```

Output looks like:

```
pose  count  total(A)  worst    residues
0     0      0.000     0.000
1     3      1.124     0.612    {26 41 43}
2     11     5.847     1.103    {26 30 41 43 67 ...}
```

Columns:

- `count` — number of clashing atom pairs
- `total` — sum of all overlap distances; rough proxy for steric strain
- `worst` — single largest overlap (A); >1 A is severe
- `residues` — receptor resids participating in the clash

Per-pair detail lives in the dict:

```tcl
foreach pr [dict get $clashes 2 pairs] {
    puts $pr
    # -> {<lig_idx> <rec_idx> <distance> <overlap> <resname> <resid> <atom_name>}
}
```

For a paper figure, dump to disk and plot the per-pose clash count:

```tcl
vmdai::write_clash_dat /tmp/clashes.dat $clashes
```

Then a matplotlib bar chart (via `python3` in the shell):

```python
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
data = np.genfromtxt("/tmp/clashes.dat", names=True, dtype=None)
poses, counts = np.unique(data["pose"], return_counts=True)
fig, ax = plt.subplots(figsize=(3.5, 2.5))
ax.bar(poses, counts, color="#D55E00")
ax.set_xlabel("Pose"); ax.set_ylabel("Clash atom pairs")
fig.savefig("/tmp/pose_clashes.png", dpi=300, bbox_inches="tight")
```

### Visualize the clashing atoms

To *see* the clash atoms in the viewport, add VDW spheres on the offending
atoms:

```tcl
vmdai::highlight_clashes $rec $lig $clashes 2  ;# pose index 2
```

That adds a red VDW rep on the receptor's clashing atoms and a yellow VDW
rep on the ligand's clashing atoms (limited to the requested pose). Returns
a list of `{molid rep_idx}` so you can remove them later:

```tcl
foreach added [vmdai::highlight_clashes $rec $lig $clashes 2] {
    lassign $added m r
    mol delrep $r $m
}
```

### Severity rules of thumb

- **`worst < 0.4 A`** — within tolerance, ignorable.
- **`0.4 A < worst < 1.0 A`** — real clash, but might be relievable by a
  side-chain rotamer flip; check the receptor resids.
- **`worst > 1.0 A`** — severe steric overlap; the pose is geometrically
  unrealistic and should be discarded or re-minimized.
- **`count > 5`** with low `worst` — many small overlaps; usually a
  systematic alignment issue (e.g., wrong chirality, atoms inside a ring).

### Filtering clashing poses

Once you have `clashes`, drop the bad poses from your downstream analysis:

```tcl
set good_poses [list]
dict for {f rec} $clashes {
    if {[dict get $rec count] == 0 ||
        [dict get $rec worst] < 0.4} {
        lappend good_poses $f
    }
}
puts "Keeping poses: $good_poses"
```

Then pass `$good_poses` to `mol drawframes` so only acceptable poses render:

```tcl
mol drawframes $lig_id $rep_idx $good_poses
```

### Pose RMSD via VMD

```tcl
proc vmdai::pose_rmsd_matrix {molid {selstr "noh"}} {
    set nf [molinfo $molid get numframes]
    set sel [atomselect $molid $selstr]
    set ref [atomselect $molid $selstr]
    set out {}
    for {set i 0} {$i < $nf} {incr i} {
        $ref frame $i
        set row {}
        for {set j 0} {$j < $nf} {incr j} {
            $sel frame $j
            lappend row [measure rmsd $sel $ref]
        }
        lappend out $row
    }
    $sel delete
    $ref delete
    return $out
}
```

Use `noh` to ignore hydrogens (most docking output is heavy-atom only and
hydrogens are unreliable across poses).

### Interaction extraction (hydrogen bonds, contacts)

```tcl
# H-bonds between ligand and pocket, per pose
proc vmdai::pose_hbonds {ligmolid recmolid {cutoff 3.5} {angle 30}} {
    set nf [molinfo $ligmolid get numframes]
    set out {}
    for {set f 0} {$f < $nf} {incr f} {
        set lig [atomselect $ligmolid "all" frame $f]
        set rec [atomselect $recmolid "protein"]
        set hb [measure hbonds $cutoff $angle $lig $rec]
        lappend out [llength [lindex $hb 0]]
        $lig delete
        $rec delete
    }
    return $out
}
```

**Note:** `measure hbonds` only accepts selections from the **same molecule**.
Because receptor and pose ensemble are loaded as separate molids, the
helper `vmdai::pose_hbonds` instead approximates H-bonds via polar-heavy-atom
contacts within the donor-acceptor cutoff (the same proxy PyMOL uses for
`polar_contacts`). The `angle` argument is preserved for API symmetry but
ignored. If you need true geometric H-bond detection, merge receptor and
poses into one molecule first via `topotools`'s `topo selectatoms` /
`topo merge`.

## Workflow checklist

When the user asks for a docking visualization:

1. **Confirm inputs.** Ask which receptor file and which docking output file.
   Confirm the docking program if it is not obvious from the extension.
2. **Load.** Use `mol new` for the receptor and `mol new` (+ `mol addfile` if
   needed) for the poses. Print pose count back to the user.
3. **Parse scores** if available. Do this before drawing — the scores often
   drive the color scheme.
4. **Reset and dress.** Drop existing reps, set the display defaults, then add
   cartoon + pocket licorice + ligand reps in that order. Use the helper Tcl
   in `scripts/scene_preset.tcl` to skip boilerplate.
5. **Snapshot and verify.** Render, then call `capture_vmd_snapshot`. If the
   ligand is hidden behind cartoon, rotate; if colors clash, switch to
   ColorID-based fixed colors.
6. **Optional plots.** If the user wants quantitative figures (score chart,
   RMSD matrix, interaction map), extract data via the helpers above and
   produce both PNG and SVG.
7. **Iterate.** Publication figures usually need 2-3 rounds: tweak rotation,
   lighting, ligand thickness, label placement.

## Common pitfalls

- **Cross-molecule selections.** `within X of` only works within one molecule.
  Use `measure contacts` and rebuild a selection from atom indices.
- **PDBQT charges show up as colors.** If the ligand looks dull or all-grey,
  you accidentally have `mol color Charge` instead of `Name`.
- **`mol drawframes` order.** The framelist takes a Tcl list (`{0}`,
  `{1 2 3}`), not a comma-separated string.
- **`measure rmsd` requires equal atom counts.** Different protonation states
  across poses break it; use `noh` selection.
- **`render snapshot` writes TGA, not PNG.** Convert via the runtime's image
  utils (`read_image_as_png_bytes`) or `render Tachyon` to a different
  filename and post-process.
- **PDBQT plugin missing on macOS ARM64.** VMD 1.9.4a57 ships without the
  pdbqt molfile plugin on Apple Silicon, so `mol new ... type pdbqt` fails.
  The helper `vmdai::load_format` detects this and falls back to `type pdb`
  automatically — PDBQT is a PDB superset and the `pdb` plugin handles it
  correctly for visualization (atom types and partial charges in the extra
  columns are dropped, BRANCH/ROOT records are ignored). If you bypass the
  helpers and call `mol new` directly, do the fallback yourself or convert
  via OpenBabel: `obabel input.pdbqt -O input.pdb`.
- **Surf representation is slow.** On a 5000-atom receptor it can hang the
  GUI for 5-10s. Restrict to pocket residues or use `QuickSurf`.
- **Display lighting.** `display ambientocclusion on` plus `display shadows
  on` add a lot of polish, but require a TachyonInternal render — they have
  no effect on `render snapshot`.
- **Background.** Always set `color Display Background white` for paper
  figures; the default near-black is fine on screen but kills printability.

## Quick recipe library

Each script in `scripts/` is sourceable with `source /path/to/script.tcl`:

- `scripts/load_docking.tcl` — receptor + poses loader with format autodetect.
- `scripts/scene_preset.tcl` — clean white-background pocket scene preset.
- `scripts/scoring.tcl` — Vina/SDF score parser, writes scores to User column.
- `scripts/interactions.tcl` — H-bond and contact extractors per pose.

Source them once per session, then call the procs they expose
(`vmdai::load_docking`, `vmdai::scene_pocket`, `vmdai::vina_scores`,
`vmdai::pose_hbonds`, `vmdai::pose_rmsd_matrix`).
