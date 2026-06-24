# viz_render_element_1crn_001 oracle. Bare body — HeadlessVMDEnv adds the PROBE
# introspection and quit. Render with TachyonInternal (works headless; `render
# snapshot` needs a GL context and yields an invalid stub). White background so
# image_foreground/check_background and the element palette read cleanly.
mol new 1crn.pdb waitfor all
mol modstyle 0 0 VDW
mol modcolor 0 0 Element
color Display Background white
display projection Orthographic
display resetview
render TachyonInternal out.tga
