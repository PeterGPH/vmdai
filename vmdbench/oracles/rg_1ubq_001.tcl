mol new 1ubq.pdb waitfor all
# Mass-weighted radius of gyration of the protein (VMD's measure rgyr).
set sel [atomselect top protein]
puts "PROBE> measure_rgyr=[measure rgyr $sel]"
$sel delete
