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
    # Connection state machine (P06-T06).
    variable probe_timer
    if {![::info exists probe_timer]} { set probe_timer "" }
    variable attempt
    if {![::info exists attempt]} { set attempt 0 }
    variable probe_failures
    if {![::info exists probe_failures]} { set probe_failures 0 }
    variable respawns
    if {![::info exists respawns]} { set respawns 0 }
    variable respawning
    if {![::info exists respawning]} { set respawning 0 }
    variable last_ready_pid
    if {![::info exists last_ready_pid]} { set last_ready_pid "" }
    # Set while the transition to `ready` ends a reconnect or a respawn.
    variable recovering
    if {![::info exists recovering]} { set recovering 0 }
    # Cancelled and rearmed on every `ready`; resets the respawn budget after
    # a period of sustained `ready`, so a crash long after an earlier one
    # does not inherit its budget.
    variable stable_timer
    if {![::info exists stable_timer]} { set stable_timer "" }
    variable max_respawns 3
    variable hung_probe_limit 5
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
    _notice $old $new $detail
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
    variable respawns
    if {$state ni {stopped down}} {
        return $state
    }
    set respawns 0
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
    set at [string first "VMDAI_READY \{" $line]
    if {$at >= 0} {
        # Keep the READY line in the tail (it helps diagnose a runtime that
        # dies right after printing it), but never its launch_token.
        regsub {("launch_token"[ \t]*:[ \t]*")[^"]*(")} $line {\1<redacted>\2} shown
        _tail_add $shown
    } else {
        _tail_add $line
    }
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
            set line [string trim [lindex $tail $i]]
            if {$line ne ""} {
                if {[string first "VMDAI_READY \{" $line] >= 0} {
                    set last "The runtime exited right after it started."
                } else {
                    set last $line
                }
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
    variable state
    if {$state eq "ready"} {
        _enter_reconnecting "The AI runtime exited."
    }
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
    variable respawning
    variable respawns
    variable max_respawns
    if {[dict get $info owned]} {
        _close_pipe
        if {[_alive $child_pid]} {
            _terminate $child_pid 0
        }
    }
    if {$respawning && $reason eq "didnt_start" && $respawns < $max_respawns} {
        _set_state reconnecting $detail
        _schedule_probe
        return
    }
    set respawning 0
    set failure $reason
    _set_state down $detail
}

proc ::vmdai::runtime::_on_health {g purpose kind args} {
    variable gen
    variable info
    if {$g != $gen} {
        return
    }
    if {$kind ne "ok" && $purpose eq "probe"} {
        _probe_failed
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
    if {$purpose eq "probe" && ![dict get $info owned]} {
        # An attached runtime restarted on the same port has a new token.
        set token [_read_token [dict get $info port]]
        if {$token ne ""} {
            dict set info launch_token $token
        }
    }
    _became_ready
}

proc ::vmdai::runtime::_became_ready {} {
    variable info
    variable attempt
    variable probe_failures
    variable probe_timer
    variable respawning
    variable last_ready_pid
    variable recovering
    variable state
    variable gen
    variable stable_timer
    ::vmdai::sched::cancel $probe_timer
    set probe_timer ""
    set attempt 0
    set probe_failures 0
    set recovering [expr {$respawning || $state eq "reconnecting"}]
    set respawning 0
    set previous $last_ready_pid
    set last_ready_pid [dict get $info pid]
    _set_state ready
    set recovering 0
    ::vmdai::sched::cancel $stable_timer
    set stable_timer [::vmdai::sched::after $::vmdai::config::respawn_reset_ms \
        [list ::vmdai::runtime::_stable $gen]]
    if {$previous ne "" && $previous ne $last_ready_pid} {
        _recover "new runtime pid $last_ready_pid (was $previous)"
    }
}

# After a long stretch of uninterrupted `ready` under one gen, the runtime
# has proven itself again: give it a fresh respawn budget.
proc ::vmdai::runtime::_stable {g} {
    variable stable_timer
    variable gen
    variable state
    variable respawns
    set stable_timer ""
    if {$g == $gen && $state eq "ready"} {
        set respawns 0
    }
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
    variable probe_timer
    variable respawns
    variable respawning
    variable last_ready_pid
    variable stable_timer
    set sync [expr {[lsearch -exact $args -sync] >= 0}]
    incr gen
    ::vmdai::sched::cancel $ready_timer
    set ready_timer ""
    ::vmdai::sched::cancel $probe_timer
    set probe_timer ""
    ::vmdai::sched::cancel $stable_timer
    set stable_timer ""
    set respawns 0
    set respawning 0
    set last_ready_pid ""
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

# --- connection state machine (spec 2d, 5, S3) ----------------------------

# 500, 1000, 2000, 4000, 8000, 8000, ... ms for attempt 1, 2, 3, ...
proc ::vmdai::runtime::backoff_ms {attempt} {
    if {$attempt >= 5} {
        return 8000
    }
    return [expr {500 << ($attempt - 1)}]
}

# The bridge calls this when an RPC fails at the transport level.
proc ::vmdai::runtime::on_transport_error {reason} {
    variable state
    if {$state eq "ready"} {
        _enter_reconnecting $reason
    }
}

# The bridge calls this after any RPC that reached the runtime.
proc ::vmdai::runtime::on_transport_ok {} {
    variable state
    variable gen
    variable probe_timer
    if {$state ne "reconnecting"} {
        return
    }
    ::vmdai::sched::cancel $probe_timer
    set probe_timer ""
    _reconnect_tick $gen
}

# The bridge calls this when a session RPC answers AUTH_FAILED: the runtime
# restarted behind the same port (attach) or lost the session.
proc ::vmdai::runtime::on_auth_failed {} {
    variable state
    variable info
    if {$state ne "ready"} {
        return
    }
    if {![dict get $info owned]} {
        set token [_read_token [dict get $info port]]
        if {$token ne ""} {
            dict set info launch_token $token
        }
    }
    _recover "AUTH_FAILED"
}

# Banner "Retry": start over from down/stopped, or probe now while reconnecting.
proc ::vmdai::runtime::retry_now {} {
    variable state
    variable gen
    variable attempt
    variable probe_timer
    variable respawns
    switch -- $state {
        down - stopped {
            set respawns 0
            ensure
        }
        reconnecting {
            set attempt 0
            ::vmdai::sched::cancel $probe_timer
            set probe_timer ""
            _reconnect_tick $gen
        }
    }
    return [state]
}

proc ::vmdai::runtime::_enter_reconnecting {detail} {
    variable attempt
    variable probe_failures
    set attempt 0
    set probe_failures 0
    _set_state reconnecting $detail
    _schedule_probe
}

proc ::vmdai::runtime::_schedule_probe {} {
    variable gen
    variable attempt
    variable probe_timer
    incr attempt
    ::vmdai::sched::cancel $probe_timer
    set probe_timer [::vmdai::sched::after [backoff_ms $attempt] \
        [list ::vmdai::runtime::_reconnect_tick $gen]]
}

proc ::vmdai::runtime::_reconnect_tick {g} {
    variable gen
    variable state
    variable info
    variable chan
    variable child_pid
    variable probe_timer
    set probe_timer ""
    if {$g != $gen || $state ne "reconnecting"} {
        return
    }
    if {[dict get $info owned] && ($chan eq "" || ![_alive $child_pid])} {
        _respawn
        return
    }
    _probe [list ::vmdai::runtime::_on_health $g probe]
}

proc ::vmdai::runtime::_probe_failed {} {
    variable info
    variable probe_failures
    variable hung_probe_limit
    variable child_pid
    incr probe_failures
    if {[dict get $info owned] && $probe_failures >= $hung_probe_limit} {
        _log "owned runtime pid $child_pid is not answering; restarting it"
        _close_pipe
        _terminate $child_pid 0
        _respawn
        return
    }
    _schedule_probe
}

proc ::vmdai::runtime::_respawn {} {
    variable respawns
    variable respawning
    variable max_respawns
    if {$respawns >= $max_respawns} {
        set respawning 0
        _fail unreachable "The AI runtime stopped and did not come back after $max_respawns restarts."
        return
    }
    incr respawns
    set respawning 1
    _launch
}

proc ::vmdai::runtime::_recover {why} {
    _log "recover: $why"
    if {[llength [::info commands ::vmdai::bridge::recover]]} {
        if {[catch {::vmdai::bridge::recover} err]} {
            _log "bridge::recover failed: $err"
        }
    }
}

# One transcript notice per state change (S3); the status bar shows the rest.
proc ::vmdai::runtime::_notice {old new detail} {
    variable failure
    variable respawns
    variable max_respawns
    variable recovering
    set level ""
    switch -- $new {
        reconnecting {
            if {$old eq "ready"} {
                set level warn
                set text "Lost the connection to the AI runtime; reconnecting."
            }
        }
        launching {
            if {$old eq "reconnecting"} {
                set level warn
                set text "The AI runtime stopped; restarting it ($respawns of $max_respawns)."
            }
        }
        ready {
            if {$recovering} {
                set level info
                set text "Reconnected to the AI runtime."
            }
        }
        down {
            set level error
            switch -- $failure {
                didnt_start { set text "The AI runtime didn't start: $detail" }
                too_old { set text $detail }
                default { set text "Can't reach the AI runtime: $detail" }
            }
        }
    }
    if {$level eq ""} {
        return
    }
    _log "notice $level: $text"
    if {[llength [::info commands ::vmdai::ui::notify]]} {
        if {[catch {::vmdai::ui::notify $level $text} err]} {
            _log "ui::notify failed: $err"
        }
    }
}
