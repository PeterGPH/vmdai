# runtime.tcl - launch, attach and stop the AI runtime, and the connection
# state machine (spec 2d, 5). No Tk.
#
# States: stopped -> launching -> connecting -> ready <-> reconnecting -> down.
# Subscribers run as {*}$cmd old new detail on every change of state.

namespace eval ::vmdai::runtime {
    variable state
    if {![::info exists state]} { set state stopped }
    variable info
    if {![::info exists info]} {
        set info [dict create host "" port "" pid "" version "" protocol "" launch_token "" owned 0]
    }
    # Owned runtime: the pipe channel and the child's pid.
    variable chan
    if {![::info exists chan]} { set chan "" }
    variable child_pid
    if {![::info exists child_pid]} { set child_pid "" }
    # Last 50 lines the runtime wrote before and after READY.
    variable tail
    if {![::info exists tail]} { set tail {} }
    variable failure
    if {![::info exists failure]} { set failure "" }
    variable subscribers
    if {![::info exists subscribers]} { set subscribers {} }
    # Bumped on every launch, attach and stop; stale callbacks compare it.
    variable gen
    if {![::info exists gen]} { set gen 0 }
    variable ready_timer
    if {![::info exists ready_timer]} { set ready_timer "" }
    variable tail_max 50
}

proc ::vmdai::runtime::_log {msg} {
    catch {::vmdai::config::log "runtime: $msg"}
}

proc ::vmdai::runtime::state {} {
    variable state
    return $state
}

proc ::vmdai::runtime::info {} {
    variable info
    return $info
}

proc ::vmdai::runtime::failure_reason {} {
    variable failure
    return $failure
}

proc ::vmdai::runtime::pipe_tail {{n 12}} {
    variable tail
    if {$n <= 0} {
        return {}
    }
    return [lrange $tail end-[expr {$n - 1}] end]
}

proc ::vmdai::runtime::subscribe {cmd} {
    variable subscribers
    if {[lsearch -exact $subscribers $cmd] < 0} {
        lappend subscribers $cmd
    }
    return
}

proc ::vmdai::runtime::launch_command {python main} {
    return [list $python -u $main --port 0 --announce --watch-stdin 2>@1]
}

proc ::vmdai::runtime::_set_state {new {detail ""}} {
    variable state
    variable subscribers
    set old $state
    if {$old eq $new} {
        return
    }
    set state $new
    _log "$old -> $new $detail"
    foreach cmd $subscribers {
        if {[catch {uplevel #0 [list {*}$cmd $old $new $detail]} err]} {
            _log "subscriber $cmd failed: $err"
        }
    }
}

proc ::vmdai::runtime::_tail_add {line} {
    variable tail
    variable tail_max
    lappend tail [string trimright $line "\r"]
    if {[llength $tail] > $tail_max} {
        set tail [lrange $tail end-[expr {$tail_max - 1}] end]
    }
}

# --- seams (tests replace these) -------------------------------------------

# Start the runtime pipeline; returns {chan pid}.
proc ::vmdai::runtime::_spawn {cmd g} {
    set ch [open "|$cmd" r+]
    fconfigure $ch -blocking 0 -buffering line -translation auto -encoding utf-8
    ::vmdai::sched::fileevent $ch readable [list ::vmdai::runtime::_on_readable $g $ch]
    return [list $ch [lindex [pid $ch] 0]]
}

proc ::vmdai::runtime::_close_pipe {} {
    variable chan
    if {$chan eq ""} {
        return
    }
    catch {::vmdai::sched::fileevent $chan readable {}}
    # Non-blocking, so close never waits for the child.
    catch {fconfigure $chan -blocking 0}
    catch {close $chan}
    set chan ""
}

proc ::vmdai::runtime::_probe {callback} {
    ::vmdai::net::http_get /health $callback -timeout 1500
}

proc ::vmdai::runtime::_signal {pid sig} {
    if {$pid ne ""} {
        catch {exec kill -$sig $pid}
    }
}

proc ::vmdai::runtime::_alive {pid} {
    if {$pid eq ""} {
        return 0
    }
    return [expr {![catch {exec kill -0 $pid}]}]
}

# --- launch -----------------------------------------------------------------

proc ::vmdai::runtime::ensure {} {
    variable state
    if {$state ni {stopped down}} {
        return $state
    }
    if {[catch {::vmdai::config::attach_target} target]} {
        _fail unreachable $target
        return [state]
    }
    if {$target ne ""} {
        _attach [lindex $target 0] [lindex $target 1]
    } else {
        _launch
    }
    return [state]
}

proc ::vmdai::runtime::_reset_info {owned} {
    variable info
    set info [dict create host 127.0.0.1 port "" pid "" version "" protocol "" \
        launch_token "" owned $owned]
}

proc ::vmdai::runtime::_launch {} {
    variable gen
    variable tail
    variable chan
    variable child_pid
    variable failure
    variable ready_timer
    set g [incr gen]
    set failure ""
    set tail {}
    _reset_info 1
    set python [::vmdai::config::resolve_python]
    if {$python eq ""} {
        _fail didnt_start "No Python 3 found. Set VMD_AI_PYTHON or choose Python in Settings."
        return
    }
    set cmd [launch_command $python $::vmdai::config::runtime_main]
    _set_state launching
    if {[catch {_spawn $cmd $g} spawned]} {
        _tail_add $spawned
        _fail didnt_start $spawned
        return
    }
    lassign $spawned chan child_pid
    set ready_timer [::vmdai::sched::after $::vmdai::config::ready_timeout_ms \
        [list ::vmdai::runtime::_ready_timeout $g]]
}

proc ::vmdai::runtime::_on_readable {g ch} {
    variable gen
    variable chan
    while {$g == $gen && $ch eq $chan && [gets $ch line] >= 0} {
        _pipe_line $g $line
    }
    if {$g == $gen && $ch eq $chan && [eof $ch]} {
        _pipe_eof $g
    }
}

proc ::vmdai::runtime::_pipe_line {g line} {
    variable state
    _tail_add $line
    set at [string first "VMDAI_READY \{" $line]
    if {$at >= 0 && $state eq "launching"} {
        _on_ready $g [string range $line [expr {$at + 12}] end]
    }
}

proc ::vmdai::runtime::_on_ready {g payload} {
    variable info
    variable ready_timer
    ::vmdai::sched::cancel $ready_timer
    set ready_timer ""
    if {[catch {::vmdai::net::decode $payload} ready]
            || ![dict exists $ready port] || ![dict exists $ready launch_token]} {
        _fail didnt_start "The runtime printed a malformed READY line."
        return
    }
    foreach key {port pid version protocol launch_token} {
        if {[dict exists $ready $key]} {
            dict set info $key [dict get $ready $key]
        }
    }
    if {![string is integer -strict [dict get $info protocol]] || [dict get $info protocol] < 2} {
        _too_old [dict get $info protocol]
        return
    }
    ::vmdai::net::configure -base_url "http://127.0.0.1:[dict get $info port]"
    _set_state connecting
    _probe [list ::vmdai::runtime::_on_health $g connect]
}

proc ::vmdai::runtime::_pipe_eof {g} {
    variable state
    variable tail
    _close_pipe
    if {$state in {launching connecting}} {
        set last "The runtime exited before it was ready."
        for {set i [expr {[llength $tail] - 1}]} {$i >= 0} {incr i -1} {
            if {[string trim [lindex $tail $i]] ne ""} {
                set last [string trim [lindex $tail $i]]
                break
            }
        }
        _fail didnt_start $last
        return
    }
    _process_exited
}

# An owned runtime's pipe hit EOF after it was ready.
proc ::vmdai::runtime::_process_exited {} {
    _fail unreachable "The AI runtime exited."
}

proc ::vmdai::runtime::_ready_timeout {g} {
    variable gen
    variable state
    if {$g != $gen || $state ne "launching"} {
        return
    }
    _fail didnt_start "The runtime printed no READY line within [expr {$::vmdai::config::ready_timeout_ms / 1000}] s."
}

proc ::vmdai::runtime::_too_old {protocol} {
    if {$protocol eq ""} {
        set protocol 1
    }
    _fail too_old "This runtime is too old (protocol $protocol)."
}

# Go to `down`, stopping an owned process that is still running.
proc ::vmdai::runtime::_fail {reason detail} {
    variable failure
    variable info
    variable child_pid
    variable ready_timer
    ::vmdai::sched::cancel $ready_timer
    set ready_timer ""
    set failure $reason
    if {[dict get $info owned]} {
        _close_pipe
        if {[_alive $child_pid]} {
            _terminate $child_pid 0
        }
    }
    _set_state down $detail
}

proc ::vmdai::runtime::_on_health {g purpose kind args} {
    variable gen
    variable info
    if {$g != $gen} {
        return
    }
    if {$kind ne "ok"} {
        _fail unreachable "Nothing answered on [dict get $info host]:[dict get $info port]."
        return
    }
    set body [lindex $args 0]
    set protocol 1
    catch {set protocol [dict get $body protocol]}
    if {![string is integer -strict $protocol] || $protocol < 2} {
        _too_old $protocol
        return
    }
    catch {dict set info pid [dict get $body pid]}
    catch {dict set info version [dict get $body version]}
    dict set info protocol $protocol
    _became_ready
}

proc ::vmdai::runtime::_became_ready {} {
    _set_state ready
}

# --- attach -----------------------------------------------------------------

proc ::vmdai::runtime::_read_token {port} {
    set path [::vmdai::config::token_file_path $port]
    if {[catch {
        set fh [open $path r]
        set text [read $fh]
        close $fh
        set token [dict get [::vmdai::net::decode $text] token]
    }]} {
        return ""
    }
    return $token
}

proc ::vmdai::runtime::_attach {host port} {
    variable gen
    variable info
    variable failure
    set g [incr gen]
    set failure ""
    _reset_info 0
    dict set info host $host
    dict set info port $port
    set token [_read_token $port]
    if {$token eq ""} {
        _fail unreachable "No token file at [::vmdai::config::token_file_path $port]. Start the runtime with scripts/run_runtime.sh."
        return
    }
    dict set info launch_token $token
    ::vmdai::net::configure -base_url "http://$host:$port"
    _set_state connecting
    _probe [list ::vmdai::runtime::_on_health $g attach]
}

# --- stop -------------------------------------------------------------------

# TERM now; KILL after shutdown_kill_ms if it is still alive. With sync=1 the
# wait is a blocking sleep (no event loop), for reload/cleanup.
proc ::vmdai::runtime::_terminate {pid sync} {
    _signal $pid TERM
    set ms $::vmdai::config::shutdown_kill_ms
    if {!$sync} {
        ::vmdai::sched::after $ms [list ::vmdai::runtime::_kill_if_alive $pid]
        return
    }
    set deadline [expr {[clock milliseconds] + $ms}]
    while {[_alive $pid] && [clock milliseconds] < $deadline} {
        ::after 50
    }
    _kill_if_alive $pid
    # Give SIGKILL a moment; each `exec kill -0` also reaps the exited child.
    set deadline [expr {[clock milliseconds] + 500}]
    while {[_alive $pid] && [clock milliseconds] < $deadline} {
        ::after 20
    }
}

proc ::vmdai::runtime::_kill_if_alive {pid} {
    if {[_alive $pid]} {
        _log "pid $pid ignored SIGTERM; sending SIGKILL"
        _signal $pid KILL
    }
}

# Stop the runtime. An owned runtime gets runtime.shutdown, stdin EOF, TERM,
# then KILL; an attached runtime is only disconnected, never killed.
proc ::vmdai::runtime::stop {args} {
    variable gen
    variable info
    variable child_pid
    variable failure
    variable ready_timer
    set sync [expr {[lsearch -exact $args -sync] >= 0}]
    incr gen
    ::vmdai::sched::cancel $ready_timer
    set ready_timer ""
    catch {::vmdai::net::bump_epoch}
    if {[dict get $info owned]} {
        set token [dict get $info launch_token]
        if {$token ne "" && [dict get $info port] ne "" && !$sync} {
            catch {::vmdai::net::call runtime.shutdown [list launch_token s $token] \
                ::vmdai::runtime::_ignore -session 0}
        }
        _close_pipe
        if {[_alive $child_pid]} {
            _terminate $child_pid $sync
        }
    }
    set child_pid ""
    set failure ""
    _reset_info 0
    dict set info host ""
    _set_state stopped
    return
}

proc ::vmdai::runtime::_ignore {args} {}
