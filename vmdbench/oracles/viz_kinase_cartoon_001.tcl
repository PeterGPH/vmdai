mol new 1hck.pdb waitfor all
# rep 0: protein cartoon, colored by secondary structure
mol modstyle 0 0 NewCartoon
mol modselect 0 0 protein
mol modcolor 0 0 Structure
# rep 1: ATP ligand as licorice
mol addrep 0
mol modstyle 1 0 Licorice
mol modselect 1 0 "resname ATP"
mol modcolor 1 0 Name
# clean publication look
color Display Background white
display projection Orthographic
display depthcue off
axes location Off
render TachyonInternal out.tga
