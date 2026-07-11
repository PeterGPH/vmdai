# gold_oracle_traj_hard.tcl — HARD-tier trajectory gold oracle.
# Env: GOLD_STRUCT (.pdb), GOLD_TRAJ (.dcd/.xtc). Emits GOLD <key> <value> for COMPOSED
# observables that have no single VMD command (std / max / range / argmin / delta / ratio),
# plus reference means (meanrg/meanrmsd/mean_rmsf) and rg_first/rg_last/rg_min for self-checking.
# rg_std is the POPULATION std (÷n); rg_argmin_frame is 0-based; rg_frac_above_mean uses strict >.
proc emit {k v} { puts "GOLD $k $v" }

if {![info exists env(GOLD_STRUCT)] || ![info exists env(GOLD_TRAJ)]} {
    puts "GOLD_ERROR missing GOLD_STRUCT / GOLD_TRAJ env"; quit
}
set pdb  $env(GOLD_STRUCT)
set traj $env(GOLD_TRAJ)
if {![file exists $pdb] || ![file exists $traj]} {
    puts "GOLD_ERROR file-not-found '$pdb' or '$traj'"; quit
}

mol new $pdb waitfor all
mol addfile $traj waitfor all
set n [molinfo top get numframes]
emit nframes $n

# ---- Rg + SASA per-frame series (both rigid-motion invariant) ----
if {[catch {
    set prot [atomselect top "protein"]
    set rgs {}; set sasas {}
    for {set i 0} {$i < $n} {incr i} {
        $prot frame $i
        lappend rgs   [measure rgyr $prot]
        lappend sasas [measure sasa 1.4 $prot]
    }
    set sum 0.0; foreach x $rgs { set sum [expr {$sum + $x}] }
    set mean [expr {$sum / $n}]
    emit meanrg $mean
    set ss 0.0; foreach x $rgs { set d [expr {$x - $mean}]; set ss [expr {$ss + $d*$d}] }
    emit rg_std [expr {sqrt($ss / $n)}]
    set rgf [lindex $rgs 0]; set rgl [lindex $rgs end]
    emit rg_first $rgf
    emit rg_last  $rgl
    emit rg_delta [expr {$rgl - $rgf}]
    emit rg_ratio [expr {$rgl / $rgf}]
    set minv $rgf; set argmin 0
    for {set i 1} {$i < $n} {incr i} {
        set v [lindex $rgs $i]
        if {$v < $minv} { set minv $v; set argmin $i }
    }
    emit rg_min $minv
    emit rg_argmin_frame $argmin
    set cnt 0; foreach x $rgs { if {$x > $mean} { incr cnt } }
    emit rg_frac_above_mean [expr {double($cnt) / $n}]
    set smin [lindex $sasas 0]; set smax $smin
    foreach x $sasas { if {$x < $smin} {set smin $x}; if {$x > $smax} {set smax $x} }
    emit sasa_range [expr {$smax - $smin}]
} err]} { puts "GOLD_ERROR rg_sasa $err" }

# ---- aligned Calpha RMSD-to-frame0 (mean + max) + per-residue RMSF (max) ----
if {[catch {
    set ca  [atomselect top "protein and name CA"]
    set ref [atomselect top "protein and name CA" frame 0]
    set all [atomselect top "all"]
    set rsum 0.0; set rmax 0.0
    for {set i 0} {$i < $n} {incr i} {
        $ca frame $i; $all frame $i
        $all move [measure fit $ca $ref]
        set r [measure rmsd $ca $ref]
        set rsum [expr {$rsum + $r}]
        if {$r > $rmax} { set rmax $r }
    }
    emit meanrmsd [expr {$rsum / $n}]
    emit rmsd_max $rmax
    set rmsf [measure rmsf $ca]
    set fsum 0.0; set fmax 0.0
    foreach v $rmsf { set fsum [expr {$fsum + $v}]; if {$v > $fmax} {set fmax $v} }
    emit mean_rmsf [expr {$fsum / [llength $rmsf]}]
    emit rmsf_max  $fmax
} err]} { puts "GOLD_ERROR rmsd_rmsf $err" }

quit
