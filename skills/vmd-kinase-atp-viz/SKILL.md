---
name: vmd-kinase-atp-viz
version: "0.1.0"
author: vmdai
tools:
  - run_vmd_command
  - capture_vmd_snapshot
requires:
  - vmd
description: >
  Publication-quality VMD visualization of protein kinases bound to ATP, ATP
  analogs (AMPPNP, AMPPCP, ANP), or kinase inhibitors. Triggers when the user
  asks for an "academic style" figure of a kinase, or for visualization of
  ATP-binding, ATP-pocket, P-loop, hinge region, DFG motif, gatekeeper residue,
  catalytic Lys, αC helix, or activation loop. Examples: CDK2, CDK4, CDK6, CDK7,
  CDK9, ERK1, ERK2, JNK1, p38α, p38β, GSK3β, Abl1, Src, Lck, EGFR, MET, ALK,
  PI3K, mTOR, AKT, PKA, PKC, AurA, AurB. Use whenever a request mentions
  "academic style" or "publication figure" alongside a kinase and a ligand.
---

## When this skill triggers

Triggers on requests of the form:
* "show CDK2 / Abl / EGFR in an academic style with its ATP / inhibitor"
* "visualize the ATP-binding pocket of <kinase>"
* "make a publication figure of <kinase> bound to <ligand>"
* "render the kinase hinge region and DFG motif"

## Canonical layered representation recipe

A kinase–ATP figure for a paper has six representation layers, in this order.
Each layer addresses a specific structural question; together they tell the
binding story.

```tcl
# Wipe defaults so we start clean.
mol delrep 0 top

# Layer 1 — protein backbone as cartoon, secondary-structure coloring.
# Distinguishes the bilobal kinase fold: N-lobe (β-sheet rich) vs C-lobe
# (α-helix rich) at a glance.
mol representation NewCartoon 0.3 12.0 4.5 1
mol color Structure
mol selection "protein"
mol material AOChalky
mol addrep top

# Layer 2 — ATP / ligand as Licorice, colored by element. Atomic-level detail.
mol representation Licorice 0.18 32.0 32.0
mol color Name
mol selection "resname ATP or resname ANP or resname AMP or resname ADP"
mol material Glossy
mol addrep top

# Layer 3 — ATP volume as transparent VDW. Occupancy in the cleft.
mol representation VDW 0.55 32.0
mol color Name
mol selection "resname ATP or resname ANP"
mol material Transparent
mol addrep top

# Layer 4 — pocket residues (within 4.5 Å of ATP) as Licorice. Side-chain
# contacts that define the binding mode. 4.5 Å is the standard cutoff;
# 5.0 Å picks up second-shell residues.
mol representation Licorice 0.12 32.0 32.0
mol color ResType
mol selection "protein and within 4.5 of (resname ATP or resname ANP)"
mol material Glossy
mol addrep top

# Layer 5 — pocket SES as ghost surface. Shape complementarity of the cleft.
mol representation Surf 1.4
mol color ResType
mol selection "protein and within 4.5 of (resname ATP or resname ANP)"
mol material Ghost
mol addrep top

# Layer 6 — H-bond geometry between ATP and protein. Explicit donors/acceptors.
mol representation HBonds 3.5 30.0 4.0
mol color ColorID 1
mol selection "resname ATP or resname ANP"
mol material Opaque
mol addrep top
```

## Display + rendering — the "academic" half

Default VMD looks wrong for papers. These four settings flip it to publication
mode in one block.

```tcl
# White background — standard for journal figures.
color Display Background white
axes location Off

# Secondary-structure palette: blue α / yellow β / silver loop.
# Most-cited convention in structural-biology figures.
color Structure Helix blue
color Structure Sheet yellow
color Structure Coil silver

# Orthographic projection — NEVER perspective for a paper.
display projection Orthographic

# Ambient occlusion + shadows. The single biggest visual upgrade.
display ambientocclusion on
display aoambient 0.75
display aodirect 0.75
display shadows on

# 4-light setup — flat lighting reads as cheap.
light 0 on
light 1 on
light 2 on
light 3 on
```

## Catalytic / regulatory features worth highlighting

Annotate these in the caption; optionally add a 7th rep for each.

| Feature | VMD selection | Why it matters |
|---|---|---|
| Hinge region | `protein and resid 80 to 86` (CDK2 numbering; ±2 across kinases) | Backbone N/O atoms H-bond to adenine — the universal anchor |
| P-loop (Gly-rich) | `protein and resid 10 to 17 and backbone` | Wraps over phosphates |
| αC helix | `protein and resid 45 to 56 and structure H` | In/out conformation = active/inactive |
| DFG motif | `protein and resname ASP and resid 145 and resname PHE and resid 146 and resname GLY and resid 147` | DFG-in (active) vs DFG-out (Type-II inhibitor binding) |
| Catalytic Lys | `protein and resname LYS and resid 33` | Coordinates α/β phosphates |
| Gatekeeper | `protein and resid 80` (CDK2) | Controls back-pocket access — mutation hotspot |

## Camera orientation for kinase figures

The canonical "kinase view" puts the hinge facing the viewer, N-lobe top,
C-lobe bottom. From `display resetview`:

```tcl
display resetview
rotate x by -60
rotate y by 25
rotate z by 10
scale by 1.35
```

## Rendering

```tcl
# Off-screen, ray-traced, paper-quality.
render TachyonInternal /tmp/kinase_figure.tga

# If you want ambient-occlusion shadows visible in the saved image,
# TachyonInternal honors the AO settings above. `render snapshot`
# does NOT — it just grabs the live framebuffer.
```

## Common PDB IDs (for the model to recognize)

* CDK2 + ATP analog: 1HCK (AMPPNP), 1FIN (CDK2-cyclin A + ATP)
* CDK6 + INK4: 1BLX
* ERK2 + ATP: 4ERK
* p38α + SB203580: 1A9U
* Abl1 + imatinib: 1IEP (DFG-out)
* EGFR + erlotinib: 1M17

## Anti-patterns the model should avoid

* `mol material Opaque` for the protein body — kills the AO depth cue
* `display projection Perspective` — reads as a screenshot, not a figure
* `render snapshot` for the final image — no AO, no shadows
* Selecting the pocket with `"resname ATP"` alone — that's the ligand, not the
  pocket; use `"protein and within 4.5 of resname ATP"`
* `mol color Type` everywhere — Type colors by atom type, very low contrast;
  prefer `Structure` for protein backbone and `Name` for ligand atomic detail
