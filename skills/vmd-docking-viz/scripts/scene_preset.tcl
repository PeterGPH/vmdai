# scene_preset.tcl
# Publication-quality scene preset for protein-ligand docking visualization.
#
# Public procs:
#   vmdai::reset_reps <molid>              -> drop every rep on a molecule
#   vmdai::pocket_resids <rec_id> <lig_id> [cutoff=5.0] [frame=0]
#                                          -> list of resid integers
#   vmdai::scene_pocket <rec_id> <lig_id>  -> dress receptor + ligand
#                                             top pose only, with pocket licorice
#   vmdai::scene_pose_ensemble <rec_id> <lig_id>
#                                          -> top pose prominent, alt poses thin
#
# All procs assume vmd_ai is driving a live VMD. They never call render —
# leave that to the caller.

namespace eval vmdai {}

proc vmdai::reset_reps {molid} {
    set n [molinfo $molid get numreps]
    for {set i [expr {$n - 1}]} {$i >= 0} {incr i -1} {
        mol delrep $i $molid
    }
}

proc vmdai::display_defaults {} {
    display projection Orthographic
    display depthcue off
    axes location Off
    color Display Background white
}

proc vmdai::pocket_resids {rec_id lig_id {cutoff 5.0} {frame 0}} {
    set lig [atomselect $lig_id "all" frame $frame]
    set rec [atomselect $rec_id "protein"]
    set contacts [measure contacts $cutoff $lig $rec]
    set rec_idx [lindex $contacts 1]
    $lig delete
    $rec delete

    if {[llength $rec_idx] == 0} {
        return [list]
    }
    set near [atomselect $rec_id "index $rec_idx"]
    set resids [lsort -unique -integer [$near get resid]]
    $near delete
    return $resids
}

proc vmdai::scene_pocket {rec_id lig_id args} {
    # Optional: -cutoff <A>, -surface <0|1>
    set cutoff 5.0
    set with_surface 0
    foreach {k v} $args {
        switch -- $k {
            "-cutoff"  { set cutoff $v }
            "-surface" { set with_surface $v }
        }
    }

    vmdai::reset_reps $rec_id
    vmdai::reset_reps $lig_id
    vmdai::display_defaults

    # Receptor cartoon (gray)
    mol representation NewCartoon 0.3 12 4.5
    mol color ColorID 8
    mol selection "protein"
    mol material AOChalky
    mol addrep $rec_id

    # Pocket licorice
    set resids [vmdai::pocket_resids $rec_id $lig_id $cutoff 0]
    if {[llength $resids] > 0} {
        mol representation Licorice 0.25 12 12
        mol color Name
        mol selection "protein and resid $resids"
        mol material Opaque
        mol addrep $rec_id

        if {$with_surface} {
            mol representation Surf 1.4
            mol color ColorID 6
            mol selection "protein and resid $resids"
            mol material Transparent
            mol addrep $rec_id
        }
    }

    # Ligand (top pose)
    mol representation Licorice 0.35 12 12
    mol color Name
    mol selection "all"
    mol material Opaque
    mol addrep $lig_id
    set lig_rep [expr {[molinfo $lig_id get numreps] - 1}]
    mol drawframes $lig_id $lig_rep {0}

    return [dict create pocket_resids $resids lig_rep $lig_rep]
}

proc vmdai::scene_pose_ensemble {rec_id lig_id args} {
    set scene [vmdai::scene_pocket $rec_id $lig_id {*}$args]
    set npose [molinfo $lig_id get numframes]
    if {$npose <= 1} { return $scene }

    mol representation Licorice 0.15 12 12
    mol color ColorID 7
    mol selection "all"
    mol material Transparent
    mol addrep $lig_id
    set rep [expr {[molinfo $lig_id get numreps] - 1}]

    set rest {}
    for {set f 1} {$f < $npose} {incr f} { lappend rest $f }
    mol drawframes $lig_id $rep $rest

    dict set scene alt_rep $rep
    return $scene
}

# Highlight clashing atoms in the viewport. Adds a red VDW rep on the
# receptor atoms involved in clashes for the requested pose, plus a yellow
# VDW rep on the ligand atoms. Useful for "where does this pose clash?"
# inspection. Returns the list of rep indices added (so the caller can
# remove them later with `mol delrep`).
proc vmdai::highlight_clashes {recmolid ligmolid clashes pose_idx} {
    set added [list]
    if {![dict exists $clashes $pose_idx]} { return $added }
    set rec [dict get $clashes $pose_idx]
    set pairs [dict get $rec pairs]
    if {[llength $pairs] == 0} { return $added }

    set lig_idx [list]
    set rec_idx [list]
    foreach pr $pairs {
        lappend lig_idx [lindex $pr 0]
        lappend rec_idx [lindex $pr 1]
    }
    set lig_idx [lsort -unique -integer $lig_idx]
    set rec_idx [lsort -unique -integer $rec_idx]

    # Receptor clashing atoms: red VDW spheres
    mol representation VDW 0.6 12
    mol color ColorID 1
    mol selection "index $rec_idx"
    mol material Glossy
    mol addrep $recmolid
    lappend added [list $recmolid [expr {[molinfo $recmolid get numreps] - 1}]]

    # Ligand clashing atoms: yellow VDW spheres
    mol representation VDW 0.6 12
    mol color ColorID 4
    mol selection "index $lig_idx"
    mol material Glossy
    mol addrep $ligmolid
    set rep [expr {[molinfo $ligmolid get numreps] - 1}]
    mol drawframes $ligmolid $rep [list $pose_idx]
    lappend added [list $ligmolid $rep]

    return $added
}

# Frame the camera around a target molecule with sensible margin. Sets
# orthographic projection, resets the view, then computes a scale factor
# such that the bounding sphere of `selstr` fits within the viewport with
# `padding` (1.0 = exact fit, 1.4 = 40% margin around the object).
#
# Optional kwargs:
#   -padding <float>   default 1.4
#   -rotate {y x}      degrees, default {-25 10}
#   -projection <p>    Orthographic (default) or Perspective
#
# Returns the computed scale factor.
proc vmdai::frame_scene {target_molid {selstr "all"} args} {
    set padding 1.4
    set rotation [list -25 10]
    set proj "Orthographic"
    foreach {k v} $args {
        switch -- $k {
            "-padding"    { set padding $v }
            "-rotate"     { set rotation $v }
            "-projection" { set proj $v }
        }
    }

    display projection $proj
    display resetview

    # Bounding box of the selection -> radius of enclosing sphere
    set sel [atomselect $target_molid $selstr]
    if {[$sel num] == 0} {
        $sel delete
        return 1.0
    }
    set bbox [measure minmax $sel]
    $sel delete
    set lo [lindex $bbox 0]
    set hi [lindex $bbox 1]
    set dx [expr {[lindex $hi 0] - [lindex $lo 0]}]
    set dy [expr {[lindex $hi 1] - [lindex $lo 1]}]
    set dz [expr {[lindex $hi 2] - [lindex $lo 2]}]
    set diag [expr {sqrt($dx*$dx + $dy*$dy + $dz*$dz)}]
    if {$diag < 1.0} { set diag 1.0 }

    # Empirically: scale 1.0 fits ~25 A in the default ortho view,
    # so target_scale ~= 25 / (diag * padding).
    set target_scale [expr {25.0 / ($diag * $padding)}]
    scale to $target_scale

    rotate y by [lindex $rotation 0]
    rotate x by [lindex $rotation 1]
    return $target_scale
}
