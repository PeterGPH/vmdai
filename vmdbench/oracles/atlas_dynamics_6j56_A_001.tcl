# atlas_dynamics_6j56_A_001 oracle — Unconventional myosin-VI (129 res), ATLAS replica 1,
# ~42 frames. Emits trajectory observables as PROBE> measure_ lines; the HeadlessVMDEnv
# wrapper appends scene introspection + quit.
# ATLAS data CC-BY-NC 4.0 — cite Vander Meersche et al., NAR 2024 (52:D1 D384).
mol new 6j56_A.pdb waitfor all
mol addfile 6j56_A_R1_s25.dcd waitfor all
set n [molinfo top get numframes]
set prot [atomselect top "protein"]
set g 0.0
set sa 0.0
for {set i 0} {$i < $n} {incr i} {
  $prot frame $i
  set g  [expr {$g  + [measure rgyr $prot]}]
  set sa [expr {$sa + [measure sasa 1.4 $prot]}]
}
puts "PROBE> measure_meanrg=[expr {$g / $n}]"
puts "PROBE> measure_meansasa=[expr {$sa / $n}]"
set ca  [atomselect top "protein and name CA"]
set ref [atomselect top "protein and name CA" frame 0]
set all [atomselect top "all"]
set rsum 0.0
for {set i 0} {$i < $n} {incr i} {
  $ca frame $i; $all frame $i
  $all move [measure fit $ca $ref]
  set rsum [expr {$rsum + [measure rmsd $ca $ref]}]
}
puts "PROBE> measure_meanrmsd=[expr {$rsum / $n}]"
set rmsf [measure rmsf $ca]
set s 0.0
foreach v $rmsf { set s [expr {$s + $v}] }
puts "PROBE> measure_mean_rmsf=[expr {$s / [llength $rmsf]}]"
