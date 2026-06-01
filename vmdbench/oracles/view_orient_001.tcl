# Oracle: view_orient_001
# Two reps (protein NewCartoon colored by chain, nucleic Licorice), camera
# oriented off the default view, white background, rendered with TachyonInternal.
# No quit / no PROBE lines -- HeadlessVMDEnv wraps those around the body.
mol new mini.pdb waitfor all
mol modstyle 0 0 NewCartoon
mol modselect 0 0 protein
mol modcolor 0 0 Chain
mol addrep 0
mol modstyle 1 0 Licorice
mol modselect 1 0 nucleic
rotate x by 30
rotate y by 45
scale by 1.5
color Display Background white
render TachyonInternal out.tga
