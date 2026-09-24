mol new 1hck.pdb waitfor all
# rep 0: protein backbone as Tube (no secondary-structure step -> no STRIDE -> no hang)
mol modstyle 0 0 Tube
mol modselect 0 0 protein
mol modcolor 0 0 ResID
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
