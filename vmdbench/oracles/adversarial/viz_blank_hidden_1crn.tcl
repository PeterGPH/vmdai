# Adversarial (anti-gold) oracle for the viz_render_element_1crn_001 card.
# An Element-colored representation EXISTS in the scene graph but is HIDDEN, so the
# rendered picture is blank. molecule_loaded / representation_exists / file_rendered
# all pass — yet the image is empty. image_foreground must FAIL on coverage.
# This is the visualization analogue of "completion is not correctness".
mol new 1crn.pdb waitfor all
mol modstyle 0 0 VDW
mol modcolor 0 0 Element
mol showrep 0 0 off
color Display Background white
display projection Orthographic
display resetview
render TachyonInternal out.tga
