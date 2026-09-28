# tests/tcl/panel_harness.tcl - shared setup for the plan-09 Tk tests.
#
# Every tests/tcl/test_*.tcl file of plan 09 sources this first, after
# helpers.tk.run_tk_test has loaded VMD's Tk into tclsh 8.6 and withdrawn ".".
# It
#   * loads the vendored json 1.1.2 (and puts VMD's http 2.9.5 on the module
#     path in case net.tcl asks for it),
#   * sources the plugin modules the panel needs - not init.tcl, so nothing
#     launches or attaches to a runtime,
#   * keeps the panel and every dialog withdrawn (::vmdai::panel::headless),
#   * replaces ::vmdai::net::call with a recording fake (no sockets), and
#   * provides ::harness::fire: `event generate` does not reach widgets of
#     a never-mapped toplevel (VMD's Tk 8.6.12 on aqua), so bindings are run
#     through the widget's bindtags the way Tk dispatches them.
package require tcltest 2
namespace import -force ::tcltest::*

if {[info exists ::env(VMDAI_TCL_TM)] && $::env(VMDAI_TCL_TM) ne ""} {
    ::tcl::tm::path add $::env(VMDAI_TCL_TM)
}
lappend ::auto_path [file join $::env(VMDAI_PLUGIN_DIR) lib json]
package require -exact json 1.1.2

namespace eval ::harness {
    variable plugin $::env(VMDAI_PLUGIN_DIR)
    variable modules {config sched net runtime bridge executor theme viewmodel
        transcript viewer composer statusbar banner toolbar tclexport panel
        settings history}
    variable bridge_calls {}
    variable busy 0
    variable runtime_state ready
    variable resume_reply {ok {ok true chat_id chat_000000000001 title {Old chat}}}
    variable clipboard ""
    variable opened {}
    variable flashes {}
    variable settings_opened {}
    variable bgerrors {}
}
foreach ::harness::module $::harness::modules {
    set ::harness::path [file join $::harness::plugin $::harness::module.tcl]
    if {[file exists $::harness::path]} { source -encoding utf-8 $::harness::path }
}
# M3 (plan 10): no test reads the real OS appearance. With a MacWindowStyle
# command that does not exist, System resolves to light and Settings offers
# only Light and Dark; M3 tests install ::m3::mws when they need one.
set ::vmdai::theme::macstyle ::harness::no_macwindowstyle
# namespace eval, not `set`: before P09-T01 creates panel.tcl the namespace
# does not exist yet, and the fail-first run must reach the test bodies.
namespace eval ::vmdai::panel { variable headless 1 }

# ---- fake transport ------------------------------------------------------
namespace eval ::fake {
    variable calls {}
    variable held {}
    variable replies
    array set replies {}
}
proc ::fake::reset {} {
    variable calls {}
    variable held {}
    variable replies
    array unset replies
    array set replies {}
}
# ::fake::reply method form ?arg ...? sets how every later call of `method`
# answers, in the P06 callback forms:
#   ::fake::reply models.list ok {models {} source server}
#   ::fake::reply chat.resume rpc_error CHAT_LOCKED "locked" {}
#   ::fake::reply models.list transport timeout
#   ::fake::reply profiles.list hold   ;# keep the callback, never run it
# A method with no reply records the call and never answers.
proc ::fake::reply {method args} {
    variable replies
    set replies($method) $args
}
proc ::vmdai::net::call {method params callback args} {
    set timeout 3000
    foreach {opt value} $args {
        if {$opt eq "-timeout"} { set timeout $value }
    }
    lappend ::fake::calls [list $method $params $timeout]
    if {![info exists ::fake::replies($method)]} { return }
    set reply $::fake::replies($method)
    if {[lindex $reply 0] eq "hold"} {
        lappend ::fake::held [list $method $callback]
        return
    }
    after 0 [list ::fake::deliver $callback $reply]
}
proc ::fake::deliver {callback reply} {
    uplevel #0 [list {*}$callback {*}$reply]
}
proc ::fake::calls_of {method} {
    set out {}
    foreach call $::fake::calls {
        if {[lindex $call 0] eq $method} { lappend out [lindex $call 1] }
    }
    return $out
}
proc ::fake::count {method} { return [llength [::fake::calls_of $method]] }
proc ::fake::last {method} { return [lindex [::fake::calls_of $method] end] }
proc ::fake::timeout_of {method} {
    set timeout ""
    foreach call $::fake::calls {
        if {[lindex $call 0] eq $method} { set timeout [lindex $call 2] }
    }
    return $timeout
}
# The value of `name` in a typed parameter list {name type value ...}.
proc ::fake::param {params name} {
    foreach {n type value} $params {
        if {$n eq $name} { return $value }
    }
    return ""
}
proc ::fake::has_param {params name} {
    foreach {n type value} $params {
        if {$n eq $name} { return 1 }
    }
    return 0
}

# ---- event loop and bindings ---------------------------------------------
# A bare `update` spins at 100% CPU under VMD's aqua Tk 8.6.12 in one case: a
# never-mapped withdrawn toplevel (the panel, in every Tk test here) whose
# transcript changes again after it has already had one `update` pass. `after
# <ms> {...}; vwait` pumps the same event loop without hitting that
# reentrancy quirk (I4).
proc ::harness::_pump {ms} {
    set ::harness::_tick 0
    set id [after $ms {set ::harness::_tick 1}]
    vwait ::harness::_tick
    after cancel $id
    update idletasks
}
proc ::harness::settle {} { ::harness::_pump 5 }
proc ::harness::wait_until {script {ms 2000}} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { return 0 }
        ::harness::_pump 10
    }
    return 1
}
# Without this, a background error (e.g. a fake-transport callback raising
# inside `after 0`) pops aqua's modal bgerror dialog and the file hangs for
# the full tcltest timeout (M3).
proc ::bgerror {message} {
    lappend ::harness::bgerrors $message
    puts stderr "background error: $message\n$::errorInfo"
}
# Run the bindings for `seq` on `w` through its bindtags, with %W
# substituted, stopping at `break`, as Tk does for a real event.
proc ::harness::fire {w seq} {
    foreach tag [bindtags $w] {
        set script [bind $tag $seq]
        if {$script eq ""} { continue }
        set script [string map [list %W $w %% %] $script]
        set code [catch {uplevel #0 $script} result]
        if {$code == 3} { break }
        if {$code == 1} { return -code error $result }
    }
    update idletasks
}
proc ::harness::descendants {w} {
    set out {}
    set queue [list $w]
    while {[llength $queue]} {
        set queue [lassign $queue current]
        foreach child [winfo children $current] {
            lappend out $child
            lappend queue $child
        }
    }
    return $out
}
proc ::harness::texts_under {w} {
    set out {}
    foreach child [::harness::descendants $w] {
        if {[winfo class $child] in {Label TLabel TButton Button TCheckbutton}} {
            lappend out [$child cget -text]
        }
    }
    return $out
}
proc ::harness::label_with_text {w text} {
    foreach child [::harness::descendants $w] {
        if {[winfo class $child] in {Label TLabel} && [$child cget -text] eq $text} { return $child }
    }
    return ""
}

# ---- panel and stubs -----------------------------------------------------
proc ::harness::fresh_panel {} {
    catch {::vmdai::panel::dispose}
    foreach top {.vmd_ai .vmd_ai_settings .vmd_ai_history} {
        if {[winfo exists $top]} { ::destroy $top }
    }
    ::fake::reset
    set ::harness::bridge_calls {}
    set ::harness::busy 0
    set ::vmdai::panel::title "New chat"
    set ::vmdai::panel::busy 0
    set ::vmdai::panel::stopping 0
    set ::vmdai::panel::nomodel 0
    return [::vmdai::panel::build]
}
proc ::harness::count_calls {name} {
    set n 0
    foreach call $::harness::bridge_calls {
        if {[lindex $call 0] eq $name} { incr n }
    }
    return $n
}
# Replace the bridge's user-facing procs with recorders; ::harness::busy
# drives the busy flag that ::vmdai::bridge::state reports.
proc ::harness::stub_bridge {} {
    proc ::vmdai::bridge::state {} {
        set rid [expr {$::harness::busy ? "req_harness" : ""}]
        return [dict create session_id sess_harness chat_id "" busy $::harness::busy \
            request_id $rid after_seq 0 epoch 1]
    }
    proc ::vmdai::bridge::send {text} { lappend ::harness::bridge_calls [list send $text]; return 1 }
    proc ::vmdai::bridge::cancel {args} { lappend ::harness::bridge_calls [list cancel] }
    proc ::vmdai::bridge::new_chat {args} { lappend ::harness::bridge_calls [list new_chat] }
    proc ::vmdai::bridge::apply_workdir {dir} { lappend ::harness::bridge_calls [list apply_workdir $dir] }
    proc ::vmdai::bridge::resume {chat_id {callback ""}} {
        lappend ::harness::bridge_calls [list resume $chat_id]
        if {$callback ne ""} {
            after 0 [list uplevel #0 [list {*}$callback {*}$::harness::resume_reply]]
        }
    }
    proc ::vmdai::runtime::stop {args} { lappend ::harness::bridge_calls [list runtime_stop] }
    proc ::vmdai::runtime::state {} { return $::harness::runtime_state }
}
# Clipboard, desktop opener and status flashes, so tests touch nothing real.
proc ::harness::stub_desktop {} {
    proc ::vmdai::panel::_set_clipboard {s} { set ::harness::clipboard $s }
    # P08-T05's transcript links (Copy, Copy Tcl, Copy path) copy through
    # their own helper; keep them off the real system clipboard too.
    proc ::vmdai::transcript::_clipboard {text} { set ::harness::clipboard $text }
    proc ::vmdai::panel::open_path {path} { lappend ::harness::opened $path }
    proc ::vmdai::statusbar::flash {text args} { lappend ::harness::flashes $text }
}
proc ::harness::stub_settings_open {} {
    proc ::vmdai::panel::open_settings {{tab model} {prefill {}}} {
        lappend ::harness::settings_opened [list $tab $prefill]
    }
}
