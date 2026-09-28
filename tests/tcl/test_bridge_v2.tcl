# P09-T07: event_protocol 2, long-poll, runtime-state wiring, NO_MODEL,
# history replay and a runtime restart while Settings is open. Runs under Tk
# because the wiring under test ends in the panel's Tk components; the
# transport is the harness's recording fake.
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
source [file join $env(VMDAI_PLUGIN_DIR) ui.tcl]
::harness::stub_desktop
proc ::vmdai::runtime::state {} { return $::harness::runtime_state }
proc ::vmdai::runtime::info {} {
    return [dict create host 127.0.0.1 port 18765 pid 4242 version 0.3.0 protocol 2 \
        launch_token feedfacefeedfacefeedfacefeedface owned 0]
}

namespace eval ::test {
    variable ops {}
    variable modes {}
    variable status {}
    variable banner {}
}
# Record what reaches the components without replacing them.
proc ::test::record_ops {cmd op} { lappend ::test::ops {*}[lindex $cmd 1] }
proc ::test::record_mode {cmd op} { lappend ::test::modes [lindex $cmd 1] }
proc ::test::record_status {cmd op} { lappend ::test::status [lindex $cmd 1] }
trace add execution ::vmdai::transcript::apply_ops enter ::test::record_ops
trace add execution ::vmdai::composer::set_mode enter ::test::record_mode
trace add execution ::vmdai::statusbar::update enter ::test::record_status
proc ::vmdai::banner::on_runtime_state {old new detail} {
    lappend ::test::banner [list $old $new $detail]
}
proc ::test::kinds {} {
    set out {}
    foreach op $::test::ops { lappend out [lindex $op 0] }
    return $out
}

set ::SESSION [dict create session_id sess_1 session_token tok_1 event_protocol 2 \
    capabilities [dict create long_poll true] chat_id null defaults {} provider ollama \
    agent_loop true runtime [dict create version 0.3.0 pid 4242] \
    profile [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b options {}]]
set ::INFO [dict create version 0.3.0 protocol 2 pid 4242 provider ollama model qwen3.8:27b \
    agent_loop true vision true tools {run_vmd_command capture_vmd_snapshot} rag false wiki false \
    max_turns 28 log_path /tmp/runtime.log settings_source file first_run [dict create servers {}]]
set ::PROFILES [dict create active qwen settings_source file profiles [dict create \
    qwen [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b options {}]]]

proc ::test::reset {} {
    ::vmdai::sched::teardown
    set ::harness::runtime_state ready
    ::harness::fresh_panel
    ::fake::reply chat.events.poll hold
    ::fake::reply runtime.info ok $::INFO
    ::fake::reply profiles.list ok $::PROFILES
    ::fake::reply settings.set ok {ok true settings {} persisted {reasoning_visible true wiki_enabled false}}
    ::fake::reply session.set_cwd ok [dict create ok true cwd [pwd]]
    set ::test::ops {}
    set ::test::modes {}
    set ::test::status {}
    set ::test::banner {}
}
proc ::test::start {session} {
    ::test::reset
    ::fake::reply session.start ok $session
    ::vmdai::bridge::start_session
    ::harness::wait_until {expr {[::fake::count chat.events.poll] > 0}} 3000
}
proc ::test::event {role type text metadata} {
    return [dict create seq 1 ts 1790000000 role $role type $type text $text metadata $metadata]
}
# The index of the last ::fake::calls entry for `method`, or -1.
proc ::test::last_index {method} {
    set idx -1
    for {set i 0} {$i < [llength $::fake::calls]} {incr i} {
        if {[lindex $::fake::calls $i 0] eq $method} { set idx $i }
    }
    return $idx
}

test v2-event_protocol_2_negotiated {session.start asks for event_protocol 2 with the launch token} -body {
    ::test::start $::SESSION
    set p [lindex [::fake::calls_of session.start] 0]
    list [::fake::param $p event_protocol] [expr {[::fake::param $p launch_token] ne ""}] \
        [::fake::has_param $p vmd_env] $::vmdai::bridge::event_protocol $::vmdai::bridge::negotiated
} -result {2 1 1 2 2}

test v2-long_poll_used {with long_poll the poll waits up to 2000 ms; without, the M1 short-poll stays} -body {
    ::test::start $::SESSION
    set p [::fake::last chat.events.poll]
    set r [list [::fake::param $p wait_ms] [::fake::timeout_of chat.events.poll] [::vmdai::bridge::poll_delay_ms]]
    ::test::start [dict replace $::SESSION capabilities {}]
    set p [::fake::last chat.events.poll]
    lappend r [::fake::has_param $p wait_ms] [::fake::timeout_of chat.events.poll] \
        [expr {[::vmdai::bridge::poll_delay_ms] == $::vmdai::config::poll_ms}]
} -result {2000 5000 20 0 3000 1}

test v2-runtime_state_to_banner_and_local_events {runtime states drive the banner, the status bar and one local event per notice} -body {
    ::test::reset
    # The state machine updates its state before it tells subscribers.
    set ::harness::runtime_state reconnecting
    ::vmdai::panel::on_runtime_state ready reconnecting "Nothing answered on 127.0.0.1:18765"
    set ::vmdai::ui::seen_ready 1
    ::vmdai::ui::notify warn "Connection lost"
    set ::harness::runtime_state ready
    set connection {}
    foreach d $::test::status {
        if {[dict exists $d connection]} { lappend connection [dict get $d connection] }
    }
    list [lindex $::test::banner end] [expr {"reconnecting" in $connection}] \
        [expr {"notice" in [::test::kinds]}] [lindex $::test::modes end]
} -result [list [list ready reconnecting "Nothing answered on 127.0.0.1:18765"] 1 1 disabled]

# I1: a refused send (no session yet) must not clear the draft, rename the
# chat or join recall - only bridge::send's return value decides that.
test v2-refused_send_keeps_draft {a refused send keeps the draft, the title and recall untouched} -body {
    ::test::reset
    set ::vmdai::bridge::session_id ""
    ::vmdai::composer::set_text "hello"
    set sent [::vmdai::panel::on_send]
    list $sent [::vmdai::composer::get_text] [::fake::count chat.send] $::vmdai::panel::title \
        $::vmdai::composer::recall [lindex $::harness::flashes end]
} -result {0 hello 0 {New chat} {} {Not connected to the AI runtime yet; try again in a moment.}}

# I1: chat.send never answering (a transport failure) must show the same
# "Message not sent" card as an rpc_error, and restore the draft.
test v2-send_transport_failure_restores_draft {a transport failure on chat.send shows Message not sent and restores the draft} -body {
    ::test::start $::SESSION
    set ::test::ops {}
    ::fake::reply chat.send transport timeout
    ::vmdai::composer::set_text "hello"
    ::vmdai::panel::on_send
    ::harness::wait_until {expr {"error.card" in [::test::kinds]}}
    set card [lindex $::test::ops [lsearch -index 0 $::test::ops error.card]]
    list [lindex $card 1] [lindex $card 2] [::vmdai::composer::get_text] [dict get [::vmdai::bridge::state] busy]
} -result {transport {Message not sent} hello 0}

# I1: a failed session.start must be visible, not swallowed by local.connection's de-dup.
test v2-session_start_failure_noted {a failed session.start is shown as one timeline note} -body {
    ::test::reset
    ::fake::reply session.start rpc_error AUTH_FAILED "invalid session or token" {}
    ::vmdai::bridge::start_session
    ::harness::wait_until {expr {[llength $::test::ops] > 0}}
    set note [lindex $::test::ops [lsearch -index 0 $::test::ops notice]]
    list [lindex $note 0] [string match "*Could not start a chat session: invalid session or token*" [lindex $note 2]]
} -result {notice 1}

test v2-no_model_card {chat.send NO_MODEL shows the card, keeps the draft and never goes busy} -body {
    ::test::start $::SESSION
    set ::test::ops {}
    ::fake::reply chat.send rpc_error NO_MODEL "No model configured" {}
    ::vmdai::composer::set_text "hello"
    ::vmdai::panel::on_send
    ::harness::wait_until {expr {"error.card" in [::test::kinds]}}
    set card [lindex $::test::ops [lsearch -index 0 $::test::ops error.card]]
    list [lindex $card 1] [lindex $::test::modes end] [dict get [::vmdai::bridge::state] busy] \
        [::vmdai::composer::get_text]
} -result {NO_MODEL nomodel 0 hello}

test v2-request_finished_ends_busy {only request.finished ends a v2 request; per-turn messages do not} -body {
    ::test::start $::SESSION
    set ::vmdai::bridge::busy 1
    set ::vmdai::bridge::request_id req_abc
    ::vmdai::panel::set_busy 1
    ::vmdai::bridge::route_display_event [::test::event assistant message "Loaded." \
        [dict create v 2 request_id req_abc turn 1 final false]]
    set mid [dict get [::vmdai::bridge::state] busy]
    ::vmdai::bridge::route_display_event [::test::event system state "" [dict create v 2 \
        kind request.finished request_id req_abc status complete wrapped_up false turns 1 \
        tool_calls 0 final_text_empty false duration_ms 900 usage {} error null run_dir ""]]
    list $mid [dict get [::vmdai::bridge::state] busy] [dict get [::vmdai::bridge::state] request_id] \
        [lindex $::test::modes end]
} -result {1 0 {} idle}

test v2-resume_replays_history {New chat shows the empty state; resume replays the display log, closes an unfinished request and rebuilds recall and the .tcl ledger} -body {
    ::test::start $::SESSION
    ::vmdai::panel::on_event [::test::event user message "Hello" [dict create request_id req_0]]
    set before_new [::vmdai::transcript::empty_state_shown]
    # The bridge's own new_chat is plan 06's and not under test here.
    proc ::vmdai::bridge::new_chat {args} {}
    ::vmdai::panel::new_chat
    set after_new [::vmdai::transcript::empty_state_shown]
    set events [list \
        [::test::event user message "Load 1hck" [dict create request_id req_1]] \
        [::test::event system state "" [dict create v 2 kind request.started request_id req_1 \
            chat_id chat_000000000001 provider ollama model qwen3.8:27b max_turns 28 vision true think true]] \
        [::test::event system state "" [dict create v 2 kind tool.started request_id req_1 turn 1 \
            call_key 0123456789ab tool_call_id call_1 tool_name run_vmd_command executor tcl origin model \
            input [dict create command "mol new 1hck.pdb" rationale "Load it"]]] \
        [::test::event system state "" [dict create v 2 kind tool.finished request_id req_1 \
            call_key 0123456789ab tool_name run_vmd_command executor tcl ok true executed yes output 0 \
            error "" truncated false duration_ms 40 statements [dict create total 1 applied 1 failed null] \
            blocked null output_path null output_bytes 1 image null saved_path null late false]] \
        [::test::event assistant message "Loaded 1hck." [dict create v 2 request_id req_1 turn 1 final true]] \
        [::test::event system state "" [dict create v 2 kind request.finished request_id req_1 \
            status complete wrapped_up false turns 2 tool_calls 1 final_text_empty false \
            duration_ms 3000 usage {} error null run_dir ""]] \
        [::test::event user message "Now color it" [dict create request_id req_2]] \
        [::test::event system state "" [dict create v 2 kind request.started request_id req_2 \
            chat_id chat_000000000001 provider ollama model qwen3.8:27b max_turns 28 vision true think true]]]
    ::fake::reply chat.history.get ok [dict create chat_id chat_000000000001 \
        manifest [dict create title "CDK2 view"] events $events]
    ::vmdai::bridge::replay_history chat_000000000001
    ::harness::wait_until {expr {$::vmdai::panel::replayed eq "chat_000000000001"}}
    set text [$::vmdai::panel::text get 1.0 end]
    list $before_new $after_new [string match "*Load 1hck*" $text] [string match "*Loaded 1hck.*" $text] \
        [string match "*Now color it*" $text] [string match "*Hello*" $text] $::vmdai::panel::title \
        [::fake::param [::fake::last chat.history.get] chat_id] $::vmdai::panel::replay_synthetic \
        $::vmdai::panel::replaying [::vmdai::transcript::empty_state_shown] $::vmdai::composer::recall \
        [string match "*mol new 1hck.pdb*" [::vmdai::tclexport::chat_tcl]]
} -result {0 1 1 1 1 0 {CDK2 view} chat_000000000001 local.request_ended 0 0 {{Load 1hck} {Now color it}} 1}

test v2-settings_after_restart {Settings reloads from the new (post-recover) runtime, not from on_runtime_state, and Save works} -body {
    ::test::start $::SESSION
    set ::vmdai::bridge::chat_id chat_000000000001
    ::fake::reply profiles.list hold
    ::fake::reply models.list ok {models {} source server}
    ::fake::reply keys.test ok {ok false message {key missing} source none}
    ::vmdai::settings::open
    ::harness::settle
    # ::fake::held also holds the session's own chat.events.poll long-poll;
    # only the Settings dialog's own profiles.list matters here.
    set held_profiles [lsearch -all -inline -index 0 $::fake::held profiles.list]
    set held [llength $held_profiles]
    set before_ready [::fake::count profiles.list]
    # I2: a runtime-state transition alone must not reload Settings (it would
    # still be using the old session and token); only on_recovered does.
    set ::harness::runtime_state reconnecting
    ::vmdai::panel::on_runtime_state ready reconnecting ""
    set ::harness::runtime_state ready
    ::vmdai::panel::on_runtime_state reconnecting ready ""
    set at_ready [::fake::count profiles.list]
    ::fake::reply profiles.list ok $::PROFILES
    ::fake::reply session.start ok [dict replace $::SESSION session_id sess_2]
    ::fake::reply chat.resume ok {chat_id chat_000000000001 last_seq 0}
    ::vmdai::bridge::recover
    set loaded [::harness::wait_until {expr {$::vmdai::settings::v(profile) eq "qwen"}}]
    set resume_before_reload [expr {[::test::last_index chat.resume] < [::test::last_index profiles.list]}]
    # The old runtime's profiles.list answer arrives late: it is dropped.
    lassign [lindex $held_profiles 0] method callback
    uplevel #0 [list {*}$callback ok [dict create active old settings_source file profiles \
        [dict create old [dict create provider ollama base_url http://127.0.0.1:1 model x options {}]]]]
    set kept [list $::vmdai::settings::v(profile) [dict exists $::vmdai::settings::profiles old]]
    ::fake::reply provider.set ok {ok true}
    ::vmdai::settings::save
    ::harness::wait_until {expr {![winfo exists .vmd_ai_settings]}}
    list $held [expr {$at_ready == $before_ready}] $loaded $resume_before_reload $kept \
        [::fake::param [::fake::last provider.set] profile]
} -result {1 1 1 1 {qwen 0} qwen}

cleanupTests
