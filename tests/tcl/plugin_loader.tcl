# load_plugin module ?module ...?: source plugin/<module>.tcl in order, at
# global level. config and net are sourced under catch: the view tests only
# need executor::split_statements, and those two may need a live VMD or json.
proc load_plugin {args} {
    foreach m $args {
        set path [file join $::env(VMDAI_PLUGIN_DIR) $m.tcl]
        if {$m in {config net}} {
            catch {uplevel #0 [list source $path]}
        } else {
            uplevel #0 [list source $path]
        }
    }
}
