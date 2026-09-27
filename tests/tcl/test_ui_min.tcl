# tests/tcl/test_ui_min.tcl - the M1 ui.tcl fixes (P06-T10). Runs under Tk
# (helpers.tk prelude). net::call is faked and records every call; the
# runtime is reported ready and the bridge has a session.
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
foreach m {config sched net runtime bridge executor ui} { source [file join $plugin $m.tcl] }

set ::calls {}
proc ::vmdai::net::call {method params callback args} {
    lappend ::calls [list $method $params]
    set result {}
    if {$method eq "chat.send"} { set result {request_id req_1} }
    ::vmdai::sched::after 0 [list ::vmdai::net::_deliver_if_current \
        [::vmdai::net::epoch] $callback ok $result]
    return rpc#fake
}
proc ::vmdai::runtime::state {} { return ready }
proc settle {{ms 30}} {
    set ::_settled 0
    after $ms {set ::_settled 1}
    vwait ::_settled
    # A process descheduled for longer than $ms sees this timer come due in
    # the same pass as the after-0 chain it waits for; finish what is due.
    update
}
proc param {params name} {
    foreach {n t v} $params { if {$n eq $name} { return $v } }
    return "<none>"
}
proc lines {} {
    set t $::vmdai::ui::transcript
    return [split [string trimright [$t get 1.0 end] "\n"] "\n"]
}
proc fresh {} {
    catch {destroy $::vmdai::ui::win}
    set ::vmdai::ui::stream_role ""
    set ::vmdai::ui::stream_request_id ""
    set ::vmdai::bridge::session_id sess_1
    set ::vmdai::bridge::busy 0
    set ::vmdai::bridge::request_id ""
    set ::calls {}
    ::vmdai::ui::show_panel
    ::vmdai::ui::_clear_transcript
}
proc ev {role type text {rid req_1}} {
    return [dict create seq 1 role $role type $type text $text metadata [dict create request_id $rid]]
}

test ui-block-1 {a block closes on every role change: no glued lines} -setup fresh -body {
    foreach e [list [ev assistant chunk "Loading "] [ev assistant chunk "the file."] \
            [ev tool_result message "ok: 1 molecule"] [ev assistant chunk "Done"] \
            [ev reasoning chunk "thinking"] [ev assistant message "Done" req_1]] {
        ::vmdai::ui::render_event $e
    }
    ::vmdai::ui::notify warn "Lost the connection to the AI runtime; reconnecting."
    lines
} -result {{ASSISTANT: Loading the file.} {TOOL_RESULT: ok: 1 molecule} {ASSISTANT: Done} {REASONING: thinking} {Lost the connection to the AI runtime; reconnecting.}}

test ui-notify-1 {notify adds exactly one line, even for multi-line text} -setup fresh -body {
    set before [llength [lines]]
    ::vmdai::ui::notify error "The AI runtime didn't start:\nTraceback (most recent call last)"
    ::vmdai::ui::notify bogus "Reconnected to the AI runtime."
    set t $::vmdai::ui::transcript
    list [expr {[llength [lines]] - $before}] [lindex [lines] end-1] \
        [lsearch -inline [$t tag names end-2c] notice_*]
} -result {2 {The AI runtime didn't start: Traceback (most recent call last)} notice_info}

test ui-folder-1 {the folder label shows the folder the bridge applied} -setup fresh -body {
    set dir [file join $::env(HOME) "a project folder"]
    file mkdir $dir
    proc ::tk_chooseDirectory {args} [list return $dir]
    ::vmdai::ui::on_choose_folder
    set shown [$::vmdai::ui::workdir_label cget -text]
    set deep [file join $::env(HOME) [string repeat d 40] [string repeat e 40]]
    file mkdir $deep
    proc ::tk_chooseDirectory {args} [list return $deep]
    ::vmdai::ui::on_choose_folder
    set long [$::vmdai::ui::workdir_label cget -text]
    list [string match "*a project folder" $shown] [string range $long 0 2] \
        [string length $long] [string match *[string repeat e 40] $long] \
        [expr {[pwd] eq [file normalize $deep]}] [llength [lsearch -all -index 0 $::calls session.set_cwd]]
} -cleanup { rename ::tk_chooseDirectory {} } -result {1 ... 59 1 1 2}

test ui-dropdown-1 {the dropdown never feeds chat.send; Apply sends provider.set without a profile} -setup fresh -body {
    set ::vmdai::ui::provider ollama
    set picked $::vmdai::ui::model_name
    $::vmdai::ui::input insert 0 "color it red"
    ::vmdai::ui::on_send
    settle
    set send [lindex [lsearch -inline -index 0 $::calls chat.send] 1]
    ::vmdai::ui::on_apply_provider
    settle
    set apply [lindex [lsearch -inline -index 0 $::calls provider.set] 1]
    list $picked [param $send text] [param $send model] $apply [lindex [lines] 0]
} -result {llama3.1:8b {color it red} <none> {provider s ollama model s llama3.1:8b} {USER: color it red}}

test ui-busy-1 {Stop is enabled and Thinking shows only while the bridge says busy} -setup fresh -body {
    set w $::vmdai::ui::win
    set idle [list [$w.header.stop cget -state] [$w.input_row.send cget -state]]
    ::vmdai::ui::set_busy 1
    set busy [list [$w.header.stop cget -state] [$w.input_row.send cget -state] [lindex [lines] end]]
    ::vmdai::ui::set_busy 0
    set ticking 0
    foreach id [::vmdai::sched::pending] {
        if {[string match *_thinking_tick* [lindex $::vmdai::sched::timers($id) 1]]} { incr ticking }
    }
    list $idle $busy [lines] $ticking
} -result {{disabled normal} {normal disabled Thinking} {} 0}

test ui-close-1 {closing withdraws the window; show_panel brings the same one back} -setup fresh -body {
    ::vmdai::ui::on_close
    set hidden [list [winfo exists $::vmdai::ui::win] [wm state $::vmdai::ui::win]]
    set again [::vmdai::ui::show_panel]
    list $hidden $again [wm state $::vmdai::ui::win]
} -result {{1 withdrawn} .vmd_ai normal}

cleanupTests
