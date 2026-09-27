# Vendored tcllib json 1.1.2 (ChatVMD, plugin/lib/json). Only json itself is
# vendored; VMD's json::write 1.0.2 is not needed by the plugin.
if {![package vsatisfies [package provide Tcl] 8.4]} {return}
package ifneeded json 1.1.2 [list source [file join $dir json.tcl]]
