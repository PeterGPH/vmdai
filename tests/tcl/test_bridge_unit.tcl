# tests/tcl/test_bridge_unit.tcl - bridge.tcl (P06-T07): session.start,
# the poll pump, routing, request state, resume/recover and the working
# directory. net::call is faked: it records {method params} and answers from
# ::replies(<method>) through net's own epoch check, one outcome per call
# (the last repeats); "hold" keeps a call in flight until `release`.
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
foreach m {config sched net runtime bridge} { source [file join $plugin $m.tcl] }
set ::vmdai::config::poll_ms 400

# --- fakes --------------------------------------------------------------------
set ::calls {}
array set ::replies {}
array set ::held {}
proc ::vmdai::net::call {method params callback args} {
    lappend ::calls [list $method $params]
    set outcome [list ok {}]
    if {[info exists ::replies($method)] && [llength $::replies($method)]} {
        set outcome [lindex $::replies($method) 0]
        if {[llength $::replies($method)] > 1} {
            set ::replies($method) [lrange $::replies($method) 1 end]
        }
    }
    if {$outcome eq "hold"} {
        lappend ::held($method) [list [::vmdai::net::epoch] $callback]
        return rpc#fake
    }
    ::vmdai::sched::after 0 [list ::vmdai::net::_deliver_if_current \
        [::vmdai::net::epoch] $callback {*}$outcome]
    return rpc#fake
}
proc release {method outcome} {
    set item [lindex $::held($method) 0]
    set ::held($method) [lrange $::held($method) 1 end]
    lassign $item epoch callback
    ::vmdai::net::_deliver_if_current $epoch $callback {*}$outcome
}
proc calls {method} {
    set out {}
    foreach c $::calls { if {[lindex $c 0] eq $method} { lappend out [lindex $c 1] } }
    return $out
}
proc param {params name} {
    foreach {n t v} $params { if {$n eq $name} { return $v } }
    return "<none>"
}

set ::rt_state ready
set ::token [string repeat a 32]
proc ::vmdai::runtime::state {} { return $::rt_state }
proc ::vmdai::runtime::info {} {
    return [dict create host 127.0.0.1 port 1 pid 7 version 0.3.0 protocol 2 \
        launch_token $::token owned 0]
}
proc ::vmdai::runtime::on_transport_error {reason} { lappend ::transport_errors $reason }
proc ::vmdai::runtime::on_transport_ok {} { incr ::oks }
proc ::vmdai::runtime::on_auth_failed {} { incr ::auth_failed }

namespace eval ::vmdai::ui {}
proc ::vmdai::ui::render_event {ev} { lappend ::rendered [dict get $ev seq] }
proc ::vmdai::ui::notify {level text} { lappend ::notices [list $level $text] }
proc ::vmdai::ui::set_busy {on} { lappend ::busy_calls $on }
proc ::vmdai::ui::status {text} { lappend ::statuses $text }
namespace eval ::vmdai::executor { variable executing 0 }
proc ::vmdai::executor::run {ev} { lappend ::executed [dict get $ev metadata call_key] }
proc ::vmdai::executor::reset {} {}
proc ::vmdai::executor::note_cancelled {rid} { lappend ::cancelled $rid }

proc settle {{ms 30}} {
    set ::_settled 0
    after $ms {set ::_settled 1}
    vwait ::_settled
}
proc fresh {} {
    ::vmdai::bridge::_reset_session
    ::vmdai::sched::teardown
    set ::vmdai::bridge::workdir ""
    set ::vmdai::bridge::finished {}
    set ::vmdai::executor::executing 0
    set ::rt_state ready
    foreach v {calls transport_errors rendered notices busy_calls statuses executed cancelled} {
        set ::$v {}
    }
    set ::oks 0
    set ::auth_failed 0
    array unset ::replies
    array unset ::held
    set ::replies(chat.events.poll) [list [list ok {events {} last_seq 0 has_more false}]]
}
# Start session sess_1 (chat null, as a token session gets it).
proc started {} {
    set ::replies(session.start) [list [list ok [dict create session_id sess_1 \
        session_token tok_1 chat_id null event_protocol 1]]]
    ::vmdai::bridge::start_session
    settle
}
proc ev {seq role type {text x} {md {}}} {
    return [dict create seq $seq role $role type $type text $text metadata $md]
}
proc st {key} { dict get [::vmdai::bridge::state] $key }

# --- tests --------------------------------------------------------------------

test bridge-start-1 {session.start carries the launch token, event_protocol 1 and vmd_env (C6)} -setup fresh -body {
    proc ::vmdinfo {what} {
        switch -- $what { version { return 1.9.4a57 } arch { return MACOSXARM64 } }
    }
    started
    rename ::vmdinfo {}
    set body [::vmdai::net::decode [::vmdai::net::encode_params [lindex [calls session.start] 0]]]
    list [dict get $body launch_token] [dict get $body event_protocol] \
        [dict exists $body session_id] [dict get $body vmd_env vmd_version] \
        [dict get $body vmd_env arch] \
        [expr {[dict get $body vmd_env tcl_patchlevel] eq [info patchlevel]}] \
        [dict exists $body vmd_env tk_patchlevel] [st session_id] [st chat_id] \
        [::vmdai::net::configure]
} -cleanup fresh -result [list [string repeat a 32] 1 0 1.9.4a57 MACOSXARM64 1 0 sess_1 {} \
    {-base_url {} -session_id sess_1 -session_token tok_1}]

test bridge-poll-bad-1 {an undecodable or malformed poll reply is a transport error; after_seq stays} -setup fresh -body {
    set ::replies(chat.events.poll) [list \
        [list ok [dict create events [list [ev 1 assistant chunk]] has_more true]] \
        {transport {undecodable response: unexpected character}} \
        {ok {has_more false}}]
    started
    set first [list [st after_seq] $::transport_errors]
    ::vmdai::bridge::_on_runtime_state reconnecting ready ""
    settle
    list $first [st after_seq] $::transport_errors $::rendered
} -cleanup fresh -result {{1 {{undecodable response: unexpected character}}} 1 {{undecodable response: unexpected character} {malformed poll result}} 1}

test bridge-poll-more-1 {has_more re-polls at once; after_seq advances per event} -setup fresh -body {
    set a {}
    for {set s 1} {$s <= 80} {incr s} { lappend a [ev $s assistant chunk] }
    set b {}
    for {set s 81} {$s <= 100} {incr s} { lappend b [ev $s assistant chunk] }
    set ::replies(chat.events.poll) [list [list ok [dict create events $a has_more true]] \
        [list ok [dict create events $b has_more false]] {ok {events {} has_more false}}]
    started
    settle 100
    set seqs {}
    foreach p [calls chat.events.poll] { lappend seqs [param $p after_seq] }
    list $seqs [llength $::rendered] [st after_seq] [param [lindex [calls chat.events.poll] 0] limit]
} -cleanup fresh -result {{0 80} 100 100 80}

test bridge-defer-1 {tool_start waits while the executor runs model Tcl, then runs once} -setup fresh -body {
    set ::vmdai::executor::executing 1
    set ::replies(chat.events.poll) [list [list ok [dict create has_more false events [list \
        [ev 1 assistant chunk] [ev 2 tool_start message x {call_key k1 request_id req_1}] \
        [ev 3 assistant chunk]]]] {ok {events {} has_more false}}]
    started
    settle 60
    set during [list $::executed $::rendered]
    set ::vmdai::executor::executing 0
    settle 60
    list $during $::executed $::rendered
} -cleanup fresh -result {{{} {1 3}} k1 {1 3}}

test bridge-busy-1 {busy starts only after chat.send answers; a failed send never goes busy} -setup fresh -body {
    started
    set ::replies(chat.send) [list hold]
    set issued [::vmdai::bridge::send "now color it red"]
    set before [list [st busy] $::busy_calls]
    release chat.send {ok {request_id req_1 chat_id chat_0123456789ab}}
    set after [list [st busy] $::busy_calls [st request_id] [st chat_id]]
    set sent [lindex [calls chat.send] 0]
    set ::vmdai::bridge::busy 0
    set ::vmdai::bridge::request_id ""
    set ::busy_calls {}
    set ::replies(chat.send) [list {rpc_error NO_MODEL {No model configured.} {}}]
    ::vmdai::bridge::send "hello"
    settle
    list $issued $before $after [param $sent text] [param $sent conversation_mode] \
        [param $sent model] [st busy] $::busy_calls [lindex $::notices end]
} -cleanup fresh -result {1 {0 {}} {1 1 req_1 chat_0123456789ab} {now color it red} full <none> 0 0 {error {Could not send: No model configured.}}}

test bridge-busy-2 {a request that ended before chat.send answered does not leave the panel busy} -setup fresh -body {
    started
    set ::replies(chat.send) [list hold]
    ::vmdai::bridge::send "hi"
    ::vmdai::bridge::_dispatch [ev 9 assistant message done {request_id req_7}]
    release chat.send {ok {request_id req_7}}
    list [st busy] $::busy_calls
} -cleanup fresh -result {0 {}}

test bridge-end-1 {v1 ends a request on the final message, an error or a cancelled lifecycle} -setup fresh -body {
    set r {}
    foreach e [list [ev 1 assistant chunk x {request_id req_1}] \
            [ev 2 assistant message x {request_id req_1}] [ev 3 error message x {}] \
            [ev 4 system lifecycle cancelled {request_id req_1}] \
            [ev 5 system lifecycle chat_resumed {request_id req_1}]] {
        set ::vmdai::bridge::busy 1
        set ::vmdai::bridge::request_id req_1
        ::vmdai::bridge::_dispatch $e
        lappend r [st busy]
    }
    set r
} -cleanup fresh -result {1 0 0 0 1}

test bridge-reconcile-1 {after a reconnect, busy with no active request goes idle with one note} -setup fresh -body {
    started
    set ::replies(chat.send) [list {ok {request_id req_1}}]
    ::vmdai::bridge::send "long job"
    settle
    set ::replies(runtime.info) [list {ok {version 0.3.0 active_request null}}]
    ::vmdai::bridge::_on_runtime_state reconnecting ready ""
    settle 60
    list [st busy] [llength [calls runtime.info]] $::notices [lindex $::busy_calls end]
} -cleanup fresh -result {0 1 {{info {Request ended (details may be missing).}}} 0}

test bridge-reconcile-2 {a request the runtime still runs stays busy} -setup fresh -body {
    started
    set ::replies(chat.send) [list {ok {request_id req_1}}]
    ::vmdai::bridge::send "long job"
    settle
    set ::replies(runtime.info) [list {ok {active_request {request_id req_1 turn 2}}}]
    ::vmdai::bridge::_on_runtime_state reconnecting ready ""
    settle 60
    list [st busy] [llength [calls runtime.info]] $::notices
} -cleanup fresh -result {1 1 {}}

test bridge-workdir-1 {apply_workdir cds VMD, remembers the folder and sends session.set_cwd} -setup fresh -body {
    started
    set dir [file join $::env(HOME) "my project"]
    file mkdir $dir
    set ok [::vmdai::bridge::apply_workdir $dir]
    settle
    set fh [open [file join $::env(HOME) .vmdai last_workdir.txt]]
    set saved [read $fh]
    close $fh
    set bad [::vmdai::bridge::apply_workdir [file join $::env(HOME) missing]]
    list $ok [expr {[pwd] eq [file normalize $dir]}] [expr {$saved eq [file normalize $dir]}] \
        [expr {[param [lindex [calls session.set_cwd] 0] cwd] eq [file normalize $dir]}] \
        $bad [lindex $::notices end 0]
} -cleanup fresh -result {1 1 1 1 0 error}

test bridge-race-1 {New Chat drops the old session's in-flight poll; after_seq restarts at 0} -setup fresh -body {
    set ::replies(chat.events.poll) [list hold]
    started
    set ::replies(session.start) [list [list ok [dict create session_id sess_2 \
        session_token tok_2 chat_id null]]]
    set ::replies(chat.events.poll) [list hold]
    ::vmdai::bridge::new_chat
    settle
    release chat.events.poll [list ok [dict create has_more false \
        events [list [ev 5 assistant chunk] [ev 6 assistant chunk]]]]
    settle
    list [st session_id] [st after_seq] $::rendered [llength [calls session.stop]] \
        [llength [calls chat.events.poll]]
} -cleanup fresh -result {sess_2 0 {} 1 2}

test bridge-resume-1 {resume: callback gets the net forms; success switches chat and after_seq} -setup fresh -body {
    started
    set ::replies(chat.resume) [list {rpc_error CHAT_LOCKED {chat is locked} {}} \
        {ok {chat_id chat_00000000000a last_seq 42}}]
    set ::got {}
    ::vmdai::bridge::resume chat_00000000000a [list apply {{args} {lappend ::got $args}}]
    settle
    ::vmdai::bridge::resume chat_00000000000a [list apply {{args} {lappend ::got [lindex $args 0]}}]
    settle
    list [lrange [lindex $::got 0] 0 1] [lindex $::got 1] [lindex $::notices 0] \
        [st chat_id] [st after_seq] [llength [calls session.set_cwd]]
} -cleanup fresh -result {{rpc_error CHAT_LOCKED} ok {error {This chat is open in another VMD window.}} chat_00000000000a 42 1}

test bridge-recover-1 {recover: new session with the token, chat.resume, the lost request reported} -setup fresh -body {
    started
    set ::vmdai::bridge::chat_id chat_00000000000b
    set ::vmdai::bridge::busy 1
    set ::vmdai::bridge::request_id req_9
    set ::replies(session.start) [list [list ok [dict create session_id sess_3 \
        session_token tok_3 chat_id null]]]
    set ::replies(chat.resume) [list {ok {chat_id chat_00000000000b last_seq 12}}]
    ::vmdai::bridge::recover
    settle 60
    list [st session_id] [st chat_id] [st after_seq] [st busy] $::statuses \
        [param [lindex [calls chat.resume] 0] chat_id] [llength [calls session.start]]
} -cleanup fresh -result {sess_3 chat_00000000000b 12 0 {{The request in progress was lost when the AI runtime restarted.}} chat_00000000000b 2}

test bridge-auth-1 {AUTH_FAILED on a poll asks the runtime to recover and stops the pump} -setup fresh -body {
    set ::replies(chat.events.poll) [list {rpc_error AUTH_FAILED {invalid session or token} {}}]
    started
    settle 100
    list $::auth_failed [llength [calls chat.events.poll]] $::vmdai::bridge::poll_timer
} -cleanup fresh -result {1 1 {}}

cleanupTests
