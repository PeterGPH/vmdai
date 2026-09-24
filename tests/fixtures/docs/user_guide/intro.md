## Getting started with VMD

VMD (Visual Molecular Dynamics) is a graphics program for displaying,
animating, and analyzing biomolecular systems. It uses Tcl as its
scripting language, and the same Tcl commands work in the GUI's text
console, in a sourced `.vmd` script, or remotely via `vmd_install_extension`.

## The Tcl Console

Press the `T` key (with focus on the OpenGL window) or use
**Extensions → Tk Console** to open the interactive Tcl prompt. Every
command in this reference can be typed at the Tcl Console. Output
appears inline.

## Loading molecules from the command line

You can pre-load files when launching VMD:

    vmd 1ubq.pdb
    vmd -dispdev text -e setup.vmd     # headless / batch mode
    vmd -psf protein.psf -dcd traj.dcd # PSF + trajectory

In headless mode (`-dispdev text`) the OpenGL viewport is disabled —
you can still run analysis but cannot render images, only compute.

## Animation controls

Use `animate goto <frame>` to jump to a specific frame, `animate
forward` to play, `animate pause` to stop. The current frame is
available via `molinfo top get frame`.
