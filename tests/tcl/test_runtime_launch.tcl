# tests/tcl/test_runtime_launch.tcl - runtime.tcl launch, READY, attach and
# stop against real stub processes (P06-T05). Environment from the wrapper:
#   VMD_AI_PYTHON     a python3 wrapper in a directory whose name has a space
#   VMDAI_STUB_DIR    a copy of tests/fixtures/stub_runtime in a spaced path
#   VMDAI_ATTACH_PORT FakeRpcServer with a token file (token VMDAI_TOKEN,
#                     /health pid VMDAI_SLEEPER_PID)
#   VMDAI_OLD_PORT    FakeRpcServer whose /health is {"ok": true} (protocol 1)
#   VMDAI_PID_LOG     every child pid is appended here; the wrapper kills leftovers
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
foreach m {config sched net runtime} { source [file join $plugin $m.tcl] }

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

proc alive {pid} { expr {$pid ne "" && ![catch {exec kill -0 $pid}]} }

proc log_pid {} {
    set pid $::vmdai::runtime::child_pid
    if {$pid ne ""} {
        set fh [open $::env(VMDAI_PID_LOG) a]; puts $fh $pid; close $fh
    }
    return $pid
}

set ::transitions {}
set ::last_detail ""
proc record {old new detail} {
    lappend ::transitions "$old>$new"
    set ::last_detail $detail
}
::vmdai::runtime::subscribe record

proc use_stub {name} {
    set ::vmdai::config::runtime_main [file join $::env(VMDAI_STUB_DIR) $name]
}

proc fresh {} {
    ::vmdai::runtime::stop -sync
    ::vmdai::sched::teardown
    set ::transitions {}
    foreach v {STUB_NOISE STUB_NO_READY STUB_PROTOCOL STUB_IGNORE_TERM VMD_AI_ATTACH} {
        unset -nocomplain ::env($v)
    }
    set ::vmdai::config::ready_timeout_ms 20000
    set ::vmdai::config::shutdown_kill_ms 1500
}

test rt-ready-1 {launch parses READY, checks /health and reaches ready} -setup fresh -body {
    use_stub "ready runtime.py"
    ::vmdai::runtime::ensure
    set started [log_pid]
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    set i [::vmdai::runtime::info]
    list [::vmdai::runtime::state] $::transitions [dict get $i owned] [dict get $i protocol] \
        [dict get $i version] [regexp {^[0-9a-f]{32}$} [dict get $i launch_token]] \
        [expr {[dict get $i pid] == $started}] \
        [expr {[dict get [::vmdai::net::configure] -base_url] eq "http://127.0.0.1:[dict get $i port]"}] \
        [::vmdai::runtime::failure_reason]
} -cleanup fresh -result {ready {stopped>launching launching>connecting connecting>ready} 1 2 0.3.0-stub 1 1 1 {}}

test rt-noise-1 {READY is found after 60 noise lines and a partial stderr line} -setup fresh -body {
    use_stub "ready runtime.py"
    set ::env(STUB_NOISE) 1
    ::vmdai::runtime::ensure
    log_pid
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    set all [::vmdai::runtime::pipe_tail 50]
    list [::vmdai::runtime::state] [llength $all] [llength [::vmdai::runtime::pipe_tail]] \
        [string match "UserWarning: a partial line*VMDAI_READY*" [lindex $all end]] \
        [lindex [::vmdai::runtime::pipe_tail 2] 0]
} -cleanup fresh -result {ready 50 12 1 {DeprecationWarning: noise line 59}}

test rt-fail-1 {stderr then exit: didnt_start, the traceback in the tail, nothing left running} -setup fresh -body {
    use_stub fail_runtime.py
    ::vmdai::runtime::ensure
    log_pid
    wait_for {expr {[::vmdai::runtime::state] eq "down"}}
    list [::vmdai::runtime::state] [::vmdai::runtime::failure_reason] \
        [lindex [::vmdai::runtime::pipe_tail] end] $::vmdai::runtime::chan \
        [::vmdai::sched::pending] [lindex $::transitions end]
} -cleanup fresh -result {down didnt_start {ModuleNotFoundError: No module named 'vmd_ai_runtime_missing'} {} {} launching>down}

test rt-fail-2 {a Python that cannot run is didnt_start with the error in the tail} -setup fresh -body {
    set saved $::env(VMD_AI_PYTHON)
    set ::env(VMD_AI_PYTHON) [file join $::env(HOME) "no such dir" python3]
    use_stub "ready runtime.py"
    ::vmdai::runtime::ensure
    wait_for {expr {[::vmdai::runtime::state] eq "down"}}
    set ::env(VMD_AI_PYTHON) $saved
    list [::vmdai::runtime::failure_reason] [expr {[llength [::vmdai::runtime::pipe_tail]] > 0}]
} -cleanup fresh -result {didnt_start 1}

test rt-timeout-1 {no READY within the timeout: didnt_start and the process is stopped} -setup fresh -body {
    use_stub "ready runtime.py"
    set ::env(STUB_NO_READY) 1
    set ::vmdai::config::ready_timeout_ms 600
    ::vmdai::runtime::ensure
    set pid [log_pid]
    wait_for {expr {[::vmdai::runtime::state] eq "down"}}
    wait_for {expr {![alive $pid]}} 3000
    list [::vmdai::runtime::failure_reason] [string match "*READY*" $::last_detail] [alive $pid]
} -cleanup fresh -result {didnt_start 1 0}

test rt-old-1 {an owned runtime that reports protocol 1 is too_old and is stopped} -setup fresh -body {
    use_stub "ready runtime.py"
    set ::env(STUB_PROTOCOL) 1
    ::vmdai::runtime::ensure
    set pid [log_pid]
    wait_for {expr {[::vmdai::runtime::state] eq "down"}}
    wait_for {expr {![alive $pid]}} 3000
    list [::vmdai::runtime::failure_reason] [alive $pid]
} -cleanup fresh -result {too_old 0}

test rt-old-2 {an attached runtime whose /health has no protocol is too_old} -setup fresh -body {
    set dir [file join $::env(HOME) .vmdai run]
    file mkdir $dir
    set fh [open [file join $dir runtime-$::env(VMDAI_OLD_PORT).json] w]
    puts $fh "{\"port\": $::env(VMDAI_OLD_PORT), \"pid\": 1, \"token\": \"[string repeat 0 32]\", \"protocol\": 1}"
    close $fh
    set ::env(VMD_AI_ATTACH) 127.0.0.1:$::env(VMDAI_OLD_PORT)
    ::vmdai::runtime::ensure
    wait_for {expr {[::vmdai::runtime::state] eq "down"}}
    list [::vmdai::runtime::failure_reason] $::last_detail [dict get [::vmdai::runtime::info] owned]
} -cleanup fresh -result {too_old {This runtime is too old (protocol 1).} 0}

test rt-attach-1 {attach reads the token file and never launches} -setup fresh -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:$::env(VMDAI_ATTACH_PORT)
    ::vmdai::runtime::ensure
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    set i [::vmdai::runtime::info]
    list [::vmdai::runtime::state] [dict get $i owned] \
        [expr {[dict get $i launch_token] eq $::env(VMDAI_TOKEN)}] \
        [expr {[dict get $i pid] == $::env(VMDAI_SLEEPER_PID)}] $::vmdai::runtime::chan
} -cleanup fresh -result {ready 0 1 1 {}}

test rt-attach-2 {attach without a token file, or to a closed port, is unreachable} -setup fresh -body {
    set srv [socket -server {apply {{c a p} {close $c}}} -myaddr 127.0.0.1 0]
    set dead [lindex [fconfigure $srv -sockname] 2]
    close $srv
    set ::env(VMD_AI_ATTACH) 127.0.0.1:$dead
    ::vmdai::runtime::ensure
    set no_token [list [::vmdai::runtime::state] [::vmdai::runtime::failure_reason]]
    set dir [file join $::env(HOME) .vmdai run]
    file mkdir $dir
    set fh [open [file join $dir runtime-$dead.json] w]
    puts $fh "{\"port\": $dead, \"pid\": 1, \"token\": \"[string repeat a 32]\", \"protocol\": 2}"
    close $fh
    ::vmdai::runtime::ensure
    wait_for {expr {[::vmdai::runtime::state] eq "down"}}
    list $no_token [::vmdai::runtime::failure_reason] [lindex $::transitions end]
} -cleanup fresh -result {{down unreachable} unreachable connecting>down}

test rt-attach-3 {a malformed VMD_AI_ATTACH is unreachable with the reason} -setup fresh -body {
    set ::env(VMD_AI_ATTACH) 10.1.2.3:8765
    ::vmdai::runtime::ensure
    list [::vmdai::runtime::state] [::vmdai::runtime::failure_reason]
} -cleanup fresh -result {down unreachable}

test rt-stop-1 {stop escalates to SIGKILL for an owned runtime that ignores SIGTERM} -setup fresh -body {
    use_stub "ready runtime.py"
    set ::env(STUB_IGNORE_TERM) 1
    set ::vmdai::config::shutdown_kill_ms 300
    ::vmdai::runtime::ensure
    set pid [log_pid]
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    set t0 [clock milliseconds]
    ::vmdai::runtime::stop
    set right_after [alive $pid]
    wait_for {expr {![alive $pid]}} 3000
    list $right_after [alive $pid] [expr {[clock milliseconds] - $t0 < 2000}] \
        [::vmdai::runtime::state] [::vmdai::sched::pending]
} -cleanup fresh -result {1 0 1 stopped {}}

test rt-stop-2 {stop -sync waits, then kills; the plain runtime exits on its own} -setup fresh -body {
    use_stub "ready runtime.py"
    set ::env(STUB_IGNORE_TERM) 1
    set ::vmdai::config::shutdown_kill_ms 300
    ::vmdai::runtime::ensure
    set stubborn [log_pid]
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    ::vmdai::runtime::stop -sync
    set stubborn_alive [alive $stubborn]
    unset ::env(STUB_IGNORE_TERM)
    ::vmdai::runtime::ensure
    set plain [log_pid]
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    ::vmdai::runtime::stop
    wait_for {expr {![alive $plain]}} 2000
    list $stubborn_alive [alive $plain] [::vmdai::runtime::state]
} -cleanup fresh -result {0 0 stopped}

test rt-stop-3 {stop never kills or shuts down an attached runtime} -setup fresh -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:$::env(VMDAI_ATTACH_PORT)
    ::vmdai::runtime::ensure
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    ::vmdai::runtime::stop
    sleep_ms 300
    list [::vmdai::runtime::state] [alive $::env(VMDAI_SLEEPER_PID)]
} -cleanup fresh -result {stopped 1}

test rt-spaces-1 {HOME, the Python wrapper and the runtime path all contain spaces} -setup fresh -body {
    use_stub "ready runtime.py"
    ::vmdai::runtime::ensure
    log_pid
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    list [string match "* *" $::env(HOME)] [string match "* *" $::env(VMD_AI_PYTHON)] \
        [string match "* *" $::vmdai::config::runtime_main] [::vmdai::runtime::state] \
        [file exists [::vmdai::config::plugin_log_path]]
} -cleanup fresh -result {1 1 1 ready 1}

cleanupTests
