mol new 1crn.pdb waitfor all
set a [atomselect top "name CA and resid 1"]
set b [atomselect top "name CA and resid 10"]
set pa [lindex [$a get {x y z}] 0]
set pb [lindex [$b get {x y z}] 0]
puts "PROBE> measure_ca1_ca10=[vecdist $pa $pb]"
$a delete
$b delete
