# interactions.tcl
# Per-pose interaction extractors: H-bonds, contacts, RMSD, and steric
# clashes against the receptor.
#
# Public procs:
#   vmdai::pose_hbonds <ligmolid> <recmolid> [cutoff=3.5] [angle=30]
#                                      -> list of integers, one per pose
#   vmdai::pose_contacts <ligmolid> <recmolid> [cutoff=4.0]
#                                      -> dict keyed by pose index, value
#                                         is sorted list of contacted resids
#   vmdai::pose_rmsd_matrix <ligmolid> [selstr="noh"]
#                                      -> NxN list of lists (RMSD in angstrom)
#   vmdai::pose_clashes <ligmolid> <recmolid> [overlap_tol=0.4]
#                                      -> dict per pose with count, total
#                                         overlap (A), worst overlap, and
#                                         a list of {lig_idx rec_idx
#                                         distance overlap rec_resname
#                                         rec_resid rec_name} tuples
#   vmdai::pose_clash_summary <ligmolid> <recmolid> [overlap_tol=0.4]
#                                      -> human-readable one-line/pose
#                                         summary suitable for `puts`
#   vmdai::write_clash_dat <path> <clashes>
#                                      -> tab-separated file consumable
#                                         by matplotlib
#   vmdai::write_dat <path> <header> <rows>
#                                      -> write a tab-delimited data file
#                                         consumable by matplotlib scripts

namespace eval vmdai {}

proc vmdai::pose_hbonds {ligmolid recmolid {cutoff 3.5} {angle 30}} {
    # VMD's `measure hbonds` requires both selections to come from the same
    # molecule. For docking we have receptor and ligand as separate molids,
    # so we approximate H-bonds via polar-heavy-atom contacts within the
    # donor-acceptor cutoff. This is the same proxy used by PyMOL's
    # `polar_contacts` and is a good stand-in for visualization purposes.
    # The `angle` argument is accepted for API compatibility but ignored
    # in this proxy; if you need true geometric H-bond detection, merge
    # the two molecules with topotools first.
    set nf [molinfo $ligmolid get numframes]
    set out {}
    for {set f 0} {$f < $nf} {incr f} {
        set lig [atomselect $ligmolid \
            "(name \"N.*\" or name \"O.*\") and not hydrogen" frame $f]
        set rec [atomselect $recmolid \
            "protein and (name \"N.*\" or name \"O.*\") and not hydrogen"]
        if {[$lig num] == 0 || [$rec num] == 0} {
            $lig delete; $rec delete
            lappend out 0
            continue
        }
        set contacts [measure contacts $cutoff $lig $rec]
        lappend out [llength [lindex $contacts 0]]
        $lig delete
        $rec delete
    }
    return $out
}

proc vmdai::pose_contacts {ligmolid recmolid {cutoff 4.0}} {
    set nf [molinfo $ligmolid get numframes]
    set out [dict create]
    for {set f 0} {$f < $nf} {incr f} {
        set lig [atomselect $ligmolid "all" frame $f]
        set rec [atomselect $recmolid "protein"]
        if {[$lig num] == 0 || [$rec num] == 0} {
            dict set out $f [list]
            $lig delete; $rec delete
            continue
        }
        set contacts [measure contacts $cutoff $lig $rec]
        set rec_idx [lindex $contacts 1]
        if {[llength $rec_idx] == 0} {
            dict set out $f [list]
        } else {
            set near [atomselect $recmolid "index $rec_idx"]
            dict set out $f [lsort -unique -integer [$near get resid]]
            $near delete
        }
        $lig delete
        $rec delete
    }
    return $out
}

proc vmdai::pose_rmsd_matrix {ligmolid {selstr "noh"}} {
    set nf [molinfo $ligmolid get numframes]
    if {$nf <= 0} { return {} }
    set sel [atomselect $ligmolid $selstr]
    set ref [atomselect $ligmolid $selstr]
    set rows {}
    for {set i 0} {$i < $nf} {incr i} {
        $ref frame $i
        set row {}
        for {set j 0} {$j < $nf} {incr j} {
            $sel frame $j
            lappend row [format "%.3f" [measure rmsd $sel $ref]]
        }
        lappend rows $row
    }
    $sel delete
    $ref delete
    return $rows
}

proc vmdai::write_dat {path header rows} {
    set fh [open $path w]
    if {$header ne ""} { puts $fh "# $header" }
    foreach r $rows {
        puts $fh [join $r "\t"]
    }
    close $fh
    return $path
}

# ---------------------------------------------------------------------------
# Steric clash analysis
#
# A "clash" is when two atoms are closer than the sum of their van der Waals
# radii minus an overlap tolerance. Probe and Reduce use 0.4 A as the
# tolerance; that's the default here. Different conventions:
#   tol = 0.0  -> any vdW overlap counts
#   tol = 0.4  -> only "significant" clashes (Probe / MolProbity standard)
#   tol = 1.0  -> only severe clashes
#
# Returns a dict with one entry per pose. Each entry is itself a dict with:
#   count       integer count of clashing atom pairs
#   total       sum of overlap distances (proxy for clash energy)
#   worst       single largest overlap (A); 0 if no clashes
#   resids      sorted list of unique receptor resids involved
#   pairs       list of {lig_idx rec_idx dist overlap rec_resname rec_resid rec_name}
# ---------------------------------------------------------------------------

proc vmdai::pose_clashes {ligmolid recmolid {overlap_tol 0.4}} {
    set nf [molinfo $ligmolid get numframes]

    # Pre-fetch receptor radii and metadata once — receptor doesn't change
    # across poses.
    set rec [atomselect $recmolid "all"]
    set rec_radii [$rec get radius]
    set rec_indices [$rec get index]
    set rec_resnames [$rec get resname]
    set rec_resids [$rec get resid]
    set rec_names [$rec get name]
    $rec delete

    set out [dict create]

    for {set f 0} {$f < $nf} {incr f} {
        set lig [atomselect $ligmolid "all" frame $f]
        if {[$lig num] == 0} {
            $lig delete
            dict set out $f [dict create count 0 total 0.0 worst 0.0 \
                resids [list] pairs [list]]
            continue
        }

        set lig_radii [$lig get radius]
        set lig_indices [$lig get index]

        # Use a generous distance cutoff so we don't miss any vdW overlaps
        # (max realistic vdW + tolerance ≈ 2.5 A; 5.0 leaves headroom).
        set rec_near [atomselect $recmolid "all"]
        set contacts [measure contacts 5.0 $lig $rec_near]
        $rec_near delete

        set lig_pair [lindex $contacts 0]
        set rec_pair [lindex $contacts 1]

        # Cache ligand coords for distance math
        set lig_xyz [$lig get {x y z}]
        set rec_all [atomselect $recmolid "all"]
        set rec_xyz [$rec_all get {x y z}]
        $rec_all delete

        set count 0
        set total 0.0
        set worst 0.0
        set pair_records [list]
        set resid_set [dict create]

        foreach li $lig_pair ri $rec_pair {
            # Map global atom indices back to position in lig/rec arrays
            set li_pos [lsearch -exact $lig_indices $li]
            set ri_pos [lsearch -exact $rec_indices $ri]
            if {$li_pos < 0 || $ri_pos < 0} { continue }

            set la [lindex $lig_xyz $li_pos]
            set ra [lindex $rec_xyz $ri_pos]
            set dx [expr {[lindex $la 0] - [lindex $ra 0]}]
            set dy [expr {[lindex $la 1] - [lindex $ra 1]}]
            set dz [expr {[lindex $la 2] - [lindex $ra 2]}]
            set d [expr {sqrt($dx*$dx + $dy*$dy + $dz*$dz)}]

            set lr [lindex $lig_radii $li_pos]
            set rr [lindex $rec_radii $ri_pos]
            # If radius=0 (some PDBs) fall back to 1.7 (carbon-ish)
            if {$lr <= 0} { set lr 1.7 }
            if {$rr <= 0} { set rr 1.7 }
            set sum_r [expr {$lr + $rr}]
            set overlap [expr {$sum_r - $d - $overlap_tol}]
            if {$overlap > 0.0} {
                incr count
                set total [expr {$total + $overlap}]
                if {$overlap > $worst} { set worst $overlap }
                set rname [lindex $rec_resnames $ri_pos]
                set rid   [lindex $rec_resids $ri_pos]
                set rnm   [lindex $rec_names $ri_pos]
                lappend pair_records [list $li $ri \
                    [format "%.3f" $d] [format "%.3f" $overlap] \
                    $rname $rid $rnm]
                dict set resid_set $rid 1
            }
        }
        $lig delete

        set resids [lsort -integer [dict keys $resid_set]]
        dict set out $f [dict create \
            count $count \
            total [format "%.3f" $total] \
            worst [format "%.3f" $worst] \
            resids $resids \
            pairs $pair_records]
    }
    return $out
}

proc vmdai::pose_clash_summary {ligmolid recmolid {overlap_tol 0.4}} {
    set clashes [vmdai::pose_clashes $ligmolid $recmolid $overlap_tol]
    set lines [list]
    lappend lines [format "%-5s %-6s %-9s %-7s %s" \
        "pose" "count" "total(A)" "worst" "residues"]
    foreach f [lsort -integer [dict keys $clashes]] {
        set rec [dict get $clashes $f]
        set rids [dict get $rec resids]
        if {[llength $rids] > 6} {
            set rids "[lrange $rids 0 5] ... ([llength $rids] total)"
        }
        lappend lines [format "%-5d %-6d %-9s %-7s %s" \
            $f \
            [dict get $rec count] \
            [dict get $rec total] \
            [dict get $rec worst] \
            $rids]
    }
    return [join $lines "\n"]
}

proc vmdai::write_clash_dat {path clashes} {
    set fh [open $path w]
    puts $fh "# pose\tlig_idx\trec_idx\tdistance\toverlap\trec_resname\trec_resid\trec_name"
    foreach f [lsort -integer [dict keys $clashes]] {
        set rec [dict get $clashes $f]
        foreach pr [dict get $rec pairs] {
            puts $fh "$f\t[join $pr "\t"]"
        }
    }
    close $fh
    return $path
}
