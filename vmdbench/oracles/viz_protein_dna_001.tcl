mol new mini.pdb waitfor all
# rep 0: protein cartoon, colored by chain
mol modstyle 0 0 NewCartoon
mol modselect 0 0 protein
mol modcolor 0 0 Chain
# rep 1: nucleic licorice
mol addrep 0
mol modstyle 1 0 Licorice
mol modselect 1 0 nucleic
# rep 2: water, hidden
mol addrep 0
mol modselect 2 0 water
mol showrep 0 2 off
color Display Background white
render TachyonInternal out.tga
