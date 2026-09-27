# toolbar.tcl -- ChatVMD toolbar (Part B V4 "Toolbar").
#
#   ::vmdai::toolbar::create path ?-onaction cmd?
#   ::vmdai::toolbar::set_title s     the chat title, centred and ellipsized
#   ::vmdai::toolbar::set_busy on     New chat and History are off while a request runs
#   ::vmdai::toolbar::menu_items      -> the ⋯ menu: {label action} items, "-" for separators
#   ::vmdai::toolbar::tooltip w text  show text under w after 600 ms (any widget)
#
# Canvas icons (New chat, History | title | ⋯, Settings) take focus, show a
# plate on hover and focus, and activate on click, Space or Return. Actions
# go to the -onaction callback when set, else to the panel procs of the same
# name (plan 09); a missing target is skipped. Tests set opt(tip_map) 0: the
# tooltip window is filled in but never mapped.

namespace eval ::vmdai::toolbar {
    variable P
    if {![info exists P]} { set P "" }
    variable on_action
    if {![info exists on_action]} { set on_action "" }
    variable opt
    if {![info exists opt]} { array set opt {tip_map 1 tip_delay 600} }
    variable tips
    if {![info exists tips]} { array set tips {} }
    variable expand
    if {![info exists expand]} { set expand 0 }
    variable S
    if {![info exists S]} { array set S {} }
}

proc ::vmdai::toolbar::_reset {} {
    variable S
    array unset S
    array set S {busy 0 title "" tip_id "" tip_for "" hover ""}
}

proc ::vmdai::toolbar::_mod {} {
    return [expr {[tk windowingsystem] eq "aqua" ? "Command" : "Control"}]
}

proc ::vmdai::toolbar::_key_hint {key} {
    return [expr {[tk windowingsystem] eq "aqua" ? "⌘$key" : "Ctrl+$key"}]
}

# The ⋯ menu (Part B V4): {kind label action ?accelerator-key?}.
proc ::vmdai::toolbar::_menu_spec {} {
    return {
        {command "New chat" new_chat N}
        {command "History…" open_history}
        {separator}
        {command "Copy chat Tcl" copy_chat_tcl}
        {command "Save chat .tcl…" save_chat_tcl}
        {separator}
        {command "Open runs folder" open_runs_folder}
        {separator}
        {check "Expand all steps" set_expand_all E}
        {command "Collapse older runs" collapse_older}
        {separator}
        {command "Settings…" open_settings ,}
        {command "Open runtime log" open_log}
        {command "Quit AI runtime" quit_runtime}
    }
}

proc ::vmdai::toolbar::create {path args} {
    variable P
    variable on_action
    set on_action ""
    foreach {opt value} $args {
        if {$opt ne "-onaction"} { error "unknown option \"$opt\": must be -onaction" }
        set on_action $value
    }
    if {[winfo exists $path]} { destroy $path }
    _reset
    set P $path
    frame $path -borderwidth 0 -highlightthickness 0
    _icon $path.new compose new_chat "New chat ([_key_hint N])"
    _icon $path.hist history open_history "History"
    label $path.title -font ChatMetaBold -anchor center -width 1 -borderwidth 0 -padx 0
    _icon $path.more more more "More"
    _icon $path.gear gear open_settings "Settings ([_key_hint ,])"
    grid $path.new -row 0 -column 0 -padx {8 0} -pady 5
    grid $path.hist -row 0 -column 1 -pady 5
    grid $path.title -row 0 -column 2 -sticky ew -padx 8
    grid $path.more -row 0 -column 3 -pady 5
    grid $path.gear -row 0 -column 4 -padx {0 8} -pady 5
    grid columnconfigure $path 2 -weight 1
    ::vmdai::theme::paint $path -background chrome
    ::vmdai::theme::paint $path.title -background chrome -foreground text
    menu $path.more.m -tearoff 0 -postcommand ::vmdai::toolbar::_sync_menu
    foreach item [_menu_spec] {
        lassign $item kind label action key
        set accel {}
        if {$key ne ""} { set accel [list -accelerator "[_mod]-$key"] }
        switch -- $kind {
            separator { $path.more.m add separator }
            check {
                $path.more.m add checkbutton -label $label {*}$accel \
                    -variable ::vmdai::toolbar::expand -command ::vmdai::toolbar::_toggle_expand
            }
            default {
                $path.more.m add command -label $label {*}$accel \
                    -command [list ::vmdai::toolbar::_action $action]
            }
        }
    }
    bind $path <Configure> ::vmdai::toolbar::_fit_title
    ::vmdai::theme::on_repaint ::vmdai::toolbar::_redraw
    return $path
}

# A borderless icon button: a rounded plate on hover and focus, like a
# macOS toolbar item. Click, Space and Return activate it.
proc ::vmdai::toolbar::_icon {w kind action tip} {
    canvas $w -width 30 -height 26 -borderwidth 0 -highlightthickness 0 -takefocus 1 -cursor hand2
    ::vmdai::theme::paint $w -background chrome
    set ::vmdai::toolbar::S(kind,$w) $kind
    set ::vmdai::toolbar::S(action,$w) $action
    _draw_icon $w
    bind $w <Enter> [list ::vmdai::toolbar::_hover $w 1]
    bind $w <Leave> [list ::vmdai::toolbar::_hover $w 0]
    bind $w <FocusIn> [list ::vmdai::toolbar::_draw_icon $w]
    bind $w <FocusOut> [list ::vmdai::toolbar::_draw_icon $w]
    foreach seq {<ButtonRelease-1> <space> <Return>} {
        bind $w $seq [list ::vmdai::toolbar::_activate $w]
    }
    tooltip $w $tip
    return $w
}

proc ::vmdai::toolbar::_enabled {w} {
    variable S
    return [expr {!($S(busy) && $S(action,$w) in {new_chat open_history})}]
}

proc ::vmdai::toolbar::_hover {w on} {
    variable S
    set S(hover) [expr {$on ? $w : ""}]
    _draw_icon $w
}

proc ::vmdai::toolbar::_draw_icon {w} {
    variable S
    if {![winfo exists $w]} { return }
    $w delete all
    set on [expr {[_enabled $w] && ($S(hover) eq $w || [::focus] eq $w)}]
    if {$on} {
        ::vmdai::theme::rrect $w 1 1 29 25 6 -fill [::vmdai::theme::c hover] -outline "" -tags plate
    }
    set col [::vmdai::theme::c [expr {[_enabled $w] ? "muted" : "faint"}]]
    $w configure -cursor [expr {[_enabled $w] ? "hand2" : "arrow"}]
    _glyph $w $S(kind,$w) 15 13 $col
}

# Native's icon glyphs (docs/design/round1/prototypes/native/proto.tcl).
proc ::vmdai::toolbar::_glyph {c kind cx cy col} {
    switch -- $kind {
        compose {
            $c create line [expr {$cx-2}] [expr {$cy-6}] [expr {$cx-6}] [expr {$cy-6}] \
                [expr {$cx-6}] [expr {$cy+6}] [expr {$cx+6}] [expr {$cy+6}] [expr {$cx+6}] [expr {$cy+1}] \
                -width 1.4 -fill $col -capstyle round -joinstyle round -tags glyph
            $c create line [expr {$cx-1}] [expr {$cy+2}] [expr {$cx+7}] [expr {$cy-6}] \
                -width 1.4 -fill $col -capstyle round -tags glyph
        }
        history {
            $c create oval [expr {$cx-7}] [expr {$cy-7}] [expr {$cx+7}] [expr {$cy+7}] \
                -width 1.4 -outline $col -tags glyph
            $c create line $cx [expr {$cy-4}] $cx $cy [expr {$cx+3}] [expr {$cy+2}] \
                -width 1.4 -fill $col -capstyle round -joinstyle round -tags glyph
        }
        more {
            foreach dx {-5 0 5} {
                $c create oval [expr {$cx+$dx-1.3}] [expr {$cy-1.3}] [expr {$cx+$dx+1.3}] \
                    [expr {$cy+1.3}] -fill $col -outline "" -tags glyph
            }
        }
        gear {
            set pts {}
            set n 8
            for {set i 0} {$i < $n * 4} {incr i} {
                set a [expr {($i / double($n * 4)) * 6.2831853 - 1.5707963 - 3.1415926 / ($n * 4)}]
                set r [expr {($i % 4) == 1 || ($i % 4) == 2 ? 7.4 : 5.5}]
                lappend pts [expr {$cx + $r * cos($a)}] [expr {$cy + $r * sin($a)}]
            }
            $c create polygon $pts -fill "" -outline $col -width 1.3 -joinstyle round -tags glyph
            $c create oval [expr {$cx-2.3}] [expr {$cy-2.3}] [expr {$cx+2.3}] [expr {$cy+2.3}] \
                -outline $col -width 1.3 -tags glyph
        }
    }
}

proc ::vmdai::toolbar::_redraw {} {
    variable P
    if {$P eq "" || ![winfo exists $P]} { return }
    foreach w [list $P.new $P.hist $P.more $P.gear] { _draw_icon $w }
}

proc ::vmdai::toolbar::_activate {w} {
    variable S
    if {![_enabled $w]} { return }
    _tip_leave
    if {$S(action,$w) eq "more"} {
        _post_menu
        return
    }
    _action $S(action,$w)
}

proc ::vmdai::toolbar::_post_menu {} {
    variable P
    set b $P.more
    tk_popup $P.more.m [winfo rootx $b] [expr {[winfo rooty $b] + [winfo height $b]}]
}

# Before the menu shows: the busy state and the transcript's expand flag.
proc ::vmdai::toolbar::_sync_menu {} {
    variable P
    variable S
    variable expand
    set state [expr {$S(busy) ? "disabled" : "normal"}]
    $P.more.m entryconfigure 0 -state $state
    $P.more.m entryconfigure 1 -state $state
    if {[info exists ::vmdai::transcript::expand_all]} {
        set expand $::vmdai::transcript::expand_all
    }
}

proc ::vmdai::toolbar::_toggle_expand {} {
    variable expand
    _action set_expand_all $expand
}

proc ::vmdai::toolbar::menu_items {} {
    variable P
    set m $P.more.m
    set out {}
    for {set i 0} {$i <= [$m index end]} {incr i} {
        if {[$m type $i] eq "separator"} {
            lappend out -
            continue
        }
        lappend out [list [$m entrycget $i -label] [lindex [lindex [_menu_spec] $i] 2]]
    }
    return $out
}

proc ::vmdai::toolbar::set_title {s} {
    variable S
    set S(title) $s
    _fit_title
}

# The room left between the icons: the bar's width minus four 30 px icons
# and the padding (8 + 8 at the edges, 8 + 8 around the title).
proc ::vmdai::toolbar::_title_room {} {
    variable P
    set w [winfo width $P]
    if {$w <= 1} { return -1 }
    return [expr {$w - 4 * 30 - 32}]
}

proc ::vmdai::toolbar::_fit_title {} {
    variable P
    variable S
    if {$P eq "" || ![winfo exists $P.title]} { return }
    set room [_title_room]
    set text $S(title)
    if {$room > 0} { set text [::vmdai::theme::fit ChatMetaBold $room $text] }
    $P.title configure -text $text
}

proc ::vmdai::toolbar::set_busy {on} {
    variable P
    variable S
    set S(busy) [expr {$on ? 1 : 0}]
    if {$P eq "" || ![winfo exists $P]} { return }
    _redraw
    _sync_menu
}

# ---- tooltips (600 ms; Part B V1 "Make tooltips work") ----------------------------

proc ::vmdai::toolbar::tooltip {w text} {
    variable tips
    set tips($w) $text
    bind $w <Enter> +[list ::vmdai::toolbar::_tip_enter $w]
    bind $w <Leave> +::vmdai::toolbar::_tip_leave
    bind $w <ButtonPress> +::vmdai::toolbar::_tip_leave
    bind $w <Destroy> +[list unset -nocomplain ::vmdai::toolbar::tips($w)]
}

proc ::vmdai::toolbar::_tip_enter {w} {
    variable S
    variable opt
    _tip_leave
    set S(tip_id) [::vmdai::sched::after $opt(tip_delay) [list ::vmdai::toolbar::_tip_show $w]]
}

proc ::vmdai::toolbar::_tip_show {w} {
    variable S
    variable opt
    variable tips
    set S(tip_id) ""
    if {![winfo exists $w] || ![info exists tips($w)]} { return }
    set tw .vmd_ai_tip
    if {![winfo exists $tw]} {
        toplevel $tw -borderwidth 0
        wm withdraw $tw
        wm overrideredirect $tw 1
        label $tw.l -font ChatMeta -borderwidth 1 -relief solid -padx 6 -pady 2
        pack $tw.l
    }
    $tw.l configure -text $tips($w) -background [::vmdai::theme::c surface] \
        -foreground [::vmdai::theme::c text]
    set S(tip_for) $w
    if {$opt(tip_map)} {
        wm geometry $tw +[winfo rootx $w]+[expr {[winfo rooty $w] + [winfo height $w] + 4}]
        wm deiconify $tw
        raise $tw
    }
}

proc ::vmdai::toolbar::_tip_leave {} {
    variable S
    if {$S(tip_id) ne ""} {
        ::vmdai::sched::cancel $S(tip_id)
        set S(tip_id) ""
    }
    set S(tip_for) ""
    if {[winfo exists .vmd_ai_tip]} { wm withdraw .vmd_ai_tip }
}

# The widget whose tooltip is showing, or "".
proc ::vmdai::toolbar::tip_shown {} {
    variable S
    return $S(tip_for)
}

# ---- actions ----------------------------------------------------------------------

proc ::vmdai::toolbar::_call {target args} {
    if {[info commands $target] eq ""} { return }
    uplevel #0 [list $target {*}$args]
}

proc ::vmdai::toolbar::_action {name args} {
    variable on_action
    if {$on_action ne ""} {
        return [uplevel #0 [list {*}$on_action $name {*}$args]]
    }
    switch -- $name {
        new_chat         { _call ::vmdai::panel::new_chat }
        open_history     { _call ::vmdai::panel::open_history }
        copy_chat_tcl    { _call ::vmdai::panel::copy_chat_tcl }
        save_chat_tcl    { _call ::vmdai::panel::save_chat_tcl }
        open_runs_folder { _call ::vmdai::panel::open_runs_folder }
        set_expand_all   { _call ::vmdai::panel::set_expand_all {*}$args }
        collapse_older   { _call ::vmdai::panel::collapse_older }
        open_settings    { _call ::vmdai::panel::open_settings }
        open_log         { _call ::vmdai::panel::open_log }
        quit_runtime     { _call ::vmdai::panel::quit_runtime }
    }
}
