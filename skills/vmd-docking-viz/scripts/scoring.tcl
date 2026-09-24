# scoring.tcl
# Docking-score parsers and helpers to push scores into the User column for
# heatmap-style coloring.
#
# Public procs:
#   vmdai::vina_scores <pdbqt_path>            -> list of {affinity rmsd_lb rmsd_ub}
#   vmdai::sdf_scores  <sdf_path> <tag>        -> list of floats (one per pose)
#   vmdai::write_score_to_user <molid> <scores>
#   vmdai::score_range <scores>                -> {min max}

namespace eval vmdai {}

proc vmdai::vina_scores {filename} {
    if {![file exists $filename]} {
        error "vmdai::vina_scores: $filename not found"
    }
    set scores {}
    set fh [open $filename r]
    while {[gets $fh line] >= 0} {
        if {[regexp {REMARK VINA RESULT:\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)} $line _ aff lb ub]} {
            lappend scores [list $aff $lb $ub]
        }
    }
    close $fh
    return $scores
}

# Parse a property tag from an SDF: e.g. tag = "minimizedAffinity" or "score"
proc vmdai::sdf_scores {filename tag} {
    if {![file exists $filename]} {
        error "vmdai::sdf_scores: $filename not found"
    }
    set scores {}
    set fh [open $filename r]
    set capture 0
    while {[gets $fh line] >= 0} {
        if {[regexp "^>\\s*<$tag>" $line]} {
            set capture 1
            continue
        }
        if {$capture && [string trim $line] ne ""} {
            if {[string is double -strict [string trim $line]]} {
                lappend scores [string trim $line]
            }
            set capture 0
        }
    }
    close $fh
    return $scores
}

proc vmdai::write_score_to_user {molid scores} {
    set sel [atomselect $molid "all"]
    set nf [molinfo $molid get numframes]
    set n [llength $scores]
    if {$n == 0} {
        $sel delete
        error "vmdai::write_score_to_user: empty score list"
    }
    for {set f 0} {$f < $nf} {incr f} {
        $sel frame $f
        set v [lindex $scores [expr {$f < $n ? $f : $n - 1}]]
        # Vina scores arrive as {affinity lb ub}; pull the affinity if so
        if {[llength $v] > 1} { set v [lindex $v 0] }
        if {$v eq "" || ![string is double -strict $v]} { set v 0.0 }
        $sel set user $v
    }
    $sel delete
}

proc vmdai::score_range {scores} {
    if {[llength $scores] == 0} { return [list 0.0 0.0] }
    set vmin 1e30
    set vmax -1e30
    foreach v $scores {
        if {[llength $v] > 1} { set v [lindex $v 0] }
        if {![string is double -strict $v]} { continue }
        if {$v < $vmin} { set vmin $v }
        if {$v > $vmax} { set vmax $v }
    }
    return [list $vmin $vmax]
}
