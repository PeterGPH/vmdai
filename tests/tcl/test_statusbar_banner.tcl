# statusbar.tcl and banner.tcl (P08-T09). Adopts cards' offline-1.
# Run by tests/test_tk_statusbar_banner.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched theme viewmodel composer statusbar banner
::vmdai::theme::init light

# Plan 06's runtime and config, reduced to the facts the banner reads.
namespace eval ::vmdai::runtime {}
namespace eval ::vmdai::config {}
array set ::RT {state ready reason "" owned 1 protocol 2}
set ::RT(tail) {}
for {set i 1} {$i <= 20} {incr i} { lappend ::RT(tail) "pipe line $i" }
proc ::vmdai::runtime::state {} { return $::RT(state) }
proc ::vmdai::runtime::failure_reason {} { return $::RT(reason) }
proc ::vmdai::runtime::info {} {
    return [dict create host 127.0.0.1 port 8765 pid 4242 version 0.9 \
        protocol $::RT(protocol) launch_token t owned $::RT(owned)]
}
proc ::vmdai::runtime::pipe_tail {{n 12}} { return [lrange $::RT(tail) end-[expr {$n - 1}] end] }
proc ::vmdai::runtime::backoff_ms {attempt} {
    if {$attempt >= 5} { return 8000 }
    return [expr {500 << ($attempt - 1)}]
}
proc ::vmdai::config::log_path {} { return /Users/me/.vmdai/logs/plugin.log }

set ::NOW 1790208000
proc ::vmdai::statusbar::_now {} { return $::NOW }
set ::actions {}
proc record {args} { lappend ::actions $args }

wm geometry . 900x300
::vmdai::banner::create .ban -onaction record
::vmdai::composer::create .cb
::vmdai::statusbar::create .sb -onaction record
grid .ban -row 0 -column 0 -sticky ew
grid remove .ban
grid .cb -row 1 -column 0 -sticky ew
grid .sb -row 2 -column 0 -sticky ew
grid columnconfigure . 0 -weight 1
update

proc sb {args} { ::vmdai::statusbar::update [dict create {*}$args] }
proc left {} { return [lindex [::vmdai::statusbar::text] 0] }
proc dot {} {
    set fill [.sb.dot itemcget dot -fill]
    foreach tok {dot_ok dot_warn dot_off faint} {
        if {$fill eq [::vmdai::theme::c $tok]} { return $tok }
    }
    return ?
}
proc fresh {} {
    set ::actions {}
    array set ::RT {state ready reason "" owned 1 protocol 2}
    ::vmdai::banner::hide
    ::vmdai::statusbar::_unflash
    sb connection ready provider Ollama model qwen3.8:27b host 127.0.0.1:11435 \
        folder [file join $::env(HOME) proj cdk2] runs 12 busy 0 activity "" t0 "" retry_in ""
    update
    ::vmdai::statusbar::_render
}
proc buttons {} {
    set out {}
    foreach b [winfo children .ban.in.btns] { lappend out [$b itemcget label -text] }
    return $out
}
proc click_all {} {
    foreach b [winfo children .ban.in.btns] { uplevel #0 [bind $b <ButtonRelease-1>] }
}

test status_texts {idle connection, the phase and its timer while busy, retries, flash, offline states} -body {
    fresh
    set r [list [::vmdai::statusbar::text] [dot]]
    sb model ""
    lappend r [left] [dot]
    sb model qwen3.8:27b busy 1 activity "Step 4 · running VMD command" t0 [expr {$::NOW - 12}]
    lappend r [::vmdai::statusbar::text]
    sb activity Thinking t0 [expr {$::NOW - 5}]
    lappend r [left]
    sb activity "Loading qwen3.8:27b" t0 [expr {$::NOW - 21}]
    lappend r [left]
    sb activity "Retrying 2/5 in 8 s" t0 ""
    lappend r [left]
    ::vmdai::statusbar::flash "Press Esc to stop" 2000
    lappend r [left]
    ::vmdai::statusbar::_unflash
    lappend r [left]
    sb busy 0 activity "" t0 ""
    foreach c {launching reconnecting down stopped} {
        sb connection $c
        lappend r [left] [dot]
    }
    sb connection reconnecting retry_in 8
    lappend r [left] [llength [::vmdai::sched::pending]]
} -result [list {{Ollama · qwen3.8:27b · 127.0.0.1:11435} {Auto-run Tcl ▾ │ ~/proj/cdk2 · 12 runs}} dot_ok \
    {Ollama · no model · 127.0.0.1:11435} faint \
    {{Step 4 · running VMD command · 00:12} {Esc to stop}} {Thinking · 00:05} {Loading qwen3.8:27b · 00:21} \
    {Retrying 2/5 in 8 s} {Press Esc to stop} {Retrying 2/5 in 8 s} \
    {Starting the AI runtime…} dot_warn {Runtime offline · reconnecting} dot_warn \
    {Runtime offline} dot_off {Runtime stopped} dot_off {Runtime offline · retry in 8 s} 0]

test status_clicks {the left segment opens Settings, the folder chooses another, the trust menu shows the mode} -body {
    fresh
    foreach w {.sb.left .sb.folder} { uplevel #0 [bind $w <ButtonRelease-1>] }
    set m .sb.trust.m
    set labels {}
    for {set i 0} {$i <= [$m index end]} {incr i} {
        if {[$m type $i] eq "separator"} { lappend labels - ; continue }
        lappend labels [$m entrycget $i -label] [$m entrycget $i -state]
    }
    $m invoke 3
    list $::actions $labels $::vmdai::statusbar::trust_mode
} -result {{open_settings choose_folder about_trust} {Auto-run normal {Ask before running} disabled - {About Tcl trust…} normal} auto}

test narrow_drop_order {segments drop in the order host, runs, folder, provider, then Auto-run shortens} -body {
    fresh
    set seen {}
    for {set w 900} {$w >= 40} {incr w -5} {
        set d [::vmdai::statusbar::_fit $w]
        if {$d ne [lindex $seen end] || $seen eq ""} { lappend seen $d }
    }
    wm geometry . 380x300
    update
    ::vmdai::statusbar::_render
    set narrow [::vmdai::statusbar::text]
    wm geometry . 900x300
    update
    ::vmdai::statusbar::_render
    list $seen [string match *127.0.0.1* [lindex $narrow 0]] [string match Auto-run* [lindex $narrow 1]] \
        [string match *127.0.0.1* [left]]
} -result {{{} host {host runs} {host runs folder} {host runs folder provider} {host runs folder provider trust}} 0 1 1}

test never_tunnel {no status bar or banner text says "tunnel"; ready shows host:port} -body {
    fresh
    set texts {}
    foreach c {stopped launching connecting ready reconnecting down} {
        foreach busy {0 1} {
            sb connection $c busy $busy activity "Thinking" t0 $::NOW retry_in 4
            lappend texts [::vmdai::statusbar::text]
        }
    }
    sb busy 0
    foreach {kind owned} {unreachable 1 didnt_start 1 too_old 1 too_old 0} {
        set ::RT(owned) $owned
        set ::RT(state) [expr {$kind eq "unreachable" ? "reconnecting" : "down"}]
        ::vmdai::banner::show $kind ""
        lappend texts [.ban.in.title cget -text] [.ban.in.detail cget -text] [buttons]
    }
    ::vmdai::banner::hide
    list [regexp -nocase {tunnel} $texts] [llength [lsearch -all $texts *127.0.0.1:11435*]]
} -result {0 1}

test offline-1 {offline shows exactly one banner and disables Send with the draft kept; ready hides it} -body {
    fresh
    ::vmdai::composer::set_text "draft"
    set ::RT(state) reconnecting
    ::vmdai::banner::on_runtime_state ready reconnecting "connection refused"
    ::vmdai::banner::on_runtime_state ready reconnecting "connection refused"
    sb connection reconnecting
    ::vmdai::composer::set_mode disabled
    set r [list [winfo manager .ban] [winfo children .ban] [.ban.in.title cget -text] [left] \
        [.cb.act.send instate disabled] [::vmdai::composer::get_text]]
    array set ::RT {state down reason didnt_start}
    ::vmdai::banner::on_runtime_state reconnecting down "ModuleNotFoundError: No module named 'x'"
    lappend r [::vmdai::banner::kind] [llength [winfo children .ban]]
    set ::RT(state) ready
    ::vmdai::banner::on_runtime_state down ready ""
    sb connection ready
    ::vmdai::composer::set_mode idle
    lappend r [winfo manager .ban] [::vmdai::banner::kind] [.cb.act.send instate disabled] \
        [::vmdai::composer::get_text] [llength [::vmdai::sched::pending]]
} -result {grid {.ban.line .ban.in} {Runtime not reachable} {Runtime offline · reconnecting} 1 draft didnt_start 2 {} {} 0 draft 0}

test banner_kinds_actions {each kind has its title, detail and actions; the countdown follows the backoff; details and narrow layout} -body {
    fresh
    set r {}
    set ::RT(state) reconnecting
    ::vmdai::banner::show unreachable ""
    lappend r [.ban.in.detail cget -text]
    ::vmdai::banner::_tick
    lappend r [.ban.in.detail cget -text]
    ::vmdai::banner::_tick
    ::vmdai::banner::_tick
    lappend r [.ban.in.detail cget -text]
    lappend r [buttons]
    click_all
    lappend r [.ban.in.detail cget -text]
    set ::RT(state) down
    set ::RT(reason) didnt_start
    ::vmdai::banner::show didnt_start "ModuleNotFoundError: No module named 'x'"
    lappend r [.ban.in.title cget -text] [.ban.in.detail cget -text] [buttons] [winfo manager .ban.in.tail]
    ::vmdai::banner::toggle_details
    set tail [split [.ban.in.tail cget -text] "\n"]
    lappend r [.ban.in.more cget -text] [lindex $tail 0] [lindex $tail 11] [lindex $tail end]
    click_all
    set ::RT(protocol) 1
    ::vmdai::banner::show too_old "This runtime is too old (protocol 1)."
    lappend r [.ban.in.title cget -text] [buttons]
    click_all
    set ::RT(owned) 0
    ::vmdai::banner::show too_old "This runtime is too old (protocol 1)."
    lappend r [buttons] [string match *scripts/run_runtime.sh* [.ban.in.detail cget -text]]
    set ::RT(owned) 1
    set ::RT(state) reconnecting
    ::vmdai::banner::show unreachable ""
    ::vmdai::banner::_relayout 380
    lappend r [dict get [grid info .ban.in.btns] -row]
    ::vmdai::banner::_relayout 600
    lappend r [dict get [grid info .ban.in.btns] -row] $::actions
    ::vmdai::banner::hide
    lappend r [llength [::vmdai::sched::pending]]
} -result {{127.0.0.1:8765 is not answering. Retrying in 1 s.} {127.0.0.1:8765 is not answering. Retrying now…} {127.0.0.1:8765 is not answering. Retrying now…} {{Retry now} {Open log}} {127.0.0.1:8765 is not answering. Retrying in 1 s.} {Runtime didn't start} {ModuleNotFoundError: No module named 'x'} {Retry {Choose Python…} {Open log}} {} {Hide details} {pipe line 9} {pipe line 20} {Log: /Users/me/.vmdai/logs/plugin.log} {This runtime is too old (protocol 1)} {{Restart runtime}} {} 1 4 0 {retry_now open_log retry choose_python open_log restart} 0}

proc pad_gap {} {
    set w [winfo width .sb]
    set maxedge 0
    foreach child {.sb.trust .sb.sep .sb.folder .sb.hint} {
        if {[winfo manager $child] eq ""} { continue }
        set edge [expr {[winfo x $child] + [winfo width $child]}]
        if {$edge > $maxedge} { set maxedge $edge }
    }
    return [expr {$w - $maxedge}]
}

test status_right_pad {the status bar's right segment keeps its 14 px pad when idle and busy} -body {
    fresh
    sb connection ready provider ollama model qwen3.8:27b host 127.0.0.1:11435 \
        folder /tmp/proj/cdk2 runs 3 busy 0
    ::vmdai::statusbar::_render
    update idletasks
    set idle [pad_gap]
    sb busy 1 activity "Step 3"
    ::vmdai::statusbar::_render
    update idletasks
    set busy [pad_gap]
    list $idle $busy
} -result {14 14}

cleanupTests
exit
