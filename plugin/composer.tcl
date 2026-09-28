# composer.tcl -- ChatVMD composer: the prompt input, its placeholder and
# the Send/Stop cell (Part B V4 "Composer", V5).
#
#   ::vmdai::composer::create path ?-onsend cmd? ?-onstop cmd?
#   ::vmdai::composer::get_text          -> the draft, exactly as typed
#   ::vmdai::composer::set_text s        replace the draft
#   ::vmdai::composer::set_mode m        idle | busy | stopping | nomodel | disabled
#   ::vmdai::composer::push_history s    remember a sent prompt (newest 50)
#   ::vmdai::composer::focus             focus the input
#
# The input is a borderless text on a rounded canvas plate with an accent
# focus ring, and grows from 1 to 6 display lines. Send (a ttk::button) and
# Stop (a canvas pill) share one grid cell. Typing is always allowed, so the
# draft survives disconnects and Stop. Return sends only when idle and the
# draft is not blank; while a request runs it flashes "Press Esc to stop" in
# the status bar. -onsend gets the draft as one argument and -onstop none;
# the caller clears the draft and sets the mode (plan 09's panel does both).
# Inside this namespace `focus` is this module's proc; Tk's is ::focus.

namespace eval ::vmdai::composer {
    variable F
    if {![info exists F]} { set F "" }
    variable T
    if {![info exists T]} { set T "" }
    variable mode
    if {![info exists mode]} { set mode idle }
    variable onsend
    if {![info exists onsend]} { set onsend "" }
    variable onstop
    if {![info exists onstop]} { set onstop "" }
    variable S
    if {![info exists S]} { array set S {lines 1 focused 0} }
}

proc ::vmdai::composer::create {path args} {
    variable F
    variable T
    variable onsend
    variable onstop
    variable mode
    variable S
    set onsend ""
    set onstop ""
    foreach {opt value} $args {
        switch -- $opt {
            -onsend { set onsend $value }
            -onstop { set onstop $value }
            default { error "unknown option \"$opt\": must be -onsend or -onstop" }
        }
    }
    if {[winfo exists $path]} { destroy $path }
    array set S {lines 1 focused 0}
    set mode idle
    set F $path
    frame $path -borderwidth 0 -highlightthickness 0
    canvas $path.field -height 34 -width 200 -borderwidth 0 -highlightthickness 0
    set T $path.field.t
    text $T -height 1 -width 10 -wrap word -borderwidth 0 -highlightthickness 0 \
        -font ChatBody -undo 1 -padx 0 -pady 0 -spacing2 3
    label $T.ph -font ChatBody -anchor w -borderwidth 0 -padx 0 -pady 0 -cursor xterm
    $path.field create window 12 8 -anchor nw -window $T -tags txt
    frame $path.act -borderwidth 0 -highlightthickness 0
    ttk::button $path.act.send -text Send -default active -command ::vmdai::composer::_on_return
    canvas $path.act.stop -height 26 -width 80 -borderwidth 0 -highlightthickness 0 \
        -takefocus 1 -cursor hand2
    grid $path.act.send -row 0 -column 0 -sticky se
    grid $path.act.stop -row 0 -column 0 -sticky se
    grid remove $path.act.stop
    grid $path.field -row 0 -column 0 -sticky ew -padx {12 0} -pady 8
    grid $path.act -row 0 -column 1 -sticky se -padx {10 12} -pady {8 12}
    grid columnconfigure $path 0 -weight 1
    ::vmdai::theme::paint $path -background chrome
    ::vmdai::theme::paint $path.field -background chrome
    ::vmdai::theme::paint $path.act -background chrome
    ::vmdai::theme::paint $path.act.stop -background chrome -highlightcolor focus_ring
    ::vmdai::theme::paint $T -background surface -foreground text -insertbackground text \
        -selectbackground sel
    ::vmdai::theme::paint $T.ph -background surface -foreground muted
    ::vmdai::theme::on_repaint ::vmdai::composer::_redraw
    bind $path.field <Configure> ::vmdai::composer::_draw_plate
    bind $T <<Modified>> ::vmdai::composer::_changed
    bind $T <FocusIn> {::vmdai::composer::_focus_changed 1}
    bind $T <FocusOut> {::vmdai::composer::_focus_changed 0}
    bind $T <Return> {::vmdai::composer::_on_return; break}
    bind $T <KP_Enter> {::vmdai::composer::_on_return; break}
    bind $T <Shift-Return> {::vmdai::composer::_newline; break}
    bind $T <Escape> ::vmdai::composer::_stop_clicked
    bind $T.ph <Button-1> [list ::focus $T]
    foreach seq {<ButtonRelease-1> <space> <Return> <KP_Enter>} {
        bind $path.act.stop $seq ::vmdai::composer::_stop_clicked
    }
    _changed
    _sync
    return $path
}

proc ::vmdai::composer::_live {} {
    variable T
    return [expr {$T ne "" && [winfo exists $T]}]
}

proc ::vmdai::composer::get_text {} {
    variable T
    if {![_live]} { return "" }
    return [$T get 1.0 "end -1c"]
}

proc ::vmdai::composer::set_text {s} {
    variable T
    if {![_live]} { return }
    $T delete 1.0 end
    $T insert 1.0 $s
    $T mark set insert "end -1c"
    $T edit reset
    _changed
}

proc ::vmdai::composer::focus {} {
    variable T
    if {[_live]} { ::focus $T }
}

proc ::vmdai::composer::placeholder_for {m} {
    switch -- $m {
        busy - stopping { return "Reply once this run finishes — or press Esc to stop" }
        nomodel {
            set key [expr {[tk windowingsystem] eq "aqua" ? "⌘," : "Ctrl+,"}]
            return "Set up a model to start — $key"
        }
    }
    return "Ask VMD to load, show or measure something…"
}

proc ::vmdai::composer::set_mode {m} {
    variable mode
    if {$m ni {idle busy stopping nomodel disabled}} {
        error "bad mode \"$m\": must be idle, busy, stopping, nomodel or disabled"
    }
    set mode $m
    _sync
}

# Called on every edit: grow or shrink (1-6 display lines), placeholder, Send.
proc ::vmdai::composer::_changed {} {
    variable F
    variable T
    variable S
    if {![_live]} { return }
    $T edit modified 0
    set n 0
    catch {set n [$T count -update -displaylines 1.0 "end -1c"]}
    if {![string is integer -strict $n]} { set n 0 }
    set n [expr {$n + 1}]
    if {$n > 6} { set n 6 }
    if {$n != [$T cget -height]} {
        $T configure -height $n
    }
    set S(lines) $n
    $F.field configure -height [expr {[winfo reqheight $T] + 16}]
    _sync
}

proc ::vmdai::composer::_newline {} {
    variable T
    if {![_live]} { return }
    $T insert insert "\n"
    $T see insert
    _changed
}

proc ::vmdai::composer::_sync {} {
    variable F
    variable T
    variable mode
    if {![_live]} { return }
    $T.ph configure -text [placeholder_for $mode]
    if {[get_text] eq ""} {
        place $T.ph -x 0 -y 0
    } else {
        place forget $T.ph
    }
    if {$mode in {busy stopping}} {
        grid remove $F.act.send
        grid $F.act.stop
        _draw_stop
        return
    }
    grid remove $F.act.stop
    grid $F.act.send
    if {$mode eq "idle" && [string trim [get_text]] ne ""} {
        $F.act.send state !disabled
        $F.act.send configure -default active
    } else {
        $F.act.send state disabled
        $F.act.send configure -default normal
    }
}

proc ::vmdai::composer::_focus_changed {on} {
    variable S
    set S(focused) $on
    _draw_plate
}

proc ::vmdai::composer::_redraw {} {
    if {![_live]} { return }
    _draw_plate
    _draw_stop
}

# The rounded field: accent outline and a focus ring while focused.
proc ::vmdai::composer::_draw_plate {} {
    variable F
    variable S
    if {![_live]} { return }
    set c $F.field
    set w [winfo width $c]
    set h [winfo height $c]
    if {$w < 30 || $h < 20} { return }
    $c delete plate
    if {$S(focused)} {
        ::vmdai::theme::rrect $c 0.5 0.5 [expr {$w - 0.5}] [expr {$h - 0.5}] 11 -fill "" \
            -outline [::vmdai::theme::c focus_ring] -width 3 -tags plate
    }
    set edge [::vmdai::theme::c [expr {$S(focused) ? "accent" : "field_bd"}]]
    ::vmdai::theme::rrect $c 2 2 [expr {$w - 2}] [expr {$h - 2}] 9 \
        -fill [::vmdai::theme::c surface] -outline $edge -width 1 -tags plate
    $c lower plate
    $c coords txt 12 8
    $c itemconfigure txt -width [expr {$w - 24}] -height [expr {$h - 16}]
}

# The Stop pill: stop_bg, a drawn square and "Stop"; "Stopping…" once clicked.
proc ::vmdai::composer::_draw_stop {} {
    variable F
    variable mode
    if {![_live]} { return }
    set c $F.act.stop
    set label [expr {$mode eq "stopping" ? "Stopping…" : "Stop"}]
    set tw [font measure ChatMetaBold $label]
    set w [expr {$tw + 40}]
    set h 26
    $c configure -width $w -height $h
    $c delete all
    set fill [::vmdai::theme::c [expr {$mode eq "stopping" ? "muted" : "stop_bg"}]]
    set fg [::vmdai::theme::c stop_fg]
    ::vmdai::theme::rrect $c 1 1 [expr {$w - 1}] [expr {$h - 1}] 12 -fill $fill -outline "" -tags pill
    $c create rectangle 13 9 21 17 -fill $fg -outline "" -tags square
    $c create text 28 [expr {$h / 2}] -anchor w -text $label -font ChatMetaBold -fill $fg -tags label
    $c configure -cursor [expr {$mode eq "stopping" ? "arrow" : "hand2"}]
}

proc ::vmdai::composer::_call {target args} {
    if {[info commands $target] eq ""} { return }
    uplevel #0 [list $target {*}$args]
}

# Return, KP_Enter and the Send button.
proc ::vmdai::composer::_on_return {} {
    variable mode
    variable onsend
    switch -- $mode {
        idle {
            set draft [get_text]
            if {[string trim $draft] eq "" || $onsend eq ""} { return }
            uplevel #0 [list {*}$onsend $draft]
        }
        busy - stopping {
            _call ::vmdai::statusbar::flash "Press Esc to stop" 2000
        }
    }
}

# The Stop pill (click, Space, Return) and Esc in the input.
proc ::vmdai::composer::_stop_clicked {} {
    variable mode
    variable onstop
    if {$mode ne "busy" || $onstop eq ""} { return }
    uplevel #0 $onstop
}

# ===========================================================================
# Prompt recall (Part B V5; P09-T03).
#
# Up on the first display line shows the previous prompt of this chat, Down
# on the last display line the next one; Down past the newest brings the
# draft back. The newest 50 prompts are kept; New chat clears them.
# ===========================================================================
namespace eval ::vmdai::composer {
    variable RECALL_MAX 50
    if {![info exists ::vmdai::composer::recall]} { variable recall {} }
    if {![info exists ::vmdai::composer::recall_pos]} { variable recall_pos -1 }
    if {![info exists ::vmdai::composer::recall_draft]} { variable recall_draft "" }
    # `history` is plan 08's name for this same list; tests/tcl/test_composer.tcl
    # (P08-T08, unmodified by this task) still reads it directly, so
    # push_history/clear_history below keep it mirroring `recall`.
    if {![info exists ::vmdai::composer::history]} { variable history {} }
}

proc ::vmdai::composer::push_history {s} {
    variable recall
    variable recall_pos
    variable history
    variable RECALL_MAX
    set s [string trim $s]
    if {$s eq ""} { return }
    if {[lindex $recall end] ne $s} { lappend recall $s }
    if {[llength $recall] > $RECALL_MAX} {
        set recall [lrange $recall end-[expr {$RECALL_MAX - 1}] end]
    }
    set recall_pos -1
    set history $recall
}

proc ::vmdai::composer::clear_history {} {
    variable recall
    variable recall_pos
    variable recall_draft
    variable history
    set recall {}
    set recall_pos -1
    set recall_draft ""
    set history {}
}

proc ::vmdai::composer::recall_prev {} {
    variable recall
    variable recall_pos
    variable recall_draft
    if {![llength $recall]} { return 0 }
    if {$recall_pos < 0} {
        set recall_draft [get_text]
        set recall_pos [llength $recall]
    }
    # Already at the oldest prompt: keep it and swallow the key.
    if {$recall_pos == 0} { return 1 }
    incr recall_pos -1
    set_text [lindex $recall $recall_pos]
    return 1
}

proc ::vmdai::composer::recall_next {} {
    variable recall
    variable recall_pos
    variable recall_draft
    if {$recall_pos < 0} { return 0 }
    incr recall_pos
    if {$recall_pos >= [llength $recall]} {
        set recall_pos -1
        set_text $recall_draft
        return 1
    }
    set_text [lindex $recall $recall_pos]
    return 1
}

# Bound to <Up>/<Down> on the input by ::vmdai::panel::bind_keys; returning 1
# makes the binding `break`, so the text class binding does not move the caret.
proc ::vmdai::composer::on_up {w} {
    set n [$w count -displaylines 1.0 insert]
    if {$n ne "" && $n > 0} { return 0 }
    return [recall_prev]
}

proc ::vmdai::composer::on_down {w} {
    set n [$w count -displaylines insert "end -1c"]
    if {$n ne "" && $n > 0} { return 0 }
    return [recall_next]
}
