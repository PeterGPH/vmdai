# tests/tcl/test_init.tcl - package, entry points, menu and reload (P06-T09,
# S4). The pytest wrapper serves a FakeRpcServer (a protocol-2 /health, a
# session.start that hands out sessions, empty polls) and writes its token
# file under $HOME; VMDAI_ATTACH_PORT names it. No Tk: the panel is stubbed.
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set ::menu {}
proc ::vmd_install_extension {name cmd path} { lappend ::menu [list $name $cmd $path] }

proc wait_for {script {ms 5000}} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { return 0 }
        set ::_tick 0
        after 20 {set ::_tick 1}
        vwait ::_tick
    }
    return 1
}
proc sleep_ms {ms} {
    set ::_slept 0
    after $ms {set ::_slept 1}
    vwait ::_slept
}
# The panel needs Tk; these tests only need its names.
proc stub_panel {} {
    proc ::vmdai::ui::show_panel {} { return .vmd_ai }
    foreach p {notify render_event set_busy status} { proc ::vmdai::ui::$p {args} {} }
}
# Attach to the fake runtime and wait for a session and a running pump.
proc attach_and_poll {} {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:$::env(VMDAI_ATTACH_PORT)
    ::vmdai::start
    wait_for {expr {[dict get [::vmdai::bridge::state] session_id] ne ""}}
    sleep_ms 300
}
# Timers whose script is the bridge's poll pump.
proc poll_timers {} {
    set n 0
    foreach id [::vmdai::sched::pending] {
        if {[string match *_poll* [lindex $::vmdai::sched::timers($id) 1]]} { incr n }
    }
    return $n
}

test init-pkg-1 {package require vmd_ai loads 2.0 and defines the entry points} -body {
    lappend ::auto_path $::env(VMDAI_PLUGIN_DIR)
    set v [package require vmd_ai]
    stub_panel
    set missing {}
    foreach p {::vmdai::start ::vmdai::stop ::vmdai::cleanup ::vmdai::reload
               ::vmdai::register_extension ::vmdai::ui::show_panel} {
        if {[info commands $p] eq ""} { lappend missing $p }
    }
    list $v [package present vmd_ai] $missing [::vmdai::runtime::state] [after info]
} -result {2.0 2.0 {} stopped {}}

test init-menu-1 {the menu entry is Extensions > VMD AI and runs ::vmdai::start} -body {
    set first $::menu
    ::vmdai::register_extension
    list $first [llength $::menu]
} -result {{{vmd_ai ::vmdai::start {VMD AI}}} 2}

test init-start-1 {::vmdai::start returns the window path and attaches} -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:$::env(VMDAI_ATTACH_PORT)
    set w [::vmdai::start]
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    list $w [::vmdai::runtime::state] [dict get [::vmdai::runtime::info] owned]
} -cleanup { ::vmdai::cleanup } -result {.vmd_ai ready 0}

test init-reload-1 {reload twice: nothing left in after info; one poll pump afterwards (S4)} -body {
    set r {}
    foreach round {1 2} {
        attach_and_poll
        set before [expr {[poll_timers] <= 1}]
        ::vmdai::reload
        stub_panel
        lappend r [list $before [after info] [::vmdai::sched::pending] [::vmdai::runtime::state] \
            [llength $::menu]]
    }
    attach_and_poll
    set ::polls 0
    trace add execution ::vmdai::net::call enter {apply {{cmd op} {
        if {[lindex $cmd 1] eq "chat.events.poll"} { incr ::polls }
    }}}
    sleep_ms 1000
    set steady [list [expr {[poll_timers] <= 1}] [expr {$::polls >= 2 && $::polls <= 5}]]
    ::vmdai::cleanup
    list $r $steady [after info] [::vmdai::runtime::state]
} -result {{{1 {} {} stopped 3} {1 {} {} stopped 4}} {1 1} {} stopped}

test init-stop-1 {::vmdai::stop leaves an attached runtime alone and ends the session} -body {
    attach_and_poll
    ::vmdai::stop
    set r [list [::vmdai::runtime::state] [dict get [::vmdai::bridge::state] session_id]]
    ::vmdai::cleanup
    lappend r [after info]
} -result {stopped {} {}}

cleanupTests
