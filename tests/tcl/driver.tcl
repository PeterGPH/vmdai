# tests/tcl/driver.tcl - the real plugin under tclsh, attached to the runtime
# tests/test_bridge_integration.py serves (P06-T11; spec 6 Bridge
# integration). Not a tcltest file. Environment:
#   VMD_AI_ATTACH   127.0.0.1:<port>; the token file is under $HOME/.vmdai/run
#   VMDAI_SCENARIO  round_trip | cancel_before_ack | cancel_after_ack |
#                   has_more | restart | race (sources t_race.tcl)
#   VMDAI_OUT       the driver writes its findings here as one JSON object
#   VMDAI_SYNC      a directory for marker files shared with pytest
# The plugin's Tk panel is not loaded: its four sinks are recorded instead.

source [file join $env(VMDAI_PLUGIN_DIR) init.tcl]

# --- VMD stand-ins (this is tclsh, not VMD) -----------------------------------
set ::vmd_calls {}
proc ::mol {args} { lappend ::vmd_calls [concat mol $args]; return 0 }
proc ::display {args} { lappend ::vmd_calls [concat display $args]; return "" }
proc ::vmdinfo {what} { return driver-$what }
# render TachyonInternal <path>: an 8x6 uncompressed 24-bit TGA.
proc ::render {renderer path args} {
    lappend ::vmd_calls [list render $renderer]
    set fh [open $path w]
    fconfigure $fh -translation binary
    puts -nonewline $fh [binary format cccsscsssscc 0 0 2 0 0 0 0 0 8 6 24 0]
    for {set i 0} {$i < 48} {incr i} { puts -nonewline $fh [binary format ccc 40 80 200] }
    close $fh
    return ""
}

# --- panel sinks ----------------------------------------------------------------
set ::notices {}
set ::events {}
set ::statuses {}
set ::transitions {}
proc ::vmdai::ui::notify {level text} {
    lappend ::notices [list [clock milliseconds] $level $text [::vmdai::runtime::state]]
}
proc ::vmdai::ui::render_event {ev} { lappend ::events $ev }
proc ::vmdai::ui::set_busy {on} {}
proc ::vmdai::ui::status {text} { lappend ::statuses $text }
proc ::record_state {old new detail} {
    lappend ::transitions [list [clock milliseconds] $old $new]
}
::vmdai::runtime::subscribe ::record_state
# Count RPCs by method, and time every chat.events.poll call.
array set ::rpc_count {}
set ::poll_calls {}
proc ::count_rpc {cmd op} {
    set m [lindex $cmd 1]
    if {![info exists ::rpc_count($m)]} { set ::rpc_count($m) 0 }
    incr ::rpc_count($m)
    if {$m eq "chat.events.poll"} { lappend ::poll_calls [clock milliseconds] }
}
trace add execution ::vmdai::net::call enter ::count_rpc
# Time every chat.events.poll reply and whether it said has_more (Minor 8:
# a structural back-to-back-polls check instead of a wall-clock budget).
set ::poll_replies {}
trace add execution ::vmdai::bridge::_on_poll enter {apply {{cmd op} {
    set result [lindex $cmd 3]
    set has_more 0
    catch {set has_more [string is true -strict [dict get $result has_more]]}
    lappend ::poll_replies [list [clock milliseconds] $has_more]
}}}

# --- helpers --------------------------------------------------------------------
proc jstr {s} { return [::vmdai::net::json_string $s] }
proc jlist {items} {
    set out {}
    foreach item $items { lappend out [jstr $item] }
    return "\[[join $out ,]\]"
}
proc write_out {pairs} {
    set fh [open $::env(VMDAI_OUT) w]
    fconfigure $fh -encoding utf-8
    puts -nonewline $fh [::vmdai::net::encode_params $pairs]
    close $fh
}
proc fail {message} {
    write_out [list error s "$message\n$::errorInfo" notices j [jlist $::notices]]
    exit 3
}
proc bgerror {message} { fail "background error: $message" }
proc wait_for {script ms what} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { fail "timed out waiting for $what" }
        set ::_tick 0
        after 20 {set ::_tick 1}
        vwait ::_tick
    }
}
proc marker {name} { file join $::env(VMDAI_SYNC) $name }
proc touch {name} { close [open [marker $name] w] }
proc bstate {key} { dict get [::vmdai::bridge::state] $key }
# Events that end a v1 request (final message, error, cancelled lifecycle).
proc ends {} {
    set n 0
    foreach ev $::events {
        set role [dict get $ev role]
        set type [dict get $ev type]
        if {($role eq "assistant" && $type eq "message") || $role eq "error"
                || ($type eq "lifecycle" && [dict get $ev text] eq "cancelled")} { incr n }
    }
    return $n
}
proc connect {} {
    ::vmdai::runtime::ensure
    wait_for {expr {[::vmdai::runtime::state] eq "ready" && [bstate session_id] ne ""
        && !$::vmdai::bridge::op_busy}} 10000 "the session"
}
# Send a prompt and wait until its request ended and the panel is idle.
proc ask {text {ms 15000}} {
    set before [ends]
    if {![::vmdai::bridge::send $text]} { fail "send refused: [lindex $::notices end]" }
    wait_for [list expr "\[ends\] > $before && !\[bstate busy\]"] $ms "the answer to: $text"
}
proc chunks_text {} {
    set text ""
    foreach ev $::events {
        if {[dict get $ev type] eq "chunk"} { append text [dict get $ev text] }
    }
    return $text
}
proc roles {} {
    set out {}
    foreach ev $::events { lappend out "[dict get $ev role]/[dict get $ev type]" }
    return $out
}
proc record_acks {} {
    set ::acks {}
    trace add execution ::vmdai::executor::_on_ack enter {apply {{cmd op} {
        lappend ::acks "[lindex $cmd 3] [lindex $cmd 4]"
    }}}
}
proc common_out {} {
    set notes {}
    foreach n $::notices { lappend notes "[lindex $n 1] [lindex $n 2]" }
    set moves {}
    foreach t $::transitions { lappend moves "[lindex $t 1]>[lindex $t 2]" }
    return [list roles j [jlist [roles]] vmd_calls j [jlist $::vmd_calls] \
        notices j [jlist $notes] transitions j [jlist $moves] statuses j [jlist $::statuses] \
        queue i [::vmdai::net::result_queue_size] chat_id s [bstate chat_id] \
        session_starts i [expr {[info exists ::rpc_count(session.start)] ? $::rpc_count(session.start) : 0}]]
}

# --- scenarios --------------------------------------------------------------------

# One request with a Tcl command and a snapshot: ack, run, puts captured, post.
proc scenario_round_trip {} {
    record_acks
    connect
    ask "Load 1abc and take a snapshot"
    write_out [concat [common_out] [list acks j [jlist $::acks] text s [chunks_text] \
        ledger i [llength [::vmdai::executor::ledger]]]]
}

# Stop before the executor acked: the late ack gets proceed false, nothing runs.
proc scenario_cancel_before_ack {} {
    connect
    rename ::vmdai::executor::run ::real_executor_run
    set ::held {}
    proc ::vmdai::executor::run {ev} { lappend ::held $ev }
    set before [ends]
    ::vmdai::bridge::send "Load 1abc"
    wait_for {expr {[llength $::held] == 1}} 10000 "the tool_start"
    set cancel_sent [::vmdai::bridge::cancel]
    wait_for [list expr "\[ends\] > $before && !\[bstate busy\]"] 10000 "the stopped request"
    rename ::vmdai::executor::run {}
    rename ::real_executor_run ::vmdai::executor::run
    # Forget the local cancel note so the ack really goes to the runtime.
    ::vmdai::executor::reset
    record_acks
    ::vmdai::executor::run [lindex $::held 0]
    wait_for {expr {[llength $::acks] == 1}} 5000 "the late ack"
    write_out [concat [common_out] [list cancel_sent b $cancel_sent acks j [jlist $::acks]]]
}

# Stop while the command runs (it waits 800 ms in vwait): the result still
# arrives within the grace period and the request ends as stopped.
proc scenario_cancel_after_ack {} {
    set ::ran 0
    record_acks
    trace add execution ::vmdai::executor::exec_command enter {apply {{cmd op} {
        after 200 ::vmdai::bridge::cancel
    }}}
    connect
    set t0 [clock milliseconds]
    ask "Run the slow command" 20000
    write_out [concat [common_out] [list ran i $::ran acks j [jlist $::acks] \
        elapsed_ms i [expr {[clock milliseconds] - $t0}]]]
}

# The count of has_more:true replies, and the largest gap between one and
# the poll call that follows it (0 when there is none): proof of
# back-to-back draining that does not depend on wall-clock budgets.
proc more_gap_stats {} {
    set more_replies 0
    set max_gap 0
    foreach entry $::poll_replies {
        lassign $entry t has_more
        if {!$has_more} { continue }
        incr more_replies
        set next_call ""
        foreach ct $::poll_calls {
            if {$ct > $t} { set next_call $ct; break }
        }
        if {$next_call ne ""} {
            set gap [expr {$next_call - $t}]
            if {$gap > $max_gap} { set max_gap $gap }
        }
    }
    return [list $more_replies $max_gap]
}

# A long answer: has_more is drained with back-to-back polls.
proc scenario_has_more {} {
    connect
    ask "Tell me a long story"
    set chunk_ms {}
    foreach t $::chunk_times { lappend chunk_ms $t }
    lassign [more_gap_stats] more_replies more_gap_max_ms
    write_out [concat [common_out] [list text s [chunks_text] \
        polls i $::rpc_count(chat.events.poll) after_seq i [bstate after_seq] \
        drain_ms i [expr {[lindex $chunk_ms end] - [lindex $chunk_ms 0]}] \
        more_replies i $more_replies more_gap_max_ms i $more_gap_max_ms]]
}

# S3: pytest kills the runtime and restarts it on the same port with a new
# token. The plugin reconnects, starts a new session, resumes the chat, and
# the next chat.send works within 10 s of the restart.
proc scenario_restart {} {
    connect
    ask "Load 1abc"
    set chat [bstate chat_id]
    set old [bstate session_id]
    set ::notices {}
    set ::transitions {}
    touch ready_for_restart
    wait_for {file exists [marker restarted]} 20000 "pytest to restart the runtime"
    set t0 [clock milliseconds]
    wait_for [list expr "\[bstate session_id\] ne {$old} && \[bstate session_id\] ne {}
        && !\$::vmdai::bridge::op_busy"] 15000 "the recovered session"
    ask "Now color it red" 15000
    write_out [concat [common_out] [list chat_before s $chat \
        elapsed_ms i [expr {[clock milliseconds] - $t0}]]]
}

set ::chunk_times {}
rename ::vmdai::ui::render_event ::record_event
proc ::vmdai::ui::render_event {ev} {
    if {[dict get $ev type] eq "chunk"} { lappend ::chunk_times [clock milliseconds] }
    ::record_event $ev
}

set scenario $::env(VMDAI_SCENARIO)
if {$scenario eq "race"} {
    source [file join $::env(VMDAI_REPO) tests tcl t_race.tcl]
}
if {[catch {scenario_$scenario} err]} {
    fail $err
}
::vmdai::cleanup
exit 0
