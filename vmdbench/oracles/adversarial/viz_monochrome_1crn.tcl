# Adversarial (anti-gold) oracle for the viz_render_element_1crn_001 card.
# A visible, non-empty render, but colored a single flat color (ColorID 1 = red)
# instead of by element. image_foreground passes (the picture is non-blank), but
# image_palette with expect_colors [red, blue] must FAIL: nitrogen-blue never
# appears because the molecule was not actually colored by element.
mol new 1crn.pdb waitfor all
mol modstyle 0 0 VDW
mol modcolor 0 0 ColorID 1
color Display Background white
display projection Orthographic
display resetview
render TachyonInternal out.tga
