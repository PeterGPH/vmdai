# pkgIndex.tcl - `package require vmd_ai` loads ChatVMD (spec 2h). The line
# scripts/install_plugin.tcl adds to ~/.vmdrc puts this directory on auto_path.
if {![package vsatisfies [package provide Tcl] 8.5]} {return}
package ifneeded vmd_ai 2.0 [list source [file join $dir init.tcl]]
