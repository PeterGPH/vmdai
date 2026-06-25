# viz_render_cartoon_1hck_001 oracle. Protein cartoon colored by secondary structure
# (STRIDE), white background, TachyonInternal render. A different style+coloring path
# than the VDW/Element demo: NewCartoon + Structure -> several distinct SS colors.
mol new 1hck.pdb waitfor all
mol modstyle 0 0 NewCartoon
mol modselect 0 0 protein
mol modcolor 0 0 Structure
color Display Background white
display projection Orthographic
display resetview
render TachyonInternal out.tga
