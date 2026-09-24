---
name: vmd-ligand-pore-viz
version: "1.0.0"
author: vmdai
tools:
  - run_vmd_command
  - capture_vmd_snapshot
requires:
  - python3
  - numpy
  - matplotlib
  - vmd
output:
  - "/tmp/<analysis>.dat"        # Tcl-extracted numerical data (one column per metric)
  - "/tmp/<figure>.png"          # 300 DPI raster figure for quick viewing
  - "/tmp/<figure>.svg"          # vector figure for publication editing
description: >
  Publication-quality ligand-pore visualization from VMD trajectories using matplotlib.
  Use this skill whenever the user wants to analyze ligand-pore interactions, plot pore
  radius profiles, track ligand positions through channels/pores, generate contact maps,
  create distance time-series plots, or produce any scientific figure from VMD trajectory
  data. Also trigger for requests involving: ion channel analysis, membrane pore profiling,
  ligand binding pathway visualization, permeation event plotting, HOLE analysis, or any
  matplotlib-based figure generation from molecular dynamics data loaded in VMD.
---

<example>
User: "Plot the ligand-pore distance over the trajectory."
Skill action:
  1. Inspect via run_vmd_command — confirm ligand resname and trajectory frame count.
  2. Run the Tcl distance loop; write /tmp/lig_pore_dist.dat (frame, distance).
  3. Generate a matplotlib script following the publication style; execute with python3.
  4. Return /tmp/ligand_pore_distance.png and .svg.
</example>

<example>
User: "Make a contact heatmap showing which pore residues touch the ligand."
Skill action:
  1. Compute residue-level contacts per frame via Tcl; write /tmp/contact_map.dat.
  2. Build a NumPy contact matrix indexed by (residue, frame) in the Python script.
  3. Render an imshow heatmap with the YlOrRd colormap and residue IDs on the Y axis.
  4. Save /tmp/contact_heatmap.png and .svg.
</example>

# VMD Ligand-Pore Visualization Skill

Generate publication-level matplotlib figures from VMD trajectory data, focusing on
ligand-pore interactions. The pipeline has two phases: **extract** numerical data from
VMD via Tcl commands, then **plot** using a Python script executed in the shell.

## Architecture

You have two tools available through the vmd_ai runtime:

- `run_vmd_command` — execute Tcl commands inside a live VMD session
- `capture_vmd_snapshot` — grab a PNG of the VMD viewport

The plotting itself happens outside VMD. After extracting data via Tcl, write a
Python/matplotlib script and run it with `python3` in the shell. VMD's Tcl console
is great for trajectory analysis but not for publication figures — matplotlib gives
you full control over aesthetics.

## Phase 1: Data Extraction via VMD Tcl

### Know your system first

Before computing anything, inspect what's loaded:

```tcl
# What molecules are loaded?
molinfo list
# How many frames in the trajectory?
molinfo top get numframes
# What's the selection syntax for the ligand?
set lig [atomselect top "resname LIG"]
$lig num
# What residues line the pore?
set pore [atomselect top "protein and within 8 of resname LIG"]
lsort -unique [$pore get resid]
```

Always confirm atom counts are nonzero before proceeding. A zero-atom selection
means the residue name or selection syntax is wrong — ask the user to clarify.

### Pore radius profile

VMD doesn't have a built-in pore radius calculator, but you can approximate it
by measuring distances from a central axis. For a proper HOLE analysis, the user
needs the HOLE executable installed. The Tcl approach below works without external
dependencies:

```tcl
# Approximate pore radius along z-axis at frame 0
set nframes [molinfo top get numframes]
set zmin -20.0
set zmax 20.0
set dz 1.0

set outfile [open "/tmp/pore_radius.dat" w]
puts $outfile "# z_coord  min_radius"

for {set z $zmin} {$z <= $zmax} {set z [expr {$z + $dz}]} {
    set ring [atomselect top "protein and z > [expr {$z - 0.5}] and z < [expr {$z + 0.5}]" frame 0]
    if {[$ring num] > 0} {
        set com [measure center $ring]
        set cx [lindex $com 0]
        set cy [lindex $com 1]
        # Compute min distance from axis to any protein atom in this slab
        set coords [$ring get {x y}]
        set minr 999.0
        foreach xy $coords {
            set dx [expr {[lindex $xy 0] - $cx}]
            set dy [expr {[lindex $xy 1] - $cy}]
            set r [expr {sqrt($dx*$dx + $dy*$dy)}]
            if {$r < $minr} { set minr $r }
        }
        puts $outfile "$z $minr"
    }
    $ring delete
}
close $outfile
```

For multi-frame analysis, wrap the z-loop inside a frame loop and write one file
per frame, or append frame index as a column.

### Ligand center-of-mass tracking

Track where the ligand moves through the pore over the trajectory:

```tcl
set lig [atomselect top "resname LIG"]
set nframes [molinfo top get numframes]
set outfile [open "/tmp/ligand_com.dat" w]
puts $outfile "# frame  x  y  z"

for {set f 0} {$f < $nframes} {incr f} {
    $lig frame $f
    $lig update
    set com [measure center $lig weight mass]
    puts $outfile "$f [lindex $com 0] [lindex $com 1] [lindex $com 2]"
}
close $outfile
$lig delete
```

### Distance time-series

Distance between ligand COM and a reference point (e.g., pore center):

```tcl
set lig [atomselect top "resname LIG"]
set pore_ref [atomselect top "protein and resid 150 151 152 and name CA"]
set nframes [molinfo top get numframes]
set outfile [open "/tmp/lig_pore_dist.dat" w]
puts $outfile "# frame  distance"

for {set f 0} {$f < $nframes} {incr f} {
    $lig frame $f
    $lig update
    $pore_ref frame $f
    $pore_ref update
    set com1 [measure center $lig weight mass]
    set com2 [measure center $pore_ref weight mass]
    set dx [expr {[lindex $com1 0] - [lindex $com2 0]}]
    set dy [expr {[lindex $com1 1] - [lindex $com2 1]}]
    set dz [expr {[lindex $com1 2] - [lindex $com2 2]}]
    set dist [expr {sqrt($dx*$dx + $dy*$dy + $dz*$dz)}]
    puts $outfile "$f $dist"
}
close $outfile
$lig delete
$pore_ref delete
```

### Contact map (residue-level)

Identify which pore-lining residues contact the ligand across frames:

```tcl
set lig [atomselect top "resname LIG"]
set nframes [molinfo top get numframes]
set cutoff 4.0
set outfile [open "/tmp/contact_map.dat" w]
puts $outfile "# frame  resid  min_distance"

for {set f 0} {$f < $nframes} {incr f} {
    $lig frame $f
    $lig update
    set nearby [atomselect top "protein and within $cutoff of resname LIG" frame $f]
    set resids [lsort -unique -integer [$nearby get resid]]
    foreach rid $resids {
        set res_atoms [atomselect top "protein and resid $rid" frame $f]
        # Use contactlist for precise distances
        set dists [measure contacts $cutoff $lig $res_atoms]
        puts $outfile "$f $rid 1"
        $res_atoms delete
    }
    $nearby delete
}
close $outfile
$lig delete
```

### Hydrogen bonds

```tcl
set nframes [molinfo top get numframes]
set outfile [open "/tmp/hbonds.dat" w]
puts $outfile "# frame  num_hbonds"

for {set f 0} {$f < $nframes} {incr f} {
    set lig [atomselect top "resname LIG" frame $f]
    set prot [atomselect top "protein and within 5 of resname LIG" frame $f]
    set hb [measure hbonds 3.5 30 $lig $prot]
    set nhb [llength [lindex $hb 0]]
    puts $outfile "$f $nhb"
    $lig delete
    $prot delete
}
close $outfile
```

## Phase 2: Matplotlib Plotting

After extracting `.dat` files from VMD, write a self-contained Python script and
execute it. The script should produce both PNG (for quick viewing) and SVG (for
publication). Save outputs to the user's working directory or `/tmp/`.

### Publication style standards

Every figure must follow these conventions:

- **Font**: Arial or Helvetica, 10-12pt for axis labels, 8-10pt for tick labels
- **Figure size**: single column = (3.5, 2.8) inches, double column = (7.0, 4.0) inches
- **DPI**: 300 for PNG
- **Line width**: 1.0-1.5pt for data lines, 0.5pt for axes
- **Colors**: Use a colorblind-safe palette (e.g., seaborn's "colorblind" or manually define)
- **Axes**: Always label with units. Use angstroms (r"$\AA$"), nanoseconds, kcal/mol as appropriate
- **No chartjunk**: remove top and right spines, minimize gridlines
- **Save both formats**: `.png` at 300 DPI and `.svg` for vector editing

### Script template

Write plotting scripts following this pattern:

```python
#!/usr/bin/env python3
"""Plot ligand-pore distance over trajectory."""
import numpy as np
import matplotlib
matplotlib.use("Agg")  # headless — no display needed
import matplotlib.pyplot as plt

# -- Style setup --
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 10,
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.major.width": 0.8,
    "ytick.major.width": 0.8,
    "lines.linewidth": 1.2,
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox_inches": "tight",
    "savefig.pad_inches": 0.1,
})

# Colorblind-safe palette
COLORS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#F0E442", "#56B4E9"]

# -- Load data --
data = np.loadtxt("/tmp/lig_pore_dist.dat", comments="#")
frames = data[:, 0]
dist = data[:, 1]

# Convert frames to time if timestep known (e.g., 2 ps/frame)
dt_ps = 2.0  # adjust based on trajectory
time_ns = frames * dt_ps / 1000.0

# -- Plot --
fig, ax = plt.subplots(figsize=(3.5, 2.8))
ax.plot(time_ns, dist, color=COLORS[0], linewidth=1.2)
ax.set_xlabel("Time (ns)")
ax.set_ylabel(r"Distance ($\AA$)")
ax.set_title("Ligand-Pore Distance", fontsize=11, fontweight="bold")

# Optional: running average overlay
window = 50
if len(dist) > window:
    avg = np.convolve(dist, np.ones(window)/window, mode="valid")
    t_avg = time_ns[:len(avg)]
    ax.plot(t_avg, avg, color=COLORS[1], linewidth=1.5, alpha=0.8, label=f"{window}-frame avg")
    ax.legend(frameon=False, fontsize=8)

fig.savefig("/tmp/ligand_pore_distance.png")
fig.savefig("/tmp/ligand_pore_distance.svg")
plt.close()
print("Saved: /tmp/ligand_pore_distance.png and .svg")
```

### Plot type recipes

**Pore radius profile** (line plot with optional error band):
```python
fig, ax = plt.subplots(figsize=(3.5, 3.5))
ax.plot(z_coords, radius_mean, color=COLORS[0])
ax.fill_between(z_coords, radius_mean - radius_std, radius_mean + radius_std,
                alpha=0.2, color=COLORS[0])
ax.set_xlabel(r"Pore axis ($\AA$)")
ax.set_ylabel(r"Pore radius ($\AA$)")
ax.axhline(y=1.4, ls="--", color="gray", lw=0.8, label="Water radius")
ax.legend(frameon=False)
```

**Contact map heatmap** (residue vs frame):
```python
fig, ax = plt.subplots(figsize=(7.0, 3.0))
im = ax.imshow(contact_matrix, aspect="auto", cmap="YlOrRd",
               interpolation="nearest", origin="lower")
ax.set_xlabel("Frame")
ax.set_ylabel("Residue ID")
ax.set_yticks(range(len(resid_labels)))
ax.set_yticklabels(resid_labels, fontsize=7)
cbar = fig.colorbar(im, ax=ax, shrink=0.8)
cbar.set_label("Contact")
```

**Ligand z-position time series** (with pore region shading):
```python
fig, ax = plt.subplots(figsize=(5.0, 2.8))
ax.plot(time_ns, lig_z, color=COLORS[0], lw=1.0)
ax.axhspan(pore_z_min, pore_z_max, alpha=0.1, color="gray", label="Pore region")
ax.set_xlabel("Time (ns)")
ax.set_ylabel(r"Ligand z-position ($\AA$)")
ax.legend(frameon=False)
```

**Hydrogen bond count** (bar/line with running average):
```python
fig, ax = plt.subplots(figsize=(5.0, 2.5))
ax.bar(time_ns, nhbonds, width=dt_ps/1000*0.8, color=COLORS[2], alpha=0.4)
ax.plot(time_ns_avg, nhbonds_avg, color=COLORS[0], lw=1.5, label="Running avg")
ax.set_xlabel("Time (ns)")
ax.set_ylabel("H-bond count")
ax.legend(frameon=False)
```

**Multi-panel composite figure** (combine several analyses):
```python
fig, axes = plt.subplots(3, 1, figsize=(5.0, 7.0), sharex=True,
                          gridspec_kw={"hspace": 0.15})
# Panel A: distance
axes[0].plot(...)
axes[0].set_ylabel(r"Distance ($\AA$)")
axes[0].text(-0.12, 1.05, "A", transform=axes[0].transAxes,
             fontsize=14, fontweight="bold")
# Panel B: contacts
axes[1].imshow(...)
axes[1].text(-0.12, 1.05, "B", ...)
# Panel C: H-bonds
axes[2].bar(...)
axes[2].set_xlabel("Time (ns)")
axes[2].text(-0.12, 1.05, "C", ...)
fig.savefig("/tmp/composite_figure.png")
fig.savefig("/tmp/composite_figure.svg")
```

## Workflow Checklist

When the user asks for a ligand-pore visualization:

1. **Inspect the system**: use `run_vmd_command` to check loaded molecules, frame count,
   and atom selection syntax for the ligand and pore residues.
2. **Confirm selections**: verify atom counts are nonzero. If the ligand residue name
   isn't obvious, list unique residue names: `lsort -unique [[atomselect top "not protein and not water"] get resname]`
3. **Extract data**: run the appropriate Tcl analysis loop(s), writing `.dat` files to `/tmp/`.
   For long trajectories (>5000 frames), consider stride sampling to keep extraction fast.
4. **Verify data**: briefly check the output file has data (e.g., read first/last lines).
5. **Plot**: write a self-contained Python script following the publication style standards.
   Execute with `python3`. Include both PNG and SVG output.
6. **Show the user**: present the PNG file. If they want the VMD viewport too, use
   `capture_vmd_snapshot` to show the 3D scene alongside the plot.
7. **Iterate**: publication figures usually need 2-3 rounds of refinement. Common asks:
   adjust colors, add annotations, change axis range, overlay multiple datasets.

## Common Pitfalls

- **atomselect leaks**: always `$sel delete` after use — VMD accumulates selections in memory
- **Frame not updated**: after `$sel frame $f`, call `$sel update` so coordinates refresh
- **Large trajectories**: extracting per-frame data for 100k frames takes time. Use stride
  (`for {set f 0} {$f < $nframes} {incr f 10}`) and tell the user it's sampling every 10th frame
- **measure hbonds syntax**: takes `cutoff angle sel1 sel2` — the angle is in degrees (typically 30)
- **Tcl floating point**: use `expr {double($x)}` to avoid integer division
- **matplotlib Agg backend**: always set `matplotlib.use("Agg")` before importing pyplot —
  there's no display server in the runtime environment
- **Missing numpy**: if numpy isn't available, use Python's built-in csv module and lists;
  but numpy is strongly preferred for any nontrivial data manipulation
