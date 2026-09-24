## atomselect

Create a selection object referencing a subset of atoms. Syntax:
`atomselect <molid> "<selection>"`. The returned handle (a Tcl proc
name like `atomselect12`) supports per-frame queries and updates.

Important: `atomselect` selections are bound to a single molecule.
Cross-molecule selectors like `within 5 of` only work inside one molid.
For cross-molecule contacts, use `measure contacts`.

Example:

    set sel [atomselect 0 "protein and resid 100 to 110"]
    $sel get {x y z}
    $sel num
    $sel delete

Always call `$sel delete` when finished — selections leak otherwise.

## atomselect frame

Switch a selection's reference frame. Syntax: `$sel frame <n>`. The
selection's atom *indices* don't change but the coordinate-returning
methods (`get x`, `measure rmsd`, etc.) reflect the new frame.

## measure contacts

Find atom pairs within a cutoff distance. Syntax:
`measure contacts <cutoff> <selA> <selB>`. Returns a two-element list:
the indices of `selA` atoms followed by the indices of `selB` atoms
(parallel lists, same length).

Cross-molecule friendly — `selA` and `selB` can come from different
molids. This is the canonical workaround when the `within` selector
isn't available because the two atoms live in different molecules.

## measure rmsd

Compute root-mean-square deviation between two selections of equal
size. Syntax: `measure rmsd <sel1> <sel2>`. Both selections must have
the same atom count; use `noh` (skip hydrogens) for stability across
poses with inconsistent protonation.

## measure hbonds

Geometric H-bond detection. Syntax:
`measure hbonds <cutoff> <angle> <selA> [<selB>]`. Returns three lists:
donors, acceptors, and hydrogens. **`selA` and `selB` must come from
the same molecule** — there is no cross-molecule mode. Merge with
topotools first if you need inter-molecular H-bonds.
