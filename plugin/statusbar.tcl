# statusbar.tcl -- ChatVMD status bar (Part B V4 "Status bar", V6).
#
#   ::vmdai::statusbar::create path ?-onaction cmd?
#   ::vmdai::statusbar::update dict    merge any of: connection provider model
#                                      host folder runs busy activity t0 retry_in
#   ::vmdai::statusbar::text           -> {left right}, as displayed
#   ::vmdai::statusbar::flash text ms  show text on the left for ms
#
# Left: a dot and the connection ("Ollama · qwen3.8:27b · 127.0.0.1:11435":
# host:port, never the word "tunnel"), or, while a request runs, the phase
# and its timer ("Step 4 · running VMD command · 00:12"). Clicking it opens
# Settings. Right: "Auto-run Tcl ▾" (a menu with the trust mode) and the
# folder with its run count (clicking the folder chooses another); while a
# request runs, "Esc to stop". When the bar is too narrow, segments drop in
# the order host, run count, folder, provider; then "Auto-run Tcl ▾" shortens
# to "Auto-run ▾", which is never dropped. Inside this namespace `update`
# and `text` are this module's procs (Tk's text widget command is ::text).

namespace eval ::vmdai::statusbar {
    variable P
    if {![info exists P]} { set P "" }
    variable on_action
    if {![info exists on_action]} { set on_action "" }
    variable trust_mode
    if {![info exists trust_mode]} { set trust_mode auto }
    variable D
    if {![info exists D]} { array set D {} }
    variable S
    if {![info exists S]} { array set S {} }
}

proc ::vmdai::statusbar::_reset {} {
    variable D
    variable S
    array unset D
    array set D {connection stopped provider "" model "" host "" folder "" runs ""
                 busy 0 activity "" t0 "" retry_in ""}
    array unset S
    array set S {flash "" flash_id "" tick "" spin 0}
}

proc ::vmdai::statusbar::create {path args} {
    variable P
    variable on_action
    set on_action ""
    foreach {opt value} $args {
        if {$opt ne "-onaction"} { error "unknown option \"$opt\": must be -onaction" }
        set on_action $value
    }
    if {$P ne "" && [winfo exists $P]} { _cancel_timers }
    if {[winfo exists $path]} { destroy $path }
    _reset
    set P $path
    frame $path -borderwidth 0 -highlightthickness 0
    canvas $path.dot -width 10 -height 10 -borderwidth 0 -highlightthickness 0
    label $path.left -font ChatMeta -anchor w -borderwidth 0 -padx 0 -cursor hand2
    label $path.trust -font ChatMeta -borderwidth 0 -padx 0 -cursor hand2
    label $path.sep -font ChatMeta -text "│" -borderwidth 0 -padx 6
    label $path.folder -font ChatMeta -borderwidth 0 -padx 0 -cursor hand2
    label $path.hint -font ChatMeta -text "Esc to stop" -borderwidth 0 -padx 0
    menu $path.trust.m -tearoff 0
    $path.trust.m add radiobutton -label "Auto-run" -value auto \
        -variable ::vmdai::statusbar::trust_mode
    $path.trust.m add radiobutton -label "Ask before running" -value ask \
        -variable ::vmdai::statusbar::trust_mode -state disabled
    $path.trust.m add separator
    $path.trust.m add command -label "About Tcl trust…" \
        -command [list ::vmdai::statusbar::_action about_trust]
    grid $path.dot -row 0 -column 0 -padx {14 6} -pady {2 5}
    grid $path.left -row 0 -column 1 -sticky w -pady {2 5}
    grid $path.trust -row 0 -column 3 -sticky e -pady {2 5}
    grid $path.sep -row 0 -column 4 -pady {2 5}
    grid $path.folder -row 0 -column 5 -sticky e -pady {2 5}
    grid $path.hint -row 0 -column 6 -sticky e -padx {0 14} -pady {2 5}
    grid columnconfigure $path 2 -weight 1
    grid columnconfigure $path 1 -weight 0
    foreach w [list $path $path.dot $path.left $path.trust $path.sep $path.folder $path.hint] {
        ::vmdai::theme::paint $w -background chrome
    }
    ::vmdai::theme::paint $path.left -foreground text
    foreach w [list $path.trust $path.folder $path.hint] {
        ::vmdai::theme::paint $w -foreground muted
    }
    ::vmdai::theme::paint $path.sep -foreground faint
    ::vmdai::theme::on_repaint ::vmdai::statusbar::_render
    bind $path.left <ButtonRelease-1> [list ::vmdai::statusbar::_action open_settings]
    bind $path.dot <ButtonRelease-1> [list ::vmdai::statusbar::_action open_settings]
    bind $path.folder <ButtonRelease-1> [list ::vmdai::statusbar::_action choose_folder]
    bind $path.trust <ButtonRelease-1> {::vmdai::statusbar::_post_trust %X %Y}
    bind $path <Configure> ::vmdai::statusbar::_render
    bind $path <Destroy> [list ::vmdai::statusbar::_on_destroy %W]
    _render
    return $path
}

proc ::vmdai::statusbar::_on_destroy {w} {
    variable P
    if {$w eq $P} { _cancel_timers }
}

proc ::vmdai::statusbar::_cancel_timers {} {
    variable S
    foreach key {flash_id tick} {
        if {[info exists S($key)] && $S($key) ne ""} {
            ::vmdai::sched::cancel $S($key)
            set S($key) ""
        }
    }
}

proc ::vmdai::statusbar::update {d} {
    variable D
    foreach key [dict keys $d] {
        if {$key in {connection provider model host folder runs busy activity t0 retry_in}} {
            set D($key) [dict get $d $key]
        }
    }
    set D(busy) [expr {[string is true -strict $D(busy)] ? 1 : 0}]
    _render
}

proc ::vmdai::statusbar::flash {text ms} {
    variable S
    if {$S(flash_id) ne ""} { ::vmdai::sched::cancel $S(flash_id) }
    set S(flash) $text
    set S(flash_id) [::vmdai::sched::after $ms ::vmdai::statusbar::_unflash]
    _render
}

proc ::vmdai::statusbar::_unflash {} {
    variable S
    if {$S(flash_id) ne ""} { ::vmdai::sched::cancel $S(flash_id) }
    set S(flash_id) ""
    set S(flash) ""
    _render
}

proc ::vmdai::statusbar::text {} {
    variable P
    if {$P eq "" || ![winfo exists $P]} { return [list "" ""] }
    set right [$P.trust cget -text]
    if {[winfo manager $P.hint] ne ""} {
        set right [$P.hint cget -text]
    } elseif {[winfo manager $P.folder] ne ""} {
        append right " │ " [$P.folder cget -text]
    }
    return [list [$P.left cget -text] $right]
}

# The clock the timer reads (tests replace it).
proc ::vmdai::statusbar::_now {} {
    return [clock seconds]
}

proc ::vmdai::statusbar::_folder_text {} {
    variable D
    set f $D(folder)
    if {$f eq ""} { return "" }
    set homes {}
    catch {lappend homes $::env(HOME) [file normalize $::env(HOME)]}
    foreach home $homes {
        if {$home ne "" && ($f eq $home || [string first "$home/" $f] == 0)} {
            return "~[string range $f [string length $home] end]"
        }
    }
    return $f
}

proc ::vmdai::statusbar::_runs_text {} {
    variable D
    if {![string is integer -strict $D(runs)]} { return "" }
    return [expr {$D(runs) == 1 ? "1 run" : "$D(runs) runs"}]
}

# Left text for the connection (idle), with the segments in $drop left out.
proc ::vmdai::statusbar::_connection_text {drop} {
    variable D
    switch -- $D(connection) {
        ready {
            set parts {}
            if {"provider" ni $drop && $D(provider) ne ""} { lappend parts $D(provider) }
            lappend parts [expr {$D(model) eq "" ? "no model" : $D(model)}]
            if {"host" ni $drop && $D(host) ne ""} { lappend parts $D(host) }
            return [join $parts " · "]
        }
        launching - connecting { return "Starting the AI runtime…" }
        reconnecting {
            if {[string is integer -strict $D(retry_in)]} {
                return "Runtime offline · retry in $D(retry_in) s"
            }
            return "Runtime offline · reconnecting"
        }
        down {
            if {[string is integer -strict $D(retry_in)]} {
                return "Runtime offline · retry in $D(retry_in) s"
            }
            return "Runtime offline"
        }
    }
    return "Runtime stopped"
}

proc ::vmdai::statusbar::_trust_text {drop} {
    return [expr {"trust" in $drop ? "Auto-run ▾" : "Auto-run Tcl ▾"}]
}

proc ::vmdai::statusbar::_folder_segment {drop} {
    set parts {}
    if {"folder" ni $drop} {
        set f [_folder_text]
        if {$f ne ""} { lappend parts $f }
        if {"runs" ni $drop && [_runs_text] ne ""} { lappend parts [_runs_text] }
    }
    return [join $parts " · "]
}

# The segments left out at a given width (V6): host, runs, folder, provider,
# then the short trust label. avail < 0 means "no limit" (not laid out yet).
proc ::vmdai::statusbar::_fit {avail} {
    set levels {{} {host} {host runs} {host runs folder} {host runs folder provider}
                {host runs folder provider trust}}
    if {$avail < 0} { return {} }
    foreach drop $levels {
        set need [expr {[font measure ChatMeta [_connection_text $drop]] + 16}]
        incr need [font measure ChatMeta [_trust_text $drop]]
        set seg [_folder_segment $drop]
        if {$seg ne ""} { incr need [expr {[font measure ChatMeta "│$seg"] + 12}] }
        if {$need <= $avail} { return $drop }
    }
    return [lindex $levels end]
}

proc ::vmdai::statusbar::_dot_token {} {
    variable D
    switch -- $D(connection) {
        ready { return [expr {$D(model) eq "" ? "faint" : "dot_ok"}] }
        launching - connecting - reconnecting { return dot_warn }
    }
    return dot_off
}

proc ::vmdai::statusbar::_render {} {
    variable P
    variable D
    variable S
    if {$P eq "" || ![winfo exists $P]} { return }
    set w [winfo width $P]
    set avail [expr {$w > 1 ? $w - 28 : -1}]
    set busy [expr {$D(busy) && $D(connection) eq "ready"}]
    set c $P.dot
    $c delete all
    if {$busy} {
        set start [expr {90 - 90 * ($S(spin) % 4)}]
        $c create oval 1 1 9 9 -outline [::vmdai::theme::c hairline] -width 2
        $c create arc 1 1 9 9 -start $start -extent 90 -style arc \
            -outline [::vmdai::theme::c accent] -width 2
    } else {
        $c create oval 1 1 9 9 -outline "" -fill [::vmdai::theme::c [_dot_token]] -tags dot
    }
    if {$busy} {
        set st [dict create busy 1 phase [expr {$D(activity) eq "" ? "Working…" : $D(activity)}] \
            phase_t0 $D(t0)]
        set left [::vmdai::vm::status_text st [_now]]
        grid remove $P.trust $P.sep $P.folder
        grid $P.hint
        _schedule_tick
    } else {
        set drop [_fit [expr {$avail < 0 ? -1 : $avail}]]
        set left [_connection_text $drop]
        $P.trust configure -text [_trust_text $drop]
        set seg [_folder_segment $drop]
        $P.folder configure -text $seg
        grid remove $P.hint
        grid $P.trust
        if {$seg eq ""} { grid remove $P.sep $P.folder } else { grid $P.sep $P.folder }
        if {$S(tick) ne ""} {
            ::vmdai::sched::cancel $S(tick)
            set S(tick) ""
        }
    }
    if {$S(flash) ne ""} { set left $S(flash) }
    if {$avail > 0} {
        if {$busy} {
            set room [expr {$avail - 16 - [winfo reqwidth $P.hint]}]
        } else {
            set room [expr {$avail - 16 - [winfo reqwidth $P.trust]}]
            if {[winfo manager $P.folder] ne ""} {
                incr room [expr {-[winfo reqwidth $P.sep] - [winfo reqwidth $P.folder]}]
            }
        }
        if {$room > 40} { set left [::vmdai::theme::fit ChatMeta $room $left 12] }
    }
    $P.left configure -text $left
}

# While busy, the timer and the spinner advance once a second.
proc ::vmdai::statusbar::_schedule_tick {} {
    variable S
    if {$S(tick) eq ""} {
        set S(tick) [::vmdai::sched::after 1000 ::vmdai::statusbar::_tick]
    }
}

proc ::vmdai::statusbar::_tick {} {
    variable S
    if {$S(tick) ne ""} { ::vmdai::sched::cancel $S(tick) }
    set S(tick) ""
    incr S(spin)
    _render
}

proc ::vmdai::statusbar::_post_trust {x y} {
    variable P
    tk_popup $P.trust.m $x $y
}

proc ::vmdai::statusbar::_call {target args} {
    if {[info commands $target] eq ""} { return }
    uplevel #0 [list $target {*}$args]
}

# Run an action: the on_action callback when set (tests), else its target.
proc ::vmdai::statusbar::_action {name} {
    variable on_action
    if {$on_action ne ""} {
        return [uplevel #0 [list {*}$on_action $name]]
    }
    switch -- $name {
        open_settings { _call ::vmdai::panel::open_settings }
        choose_folder { _call ::vmdai::panel::choose_folder }
        about_trust   { _about_trust }
    }
}

proc ::vmdai::statusbar::_about_trust {} {
    variable P
    tk_messageBox -parent [winfo toplevel $P] -icon info -title "Tcl trust" \
        -message "Model-written Tcl runs unsandboxed in this VMD session." \
        -detail "ChatVMD runs the model's Tcl automatically, with your permissions. Only load files you trust; asking before running arrives in a later version."
}
