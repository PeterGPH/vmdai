# transcript.tcl -- ChatVMD transcript: render ops -> one read-only text widget.
#
#   ::vmdai::transcript::create path     -> path.t, the read-only Text (path is
#                                           the frame the caller grids)
#   ::vmdai::transcript::apply_ops ops    draw each op with its op_<name> proc
#   ::vmdai::transcript::dump             -> "images N", then one line per
#                                           displayed text line (Tk goldens)
#   ::vmdai::transcript::clear            empty it and free every photo
#   ::vmdai::transcript::relayout         margins, tab stops, row refit
#   ::vmdai::transcript::jump_to call_key show, scroll to and flash a row
#
# Part B V4 "Transcript blocks", V5 "Scrolling", V6, S2. The real text
# command is renamed to ::vmdai::transcript::_w (the variable W); path.t
# becomes a proxy that drops insert, delete and replace and passes every
# other subcommand (tag, mark, peer, get, search, yview, see, ...). The
# transcript can take focus, select and copy, but no binding can edit it,
# and it is never -state disabled. Every element ends with its own newline,
# so prose, reasoning, notes and tool rows never share a line (S2).

namespace eval ::vmdai::transcript {
    variable W
    if {![info exists W]} { set W "" }
    variable T
    if {![info exists T]} { set T "" }
    variable F
    if {![info exists F]} { set F "" }
    variable opt
    if {![info exists opt]} { array set opt {animate 1} }
    variable on_action
    if {![info exists on_action]} { set on_action "" }
    variable S
    if {![info exists S]} { array set S {} }
    variable B
    if {![info exists B]} { array set B {} }
}

proc ::vmdai::transcript::_reset {} {
    variable S
    variable B
    array unset S
    array set S {cur_run "" answer 0 lastw 0 relayout "" link 0 rules {} photos {}
                 last_user "" flash "" tick "" errors 0 last_error ""}
    array unset B
    array set B {}
}

# ---- widget -------------------------------------------------------------------

proc ::vmdai::transcript::create {path} {
    variable W
    variable T
    variable F
    if {$F ne "" && [winfo exists $F]} { destroy $F }
    if {[winfo exists $path]} { destroy $path }
    catch {rename ::vmdai::transcript::_w {}}
    _reset
    set F $path
    frame $path -borderwidth 0 -highlightthickness 0
    set T $path.t
    text $T -wrap word -borderwidth 0 -highlightthickness 0 -padx 20 -pady 14 \
        -cursor arrow -exportselection 1 -undo 0 -takefocus 1 -insertwidth 0 \
        -width 10 -height 10 -font ChatBody \
        -yscrollcommand [list ::vmdai::transcript::_on_yview]
    ttk::scrollbar $path.sb -orient vertical -command [list $T yview]
    grid $T -row 0 -column 0 -sticky nsew
    grid $path.sb -row 0 -column 1 -sticky ns
    grid columnconfigure $path 0 -weight 1
    grid rowconfigure $path 0 -weight 1
    set W ::vmdai::transcript::_w
    rename ::$T $W
    proc ::$T {args} {
        if {[lindex $args 0] in {insert delete replace}} { return }
        uplevel 1 [list ::vmdai::transcript::_w {*}$args]
    }
    ::vmdai::theme::paint $path -background surface
    ::vmdai::theme::paint $T -background surface -foreground text \
        -selectbackground sel -inactiveselectbackground sel
    canvas $path.pill -highlightthickness 0 -borderwidth 0 -cursor hand2
    bind $path.pill <ButtonRelease-1> ::vmdai::transcript::_pill_clicked
    _tags
    ::vmdai::theme::on_repaint ::vmdai::transcript::_tags
    bind $T <1> {+focus %W}
    bind $T <Configure> [list ::vmdai::transcript::_on_configure %w]
    bind $T <Destroy> [list ::vmdai::transcript::_on_destroy %W]
    foreach seq [_menu_sequences] {
        bind $T $seq [list ::vmdai::transcript::_context %x %y %X %Y]
    }
    bind ChatVMDScroll <MouseWheel> {::vmdai::transcript::_wheel %D}
    return $T
}

proc ::vmdai::transcript::_on_destroy {w} {
    variable T
    variable S
    if {$w ne $T} { return }
    catch {rename ::$w {}}
    foreach key {relayout flash tick} {
        if {[info exists S($key)] && $S($key) ne ""} { ::vmdai::sched::cancel $S($key) }
    }
    if {[info exists S(photos)]} {
        foreach p $S(photos) { catch {image delete $p} }
        set S(photos) {}
    }
}

# Style tags (no ":" in the name) are what the Tk goldens show; per-item
# tags (row:$k, blk:$b, act:N, wl:$run, ...) carry state and bindings.
proc ::vmdai::transcript::_tags {} {
    variable W
    variable F
    if {$W eq "" || [info commands $W] eq ""} { return }
    set C ::vmdai::theme::c
    $W tag configure role -font ChatRole -foreground [$C text] -spacing1 20 -spacing3 4
    $W tag configure rolemeta -font ChatMeta -foreground [$C muted]
    $W tag configure user -font ChatBody -foreground [$C text] -spacing3 8
    $W tag configure prose -font ChatBody -foreground [$C text] -spacing3 8
    $W tag configure think -font ChatBodyItal -foreground [$C muted] -spacing1 4 -spacing3 4
    $W tag configure thinkbody -font ChatMeta -foreground [$C muted] \
        -lmargin1 24 -lmargin2 24 -spacing3 6
    $W tag configure note -font ChatMeta -foreground [$C muted] -justify center \
        -spacing1 12 -spacing3 4
    $W tag configure notewarn -foreground [$C warn]
    $W tag configure ecard -background [$C err_bg] -lmargin1 12 -lmargin2 12 -rmargin 12
    $W tag configure ecard_t -font ChatBodyBold -foreground [$C text] -spacing1 10
    $W tag configure ecard_x -foreground [$C err]
    $W tag configure ecard_h -font ChatMeta -foreground [$C muted] -spacing1 2
    $W tag configure ecard_c -font ChatCodeSmall -foreground [$C text] -spacing1 2
    $W tag configure ecard_a -font ChatMeta -spacing1 6 -spacing3 10
    $W tag configure rule -spacing1 8 -spacing3 8
    $W tag configure flash -background [$C hover]
    $W tag configure link -foreground [$C accent]
    catch {$W tag configure ecard -lmargincolor [$C err_bg] -rmargincolor [$C err_bg]}
    $W tag bind link <Enter> [list $W configure -cursor hand2]
    $W tag bind link <Leave> [list $W configure -cursor arrow]
    foreach extra {_tags_rows _tags_snaps} {
        if {[info commands ::vmdai::transcript::$extra] ne ""} { $extra }
    }
    $W tag raise sel
    _draw_pill
}

# ---- ops ------------------------------------------------------------------------

proc ::vmdai::transcript::apply_ops {ops} {
    variable W
    variable S
    if {$W eq "" || [info commands $W] eq ""} { return }
    set bottom [_at_bottom]
    set before [$W index "end -1c"]
    foreach op $ops {
        set name [lindex $op 0]
        if {[info commands ::vmdai::transcript::op_$name] eq ""} { continue }
        if {[catch {op_$name {*}[lrange $op 1 end]} err]} {
            incr S(errors)
            set S(last_error) "$name: $err"
            catch {::vmdai::config::log "transcript: $name failed: $err"}
        }
    }
    if {$bottom} {
        $W see end
        _pill 0
    } elseif {[$W compare "end -1c" != $before]} {
        _pill 1
    }
}

# Blocks inside a run's work log get wl:$run (collapse, P08-T06); the
# answer after the run's rule does not.
proc ::vmdai::transcript::_wl {} {
    variable S
    if {$S(cur_run) eq "" || $S(answer)} { return {} }
    return [list wl:$S(cur_run)]
}

proc ::vmdai::transcript::_clock {secs} {
    if {![string is wide -strict $secs] || $secs <= 0} { return "" }
    return [string trimleft [clock format $secs -format "%I:%M %p"] 0]
}

proc ::vmdai::transcript::op_block.open {b role turn {time ""}} {
    variable W
    variable B
    variable S
    if {[info exists B($b,tags)]} { return }
    if {$role eq "user"} {
        set S(cur_run) ""
        set S(answer) 0
        set S(last_user) ""
        $W insert end "You" role "\t" role [_clock $time] {role rolemeta} "\n" role
        set B($b,kind) user
        set B($b,tags) [list user blk:$b]
    } else {
        set B($b,kind) text
        set B($b,tags) [concat prose blk:$b [_wl]]
    }
    $W insert end "\n" $B($b,tags)
}

proc ::vmdai::transcript::op_block.append {b text} {
    variable W
    variable B
    variable S
    if {![info exists B($b,tags)]} { return }
    if {$B($b,kind) eq "user"} { append S(last_user) $text }
    set z [lindex [$W tag ranges blk:$b] end]
    $W insert "$z -1c" $text $B($b,tags)
}

# The canonical text replaces what was streamed, in place (§2c Sealing).
proc ::vmdai::transcript::op_block.seal {b canonical} {
    variable W
    variable B
    if {![info exists B($b,tags)]} { return }
    set r [$W tag ranges blk:$b]
    set at [lindex $r 0]
    $W delete $at "[lindex $r end] -1c"
    set text [string trimright $canonical "\n"]
    set tags $B($b,tags)
    $W insert $at $text $tags
    set B($b,sealed) 1
}

proc ::vmdai::transcript::op_block.discard {b} {
    variable W
    variable B
    if {![info exists B($b,tags)]} { return }
    set r [$W tag ranges blk:$b]
    if {[llength $r]} { $W delete [lindex $r 0] [lindex $r end] }
    array unset B $b,*
}

# Reasoning: one muted italic line, "Thinking…" while it streams and
# "Thought for N s ▸" once sealed; a click shows the text underneath.
proc ::vmdai::transcript::op_reasoning.open {b turn} {
    variable W
    variable B
    if {[info exists B($b,tags)]} { return }
    set wl [_wl]
    set B($b,kind) reasoning
    set B($b,tags) [concat think think:$b $wl]
    set B($b,body) [concat thinkbody tb:$b $wl]
    set B($b,sealed) 0
    set B($b,open) 0
    $W insert end "Thinking…" $B($b,tags) "\n" $B($b,tags) "\n" $B($b,body)
    $W tag configure tb:$b -elide 1
    $W tag bind think:$b <ButtonRelease-1> [list ::vmdai::transcript::toggle_think $b]
}

proc ::vmdai::transcript::op_reasoning.append {b text} {
    variable W
    variable B
    if {![info exists B($b,body)]} { return }
    set z [lindex [$W tag ranges tb:$b] end]
    $W insert "$z -1c" $text $B($b,body)
}

proc ::vmdai::transcript::op_reasoning.seal {b duration_s} {
    variable B
    if {![info exists B($b,body)]} { return }
    set secs 1
    if {[string is double -strict $duration_s] && $duration_s >= 1} {
        set secs [expr {int(round($duration_s))}]
    }
    set B($b,secs) $secs
    set B($b,sealed) 1
    _think_head $b
}

proc ::vmdai::transcript::_think_head {b} {
    variable W
    variable B
    set label "Thought for $B($b,secs) s [expr {$B($b,open) ? "▾" : "▸"}]"
    set r [$W tag ranges think:$b]
    set at [lindex $r 0]
    $W delete $at "[lindex $r end] -1c"
    $W insert $at $label $B($b,tags)
}

proc ::vmdai::transcript::toggle_think {b} {
    variable W
    variable B
    if {![info exists B($b,sealed)] || !$B($b,sealed)} { return }
    set B($b,open) [expr {!$B($b,open)}]
    $W tag configure tb:$b -elide [expr {!$B($b,open)}]
    _think_head $b
}

# Timeline notes: centred, muted, one line each (Part B V4).
proc ::vmdai::transcript::op_notice {level text {action ""}} {
    variable W
    set tags [list note]
    if {$level eq "warn"} { lappend tags notewarn }
    $W insert end $text $tags
    if {$action ne ""} {
        $W insert end " · " $tags [_action_label $action ""] [concat $tags link [_link $action]]
    }
    $W insert end "\n" $tags
}

# One card per error: ✗ and the title, the hint (a copyable command for
# model_not_found), then the action link (Part B V4 "Error cards").
proc ::vmdai::transcript::op_error.card {code title hint action} {
    variable W
    set t [list ecard ecard_t]
    $W insert end "✗ " [concat $t ecard_x] $title $t "\n" $t
    if {$hint ne ""} {
        if {$code eq "model_not_found"} {
            set h [list ecard ecard_c]
            $W insert end $hint $h "   " $h "Copy" [concat $h link [_link copy_text $hint]] "\n" $h
        } else {
            $W insert end $hint {ecard ecard_h} "\n" {ecard ecard_h}
        }
    }
    set a [list ecard ecard_a]
    $W insert end [_action_label $action $code] [concat $a link [_link $action]] "\n" $a
}

# The hairline before a run's final answer; what follows is the answer.
proc ::vmdai::transcript::op_rule {run} {
    variable W
    variable T
    variable S
    set S(cur_run) $run
    set S(answer) 1
    set f $T.rule[llength $S(rules)]
    frame $f -height 1 -width [_content_width] -borderwidth 0 -highlightthickness 0
    ::vmdai::theme::paint $f -background hairline
    lappend S(rules) $f
    set at [$W index "end -1c"]
    $W window create $at -window [_embed $f] -align center
    $W insert end "\n" rule
    $W tag add rule $at
}

# ---- links and actions ------------------------------------------------------------

proc ::vmdai::transcript::_link {args} {
    variable W
    variable S
    set tag act:[incr S(link)]
    $W tag bind $tag <ButtonRelease-1> [list ::vmdai::transcript::_action {*}$args]
    return $tag
}

proc ::vmdai::transcript::_action_label {action code} {
    switch -- $action {
        open_settings   { return [expr {$code eq "NO_MODEL" ? "Set up a model" : "Open Settings"}] }
        switch_profile  { return "Switch profile" }
        choose_model    { return "Choose model" }
        test_connection { return "Test connection" }
        open_log        { return "Open log" }
        retry           { return "Retry" }
    }
    return [string totitle [string map {_ " "} $action]]
}

# Run an action: the on_action callback when set (tests), else the target.
# A target that does not exist (yet) is skipped, never an error.
proc ::vmdai::transcript::_action {name args} {
    variable on_action
    if {$on_action ne ""} {
        return [uplevel #0 [list {*}$on_action $name {*}$args]]
    }
    switch -- $name {
        open_settings - switch_profile - choose_model - test_connection {
            _call ::vmdai::panel::open_settings
        }
        open_log  { _call ::vmdai::panel::open_log }
        copy_text { _clipboard [lindex $args 0] }
        default   { _call ::vmdai::transcript::_do_$name {*}$args }
    }
}

proc ::vmdai::transcript::_call {target args} {
    if {[info commands $target] eq ""} { return }
    uplevel #0 [list $target {*}$args]
}

proc ::vmdai::transcript::_clipboard {text} {
    clipboard clear
    clipboard append -- $text
}

# "Reconnected: request lost · Retry" puts the last prompt back in the
# composer; it never sends by itself.
proc ::vmdai::transcript::_do_retry {} {
    variable S
    _call ::vmdai::composer::set_text $S(last_user)
    _call ::vmdai::composer::focus
}

# ---- scrolling: sticky autoscroll and the "↓ New output" pill (V5) --------------

proc ::vmdai::transcript::_at_bottom {} {
    variable W
    return [expr {[lindex [$W yview] 1] >= 0.999}]
}

proc ::vmdai::transcript::_on_yview {first last} {
    variable F
    if {[winfo exists $F.sb]} { $F.sb set $first $last }
    if {$last >= 0.999} { _pill 0 }
}

proc ::vmdai::transcript::_draw_pill {} {
    variable F
    if {![winfo exists $F.pill]} { return }
    set c $F.pill
    $c delete all
    set text "↓ New output"
    set w [expr {[font measure ChatMetaBold $text] + 24}]
    set h [expr {[font metrics ChatMetaBold -linespace] + 10}]
    $c configure -width $w -height $h -background [::vmdai::theme::c surface]
    ::vmdai::theme::rrect $c 0 0 $w $h [expr {$h / 2}] -fill [::vmdai::theme::c accent] -outline ""
    $c create text [expr {$w / 2}] [expr {$h / 2}] -text $text -font ChatMetaBold \
        -fill [::vmdai::theme::c surface]
}

proc ::vmdai::transcript::_pill {on} {
    variable F
    if {![winfo exists $F.pill]} { return }
    if {$on} {
        place $F.pill -in $F -relx 1.0 -rely 1.0 -anchor se -x -28 -y -12
        raise $F.pill
    } else {
        place forget $F.pill
    }
}

proc ::vmdai::transcript::pill_shown {} {
    variable F
    return [expr {[winfo exists $F.pill] && [winfo manager $F.pill] eq "place"}]
}

proc ::vmdai::transcript::_pill_clicked {} {
    variable W
    $W yview moveto 1.0
    _pill 0
}

# Embedded windows get the ChatVMDScroll bindtag, so the wheel keeps
# scrolling the transcript over a card (V5, cards' CVScroll).
proc ::vmdai::transcript::_embed {w} {
    bindtags $w [concat ChatVMDScroll [bindtags $w]]
    return $w
}

proc ::vmdai::transcript::_wheel {delta} {
    variable W
    if {$W eq "" || [info commands $W] eq ""} { return }
    if {[tk windowingsystem] eq "aqua"} {
        $W yview scroll [expr {-$delta}] units
    } else {
        $W yview scroll [expr {-$delta / 120}] units
    }
}

# ---- layout (V6) ------------------------------------------------------------------

proc ::vmdai::transcript::_content_width {} {
    variable T
    set w [winfo width $T]
    if {$w < 100} { return 480 }
    return [expr {$w - 2 * [$T cget -padx] - 2}]
}

proc ::vmdai::transcript::_on_configure {width} {
    variable S
    if {$width == $S(lastw)} { return }
    set S(lastw) $width
    if {$S(relayout) ne ""} { ::vmdai::sched::cancel $S(relayout) }
    set S(relayout) [::vmdai::sched::after_idle ::vmdai::transcript::relayout]
}

proc ::vmdai::transcript::relayout {} {
    variable W
    variable T
    variable S
    set S(relayout) ""
    if {$W eq "" || ![winfo exists $T]} { return }
    set narrow [expr {[winfo width $T] > 1 && [winfo width $T] < 440}]
    $T configure -padx [expr {$narrow ? 14 : 20}]
    set cw [_content_width]
    $W tag configure role -tabs [list $cw right]
    set rm [expr {$cw > 680 ? $cw - 680 : 0}]
    foreach tag {prose user} { $W tag configure $tag -rmargin $rm }
    foreach f $S(rules) {
        if {[winfo exists $f]} { $f configure -width $cw }
    }
    foreach hook {_relayout_rows _relayout_snaps} {
        if {[info commands ::vmdai::transcript::$hook] ne ""} { $hook $cw $narrow }
    }
}

# ---- navigation ---------------------------------------------------------------------

# Show the row's run if it is collapsed, scroll to the row, flash it 600 ms.
proc ::vmdai::transcript::jump_to {k} {
    variable W
    set r [$W tag ranges row:$k]
    if {![llength $r]} { return 0 }
    foreach tag [$W tag names [lindex $r 0]] {
        if {[string match wl:* $tag]} { _show_run [string range $tag 3 end] }
    }
    $W see [lindex $r 0]
    _flash $r
    return 1
}

proc ::vmdai::transcript::_show_run {run} {
    variable W
    if {[info commands ::vmdai::transcript::_collapse] ne ""} {
        _collapse $run 0
    } else {
        $W tag configure wl:$run -elide 0
    }
}

proc ::vmdai::transcript::_flash {range} {
    variable W
    variable S
    variable opt
    if {$S(flash) ne ""} { ::vmdai::sched::cancel $S(flash) }
    $W tag remove flash 1.0 end
    $W tag add flash {*}$range
    set S(flash) ""
    if {$opt(animate)} {
        set S(flash) [::vmdai::sched::after 600 [list ::vmdai::transcript::_unflash]]
    }
}

proc ::vmdai::transcript::_unflash {} {
    variable W
    variable S
    set S(flash) ""
    if {$W ne "" && [info commands $W] ne ""} { $W tag remove flash 1.0 end }
}

# ---- context menus (V5) ----------------------------------------------------------

proc ::vmdai::transcript::_menu_sequences {} {
    if {[tk windowingsystem] eq "aqua"} { return {<Button-2> <Control-Button-1>} }
    return {<Button-3>}
}

# menu_items index -> {label command ...}: the item under index picks the
# menu (rows, run headers and snapshots add theirs in P08-T06/T07).
proc ::vmdai::transcript::menu_items {index} {
    variable W
    foreach tag [$W tag names $index] {
        foreach {pattern provider} {row:* _row_menu hdr:* _run_menu snap:* _snap_menu} {
            if {[string match $pattern $tag]
                    && [info commands ::vmdai::transcript::$provider] ne ""} {
                return [$provider [string range $tag [string first : $tag]+1 end]]
            }
        }
    }
    return [list Copy ::vmdai::transcript::_copy_selection \
                 "Select all" [list $W tag add sel 1.0 end]]
}

proc ::vmdai::transcript::_copy_selection {} {
    variable W
    if {[catch {$W get -displaychars sel.first sel.last} s]} { return }
    _clipboard [string map [list "\t" "  "] $s]
}

proc ::vmdai::transcript::_context {x y rx ry} {
    variable T
    set m $T.menu
    catch {destroy $m}
    menu $m -tearoff 0
    foreach {label cmd} [menu_items [$T index @$x,$y]] {
        $m add command -label $label -command $cmd
    }
    tk_popup $m $rx $ry
}

# ---- clear and dump ---------------------------------------------------------------

proc ::vmdai::transcript::clear {} {
    variable W
    variable T
    variable S
    if {$W eq "" || [info commands $W] eq ""} { return }
    foreach hook {_clear_rows _clear_snaps} {
        if {[info commands ::vmdai::transcript::$hook] ne ""} { $hook }
    }
    if {$S(flash) ne ""} { ::vmdai::sched::cancel $S(flash) }
    $W delete 1.0 end
    foreach tag [$W tag names] {
        if {[string first : $tag] >= 0} { $W tag delete $tag }
    }
    foreach mark [$W mark names] {
        if {$mark ni {insert current}} { $W mark unset $mark }
    }
    foreach f $S(rules) { catch {destroy $f} }
    foreach p $S(photos) { catch {image delete $p} }
    set lastw $S(lastw)
    set pending $S(relayout)
    _reset
    set S(lastw) $lastw
    set S(relayout) $pending
    _pill 0
}

# Is the character at index hidden? The highest-priority tag that sets
# -elide decides (count -displaychars does not see embedded windows).
proc ::vmdai::transcript::_elided {index} {
    variable W
    set hidden 0
    foreach tag [$W tag names $index] {
        set e [$W tag cget $tag -elide]
        if {$e ne ""} { set hidden [expr {$e ? 1 : 0}] }
    }
    return $hidden
}

proc ::vmdai::transcript::dump {} {
    variable W
    variable S
    set lines [list "images [llength $S(photos)]"]
    set last [$W index "end -1c"]
    set n [lindex [split $last .] 0]
    for {set i 1} {$i <= $n} {incr i} {
        if {[$W compare $i.0 == $last]} { break }
        if {[$W count -displaychars $i.0 "$i.0 +1 lines"] == 0} { continue }
        set text ""
        foreach {key value index} [$W dump -text -window $i.0 "$i.0 lineend"] {
            if {$key eq "text"} {
                append text [$W get -displaychars $index "$index + [string length $value] chars"]
            } elseif {![_elided $index]} {
                append text [expr {$value in $S(rules) ? "<rule>" : "<card>"}]
            }
        }
        set tags [$W tag names $i.0]
        foreach tag [$W tag names] {
            if {[llength [$W tag nextrange $tag "$i.0 +1c" "$i.0 +1 lines"]]} { lappend tags $tag }
        }
        set style {}
        foreach tag [lsort -unique $tags] {
            if {$tag ne "sel" && [string first : $tag] < 0} { lappend style $tag }
        }
        lappend lines [format "%03d %s | %s" $i [join $style] [string map [list "\t" "⇥"] $text]]
    }
    return "[join $lines \n]\n"
}
