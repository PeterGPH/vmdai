mol new 1crn.pdb waitfor all
# Mass-weighted radius of gyration over all atoms (VMD's measure rgyr).
set sel [atomselect top all]
puts "PROBE> measure_rgyr=[measure rgyr $sel]"
$sel delete
