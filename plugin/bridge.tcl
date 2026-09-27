# bridge.tcl - session, poll pump, request state, routing and the working
# directory (spec 2c, 2d, 3). No Tk, no nested event loops.
#
# The panel is reached only through ::vmdai::ui::render_event, notify,
# set_busy and status; the executor through ::vmdai::executor::run. Every
# RPC outcome is fed to the connection state machine (P06-T06 contract).

namespace eval ::vmdai::bridge {
    # The display events this plugin asks for (spec 2c). M1 renders v1.
    variable event_protocol 1
    variable session_id
    if {![info exists session_id]} { set session_id "" }
    variable session_token
    if {![info exists session_token]} { set session_token "" }
    variable chat_id
    if {![info exists chat_id]} { set chat_id "" }
    variable after_seq
    if {![info exists after_seq]} { set after_seq 0 }
    variable busy
    if {![info exists busy]} { set busy 0 }
    variable request_id
    if {![info exists request_id]} { set request_id "" }
    variable workdir
    if {![info exists workdir]} { set workdir "" }
    # Poll pump: one timer and at most one poll outstanding.
    variable poll_timer
    if {![info exists poll_timer]} { set poll_timer "" }
    variable polling
    if {![info exists polling]} { set polling 0 }
    # tool_start events held back while the executor runs model Tcl.
    variable deferred
    if {![info exists deferred]} { set deferred {} }
    variable drain_timer
    if {![info exists drain_timer]} { set drain_timer "" }
    # Session changes (start, new chat, resume, recover) run one at a time.
    variable op_busy
    if {![info exists op_busy]} { set op_busy 0 }
    variable op_queue
    if {![info exists op_queue]} { set op_queue {} }
    variable recovering
    if {![info exists recovering]} { set recovering 0 }
    # Set after a reconnect while busy: check runtime.info once drained.
    variable reconcile_pending
    if {![info exists reconcile_pending]} { set reconcile_pending 0 }
    # Requests whose end event arrived before chat.send answered.
    variable finished
    if {![info exists finished]} { set finished {} }
    variable ready_timer
    if {![info exists ready_timer]} { set ready_timer "" }
    # A CHAT_LOCKED resume during automatic recovery gets one retry, after
    # the old runtime's kill deadline plus a margin (it may still hold the
    # chat's flock until then).
    variable recover_retries
    if {![info exists recover_retries]} { set recover_retries 0 }
    variable recover_timer
    if {![info exists recover_timer]} { set recover_timer "" }
    variable recover_retry_margin_ms 250
    variable poll_limit 80
    variable client_version "vmd_ai 2.0"
}

proc ::vmdai::bridge::_log {msg} {
    catch {::vmdai::config::log "bridge: $msg"}
}

proc ::vmdai::bridge::_ignore {args} {}

proc ::vmdai::bridge::_dget {d key default} {
    if {[catch {dict get $d $key} value] || $value eq "null"} {
        return $default
    }
    return $value
}

proc ::vmdai::bridge::state {} {
    variable session_id
    variable chat_id
    variable busy
    variable request_id
    variable after_seq
    return [dict create session_id $session_id chat_id $chat_id busy $busy \
        request_id $request_id after_seq $after_seq epoch [::vmdai::net::epoch]]
}

# Feed one RPC outcome to the connection state machine: a transport error
# may start a reconnect, any answer ends one, and AUTH_FAILED (except from
# session.start itself) makes the runtime recover the session.
proc ::vmdai::bridge::note_outcome {method kind args} {
    if {![llength [info commands ::vmdai::runtime::on_transport_ok]]} {
        return
    }
    switch -- $kind {
        transport {
            ::vmdai::runtime::on_transport_error [lindex $args 0]
        }
        rpc_error {
            ::vmdai::runtime::on_transport_ok
            if {[lindex $args 0] eq "AUTH_FAILED" && $method ne "session.start"} {
                ::vmdai::runtime::on_auth_failed
            }
        }
        default {
            ::vmdai::runtime::on_transport_ok
        }
    }
}

# Note the outcome, then hand it to the caller's callback (net forms).
proc ::vmdai::bridge::_relay {method callback kind args} {
    note_outcome $method $kind {*}$args
    if {$callback ne ""} {
        ::vmdai::net::deliver $callback $kind {*}$args
    }
}

proc ::vmdai::bridge::_runtime_ready {} {
    if {![llength [info commands ::vmdai::runtime::state]]} {
        return 1
    }
    return [expr {[::vmdai::runtime::state] eq "ready"}]
}

# C6: {vmd_version, arch, tcl_patchlevel, tk_patchlevel}, each in catch.
proc ::vmdai::bridge::vmd_env_json {} {
    set parts {}
    foreach {key script} {
        vmd_version {vmdinfo version}
        arch {vmdinfo arch}
        tcl_patchlevel {info patchlevel}
        tk_patchlevel {package present Tk}
    } {
        if {![catch {uplevel #0 $script} value] && $value ne ""} {
            lappend parts "[::vmdai::net::json_string $key]:[::vmdai::net::json_string $value]"
        }
    }
    return "\{[join $parts ,]\}"
}

# --- one session change at a time -----------------------------------------

proc ::vmdai::bridge::_op {script} {
    variable op_busy
    variable op_queue
    if {$op_busy} {
        lappend op_queue $script
        return
    }
    set op_busy 1
    if {[catch {uplevel #0 $script} err]} {
        _log "operation failed: $::errorInfo"
        _op_done
    }
}

proc ::vmdai::bridge::_op_done {} {
    variable op_busy
    variable op_queue
    set op_busy 0
    if {[llength $op_queue]} {
        set next [lindex $op_queue 0]
        set op_queue [lrange $op_queue 1 end]
        ::vmdai::sched::after 0 [list ::vmdai::bridge::_op $next]
        return
    }
    _schedule_poll 0
}

# --- session ------------------------------------------------------------------

proc ::vmdai::bridge::start_session {{callback ""}} {
    _op [list ::vmdai::bridge::_start_session $callback]
}

proc ::vmdai::bridge::_start_session {callback} {
    variable event_protocol
    variable workdir
    variable client_version
    variable polling
    variable session_id
    variable session_token
    variable after_seq
    variable deferred
    _stop_pump
    ::vmdai::net::bump_epoch
    set polling 0
    set deferred {}
    catch {::vmdai::executor::reset}
    set session_id ""
    set session_token ""
    set after_seq 0
    ::vmdai::net::configure -session_id "" -session_token ""
    if {$workdir eq ""} {
        _load_workdir
    }
    set params [list cwd s $workdir ui_mode s tk client_version s $client_version \
        platform s $::tcl_platform(os) event_protocol i $event_protocol \
        vmd_env j [vmd_env_json]]
    set token ""
    catch {set token [dict get [::vmdai::runtime::info] launch_token]}
    if {$token ne ""} {
        lappend params launch_token s $token
    }
    ::vmdai::net::call session.start $params \
        [list ::vmdai::bridge::_on_session_started $callback]
}

proc ::vmdai::bridge::_on_session_started {callback kind args} {
    variable session_id
    variable session_token
    variable chat_id
    variable after_seq
    variable recovering
    note_outcome session.start $kind {*}$args
    if {$kind eq "ok"} {
        set result [lindex $args 0]
        set session_id [_dget $result session_id ""]
        set session_token [_dget $result session_token ""]
        ::vmdai::net::configure -session_id $session_id -session_token $session_token
        # A new chat takes the runtime's chat id (null until the first send
        # for a token session); a recovered session keeps its chat.
        if {$chat_id eq ""} {
            set chat_id [_dget $result chat_id ""]
        }
        set after_seq 0
    } else {
        set recovering 0
        set message [lindex $args [expr {$kind eq "rpc_error" ? 1 : 0}]]
        if {[catch {::vmdai::ui::notify error "Could not start a chat session: $message"} err]} {
            _log "ui: $err"
        }
    }
    _op_done
    if {$callback ne ""} {
        ::vmdai::net::deliver $callback $kind {*}$args
    }
}

# The runtime came back with a new pid or answered AUTH_FAILED (P06-T06):
# start a new session, resume the current chat, and report a lost request.
proc ::vmdai::bridge::recover {} {
    variable recovering
    variable busy
    variable request_id
    if {$recovering} {
        return
    }
    set recovering 1
    if {$busy} {
        _request_ended $request_id
        if {[catch {::vmdai::ui::status "The request in progress was lost when the AI runtime restarted."} err]} {
            _log "ui: $err"
        }
    }
    _op [list ::vmdai::bridge::_start_session ::vmdai::bridge::_recovered]
}

proc ::vmdai::bridge::_recovered {kind args} {
    variable recovering
    variable chat_id
    variable recover_retries
    if {$kind ne "ok" || $chat_id eq ""} {
        set recovering 0
        return
    }
    set recover_retries 1
    _op [list ::vmdai::bridge::_resume $chat_id "" ::vmdai::bridge::_on_recover_resume]
}

proc ::vmdai::bridge::_on_recover_resume {target callback kind args} {
    variable recovering
    variable chat_id
    variable recover_retries
    variable recover_timer
    variable recover_retry_margin_ms
    variable session_id
    note_outcome chat.resume $kind {*}$args
    set recovering 0
    if {$kind eq "ok"} {
        _resumed $target [lindex $args 0]
    } elseif {$kind eq "rpc_error" && [lindex $args 0] eq "CHAT_LOCKED" && $recover_retries > 0} {
        incr recover_retries -1
        _log "recover: chat.resume $target got CHAT_LOCKED, retrying ($recover_retries left)"
        set chat_id ""
        set recover_timer [::vmdai::sched::after \
            [expr {$::vmdai::config::shutdown_kill_ms + $recover_retry_margin_ms}] \
            [list ::vmdai::bridge::_retry_recover_resume $target $session_id]]
    } else {
        # The chat stays on disk; this session starts a new one.
        _log "recover: chat.resume $target failed: $args"
        set chat_id ""
        if {$kind eq "transport"} {
            set reason "the AI runtime did not answer"
        } else {
            lassign $args code message
            switch -- $code {
                CHAT_LOCKED { set reason "it is open in another VMD window" }
                NOT_FOUND { set reason "it no longer exists" }
                default { set reason $message }
            }
        }
        set text "Could not reopen this chat after the AI runtime restarted ($reason). Your next message starts a new chat."
        if {[catch {::vmdai::ui::notify warn $text} err]} {
            _log "ui: $err"
        }
    }
    _op_done
}

# One retry of a chat.resume that lost to CHAT_LOCKED during recovery, timed
# for after the old runtime (if any) was killed. Abandoned if the session
# moved on, a chat is already set, or a request is running.
proc ::vmdai::bridge::_retry_recover_resume {target sid} {
    variable recover_timer
    variable session_id
    variable chat_id
    variable busy
    set recover_timer ""
    if {$sid ne $session_id || $chat_id ne "" || $busy} {
        return
    }
    _op [list ::vmdai::bridge::_resume $target "" ::vmdai::bridge::_on_recover_resume]
}

# New Chat: cancel a running request, stop the old session (which releases
# its chat lock), then start a new session with no chat.
proc ::vmdai::bridge::new_chat {} {
    _op ::vmdai::bridge::_new_chat
}

proc ::vmdai::bridge::_new_chat {} {
    variable session_id
    variable busy
    variable request_id
    variable chat_id
    if {$busy && $request_id ne ""} {
        catch {::vmdai::executor::note_cancelled $request_id}
        ::vmdai::net::call chat.cancel [list request_id s $request_id] ::vmdai::bridge::_ignore
    }
    _request_ended $request_id
    set chat_id ""
    if {$session_id eq ""} {
        _start_session ""
        return
    }
    _stop_pump
    ::vmdai::net::call session.stop {} ::vmdai::bridge::_on_session_stopped
}

proc ::vmdai::bridge::_on_session_stopped {kind args} {
    # The old session is gone either way; only a transport error says
    # something about the runtime.
    if {$kind eq "transport"} {
        note_outcome session.stop $kind {*}$args
    }
    _start_session ""
}

# Resume a stored chat in this session. The callback gets the net forms:
# ok <result> | rpc_error <code> <message> <data> | transport <reason>.
proc ::vmdai::bridge::resume {target {callback ""}} {
    _op [list ::vmdai::bridge::_resume $target $callback ::vmdai::bridge::_on_resume]
}

proc ::vmdai::bridge::_resume {target callback handler} {
    variable session_id
    if {$session_id eq ""} {
        ::vmdai::sched::after 0 [list $handler $target $callback \
            rpc_error NOT_CONNECTED "Not connected to the AI runtime yet." {}]
        return
    }
    _stop_pump
    ::vmdai::net::call chat.resume [list chat_id s $target] [list $handler $target $callback]
}

proc ::vmdai::bridge::_on_resume {target callback kind args} {
    note_outcome chat.resume $kind {*}$args
    if {$kind eq "ok"} {
        _resumed $target [lindex $args 0]
    } else {
        _resume_failed $kind {*}$args
    }
    _op_done
    if {$callback ne ""} {
        ::vmdai::net::deliver $callback $kind {*}$args
    }
}

# chat.resume succeeded: switch chat_id and after_seq (the runtime's
# last_seq; older runtimes restart at 0), drop replies meant for the old
# chat, and apply the folder again.
proc ::vmdai::bridge::_resumed {target result} {
    variable chat_id
    variable after_seq
    variable polling
    variable deferred
    variable request_id
    ::vmdai::net::bump_epoch
    set polling 0
    set deferred {}
    _request_ended $request_id
    set chat_id $target
    set after_seq [_dget $result last_seq 0]
    if {![string is integer -strict $after_seq]} {
        set after_seq 0
    }
    _send_cwd
}

proc ::vmdai::bridge::_resume_failed {kind args} {
    if {$kind eq "transport"} {
        set text "Could not resume the chat: the AI runtime did not answer."
    } else {
        lassign $args code message
        switch -- $code {
            CHAT_LOCKED { set text "This chat is open in another VMD window." }
            REQUEST_CONFLICT { set text "Stop the running request before switching chats." }
            NOT_FOUND { set text "That chat no longer exists." }
            default { set text "Could not resume the chat: $message" }
        }
    }
    if {[catch {::vmdai::ui::notify error $text} err]} {
        _log "ui: $err"
    }
}

# --- requests -----------------------------------------------------------------

# Send a prompt. Returns 1 when chat.send was issued. The panel turns busy
# only after the runtime accepted the request (spec 2h, 4).
proc ::vmdai::bridge::send {text} {
    variable session_id
    variable busy
    variable chat_id
    variable op_busy
    if {$session_id eq "" || $op_busy || ![_runtime_ready]} {
        set why "Not connected to the AI runtime yet; try again in a moment."
    } elseif {$busy} {
        set why "A request is still running; stop it first."
    } else {
        set params [list text s $text conversation_mode s full]
        if {$chat_id ne ""} {
            lappend params chat_id s $chat_id
        }
        ::vmdai::net::call chat.send $params ::vmdai::bridge::_on_send
        return 1
    }
    if {[catch {::vmdai::ui::notify warn $why} err]} {
        _log "ui: $err"
    }
    return 0
}

proc ::vmdai::bridge::_on_send {kind args} {
    variable busy
    variable request_id
    variable chat_id
    variable finished
    note_outcome chat.send $kind {*}$args
    switch -- $kind {
        ok {
            set result [lindex $args 0]
            set rid [_dget $result request_id ""]
            set cid [_dget $result chat_id ""]
            if {$cid ne ""} {
                set chat_id $cid
            }
            if {$rid ne "" && [lsearch -exact $finished $rid] < 0} {
                set request_id $rid
                set busy 1
                if {[catch {::vmdai::ui::set_busy 1} err]} {
                    _log "ui: $err"
                }
            }
            _schedule_poll 0
        }
        rpc_error {
            lassign $args code message
            if {[catch {::vmdai::ui::notify error "Could not send: $message"} err]} {
                _log "ui: $err"
            }
            catch {::vmdai::ui::set_busy 0}
        }
        default {
            if {[catch {::vmdai::ui::notify error "Could not send: the AI runtime did not answer."} err]} {
                _log "ui: $err"
            }
            catch {::vmdai::ui::set_busy 0}
        }
    }
}

proc ::vmdai::bridge::cancel {} {
    variable busy
    variable request_id
    if {!$busy || $request_id eq ""} {
        return 0
    }
    catch {::vmdai::executor::note_cancelled $request_id}
    ::vmdai::net::call chat.cancel [list request_id s $request_id] \
        [list ::vmdai::bridge::_relay chat.cancel ""]
    return 1
}

proc ::vmdai::bridge::_request_ended {rid} {
    variable busy
    variable request_id
    variable finished
    if {$rid ne ""} {
        lappend finished $rid
        set finished [lrange $finished end-19 end]
    }
    if {$rid ne $request_id || $request_id eq ""} {
        return
    }
    set busy 0
    set request_id ""
    if {[catch {::vmdai::ui::set_busy 0} err]} {
        _log "ui: $err"
    }
}

# --- poll pump (spec 2d) ------------------------------------------------------

proc ::vmdai::bridge::_schedule_poll {ms} {
    variable poll_timer
    ::vmdai::sched::cancel $poll_timer
    set poll_timer [::vmdai::sched::after $ms ::vmdai::bridge::_poll]
}

proc ::vmdai::bridge::_stop_pump {} {
    variable poll_timer
    ::vmdai::sched::cancel $poll_timer
    set poll_timer ""
}

proc ::vmdai::bridge::poll_now {} {
    _schedule_poll 0
}

proc ::vmdai::bridge::_poll {} {
    variable poll_timer
    variable polling
    variable session_id
    variable after_seq
    variable poll_limit
    variable op_busy
    set poll_timer ""
    if {$polling || $session_id eq "" || $op_busy || ![_runtime_ready]} {
        return
    }
    set polling 1
    ::vmdai::net::call chat.events.poll [list after_seq i $after_seq limit i $poll_limit] \
        [list ::vmdai::bridge::_on_poll $session_id] -timeout $::vmdai::config::request_timeout_ms
}

proc ::vmdai::bridge::_on_poll {sid kind args} {
    variable polling
    variable session_id
    variable after_seq
    variable op_busy
    variable reconcile_pending
    set polling 0
    if {$sid ne $session_id} {
        return
    }
    note_outcome chat.events.poll $kind {*}$args
    if {$kind eq "transport"} {
        # The state machine reconnects; _after_ready restarts the pump.
        return
    }
    if {$kind eq "rpc_error"} {
        if {[lindex $args 0] ne "AUTH_FAILED"} {
            _log "poll: [lindex $args 0] [lindex $args 1]"
            _schedule_poll $::vmdai::config::poll_ms
        }
        return
    }
    set result [lindex $args 0]
    if {[catch {dict get $result events} events] || [catch {llength $events}]} {
        # Undecodable poll body: a transport error; after_seq stays (spec 5).
        catch {::vmdai::runtime::on_transport_error "malformed poll result"}
        return
    }
    foreach ev $events {
        set seq ""
        catch {set seq [dict get $ev seq]}
        if {![string is integer -strict $seq] || $seq <= $after_seq} {
            continue
        }
        set after_seq $seq
        if {[catch {_dispatch $ev} err]} {
            _log "dispatch of seq $seq failed: $::errorInfo"
        }
        if {$sid ne $session_id} {
            return
        }
    }
    set more 0
    catch {set more [string is true -strict [dict get $result has_more]]}
    if {!$more && $reconcile_pending} {
        set reconcile_pending 0
        _reconcile
    }
    if {$op_busy} {
        return
    }
    _schedule_poll [expr {$more ? 0 : $::vmdai::config::poll_ms}]
}

proc ::vmdai::bridge::_executing {} {
    return [expr {[info exists ::vmdai::executor::executing] && $::vmdai::executor::executing}]
}

# One event: tool_start goes to the executor (held back while model Tcl is
# running, e.g. when it calls update or vwait); everything else to the panel.
proc ::vmdai::bridge::_dispatch {ev} {
    variable deferred
    set role ""
    catch {set role [dict get $ev role]}
    if {$role eq "tool_start"} {
        if {[_executing] || [llength $deferred]} {
            _defer $ev
            return
        }
        ::vmdai::executor::run $ev
        return
    }
    if {[catch {::vmdai::ui::render_event $ev} err]} {
        _log "render_event: $err"
    }
    _check_end $ev
}

proc ::vmdai::bridge::_defer {ev} {
    variable deferred
    variable drain_timer
    lappend deferred $ev
    if {$drain_timer eq ""} {
        set drain_timer [::vmdai::sched::after 20 ::vmdai::bridge::_drain]
    }
}

proc ::vmdai::bridge::_drain {} {
    variable deferred
    variable drain_timer
    set drain_timer ""
    if {[_executing]} {
        set drain_timer [::vmdai::sched::after 20 ::vmdai::bridge::_drain]
        return
    }
    set batch $deferred
    set deferred {}
    foreach ev $batch {
        if {[catch {::vmdai::executor::run $ev} err]} {
            _log "executor::run failed: $::errorInfo"
        }
    }
}

# v1 end of a request: the final assistant/message, an error event, or the
# `cancelled` lifecycle event.
proc ::vmdai::bridge::_check_end {ev} {
    variable request_id
    set role [_dget $ev role ""]
    set type [_dget $ev type ""]
    set text [_dget $ev text ""]
    set rid ""
    catch {set rid [dict get $ev metadata request_id]}
    set ends [expr {($role eq "assistant" && $type eq "message") || $role eq "error"
        || ($role eq "system" && $type eq "lifecycle" && $text eq "cancelled")}]
    if {!$ends} {
        return
    }
    if {$rid eq "" || $rid eq "null"} {
        set rid $request_id
    }
    _request_ended $rid
}

# --- connection state (P06-T06 contract) --------------------------------------

proc ::vmdai::bridge::_on_runtime_state {old new detail} {
    variable ready_timer
    switch -- $new {
        ready {
            ::vmdai::sched::cancel $ready_timer
            set ready_timer [::vmdai::sched::after 0 ::vmdai::bridge::_after_ready]
        }
        stopped {
            _reset_session
        }
        default {
            _stop_pump
        }
    }
}

# Runs after the state machine finished its transition (and any recover).
proc ::vmdai::bridge::_after_ready {} {
    variable ready_timer
    variable session_id
    variable op_busy
    variable busy
    variable reconcile_pending
    set ready_timer ""
    if {![_runtime_ready] || $op_busy} {
        return
    }
    if {$session_id eq ""} {
        start_session
        return
    }
    if {$busy} {
        set reconcile_pending 1
    }
    _schedule_poll 0
}

# Busy after a reconnect (spec 2c): once the events are drained, a request
# the runtime no longer runs is ended locally.
proc ::vmdai::bridge::_reconcile {} {
    variable busy
    variable request_id
    if {!$busy} {
        return
    }
    ::vmdai::net::call runtime.info {} [list ::vmdai::bridge::_on_info $request_id]
}

proc ::vmdai::bridge::_on_info {rid kind args} {
    variable busy
    variable request_id
    note_outcome runtime.info $kind {*}$args
    if {$kind ne "ok" || !$busy || $request_id ne $rid} {
        return
    }
    set active ""
    catch {set active [dict get [lindex $args 0] active_request request_id]}
    if {$active eq $rid} {
        return
    }
    _request_ended $rid
    if {[catch {::vmdai::ui::notify info "Request ended (details may be missing)."} err]} {
        _log "ui: $err"
    }
}

proc ::vmdai::bridge::_reset_session {} {
    variable session_id
    variable session_token
    variable chat_id
    variable after_seq
    variable polling
    variable deferred
    variable drain_timer
    variable op_busy
    variable op_queue
    variable recovering
    variable reconcile_pending
    variable request_id
    variable ready_timer
    variable recover_timer
    variable recover_retries
    _stop_pump
    ::vmdai::sched::cancel $drain_timer
    ::vmdai::sched::cancel $ready_timer
    ::vmdai::sched::cancel $recover_timer
    _request_ended $request_id
    set drain_timer ""
    set ready_timer ""
    set recover_timer ""
    set recover_retries 0
    set session_id ""
    set session_token ""
    set chat_id ""
    set after_seq 0
    set polling 0
    set deferred {}
    set op_busy 0
    set op_queue {}
    set recovering 0
    set reconcile_pending 0
    catch {::vmdai::net::configure -session_id "" -session_token ""}
}

# ::vmdai::stop: end the session (an attached runtime keeps running and must
# release the chat lock), then forget it. With -sync, an attached runtime
# gets a synchronous session.stop (at most 500 ms), because cleanup resets
# every http token before an async request would be written.
proc ::vmdai::bridge::shutdown {args} {
    variable session_id
    variable drain_timer
    variable ready_timer
    set sync [expr {[lsearch -exact $args -sync] >= 0}]
    if {$session_id ne ""} {
        set owned 1
        catch {set owned [dict get [::vmdai::runtime::info] owned]}
        if {$sync && !$owned} {
            _stop_pump
            ::vmdai::sched::cancel $drain_timer
            set drain_timer ""
            ::vmdai::sched::cancel $ready_timer
            set ready_timer ""
            catch {::vmdai::net::bump_epoch}
            catch {::vmdai::net::call_sync session.stop {} -timeout 500}
        } else {
            catch {::vmdai::net::call session.stop {} ::vmdai::bridge::_ignore}
        }
    }
    _reset_session
}

# --- working directory (spec 2d) ----------------------------------------------

proc ::vmdai::bridge::_workdir_file {} {
    return [file join [::vmdai::config::home] .vmdai last_workdir.txt]
}

# The folder from last time, else VMD's current directory.
proc ::vmdai::bridge::_load_workdir {} {
    variable workdir
    set dir ""
    catch {
        set fh [open [_workdir_file] r]
        fconfigure $fh -encoding utf-8
        set dir [string trim [read $fh]]
        close $fh
    }
    if {$dir ne "" && [file isdirectory $dir] && ![catch {cd $dir}]} {
        set workdir [file normalize $dir]
        return
    }
    set workdir [pwd]
}

# Apply a folder: cd VMD there (model Tcl resolves relative paths against
# VMD's cwd), remember it, and tell the runtime (save_path resolves against
# the session cwd). Returns 1 on success.
proc ::vmdai::bridge::apply_workdir {dir} {
    variable workdir
    set dir [file normalize $dir]
    if {![file isdirectory $dir] || [catch {cd $dir} err]} {
        if {[catch {::vmdai::ui::notify error "Can't use the folder $dir."} err]} {
            _log "ui: $err"
        }
        return 0
    }
    set workdir $dir
    catch {
        set path [_workdir_file]
        file mkdir [file dirname $path]
        set fh [open $path w]
        fconfigure $fh -encoding utf-8
        puts -nonewline $fh $dir
        close $fh
    }
    _send_cwd
    return 1
}

proc ::vmdai::bridge::_send_cwd {} {
    variable session_id
    variable workdir
    if {$session_id eq "" || $workdir eq ""} {
        return
    }
    ::vmdai::net::call session.set_cwd [list cwd s $workdir] \
        [list ::vmdai::bridge::_relay session.set_cwd ""]
}

# --- other RPCs the M1 panel uses ----------------------------------------------

proc ::vmdai::bridge::history_list {callback} {
    ::vmdai::net::call chat.history.list [list offset i 0 limit i 50] \
        [list ::vmdai::bridge::_relay chat.history.list $callback]
}

proc ::vmdai::bridge::history_get {target callback} {
    ::vmdai::net::call chat.history.get [list chat_id s $target limit i 200] \
        [list ::vmdai::bridge::_relay chat.history.get $callback]
}

# M1 Apply: provider.set {provider, model}, no profile (spec 2h).
proc ::vmdai::bridge::set_provider {provider model {callback ""}} {
    ::vmdai::net::call provider.set [list provider s $provider model s $model] \
        [list ::vmdai::bridge::_relay provider.set $callback]
}

if {[llength [info commands ::vmdai::runtime::subscribe]]} {
    ::vmdai::runtime::subscribe ::vmdai::bridge::_on_runtime_state
}
