# banner.tcl -- ChatVMD connection banner (Part B V4 "Banner", §5).
#
#   ::vmdai::banner::create path ?-onaction cmd?
#   ::vmdai::banner::show kind detail  kind: unreachable, didnt_start, too_old
#   ::vmdai::banner::hide
#   ::vmdai::banner::on_runtime_state old new detail   (a runtime::subscribe callback)
#   ::vmdai::banner::kind              -> the kind shown, or ""
#
# One banner at a time in grid slot 2: the panel grids path once and then
# `grid remove`s it; show re-grids it and hide removes it again. The look is
# warn_bg, a warning triangle, a bold title, a detail line (host:port and,
# while reconnecting, a countdown that follows the runtime's backoff), then
# pill buttons, which move under the text below 440 px. Actions go to the
# -onaction callback when set, else: Retry now / Retry -> runtime::retry_now,
# Open log -> panel::open_log, Choose Python… -> panel::open_settings panel,
# Restart runtime -> runtime::stop, then runtime::ensure.

namespace eval ::vmdai::banner {
    variable P
    if {![info exists P]} { set P "" }
    variable on_action
    if {![info exists on_action]} { set on_action "" }
    variable S
    if {![info exists S]} { array set S {} }
}

proc ::vmdai::banner::_reset {} {
    variable S
    array unset S
    array set S {kind "" detail "" attempt 0 remaining 0 tick "" details 0 narrow 0 lastw 0}
}

proc ::vmdai::banner::create {path args} {
    variable P
    variable on_action
    set on_action ""
    foreach {opt value} $args {
        if {$opt ne "-onaction"} { error "unknown option \"$opt\": must be -onaction" }
        set on_action $value
    }
    if {$P ne "" && [winfo exists $P]} { _stop_countdown }
    if {[winfo exists $path]} { destroy $path }
    _reset
    set P $path
    frame $path -borderwidth 0 -highlightthickness 0
    frame $path.line -height 1 -borderwidth 0 -highlightthickness 0
    pack $path.line -side bottom -fill x
    ::vmdai::theme::paint $path -background warn_bg
    ::vmdai::theme::paint $path.line -background warn_bd
    ::vmdai::theme::on_repaint ::vmdai::banner::_rebuild
    bind $path <Configure> {::vmdai::banner::_relayout %w}
    bind $path <Destroy> [list ::vmdai::banner::_on_destroy %W]
    return $path
}

proc ::vmdai::banner::_on_destroy {w} {
    variable P
    if {$w eq $P} { _stop_countdown }
}

proc ::vmdai::banner::kind {} {
    variable S
    return $S(kind)
}

# ---- runtime facts (plan 06), each optional ----------------------------------

proc ::vmdai::banner::_rt {what args} {
    set cmd ::vmdai::runtime::$what
    if {[info commands $cmd] eq ""} { return "" }
    if {[catch {uplevel #0 [list $cmd {*}$args]} v]} { return "" }
    return $v
}

proc ::vmdai::banner::_hostport {} {
    set info [_rt info]
    if {[catch {set hp "[dict get $info host]:[dict get $info port]"}] || $hp eq ":"} {
        return "the AI runtime"
    }
    return $hp
}

proc ::vmdai::banner::_backoff_s {attempt} {
    set ms [_rt backoff_ms $attempt]
    if {![string is integer -strict $ms]} {
        set ms [expr {$attempt >= 5 ? 8000 : 500 << ($attempt - 1)}]
    }
    return [expr {int(ceil($ms / 1000.0))}]
}

# ---- content --------------------------------------------------------------------

proc ::vmdai::banner::_title {kind} {
    switch -- $kind {
        unreachable { return "Runtime not reachable" }
        didnt_start { return "Runtime didn't start" }
        too_old {
            set protocol 1
            catch {set protocol [dict get [_rt info] protocol]}
            if {![string is integer -strict $protocol]} { set protocol 1 }
            return "This runtime is too old (protocol $protocol)"
        }
    }
    return $kind
}

proc ::vmdai::banner::_owned {} {
    set owned 1
    catch {set owned [dict get [_rt info] owned]}
    return [expr {[string is true -strict $owned] ? 1 : 0}]
}

# {label action ...} for a kind (§5, Part B V4).
proc ::vmdai::banner::_buttons {kind} {
    switch -- $kind {
        unreachable { return {"Retry now" retry_now "Open log" open_log} }
        didnt_start { return {"Retry" retry "Choose Python…" choose_python "Open log" open_log} }
        too_old {
            if {[_owned]} { return {"Restart runtime" restart} }
            return {}
        }
    }
    return {}
}

proc ::vmdai::banner::_detail_text {} {
    variable S
    set hp [_hostport]
    switch -- $S(kind) {
        unreachable {
            if {$S(attempt) > 0} {
                if {$S(remaining) > 0} {
                    return "$hp is not answering. Retrying in $S(remaining) s."
                }
                return "$hp is not answering. Retrying now…"
            }
            if {$S(detail) ne ""} { return $S(detail) }
            return "Nothing answered on $hp."
        }
        didnt_start {
            if {$S(detail) ne ""} { return $S(detail) }
            return "The AI runtime exited before it was ready."
        }
        too_old {
            if {[_owned]} { return "Restart it to use the runtime that ships with this panel." }
            return "ChatVMD never restarts a runtime it did not start. Restart scripts/run_runtime.sh on $hp with this version, then reopen the panel."
        }
    }
    return $S(detail)
}

proc ::vmdai::banner::show {kind detail} {
    variable P
    variable S
    if {$P eq "" || ![winfo exists $P]} { return }
    _stop_countdown
    set S(kind) $kind
    set S(detail) $detail
    set S(details) 0
    if {$kind eq "unreachable" && [_rt state] eq "reconnecting"} {
        _start_countdown 1
    }
    _rebuild
    grid $P
}

proc ::vmdai::banner::hide {} {
    variable P
    variable S
    _stop_countdown
    set S(kind) ""
    set S(detail) ""
    if {$P ne "" && [winfo exists $P]} { grid remove $P }
}

# The runtime state machine drives the banner (plan 06's subscribe).
proc ::vmdai::banner::on_runtime_state {old new detail} {
    variable S
    switch -- $new {
        ready - stopped { hide }
        reconnecting { show unreachable $detail }
        launching - connecting {
            if {$S(kind) ne ""} {
                _stop_countdown
                set S(detail) "Starting the AI runtime…"
                _set_detail [_detail_text]
            }
        }
        down {
            set reason [_rt failure_reason]
            if {$reason ni {didnt_start too_old}} { set reason unreachable }
            show $reason $detail
        }
    }
}

proc ::vmdai::banner::_set_detail {text} {
    variable P
    if {[winfo exists $P.in.detail]} { $P.in.detail configure -text $text }
}

proc ::vmdai::banner::_rebuild {} {
    variable P
    variable S
    if {$P eq "" || ![winfo exists $P] || $S(kind) eq ""} { return }
    catch {destroy $P.in}
    set in [frame $P.in -borderwidth 0 -highlightthickness 0]
    ::vmdai::theme::paint $in -background warn_bg
    canvas $in.icon -width 20 -height 18 -borderwidth 0 -highlightthickness 0
    ::vmdai::theme::paint $in.icon -background warn_bg
    $in.icon create polygon 10 2 18 16 2 16 -fill [::vmdai::theme::c warn] \
        -outline [::vmdai::theme::c warn] -width 1.5 -joinstyle round
    $in.icon create line 10 7 10 11 -fill [::vmdai::theme::c warn_bg] -width 1.6 -capstyle round
    $in.icon create oval 9.1 13 10.9 14.8 -fill [::vmdai::theme::c warn_bg] -outline ""
    label $in.title -text [_title $S(kind)] -font ChatBodyBold -anchor w -borderwidth 0 -padx 0
    label $in.detail -text [_detail_text] -font ChatMeta -anchor w -justify left \
        -borderwidth 0 -padx 0 -wraplength 360
    foreach w [list $in.title $in.detail] {
        ::vmdai::theme::paint $w -background warn_bg -foreground warn_fg
    }
    grid $in.icon -row 0 -column 0 -rowspan 2 -sticky n -padx {0 8} -pady {1 0}
    grid $in.title -row 0 -column 1 -sticky w
    grid $in.detail -row 1 -column 1 -sticky w
    if {$S(kind) eq "didnt_start"} {
        label $in.more -text [expr {$S(details) ? "Hide details" : "Show details"}] \
            -font ChatMeta -cursor hand2 -borderwidth 0 -padx 0
        ::vmdai::theme::paint $in.more -background warn_bg -foreground accent
        bind $in.more <ButtonRelease-1> ::vmdai::banner::toggle_details
        grid $in.more -row 2 -column 1 -sticky w -pady {2 0}
        label $in.tail -text [_tail_text] -font ChatCodeSmall -anchor w -justify left \
            -borderwidth 0 -padx 0
        ::vmdai::theme::paint $in.tail -background warn_bg -foreground warn_fg
        grid $in.tail -row 3 -column 1 -sticky w -pady {4 0}
        if {!$S(details)} { grid remove $in.tail }
    }
    frame $in.btns -borderwidth 0 -highlightthickness 0
    ::vmdai::theme::paint $in.btns -background warn_bg
    set i 0
    foreach {label action} [_buttons $S(kind)] {
        _pill $in.btns.$action $label $action [expr {$i == 0}]
        pack $in.btns.$action -side left -padx {0 6}
        incr i
    }
    grid columnconfigure $in 1 -weight 1
    pack $in -side top -fill x -padx 16 -pady 10
    set S(lastw) 0
    _relayout [winfo width $P]
}

# Buttons beside the text, or under it below 440 px (V6 narrow rules).
proc ::vmdai::banner::_relayout {w} {
    variable P
    variable S
    if {![winfo exists $P.in.btns]} { return }
    if {$w <= 1} { set w 560 }
    set narrow [expr {$w < 440}]
    if {$narrow == $S(narrow) && $S(lastw) != 0} { return }
    set S(narrow) $narrow
    set S(lastw) $w
    grid forget $P.in.btns
    if {$narrow} {
        grid $P.in.btns -row 4 -column 1 -sticky w -pady {8 0}
    } else {
        grid $P.in.btns -row 0 -column 2 -rowspan 2 -sticky e -padx {12 0}
    }
    $P.in.detail configure -wraplength [expr {$narrow ? $w - 70 : max(200, $w - 300)}]
}

# A rounded pill on the tinted surface (native's pill): the first is filled.
proc ::vmdai::banner::_pill {w label action primary} {
    set tw [font measure ChatMetaBold $label]
    set width [expr {$tw + 22}]
    set height 24
    canvas $w -width $width -height $height -borderwidth 0 -highlightthickness 1 \
        -takefocus 1 -cursor hand2
    ::vmdai::theme::paint $w -background warn_bg -highlightbackground warn_bg \
        -highlightcolor focus_ring
    if {$primary} {
        set fill [::vmdai::theme::c warn_fg]
        set fg [::vmdai::theme::c warn_bg]
        set edge $fill
    } else {
        set fill [::vmdai::theme::c warn_bg]
        set fg [::vmdai::theme::c warn_fg]
        set edge [::vmdai::theme::c warn_bd]
    }
    ::vmdai::theme::rrect $w 1 1 [expr {$width - 1}] [expr {$height - 1}] 7 \
        -fill $fill -outline $edge -width 1
    $w create text [expr {$width / 2.0}] [expr {$height / 2.0}] -text $label \
        -font ChatMetaBold -fill $fg -tags label
    foreach seq {<ButtonRelease-1> <space> <Return>} {
        bind $w $seq [list ::vmdai::banner::_action $action]
    }
    return $w
}

proc ::vmdai::banner::_tail_text {} {
    set lines [_rt pipe_tail 12]
    set log ""
    if {[info commands ::vmdai::config::log_path] ne ""} {
        catch {set log [::vmdai::config::log_path]}
    }
    set out [join $lines "\n"]
    if {$out eq ""} { set out "(the runtime printed nothing)" }
    if {$log ne ""} { append out "\n\nLog: $log" }
    return $out
}

proc ::vmdai::banner::toggle_details {} {
    variable S
    set S(details) [expr {!$S(details)}]
    _rebuild
}

# ---- countdown while reconnecting ---------------------------------------------
#
# The runtime probes after runtime::backoff_ms attempt (0.5, 1, 2, 4, then 8 s);
# the banner counts the same schedule down, one second at a time.

proc ::vmdai::banner::_start_countdown {attempt} {
    variable S
    _stop_countdown
    set S(attempt) $attempt
    set S(remaining) [_backoff_s $attempt]
    set S(tick) [::vmdai::sched::after 1000 ::vmdai::banner::_tick]
}

proc ::vmdai::banner::_stop_countdown {} {
    variable S
    if {[info exists S(tick)] && $S(tick) ne ""} { ::vmdai::sched::cancel $S(tick) }
    set S(tick) ""
    set S(attempt) 0
    set S(remaining) 0
}

proc ::vmdai::banner::_tick {} {
    variable S
    if {$S(tick) ne ""} { ::vmdai::sched::cancel $S(tick) }
    set S(tick) ""
    if {$S(kind) ne "unreachable" || $S(attempt) == 0} { return }
    if {$S(remaining) > 0} {
        incr S(remaining) -1
    } else {
        incr S(attempt)
        set S(remaining) [_backoff_s $S(attempt)]
    }
    _set_detail [_detail_text]
    set S(tick) [::vmdai::sched::after 1000 ::vmdai::banner::_tick]
}

# ---- actions ----------------------------------------------------------------------

proc ::vmdai::banner::_call {target args} {
    if {[info commands $target] eq ""} { return }
    uplevel #0 [list $target {*}$args]
}

proc ::vmdai::banner::_action {name} {
    variable on_action
    variable S
    if {$S(kind) eq "unreachable" && $S(attempt) > 0 && $name eq "retry_now"} {
        _start_countdown 1
        _set_detail [_detail_text]
    }
    if {$on_action ne ""} {
        return [uplevel #0 [list {*}$on_action $name]]
    }
    switch -- $name {
        retry_now - retry { _call ::vmdai::runtime::retry_now }
        open_log { _call ::vmdai::panel::open_log }
        choose_python { _call ::vmdai::panel::open_settings panel }
        restart {
            _call ::vmdai::runtime::stop
            _call ::vmdai::runtime::ensure
        }
    }
}
