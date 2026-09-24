## Loading Vina docking output

AutoDock Vina writes all top-N poses as sequential frames in one PDBQT
file. The receptor is in a separate file. Standard pattern:

    set rec_id [mol new "receptor.pdbqt" type pdbqt waitfor all]
    mol rename $rec_id "receptor"
    set lig_id [mol new "vina_out.pdbqt" type pdbqt waitfor all]
    mol rename $lig_id "poses"
    set npose [molinfo $lig_id get numframes]

PDBQT plugin missing on macOS ARM64? Fall back to `type pdb`. PDBQT is
a PDB superset and the pdb loader handles it correctly for visualization.

## Pocket residue selection

The pocket is whatever protein residue sits within ~5 angstrom of the
ligand in the top pose. Compute it from `measure contacts` because
cross-molecule `within X of` is not supported:

    set lig_cur [atomselect $lig_id "all" frame 0]
    set rec_all [atomselect $rec_id "protein"]
    set contacts [measure contacts 5.0 $lig_cur $rec_all]
    set rec_idx [lindex $contacts 1]
    set near [atomselect $rec_id "index $rec_idx"]
    set pocket_resids [lsort -unique -integer [$near get resid]]

## Coloring poses by Vina score

Write the affinity into the User column then `mol color User`:

    set sel [atomselect $lig_id "all"]
    for {set f 0} {$f < [molinfo $lig_id get numframes]} {incr f} {
        $sel frame $f
        $sel set user [lindex $scores $f 0]
    }
    mol representation Licorice 0.25 12 12
    mol color User
    mol scaleminmax $lig_id $rep_idx -12.0 -4.0

## Multi-pose rendering

`mol drawframes` shows specific frames in a single rep — far better
than animating and rendering each pose:

    mol drawframes $lig_id $rep_idx {0 1 2 3 4}
