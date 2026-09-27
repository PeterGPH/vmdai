# tests/tcl/test_sched.tcl - sched registry and config (P06-T02, S4).
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}
package require http

set plugin $::env(VMDAI_PLUGIN_DIR)
source [file join $plugin config.tcl]
source [file join $plugin sched.tcl]

proc wait_for {script {ms 3000}} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { return 0 }
        set ::_tick 0
        after 10 {set ::_tick 1}
        vwait ::_tick
    }
    return 1
}

proc plugin_log {} {
    set path [::vmdai::config::plugin_log_path]
    if {![file exists $path]} { return "" }
    set fh [open $path r]
    set text [read $fh]
    close $fh
    return $text
}

# A listener that accepts and never answers, so http tokens stay open.
proc silent_server {} {
    set srv [socket -server {apply {{ch addr port} {lappend ::held $ch}}} -myaddr 127.0.0.1 0]
    return [list $srv [lindex [fconfigure $srv -sockname] 2]]
}

test sched-teardown-1 {teardown cancels timers, idle callbacks, fileevents and http tokens} -body {
    set ::held {}
    lassign [silent_server] srv port
    set ::cb_calls 0
    set tok [http::geturl http://127.0.0.1:$port/x -timeout 60000 \
        -command {apply {{t} {incr ::cb_calls; ::vmdai::sched::after 0 {set ::never 5}; http::cleanup $t}}}]
    ::vmdai::sched::track_http $tok
    wait_for {expr {[llength $::held] == 1}}
    ::vmdai::sched::after 60000 {set ::never 1}
    ::vmdai::sched::after 30000 {set ::never 2}
    ::vmdai::sched::after_idle {set ::never 3}
    lassign [chan pipe] rd wr
    ::vmdai::sched::fileevent $rd readable {set ::never 4}
    set before [list [llength [after info]] [llength [::vmdai::sched::pending]]]
    ::vmdai::sched::teardown
    set after_td [list [after info] [::vmdai::sched::pending] [fileevent $rd readable] \
        [info exists $tok] $::cb_calls]
    close $rd; close $wr; close $srv
    foreach ch $::held { close $ch }
    list $before $after_td [info exists ::never]
} -result {{4 3} {{} {} {} 0 1} 0}

test sched-teardown-2 {re-sourcing keeps the registry, so teardown after a reload still cancels} -body {
    set id [::vmdai::sched::after 60000 {set ::never 6}]
    source [file join $plugin sched.tcl]
    set kept [expr {$id in [::vmdai::sched::pending]}]
    ::vmdai::sched::teardown
    list $kept [after info] [::vmdai::sched::pending]
} -result {1 {} {}}

test sched-fire-1 {a fired timer runs at global level and leaves pending} -body {
    set ::fired {}
    set id [::vmdai::sched::after 10 {lappend ::fired [info level]}]
    set live [expr {$id in [::vmdai::sched::pending]}]
    wait_for {expr {$::fired ne ""}}
    list $live $::fired [::vmdai::sched::pending] [after info]
} -result {1 0 {} {}}

test sched-cancel-1 {cancel removes a timer; unknown and empty ids are ignored} -body {
    set id [::vmdai::sched::after 60000 {set ::never 7}]
    ::vmdai::sched::cancel $id
    ::vmdai::sched::cancel $id
    ::vmdai::sched::cancel ""
    ::vmdai::sched::cancel vmdai_sched#999999
    list [::vmdai::sched::pending] [after info]
} -result {{} {}}

test sched-throw-1 {a failing timer is logged, not raised, and later timers still run} -body {
    set ::ran 0
    ::vmdai::sched::after 0 {error "boom from a timer"}
    ::vmdai::sched::after 20 {set ::ran 1}
    wait_for {expr {$::ran == 1}}
    list $::ran [string match "*boom from a timer*" [plugin_log]] [::vmdai::sched::pending]
} -result {1 1 {}}

test sched-closing-1 {nothing can be scheduled while teardown runs} -body {
    set ::inner none
    set ::held {}
    lassign [silent_server] srv port
    set tok [http::geturl http://127.0.0.1:$port/y -timeout 60000 \
        -command {apply {{t} {set ::inner [::vmdai::sched::after 0 {set ::never 8}]; http::cleanup $t}}}]
    ::vmdai::sched::track_http $tok
    wait_for {expr {[llength $::held] == 1}}
    ::vmdai::sched::teardown
    close $srv
    foreach ch $::held { close $ch }
    list $::inner [after info] [expr {[::vmdai::sched::after 0 {set ::ok 1}] ne ""}]
} -cleanup {::vmdai::sched::teardown} -result {{} {} 1}

test sched-fileevent-1 {an empty script unregisters a fileevent} -body {
    lassign [chan pipe] rd wr
    ::vmdai::sched::fileevent $rd readable {set ::never 9}
    set on [fileevent $rd readable]
    ::vmdai::sched::fileevent $rd readable {}
    set r [list $on [fileevent $rd readable] [array names ::vmdai::sched::fevents]]
    close $rd; close $wr
    set r
} -result {{set ::never 9} {} {}}

test config-python-1 {VMD_AI_PYTHON wins, then plugin.json, then python3 on PATH} -setup {
    set saved_path $::env(PATH)
    set bin [file join $::env(HOME) "bin dir"]
    file mkdir $bin
    foreach name {python3 envpy} {
        set fh [open [file join $bin $name] w]; puts $fh "#!/bin/sh"; close $fh
        file attributes [file join $bin $name] -permissions 0755
    }
    set ::env(PATH) "$bin:/usr/bin:/bin"
    unset -nocomplain ::auto_execs
    unset -nocomplain ::env(VMD_AI_PYTHON)
    file delete -force [::vmdai::config::plugin_json_path]
} -body {
    set r {}
    lappend r [expr {[::vmdai::config::resolve_python] eq [file normalize [file join $bin python3]]}]
    ::vmdai::config::save_plugin_settings [dict create version 1 python /opt/json/python3]
    lappend r [::vmdai::config::resolve_python]
    set ::env(VMD_AI_PYTHON) /opt/env/python3
    lappend r [::vmdai::config::resolve_python]
    set ::env(VMD_AI_PYTHON) envpy
    lappend r [expr {[::vmdai::config::resolve_python] eq [file normalize [file join $bin envpy]]}]
    set r
} -cleanup {
    set ::env(PATH) $saved_path
    unset -nocomplain ::auto_execs ::env(VMD_AI_PYTHON)
    file delete -force [::vmdai::config::plugin_json_path]
} -result {1 /opt/json/python3 /opt/env/python3 1}

test config-python-2 {a relative path is made absolute; nothing found gives ""} -setup {
    set saved_path $::env(PATH)
    set saved_pwd [pwd]
    unset -nocomplain ::auto_execs ::env(VMD_AI_PYTHON)
} -body {
    cd $::env(HOME)
    set ::env(VMD_AI_PYTHON) ./venv/bin/python
    set rel [::vmdai::config::resolve_python]
    unset ::env(VMD_AI_PYTHON)
    set ::env(PATH) [file join $::env(HOME) empty]
    unset -nocomplain ::auto_execs
    list [expr {$rel eq [file join [file normalize $::env(HOME)] venv bin python]}] \
        [::vmdai::config::resolve_python]
} -cleanup {
    cd $saved_pwd
    set ::env(PATH) $saved_path
    unset -nocomplain ::auto_execs ::env(VMD_AI_PYTHON)
} -result {1 {}}

test config-attach-1 {VMD_AI_ATTACH host:port, bare host with VMD_AI_PORT, unset} -body {
    set r {}
    unset -nocomplain ::env(VMD_AI_ATTACH) ::env(VMD_AI_PORT)
    lappend r [::vmdai::config::attach_target]
    set ::env(VMD_AI_ATTACH) 127.0.0.1:8765
    lappend r [::vmdai::config::attach_target]
    set ::env(VMD_AI_ATTACH) LOCALHOST:09001
    lappend r [::vmdai::config::attach_target]
    set ::env(VMD_AI_ATTACH) localhost
    lappend r [::vmdai::config::attach_target]
    set ::env(VMD_AI_PORT) 18765
    lappend r [::vmdai::config::attach_target]
    set r
} -cleanup {unset -nocomplain ::env(VMD_AI_ATTACH) ::env(VMD_AI_PORT)} \
  -result {{} {127.0.0.1 8765} {localhost 9001} {localhost 8765} {localhost 18765}}

test config-attach-2 {malformed or non-loopback VMD_AI_ATTACH is an error} -body {
    set r {}
    foreach value {127.0.0.1:abc 10.0.0.2:8765 attacker.example:8765 127.0.0.1:0 127.0.0.1:70000 :8765} {
        set ::env(VMD_AI_ATTACH) $value
        lappend r [catch {::vmdai::config::attach_target} msg] [string match VMD_AI_ATTACH* $msg]
    }
    set r
} -cleanup {unset -nocomplain ::env(VMD_AI_ATTACH)} -result {1 1 1 1 1 1 1 1 1 1 1 1}

test config-json-1 {plugin.json: defaults, round trip, ASCII on disk, broken file} -body {
    file delete -force [::vmdai::config::plugin_json_path]
    set defaults [::vmdai::config::load_plugin_settings]
    ::vmdai::config::save_plugin_settings [dict create version 1 \
        python "/Users/a b/[format %c 0xc5]/py\"thon" appearance dark expand_steps 1 geometry 600x700+1+1]
    set fh [open [::vmdai::config::plugin_json_path] rb]; set raw [read $fh]; close $fh
    set back [::vmdai::config::load_plugin_settings]
    set fh [open [::vmdai::config::plugin_json_path] w]; puts $fh "\{not json"; close $fh
    set broken [::vmdai::config::load_plugin_settings]
    list $defaults [regexp {^[\x20-\x7e]*$} $raw] \
        [expr {[dict get $back python] eq "/Users/a b/[format %c 0xc5]/py\"thon"}] \
        [dict get $back expand_steps] [dict get $back geometry] [dict get $broken appearance]
} -cleanup {file delete -force [::vmdai::config::plugin_json_path]} \
  -result {{version 1 python {} appearance system expand_steps 0 geometry {}} 1 1 true 600x700+1+1 system}

cleanupTests
