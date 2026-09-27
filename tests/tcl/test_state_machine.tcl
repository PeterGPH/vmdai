# tests/tcl/test_state_machine.tcl - connection state machine (P06-T06, S3).
# Deterministic: the scheduler, the process seams and /health are faked, and
# the tests fire timers by hand.
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
foreach m {config sched net runtime} { source [file join $plugin $m.tcl] }

# --- fakes --------------------------------------------------------------------
# Timers: ::timers is a list of {id ms script}; fire_probe runs the first
# reconnect timer (kill timers from _terminate are left alone).
set ::timer_seq 0
set ::timers {}
proc ::vmdai::sched::after {ms script} {
    set id fake#[incr ::timer_seq]
    lappend ::timers [list $id $ms $script]
    return $id
}
proc ::vmdai::sched::cancel {id} {
    set keep {}
    foreach t $::timers { if {[lindex $t 0] ne $id} { lappend keep $t } }
    set ::timers $keep
}
proc fire_probe {} {
    set i [lsearch -glob $::timers {* *_reconnect_tick *}]
    set t [lindex $::timers $i]
    set ::timers [lreplace $::timers $i $i]
    uplevel #0 [lindex $t 2]
    return [lindex $t 1]
}
proc probe_ms {} {
    set r {}
    foreach t $::timers {
        if {[string match *_reconnect_tick* [lindex $t 2]]} { lappend r [lindex $t 1] }
    }
    return $r
}

# Processes: _spawn hands out fake pids 9001, 9002, ...; ::alive holds live pids.
set ::spawned {}
set ::alive {}
set ::signals {}
proc ::vmdai::config::resolve_python {} { return /fake/python3 }
proc ::vmdai::runtime::_spawn {cmd g} {
    set pid [expr {9001 + [llength $::spawned]}]
    lappend ::spawned $pid
    lappend ::alive $pid
    return [list fakechan$pid $pid]
}
proc ::vmdai::runtime::_close_pipe {} { set ::vmdai::runtime::chan "" }
proc ::vmdai::runtime::_alive {pid} { expr {$pid in $::alive} }
proc ::vmdai::runtime::_signal {pid sig} {
    lappend ::signals "$sig $pid"
    set i [lsearch -exact $::alive $pid]
    if {$i >= 0} { set ::alive [lreplace $::alive $i $i] }
}
# /health: ::health is a list of replies, e.g. {ok {pid 9001 protocol 2}} or
# {transport refused}; the last one repeats.
set ::health {}
set ::probes 0
proc ::vmdai::runtime::_probe {callback} {
    incr ::probes
    set reply [lindex $::health 0]
    if {[llength $::health] > 1} { set ::health [lrange $::health 1 end] }
    uplevel #0 [list {*}$callback {*}$reply]
}
# Sinks.
namespace eval ::vmdai::ui {}
namespace eval ::vmdai::bridge {}
set ::notices {}
proc ::vmdai::ui::notify {level text} { lappend ::notices [list $level $text] }
set ::recovers 0
proc ::vmdai::bridge::recover {} { incr ::recovers }
set ::transitions {}
proc record {old new detail} { lappend ::transitions "$old>$new" }
::vmdai::runtime::subscribe record

proc current_gen {} { return $::vmdai::runtime::gen }
proc ready_line {pid} {
    return "VMDAI_READY \{\"port\":40001,\"pid\":$pid,\"version\":\"0.3.0\",\"protocol\":2,\"launch_token\":\"[string repeat a 32]\"\}"
}
# Launch an owned runtime and bring it to ready.
proc start_owned {} {
    ::vmdai::runtime::ensure
    set pid [lindex $::spawned end]
    set ::health [list [list ok [list pid $pid protocol 2 version 0.3.0]]]
    ::vmdai::runtime::_pipe_line [current_gen] [ready_line $pid]
    return $pid
}
proc reset_all {} {
    ::vmdai::runtime::stop -sync
    unset -nocomplain ::env(VMD_AI_ATTACH)
    set ::timers {}
    set ::spawned {}
    set ::alive {}
    set ::signals {}
    set ::health {}
    set ::probes 0
    set ::notices {}
    set ::recovers 0
    set ::transitions {}
}
proc write_token {port token} {
    set dir [file join $::env(HOME) .vmdai run]
    file mkdir $dir
    set fh [open [file join $dir runtime-$port.json] w]
    puts $fh "{\"port\": $port, \"pid\": 1, \"token\": \"$token\", \"protocol\": 2}"
    close $fh
}

# --- tests --------------------------------------------------------------------

test sm-backoff-1 {backoff_ms doubles from 0.5 s and caps at 8 s} -body {
    set r {}
    foreach a {1 2 3 4 5 6 7} { lappend r [::vmdai::runtime::backoff_ms $a] }
    set r
} -result {500 1000 2000 4000 8000 8000 8000}

test sm-notice-1 {one notice per transition; repeated errors add none} -setup reset_all -body {
    set pid [start_owned]
    set first_start [list [::vmdai::runtime::state] $::notices]
    foreach i {1 2 3 4 5} { ::vmdai::runtime::on_transport_error "connection refused" }
    set lost [list [::vmdai::runtime::state] [llength $::notices] [probe_ms]]
    set ::health [list [list ok [list pid $pid protocol 2]]]
    fire_probe
    list $first_start $lost [::vmdai::runtime::state] $::notices $::recovers \
        [lrange $::transitions end-1 end]
} -cleanup reset_all -result {{ready {}} {reconnecting 1 500} ready {{warn {Lost the connection to the AI runtime; reconnecting.}} {info {Reconnected to the AI runtime.}}} 0 {ready>reconnecting reconnecting>ready}}

test sm-backoff-2 {an attached runtime that stays away is probed at 0.5, 1, 2, 4, 8, 8 s} -setup reset_all -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:40002
    write_token 40002 [string repeat b 32]
    set ::health [list [list ok {pid 500 protocol 2}]]
    ::vmdai::runtime::ensure
    set ::health [list {transport refused}]
    ::vmdai::runtime::on_transport_error "connection refused"
    set delays {}
    foreach i {1 2 3 4 5 6} { lappend delays [fire_probe] }
    list $delays [::vmdai::runtime::state] [llength $::notices] [probe_ms] $::spawned
} -cleanup reset_all -result {{500 1000 2000 4000 8000 8000} reconnecting 1 8000 {}}

test sm-respawn-1 {an owned runtime that keeps dying is respawned at most 3 times} -setup reset_all -body {
    set pid [start_owned]
    set ::alive {}
    ::vmdai::runtime::_pipe_eof [current_gen]
    foreach i {1 2 3} {
        fire_probe
        ::vmdai::runtime::_pipe_eof [current_gen]
    }
    set levels {}
    foreach n $::notices { lappend levels [lindex $n 0] }
    list [::vmdai::runtime::state] [::vmdai::runtime::failure_reason] [llength $::spawned] \
        $levels [lindex $::notices 1 1] [probe_ms]
} -cleanup reset_all -result {down didnt_start 4 {warn warn warn warn error} {The AI runtime stopped; restarting it (1 of 3).} {}}

test sm-respawn-4 {sustained ready resets the respawn budget; a stale generation's timer does not} -setup reset_all -body {
    set pid [start_owned]
    set old_gen [current_gen]
    set ::alive {}
    ::vmdai::runtime::_pipe_eof [current_gen]
    fire_probe
    set new [lindex $::spawned end]
    set ::health [list [list ok [list pid $new protocol 2]]]
    ::vmdai::runtime::_pipe_line [current_gen] [ready_line $new]
    set after_cycle $::vmdai::runtime::respawns
    ::vmdai::runtime::_stable $old_gen
    set stale $::vmdai::runtime::respawns
    set i [lsearch -glob $::timers {* *_stable *}]
    set t [lindex $::timers $i]
    set ::timers [lreplace $::timers $i $i]
    uplevel #0 [lindex $t 2]
    list $after_cycle $stale $::vmdai::runtime::respawns
} -cleanup reset_all -result {1 1 0}

test sm-respawn-2 {a respawn that reaches ready recovers the session once} -setup reset_all -body {
    set pid [start_owned]
    set ::alive {}
    ::vmdai::runtime::_pipe_eof [current_gen]
    fire_probe
    set new [lindex $::spawned end]
    set ::health [list [list ok [list pid $new protocol 2]]]
    ::vmdai::runtime::_pipe_line [current_gen] [ready_line $new]
    list [::vmdai::runtime::state] $::recovers [lindex $::notices end] $::vmdai::runtime::respawns
} -cleanup reset_all -result {ready 1 {info {Reconnected to the AI runtime.}} 1}

test sm-respawn-3 {after 3 respawns, a runtime that dies once more ends down/unreachable} -setup reset_all -body {
    start_owned
    foreach i {1 2 3} {
        set ::alive {}
        ::vmdai::runtime::_pipe_eof [current_gen]
        fire_probe
        set new [lindex $::spawned end]
        set ::health [list [list ok [list pid $new protocol 2]]]
        ::vmdai::runtime::_pipe_line [current_gen] [ready_line $new]
    }
    set ::alive {}
    ::vmdai::runtime::_pipe_eof [current_gen]
    fire_probe
    list [::vmdai::runtime::state] [::vmdai::runtime::failure_reason] [llength $::spawned] $::recovers
} -cleanup reset_all -result {down unreachable 4 3}

test sm-retry-1 {retry_now from down starts again with a fresh respawn budget} -setup reset_all -body {
    set pid [start_owned]
    set ::alive {}
    ::vmdai::runtime::_pipe_eof [current_gen]
    foreach i {1 2 3} { fire_probe; ::vmdai::runtime::_pipe_eof [current_gen] }
    set before [::vmdai::runtime::state]
    ::vmdai::runtime::retry_now
    list $before [::vmdai::runtime::state] [llength $::spawned] $::vmdai::runtime::respawns
} -cleanup reset_all -result {down launching 5 0}

test sm-ensure-1 {ensure from down also resets the respawn budget} -setup reset_all -body {
    set pid [start_owned]
    set ::alive {}
    ::vmdai::runtime::_pipe_eof [current_gen]
    foreach i {1 2 3} { fire_probe; ::vmdai::runtime::_pipe_eof [current_gen] }
    set before [::vmdai::runtime::state]
    ::vmdai::runtime::ensure
    list $before [::vmdai::runtime::state] [llength $::spawned] $::vmdai::runtime::respawns
} -cleanup reset_all -result {down launching 5 0}

test sm-ready-tail-1 {a runtime that exits right after READY: the tail keeps the line, not the token} -setup reset_all -body {
    set saved_probe_args [info args ::vmdai::runtime::_probe]
    set saved_probe_body [info body ::vmdai::runtime::_probe]
    proc ::vmdai::runtime::_probe {callback} {}
    ::vmdai::runtime::ensure
    ::vmdai::runtime::_pipe_line [current_gen] [ready_line 9001]
    ::vmdai::runtime::_pipe_eof [current_gen]
    list [::vmdai::runtime::state] [::vmdai::runtime::failure_reason] \
        [string match {*exited right after it started*} [lindex $::notices end 1]] \
        [expr {[string first [string repeat a 32] [join [::vmdai::runtime::pipe_tail 50]]] < 0}]
} -cleanup {
    proc ::vmdai::runtime::_probe $saved_probe_args $saved_probe_body
    reset_all
} -result {down didnt_start 1 1}

test sm-newpid-1 {an attached runtime back with a new pid: new token, one recover} -setup reset_all -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:40003
    write_token 40003 [string repeat c 32]
    set ::health [list [list ok {pid 100 protocol 2}]]
    ::vmdai::runtime::ensure
    set before [list [::vmdai::runtime::state] $::recovers]
    ::vmdai::runtime::on_transport_error "connection reset"
    write_token 40003 [string repeat d 32]
    set ::health [list [list ok {pid 200 protocol 2}]]
    fire_probe
    list $before [::vmdai::runtime::state] $::recovers \
        [dict get [::vmdai::runtime::info] pid] [dict get [::vmdai::runtime::info] launch_token]
} -cleanup reset_all -result [list {ready 0} ready 1 200 [string repeat d 32]]

test sm-auth-1 {AUTH_FAILED re-reads the attach token and recovers} -setup reset_all -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:40004
    write_token 40004 [string repeat e 32]
    set ::health [list [list ok {pid 300 protocol 2}]]
    ::vmdai::runtime::ensure
    write_token 40004 [string repeat f 32]
    ::vmdai::runtime::on_auth_failed
    list [::vmdai::runtime::state] $::recovers [dict get [::vmdai::runtime::info] launch_token]
} -cleanup reset_all -result [list ready 1 [string repeat f 32]]

test sm-ok-1 {a successful RPC while reconnecting probes at once} -setup reset_all -body {
    set pid [start_owned]
    ::vmdai::runtime::on_transport_error "timeout"
    set probes_before $::probes
    set ::health [list [list ok [list pid $pid protocol 2]]]
    ::vmdai::runtime::on_transport_ok
    list [expr {$::probes - $probes_before}] [::vmdai::runtime::state] [probe_ms]
} -cleanup reset_all -result {1 ready {}}

test sm-hung-1 {an owned runtime that stops answering is killed and respawned} -setup reset_all -body {
    set pid [start_owned]
    set ::health [list {transport timeout}]
    ::vmdai::runtime::on_transport_error "timeout"
    foreach i {1 2 3 4 5} { fire_probe }
    list [lindex $::signals 0] [::vmdai::runtime::state] [llength $::spawned] $::vmdai::runtime::respawns
} -cleanup reset_all -result {{TERM 9001} launching 2 1}

test sm-stop-1 {stop while reconnecting cancels the probe timer} -setup reset_all -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:40005
    write_token 40005 [string repeat 1 32]
    set ::health [list [list ok {pid 400 protocol 2}]]
    ::vmdai::runtime::ensure
    set ::health [list {transport refused}]
    ::vmdai::runtime::on_transport_error "refused"
    set armed [llength $::timers]
    ::vmdai::runtime::stop
    list $armed $::timers [::vmdai::runtime::state] $::signals
} -cleanup reset_all -result {2 {} stopped {}}

cleanupTests
