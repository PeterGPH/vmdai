# STRIDE / render hang locator for 1HCK.
# Run from the vmd_ai repo root:
#   /Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64 -dispdev text -eofexit -e probe_stride.tcl
# The LAST ">>>" line printed before it stalls tells you the culprit:
#   stalls after CKPT3 (no CKPT4) -> STRIDE deadlock on NewCartoon -> use the Tube task.
#   stalls after CKPT1/CKPT2      -> render problem, not STRIDE (tell me).
mol new vmdbench/fixtures/1hck.pdb waitfor all
puts ">>> CKPT1 loaded [molinfo top get numatoms] atoms"; flush stdout
mol modstyle 0 0 Lines
color Display Background white
render TachyonInternal /tmp/probe_lines.tga
puts ">>> CKPT2 render OK with Lines (TachyonInternal is fine)"; flush stdout
mol modstyle 0 0 Tube
render TachyonInternal /tmp/probe_tube.tga
puts ">>> CKPT3 render OK with Tube (no-STRIDE path works; /tmp/probe_tube.tga written)"; flush stdout
mol modstyle 0 0 NewCartoon
puts ">>> CKPT4 NewCartoon set — if you SEE this line, STRIDE returned"; flush stdout
render TachyonInternal /tmp/probe_cartoon.tga
puts ">>> CKPT5 render OK with NewCartoon (everything works)"; flush stdout
quit
