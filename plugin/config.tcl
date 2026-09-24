namespace eval ::vmdai::config {
    variable host "127.0.0.1"
    variable port 8765
    variable poll_ms 250
    variable poll_limit 80
    variable request_timeout_ms 3000

    variable plugin_dir [file dirname [info script]]
    variable runtime_main [file normalize [file join $plugin_dir .. runtime main.py]]
    variable runtime_log [file normalize [file join $plugin_dir .. runtime runtime.log]]

    if {[info exists ::env(VMD_AI_PYTHON)]} {
        variable python_exec $::env(VMD_AI_PYTHON)
    } else {
        variable python_exec "python3"
    }
}

proc ::vmdai::config::runtime_url {} {
    variable host
    variable port
    return "http://${host}:${port}"
}
