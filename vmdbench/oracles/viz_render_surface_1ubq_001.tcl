# viz_render_surface_1ubq_001 oracle. Solid molecular surface (QuickSurface, no MSMS
# dependency so it works headless) colored by element, white background, TachyonInternal
# render. Exercises a high-coverage solid-blob render vs the thin cartoon / sphere demos.
mol new 1ubq.pdb waitfor all
mol modstyle 0 0 QuickSurf
mol modselect 0 0 protein
mol modcolor 0 0 Element
color Display Background white
display projection Orthographic
display resetview
render TachyonInternal out.tga
