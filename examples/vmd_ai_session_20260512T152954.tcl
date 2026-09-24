# VMD AI session transcript
# saved_at : 2026-05-12T20:29:57Z
# workdir  : /Users/pinhaogu/Documents/GitHub/PyMolAI/vmd_ai/examples
# turns    : 12
#
# This file is replayable in fresh VMD:
#   vmd -e 
# (or vmd -dispdev text -e ... for headless replay)

# --- turn 01 | 2026-05-12T20:28:31Z | command ---
exec curl -s -o /tmp/1hck.pdb "http://files.rcsb.org/download/1HCK.pdb"
puts "Download complete"

# --- turn 02 | 2026-05-12T20:28:33Z | command ---
mol load pdb "/tmp/1hck.pdb"

# --- turn 03 | 2026-05-12T20:28:37Z | command ---
# Check what residues/ligands are in the structure
set sel [atomselect top "not protein and not water"]
set resnames [lsort -unique [$sel get resname]]
puts "Non-protein, non-water residues: $resnames"
$sel delete

set psel [atomselect top "protein"]
puts "Protein atoms: [$psel num]"
$psel delete

set chains [atomselect top "all"]
set chainlist [lsort -unique [$chains get chain]]
puts "Chains: $chainlist"
$chains delete

# --- turn 04 | 2026-05-12T20:28:48Z | command ---
color Display Background white

# --- turn 05 | 2026-05-12T20:28:51Z | command ---
display projection Orthographic
display depthcue off
display shadows on
display ambientocclusion on
axes location Off

# Remove all existing reps
set nreps [molinfo top get numreps]
for {set i [expr {$nreps-1}]} {$i >= 0} {incr i -1} { mol delrep $i top }

puts "Scene setup done, reps cleared"

# --- turn 06 | 2026-05-12T20:28:54Z | command ---
# REP 0 – Protein NewCartoon colored by secondary structure
mol representation NewCartoon 0.3 10.0 4.5 0
mol color Structure
mol selection "protein"
mol material AOChalky
mol addrep top
puts "Rep 0 (cartoon) added"

# --- turn 07 | 2026-05-12T20:28:57Z | command ---
# REP 1 – Transparent molecular surface for the protein
mol representation Surf 1.4
mol color ColorID 23
mol selection "protein"
mol material Transparent
mol addrep top
puts "Rep 1 (surface) added"

# --- turn 08 | 2026-05-12T20:28:59Z | command ---
# REP 2 – ATP in Licorice (high detail), colored by atom name
mol representation Licorice 0.15 30.0 30.0
mol color Name
mol selection "resname ATP"
mol material Glossy
mol addrep top
puts "Rep 2 (ATP Licorice) added"

# --- turn 09 | 2026-05-12T20:29:02Z | command ---
# REP 3 – ATP VDW surface (semi-transparent) to show shape
mol representation Surf 1.4
mol color ColorID 4
mol selection "resname ATP"
mol material Transparent
mol addrep top
puts "Rep 3 (ATP surface) added"

# --- turn 10 | 2026-05-12T20:29:06Z | command ---
# REP 4 – Mg2+ ion as VDW sphere
mol representation VDW 0.6 12.0
mol color ColorID 10
mol selection "resname MG"
mol material Glossy
mol addrep top
puts "Rep 4 (Mg VDW) added"

# --- turn 11 | 2026-05-12T20:29:09Z | command ---
# REP 5 – Binding-site residues within 4 Å of ATP – Licorice
mol representation Licorice 0.12 30.0 30.0
mol color ResType
mol selection "protein and within 4.0 of resname ATP"
mol material Glossy
mol addrep top
puts "Rep 5 (binding-site residues) added"

# --- turn 12 | 2026-05-12T20:29:12Z | command ---
# REP 6 – H-bond donor/acceptor residues – Labels as CPK
mol representation CPK 0.5 0.15 30.0 30.0
mol color ResType
mol selection "protein and within 4.0 of resname ATP"
mol material AOChalky
mol addrep top
puts "Rep 6 (binding-site CPK) added"

