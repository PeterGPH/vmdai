# VMD Tcl correctness cheatsheet — common agent pitfalls

Concise, correct idioms for headless VMD scripting. Each entry exists because an
agent got it wrong; the **right** form is given first. Indexed under scope `vmd_ref`.

## Loading a structure

- Load **any** format with `mol new <path>` — VMD auto-detects PDB, mmCIF/PDBx, GRO, XYZ, DCD, etc.
- `mol new file.cif` works directly: the mmCIF reader plugin is named **`pdbx`** (you may see "Using plugin pdbx").
- **Wrong:** `mol load cif <path>` — `cif` is not a valid loader keyword and fails with "Cannot read file of type cif".
- Do **not** fetch a structure by PDB ID when a local file path is provided — load the given file.
- Explicit form if needed: `mol new <path> type pdbx waitfor all`.

## Atom selections

- `set sel [atomselect $molid "protein"]` — and call `$sel delete` when finished (selections leak otherwise).
- Coordinates: `$sel get {x y z}` — the list literal is `{x y z}`. **Wrong:** `{x y z]` (unbalanced brace → VMD waits for more input and the command appears to hang).
- One atom's index: `set i [lindex [$sel get index] 0]`.
- Useful selections: `protein`, `name CA`, `resid 1 to 10`, `name CA and resid 5`, `element C`, `resname PHE TYR TRP`.

## Measurements

- Radius of gyration: `measure rgyr $sel` → single value in Å (mass-weighted).
- RMSD: `measure rmsd $sel1 $sel2` → one value. For a single static structure compared with itself it is exactly **0.0** — report `0.0`, do not recompute or align.
- RMSF: `measure rmsf $sel` → a per-atom **list**. If one number is wanted, report its mean; for a single frame the RMSF is 0.
- Distance between two atoms: `measure bond [list $i $j]` → Å (indices, not selections).
- Angle / dihedral: `measure angle [list $i $j $k]` · `measure dihed [list $i $j $k $l]` → degrees, from four atom **indices** in a list.
- Contacts: `measure contacts <cutoff> $sel` → returns **two parallel lists** `{i-indices} {j-indices}`. The contact **count** is `[llength [lindex $result 0]]` — the result itself is not a number.

## Backbone dihedrals of residue *i*

- phi = C(i−1)–N(i)–CA(i)–C(i); psi = N(i)–CA(i)–C(i)–N(i+1).
- `set C0 [lindex [[atomselect $m "name C and resid [expr {$i-1}]"] get index] 0]` … then `measure dihed [list $C0 $N $CA $C]`.

## Representations (set properties *before* addrep)

```tcl
mol delrep 0 top
mol representation Licorice      ;# or NewCartoon, VDW, Lines
mol color Name                   ;# or Element, ResName, Charge
mol selection "protein"
mol addrep top
```

## Writing answer/result files

- Create the directory first — `open ... w` fails if it doesn't exist: `file mkdir <dir>`.
- `set f [open <path> w]; puts $f $value; close $f`.

## General Tcl gotchas

- Keep braces `{}` and brackets `[]` balanced; an open brace makes the interpreter wait for continuation (looks like a hang).
- Don't print per-atom coordinate dumps to the console — it floods output and burns context. Use summary measures.
