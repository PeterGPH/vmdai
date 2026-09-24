# gold_oracle_traj.tcl — trajectory gold oracle for the agent-vs-ATLAS test.
# Env: GOLD_STRUCT = topology (.pdb), GOLD_TRAJ = trajectory (.dcd/.xtc).
# Emits parseable lines:  GOLD <key> <value>  for the portable trajectory observables
# (mean over ALL frames). Mirrors the vmdbench atlas_dynamics oracle so the agent is graded
# against the exact same computation. Each measurement is wrapped in catch{}.
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

# (1) mean Rg + (2) mean SASA over all frames (one pass)
if {[catch {
    set prot [atomselect top "protein"]
    set g 0.0; set sa 0.0
    for {set i 0} {$i < $n} {incr i} {
        $prot frame $i
        set g  [expr {$g  + [measure rgyr $prot]}]
        set sa [expr {$sa + [measure sasa 1.4 $prot]}]
    }
    emit meanrg   [expr {$g  / $n}]
    emit meansasa [expr {$sa / $n}]
} err]} { puts "GOLD_ERROR rg_sasa $err" }

# (3) mean Calpha RMSD to frame 0 + (4) mean Calpha RMSF, aligning each frame to frame 0
if {[catch {
    set ca  [atomselect top "protein and name CA"]
    set ref [atomselect top "protein and name CA" frame 0]
    set all [atomselect top "all"]
    set rsum 0.0
    for {set i 0} {$i < $n} {incr i} {
        $ca frame $i; $all frame $i
        $all move [measure fit $ca $ref]
        set rsum [expr {$rsum + [measure rmsd $ca $ref]}]
    }
    emit meanrmsd [expr {$rsum / $n}]
    set rmsf [measure rmsf $ca]
    set s 0.0
    foreach v $rmsf { set s [expr {$s + $v}] }
    emit mean_rmsf [expr {$s / [llength $rmsf]}]
} err]} { puts "GOLD_ERROR rmsd_rmsf $err" }

quit
