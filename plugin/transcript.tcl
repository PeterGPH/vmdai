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

# ===========================================================================
# Tool rows, step detail, run headers, chips, footers, collapse (P08-T06).
#
# Part B V4 "Tool rows", "Step detail", "Run header", "Collapse"; V6 row
# refit. A row is exactly one display line, keyed by call_key: the glyph
# (glyph:$k), a tab, the command, muted extras, a right tab, the result or
# label, the duration and a chevron, all tagged row:$k. The left-gravity
# mark rowend:$k sits at the start of the line after the row; below it come,
# in this order, the error line (err:$k) or output preview (prev:$k), the
# step detail (detail:$k) and the snapshot card (snap:$k, Task 7).
# ===========================================================================

namespace eval ::vmdai::transcript {
    variable RUN
    if {![info exists RUN]} { array set RUN {} }
    variable ROW
    if {![info exists ROW]} { array set ROW {} }
    variable run_order
    if {![info exists run_order]} { set run_order {} }
    variable expand_all
    if {![info exists expand_all]} { set expand_all 0 }
}

proc ::vmdai::transcript::_tags_rows {} {
    variable W
    set C ::vmdai::theme::c
    $W tag configure runhdr -font ChatRole -foreground [$C text] -spacing1 20 -spacing3 4
    $W tag configure runmodel -font ChatMeta -foreground [$C muted]
    $W tag configure runsum -font ChatMeta -foreground [$C muted]
    $W tag configure chip -font ChatMetaBold
    $W tag configure chip_ok -foreground [$C ok]
    $W tag configure chip_err -foreground [$C err]
    $W tag configure chip_warn -foreground [$C warn]
    $W tag configure chip_running -foreground [$C muted]
    $W tag configure chip_notrun -foreground [$C muted]
    $W tag configure row -spacing1 3 -spacing3 3 -lmargin1 0 -lmargin2 24
    $W tag configure cmd -font ChatCodeSmall -foreground [$C text2]
    $W tag configure snapcmd -font ChatBody -foreground [$C text]
    $W tag configure extra -font ChatMeta -foreground [$C muted]
    $W tag configure meta -font ChatMeta -foreground [$C muted]
    $W tag configure chev -font ChatMeta -foreground [$C muted]
    $W tag configure g_ok -font ChatMetaBold -foreground [$C ok]
    $W tag configure g_err -font ChatMetaBold -foreground [$C err]
    $W tag configure g_warn -font ChatMetaBold -foreground [$C warn]
    $W tag configure g_no -font ChatMetaBold -foreground [$C muted]
    $W tag configure g_run -font ChatMetaBold -foreground [$C muted]
    $W tag configure errline -font ChatCodeSmall -foreground [$C err] \
        -lmargin1 24 -lmargin2 24 -spacing3 4
    $W tag configure preview -font ChatCodeSmall -foreground [$C muted] -lmargin1 24 -lmargin2 24
    $W tag configure detail -font ChatCode -foreground [$C text] -background [$C code_bg] \
        -lmargin1 24 -lmargin2 36 -rmargin 8
    $W tag configure dnote -font ChatMeta -foreground [$C muted]
    $W tag configure dgut -foreground [$C faint]
    $W tag configure dgutx -foreground [$C err]
    $W tag configure dcode
    $W tag configure dfail -background [$C err_bg]
    $W tag configure dmuted -foreground [$C muted]
    $W tag configure dout -foreground [$C muted]
    $W tag configure dlink -font ChatMeta
    $W tag configure dfirst -spacing1 8
    $W tag configure dlast -spacing3 8
    $W tag configure footer -font ChatMeta -foreground [$C muted] -justify right \
        -spacing1 2 -spacing3 8
    catch {$W tag configure detail -lmargincolor [$C code_bg]}
    catch {$W tag configure dfail -lmargincolor [$C err_bg]}
    $W tag raise link
    $W tag raise flash
}

proc ::vmdai::transcript::_clear_rows {} {
    variable S
    variable RUN
    variable ROW
    variable run_order
    if {[info exists S(tick)] && $S(tick) ne ""} {
        ::vmdai::sched::cancel $S(tick)
        set S(tick) ""
    }
    array unset RUN
    array unset ROW
    set run_order {}
}

# ---- run header, chips, footer -------------------------------------------------

proc ::vmdai::transcript::op_run.open {run request_id model t0} {
    variable W
    variable S
    variable RUN
    variable run_order
    variable expand_all
    if {[info exists RUN($run,status)]} { return }
    # When a new run starts, earlier runs that ended without an unrecovered
    # failure hide their work log (Part B V4 "Collapse").
    if {!$expand_all} {
        foreach r $run_order {
            if {[_collapsible $r]} { _collapse $r 1 }
        }
    }
    lappend run_order $run
    array set RUN [list $run,req $request_id $run,model $model $run,t0 $t0 \
        $run,status running $run,chips {} $run,summary "" $run,collapsed 0 \
        $run,failed 0 $run,recovered 0 $run,snaps {}]
    set S(cur_run) $run
    set S(answer) 0
    $W insert end "\n" [list runhdr hdr:$run]
    _render_header $run
}

proc ::vmdai::transcript::op_run.chip {run k state} {
    variable RUN
    variable ROW
    if {![info exists RUN($run,status)] || ![info exists ROW($k,name)]} { return }
    dict set RUN($run,chips) $k $state
    if {$ROW($k,run) ne $run} {
        set ROW($k,run) $run
        _row_wl $k
    }
    _render_header $run
}

proc ::vmdai::transcript::op_run.close {run status steps failed recovered duration_s final_text_empty {max_turns 28}} {
    variable RUN
    if {![info exists RUN($run,status)]} { return }
    array set RUN [list $run,status $status $run,failed $failed $run,recovered $recovered \
        $run,summary [::vmdai::vm::run_summary $status $steps $failed $recovered $duration_s $max_turns]]
    _render_header $run
}

# The footer appears once a run applied at least one statement; M2 prints
# the links only (the usage line is plan 10's).
proc ::vmdai::transcript::op_footer {run applied usage_text} {
    variable W
    variable RUN
    if {![info exists RUN($run,req)] || ![string is integer -strict $applied] || $applied < 1} {
        return
    }
    set req $RUN($run,req)
    set tags [list footer]
    $W insert end "Copy Tcl" [concat $tags link [_link copy_run_tcl $req]] " · " $tags \
        "Save .tcl…" [concat $tags link [_link save_run_tcl $req]] "\n" $tags
}

# A run stays expanded while it runs, and when it ended with an error, stuck,
# lost, or with a failure it did not recover from.
proc ::vmdai::transcript::_collapsible {run} {
    variable RUN
    if {$RUN($run,status) in {running error stuck lost ended}} { return 0 }
    if {$RUN($run,failed) > 0 && !$RUN($run,recovered)} { return 0 }
    return 1
}

proc ::vmdai::transcript::_collapse {run on} {
    variable W
    variable RUN
    if {![info exists RUN($run,status)]} { return }
    set RUN($run,collapsed) [expr {$on ? 1 : 0}]
    $W tag configure wl:$run -elide $RUN($run,collapsed)
}

proc ::vmdai::transcript::_chip_glyph {state} {
    switch -- $state {
        ok      { return "✓" }
        err     { return "✗" }
        warn    { return "!" }
        notrun  { return "–" }
    }
    return "•"
}

# Chips as counts ("✓14 ✗2"), used past 12 steps or when the header is narrow.
proc ::vmdai::transcript::_chip_counts {chips} {
    set out {}
    foreach state {ok err warn notrun running} {
        set n 0
        dict for {k s} $chips { if {$s eq $state} { incr n } }
        if {$n} { lappend out $state "[_chip_glyph $state]$n" }
    }
    return $out
}

# Header refit (V6): drop the model name, then shorten "N failed, recovered"
# to "N failed", then switch the chips to counts.
proc ::vmdai::transcript::_header_fit {run cw} {
    variable RUN
    set chips $RUN($run,chips)
    set summary $RUN($run,summary)
    set model $RUN($run,model)
    set counts [expr {[dict size $chips] > 12}]
    foreach step {full nomodel short counts} {
        switch -- $step {
            nomodel { set model "" }
            short   { regsub {, recovered} $summary "" summary }
            counts  { set counts 1 }
        }
        if {$counts} {
            set chiptext [join [dict values [_chip_counts $chips]] " "]
        } else {
            set chiptext [string repeat "✓ " [dict size $chips]]
        }
        set left [font measure ChatRole "ChatVMD"]
        if {$model ne ""} { incr left [font measure ChatMeta "  $model"] }
        set right [expr {[font measure ChatMetaBold $chiptext] + [font measure ChatMeta "  $summary"]}]
        if {$left + $right + 16 <= $cw} { break }
    }
    return [list $model $summary $counts]
}

proc ::vmdai::transcript::_render_header {run} {
    variable W
    variable RUN
    set r [$W tag ranges hdr:$run]
    if {![llength $r]} { return }
    set at [lindex $r 0]
    $W delete $at "[lindex $r end] -1c"
    lassign [_header_fit $run [_content_width]] model summary counts
    set tags [list runhdr hdr:$run]
    set pieces [list "ChatVMD" $tags]
    if {$model ne ""} { lappend pieces "  $model" [concat $tags runmodel] }
    lappend pieces "\t" $tags
    set chips $RUN($run,chips)
    if {$counts} {
        foreach {state text} [_chip_counts $chips] {
            lappend pieces $text [concat $tags chip chip_$state] " " $tags
        }
    } else {
        dict for {k state} $chips {
            lappend pieces [_chip_glyph $state] [concat $tags chip chip_$state chip:$k] " " $tags
        }
    }
    if {$summary ne ""} { lappend pieces " $summary" [concat $tags runsum] }
    $W insert $at {*}$pieces
    dict for {k state} $chips {
        $W tag bind chip:$k <ButtonRelease-1> [list ::vmdai::transcript::jump_to $k]
    }
}

# ---- rows -----------------------------------------------------------------------

proc ::vmdai::transcript::op_tool.open {k name command executor origin {rationale ""}} {
    variable W
    variable S
    variable ROW
    variable opt
    variable expand_all
    if {[info exists ROW($k,name)]} { return }
    array set ROW [list $k,name $name $k,cmd $command $k,executor $executor \
        $k,origin $origin $k,rationale $rationale $k,state running $k,dur "" \
        $k,detail {} $k,open 0 $k,run $S(cur_run) $k,t0 [clock seconds] $k,frame 0 $k,fit ""]
    set tags [concat row row:$k [_wl]]
    $W insert end "•" [concat $tags glyph:$k g_run] "\n" $tags
    $W mark set rowend:$k "end -1c"
    $W mark gravity rowend:$k left
    _render_row $k
    $W tag bind row:$k <Enter> [list ::vmdai::transcript::_row_hover $k 1]
    $W tag bind row:$k <Leave> [list ::vmdai::transcript::_row_hover $k 0]
    $W tag bind row:$k <ButtonPress-1> [list ::vmdai::transcript::_row_press %x %y]
    $W tag bind row:$k <ButtonRelease-1> [list ::vmdai::transcript::_row_release $k %x %y]
    if {$expand_all} { _open_detail $k }
    if {$opt(animate) && $S(tick) eq ""} {
        set S(tick) [::vmdai::sched::after 1000 ::vmdai::transcript::_tick]
    }
}

proc ::vmdai::transcript::op_tool.close {k state duration_text detail thumb} {
    variable W
    variable ROW
    variable expand_all
    if {![info exists ROW($k,name)]} { return }
    array set ROW [list $k,state $state $k,dur $duration_text $k,detail $detail $k,fit ""]
    foreach section {err prev} {
        set r [$W tag ranges $section:$k]
        if {[llength $r]} { $W delete [lindex $r 0] [lindex $r end] }
    }
    _set_glyph $k
    _row_wl $k
    set wl [_row_run_wl $k]
    if {$state eq "err" && [dict get $detail error] ne ""} {
        set tags [list errline err:$k]
        $W insert rowend:$k [dict get $detail error] $tags "\n" $tags
    } elseif {$state eq "ok"} {
        set tags [concat preview prev:$k $wl]
        set at rowend:$k
        foreach line [lreverse [dict get $detail preview]] {
            $W insert $at $line $tags "\n" $tags
        }
    }
    _render_row $k
    set total [dict get $detail total]
    if {$ROW($k,open)} {
        _close_detail $k
        _open_detail $k
    } elseif {$expand_all || ($state eq "err" && [string is integer -strict $total] && $total > 1)} {
        _open_detail $k
    }
}

# The work-log tag for what hangs under a row; a failed row's error line
# and detail stay visible when its run collapses.
proc ::vmdai::transcript::_row_run_wl {k} {
    variable ROW
    if {$ROW($k,run) eq "" || $ROW($k,state) eq "err"} { return {} }
    return [list wl:$ROW($k,run)]
}

# A failed row and its error line stay visible when the run collapses.
proc ::vmdai::transcript::_row_wl {k} {
    variable W
    variable ROW
    set r [$W tag ranges row:$k]
    if {![llength $r]} { return }
    foreach tag [$W tag names] {
        if {[string match wl:* $tag]} { $W tag remove $tag {*}$r }
    }
    if {$ROW($k,state) ne "err" && $ROW($k,run) ne ""} { $W tag add wl:$ROW($k,run) {*}$r }
}

proc ::vmdai::transcript::_set_glyph {k {char ""}} {
    variable W
    variable ROW
    switch -- $ROW($k,state) {
        ok      { set g "✓"; set style g_ok }
        err     { set g "✗"; set style g_err }
        notrun  { set g "–"; set style g_no }
        unknown { set g "!"; set style g_warn }
        default { set g "•"; set style g_run }
    }
    if {$char ne ""} { set g $char }
    set at [lindex [$W tag ranges glyph:$k] 0]
    set keep {}
    foreach tag [$W tag names $at] {
        if {$tag ni {g_ok g_err g_no g_warn g_run}} { lappend keep $tag }
    }
    $W delete $at
    $W insert $at $g [concat $keep $style]
}

# The command text a row shows (Part B V4 "Which command line is shown").
proc ::vmdai::transcript::_row_command {k} {
    variable ROW
    set cmd $ROW($k,cmd)
    set d $ROW($k,detail)
    set name $ROW($k,name)
    switch -glob -- $name {
        capture_vmd_snapshot { return [list "Snapshot" snapcmd] }
        search_docs          { return [list "Docs: [_first_line $cmd]" snapcmd] }
        wiki_*               { return [list "Wiki: [_first_line $cmd]" snapcmd] }
    }
    if {$ROW($k,state) eq "err" && [_dget $d failed_text] ne ""} {
        return [list [_first_line [_dget $d failed_text]] cmd]
    }
    if {$ROW($k,state) eq "ok" && [_dget $d inline] ne ""} {
        set stmts [_statements $cmd]
        if {[llength $stmts] > 1} {
            return [list "… [_first_line [lindex $stmts end]]" cmd]
        }
    }
    return [list [_first_line $cmd] cmd]
}

proc ::vmdai::transcript::_dget {d key} {
    if {[catch {dict get $d $key} v] || $v eq "null"} { return "" }
    return $v
}

proc ::vmdai::transcript::_first_line {s} {
    foreach line [split $s "\n"] {
        if {[string trim $line] ne ""} { return [string trim $line] }
    }
    return ""
}

# Statements as the executor splits them (C3); the whole text when the
# splitter is not loaded.
proc ::vmdai::transcript::_statements {cmd} {
    if {[catch {::vmdai::executor::split_statements $cmd} d]} { return [list $cmd] }
    set out [dict get $d statements]
    if {[string trim [dict get $d tail]] ne ""} { lappend out [dict get $d tail] }
    return $out
}

proc ::vmdai::transcript::_row_meta {k} {
    variable ROW
    set d $ROW($k,detail)
    set parts {}
    switch -- $ROW($k,state) {
        running {
            set secs [expr {[clock seconds] - $ROW($k,t0)}]
            lappend parts [expr {$secs >= 2 ? "running… $secs s" : "running…"}]
        }
        ok {
            if {[_dget $d inline] ne ""} { lappend parts "→ [_dget $d inline]" }
            lappend parts $ROW($k,dur)
        }
        err { lappend parts $ROW($k,dur) }
    }
    lappend parts [_dget $d label]
    set out {}
    foreach p $parts { if {$p ne ""} { lappend out $p } }
    return $out
}

# Fit a row into one display line (V6 refit order): drop the rationale,
# then "+N lines", then ellipsize the command (never below 12 characters),
# then drop the duration; a label that still does not fit is ellipsized.
proc ::vmdai::transcript::_row_fit {k cw} {
    variable ROW
    lassign [_row_command $k] text style
    set font [expr {$style eq "cmd" ? "ChatCodeSmall" : "ChatBody"}]
    set extras {}
    if {$ROW($k,name) eq "capture_vmd_snapshot"} {
        set why [_first_line $ROW($k,cmd)]
    } else {
        set why $ROW($k,rationale)
        set n [llength [split [string trimright $ROW($k,cmd) "\n"] "\n"]]
        if {$n > 1 && $style eq "cmd"} { lappend extras "+[expr {$n - 1}] lines" }
    }
    set from [expr {$ROW($k,origin) eq "rescued" ? "  (from text)" : ""}]
    set meta [_row_meta $k]
    set chev [expr {$ROW($k,open) ? "▾" : "▸"}]
    set room [expr {$cw - 24 - 12}]
    foreach step {full norationale noextras ellipsize noduration label} {
        switch -- $step {
            norationale { set why "" }
            noextras    { set extras {} }
            noduration  {
                if {$ROW($k,dur) ne ""} {
                    set i [lsearch -exact $meta $ROW($k,dur)]
                    if {$i >= 0} { set meta [lreplace $meta $i $i] }
                }
            }
        }
        set right "[join $meta "  "]  $chev"
        set avail [expr {$room - [font measure ChatMeta $right] - [font measure ChatMeta $from]}]
        set suffix ""
        foreach e $extras { append suffix "  $e" }
        if {$why ne ""} { append suffix "  $why" }
        if {$step in {ellipsize noduration label}} {
            set text [::vmdai::theme::fit $font [expr {$avail - [font measure ChatMeta $suffix]}] $text 12]
        }
        if {$step eq "label"} {
            set right "[::vmdai::theme::fit ChatMeta [expr {$room / 2}] [join $meta "  "] 8]  $chev"
        }
        if {[font measure $font $text] + [font measure ChatMeta $suffix] <= $avail} { break }
    }
    return [list $text $style "$suffix$from" $right]
}

proc ::vmdai::transcript::_render_row {k} {
    variable W
    variable ROW
    set fit [_row_fit $k [_content_width]]
    set g [$W tag ranges glyph:$k]
    if {![llength $g]} { return }
    set at [lindex $g 1]
    set line [$W get $at "rowend:$k -1c"]
    if {$fit eq $ROW($k,fit) && $line ne ""} { return }
    set ROW($k,fit) $fit
    lassign $fit text style suffix right
    set rt [concat row row:$k [lsearch -all -inline [$W tag names $at] wl:*]]
    $W delete $at "rowend:$k -1c"
    $W insert $at "\t" $rt $text [concat $rt $style] $suffix [concat $rt extra] "\t" $rt \
        [string range $right 0 end-1] [concat $rt meta] [string index $right end] [concat $rt chev]
}

proc ::vmdai::transcript::_relayout_rows {cw narrow} {
    variable W
    variable ROW
    variable RUN
    $W tag configure row -tabs [list 24 left [expr {$cw - 2}] right]
    $W tag configure runhdr -tabs [list $cw right]
    foreach key [array names ROW *,name] { _render_row [lindex [split $key ,] 0] }
    foreach key [array names RUN *,status] { _render_header [lindex [split $key ,] 0] }
}

# One shared 1 s ticker while any row runs: elapsed time and the spinner.
proc ::vmdai::transcript::_tick {} {
    variable S
    variable ROW
    variable W
    set S(tick) ""
    if {$W eq "" || [info commands $W] eq ""} { return }
    set frames [list "◐" "◓" "◑" "◒"]
    set running 0
    foreach key [array names ROW *,state] {
        set k [lindex [split $key ,] 0]
        if {$ROW($key) ne "running"} { continue }
        incr running
        set ROW($k,frame) [expr {($ROW($k,frame) + 1) % 4}]
        _set_glyph $k [lindex $frames $ROW($k,frame)]
        _render_row $k
    }
    if {$running} { set S(tick) [::vmdai::sched::after 1000 ::vmdai::transcript::_tick] }
}

proc ::vmdai::transcript::_row_hover {k on} {
    variable W
    set bg [expr {$on ? [::vmdai::theme::c hover] : ""}]
    $W tag configure row:$k -background $bg
    catch {$W tag configure row:$k -lmargincolor $bg}
    $W configure -cursor [expr {$on ? "hand2" : "arrow"}]
}

# A click toggles the detail, but not after a drag of more than 3 px or a
# new selection, so text in a row can still be selected (V5).
proc ::vmdai::transcript::_row_press {x y} {
    variable W
    variable S
    set S(press) [list $x $y [$W tag ranges sel]]
}

proc ::vmdai::transcript::_row_release {k x y} {
    variable W
    variable S
    if {![info exists S(press)]} { return }
    lassign $S(press) x0 y0 sel0
    unset S(press)
    if {abs($x - $x0) > 3 || abs($y - $y0) > 3 || [$W tag ranges sel] ne $sel0} { return }
    toggle_detail $k
}

# ---- step detail ----------------------------------------------------------------

proc ::vmdai::transcript::toggle_detail {k} {
    variable ROW
    if {![info exists ROW($k,name)]} { return 0 }
    if {$ROW($k,open)} { _close_detail $k } else { _open_detail $k }
    return $ROW($k,open)
}

proc ::vmdai::transcript::_close_detail {k} {
    variable W
    variable ROW
    set r [$W tag ranges detail:$k]
    if {[llength $r]} { $W delete [lindex $r 0] [lindex $r end] }
    set ROW($k,open) 0
    set ROW($k,fit) ""
    _render_row $k
}

proc ::vmdai::transcript::_open_detail {k} {
    variable W
    variable ROW
    if {$ROW($k,open)} { return }
    set ROW($k,open) 1
    set ROW($k,fit) ""
    _render_row $k
    set at rowend:$k
    foreach section {err prev} {
        set r [$W tag ranges $section:$k]
        if {[llength $r]} { set at [lindex $r end] }
    }
    $W mark set dins:$k $at
    $W mark gravity dins:$k right
    _build_detail $k
    $W mark unset dins:$k
}

# Split cmd into {text class} segments that cover it byte for byte:
# statements before the failing one are "", the failing one "dfail", the
# rest "dmuted" (the executor's own splitter decides the boundaries).
proc ::vmdai::transcript::_cmd_segments {cmd failed_index} {
    if {![string is integer -strict $failed_index] || $failed_index < 1} {
        return [list $cmd ""]
    }
    set segs {}
    set pos 0
    set i 0
    foreach stmt [_statements $cmd] {
        incr i
        set s [string first $stmt $cmd $pos]
        if {$s < 0} { continue }
        set e [expr {$s + [string length $stmt]}]
        if {$s > $pos} { lappend segs [string range $cmd $pos [expr {$s - 1}]] "" }
        set class [expr {$i < $failed_index ? "" : ($i == $failed_index ? "dfail" : "dmuted")}]
        lappend segs [string range $cmd $s [expr {$e - 1}]] $class
        set pos $e
    }
    if {$pos < [string length $cmd]} { lappend segs [string range $cmd $pos end] "" }
    return $segs
}

# The command as display lines, each a flat list {text class ...}.
proc ::vmdai::transcript::_cmd_lines {cmd failed_index} {
    set lines {}
    set cur {}
    foreach {text class} [_cmd_segments $cmd $failed_index] {
        set parts [split $text "\n"]
        lappend cur [lindex $parts 0] $class
        foreach part [lrange $parts 1 end] {
            lappend lines $cur
            set cur [list $part $class]
        }
    }
    lappend lines $cur
    return $lines
}

proc ::vmdai::transcript::_export_note {total applied} {
    if {![string is integer -strict $applied] || $applied < 1} { return "Not in Save .tcl" }
    if {$applied == 1} {
        return "Statement 1 ran and is kept in Save .tcl; the rest is commented out"
    }
    return "Statements 1–$applied ran and are kept in Save .tcl; the rest is commented out"
}

# The step detail (Part B V4): the rationale, the exact command bytes (10
# lines, then "Show all N lines"; a failure shows every statement, the
# failing one on err_bg with a ✗ in the gutter and the rest muted), the
# output (12 lines), "Open full output · Reveal" when output_path is set
# (C5), the export note for a failure, and Copy. Inserted at mark dins:$k.
proc ::vmdai::transcript::_build_detail {k} {
    variable W
    variable ROW
    set d $ROW($k,detail)
    set cmd $ROW($k,cmd)
    set base [concat detail detail:$k [_row_run_wl $k]]
    set failed [_dget $d failed_index]
    set first [$W index dins:$k]
    if {$ROW($k,rationale) ne ""} {
        $W insert dins:$k $ROW($k,rationale) [concat $base dnote] "\n" $base
    }
    set total_lines [llength [split $cmd "\n"]]
    set limit [expr {$failed eq "" && ![info exists ROW($k,all)] ? 10 : $total_lines}]
    set marked 0
    set n 0
    foreach line [_cmd_lines $cmd $failed] {
        if {$n == $limit} { break }
        incr n
        set gutter [list "  " [concat $base dgut]]
        if {!$marked && [lsearch -exact $line dfail] >= 0} {
            set gutter [list "✗ " [concat $base dgut dgutx]]
            set marked 1
        }
        $W insert dins:$k {*}$gutter
        foreach {text class} $line {
            if {$text ne ""} { $W insert dins:$k $text [concat $base dcode $class] }
        }
        $W insert dins:$k "\n" $base
    }
    if {$total_lines > $limit} {
        $W insert dins:$k "Show all $total_lines lines" \
            [concat $base dlink link [_link show_all $k]] "\n" $base
    }
    set out [string trimright [_dget $d output] "\n"]
    if {$out ne ""} {
        set olines [split $out "\n"]
        set shown [lrange $olines 0 11]
        set shown [lreplace $shown 0 0 "→ [lindex $shown 0]"]
        foreach l $shown { $W insert dins:$k $l [concat $base dout] "\n" $base }
        if {[llength $olines] > 12} {
            $W insert dins:$k "… [expr {[llength $olines] - 12}] more lines" [concat $base dout] "\n" $base
        }
    }
    set path [_dget $d output_path]
    if {$path ne ""} {
        $W insert dins:$k "Open full output" [concat $base dlink link [_link open_file $path]] \
            " · " [concat $base dlink] "Reveal" [concat $base dlink link [_link reveal_file $path]] "\n" $base
    }
    if {$failed ne "" || $ROW($k,state) eq "err"} {
        $W insert dins:$k [_export_note [_dget $d total] [_dget $d applied]] [concat $base dnote] "\n" $base
    }
    $W insert dins:$k "Copy" [concat $base dlink link [_link copy_text $cmd]] "\n" $base
    $W tag add dfirst $first "$first lineend +1c"
    $W tag add dlast "dins:$k -1l linestart" dins:$k
}

proc ::vmdai::transcript::_do_show_all {k} {
    variable ROW
    if {![info exists ROW($k,name)]} { return }
    set ROW($k,all) 1
    _close_detail $k
    _open_detail $k
}

# ⌘E / "Expand all steps": every run shown and every detail open. Off: the
# collapse rule applies again (the newest run stays open) and details close.
proc ::vmdai::transcript::set_expand_all {on} {
    variable ROW
    variable RUN
    variable run_order
    variable expand_all
    variable W
    set expand_all [expr {$on ? 1 : 0}]
    if {$W eq "" || [info commands $W] eq ""} { return }
    foreach key [array names ROW *,name] {
        set k [lindex [split $key ,] 0]
        if {$expand_all} { _open_detail $k } elseif {$ROW($k,open)} { _close_detail $k }
    }
    foreach run $run_order {
        if {$expand_all} {
            _collapse $run 0
        } elseif {$run ne [lindex $run_order end] && [_collapsible $run]} {
            _collapse $run 1
        }
    }
}

# ---- right-click menus and actions ---------------------------------------------

proc ::vmdai::transcript::_row_menu {k} {
    variable ROW
    set d $ROW($k,detail)
    set items [list "Copy command" [list ::vmdai::transcript::_clipboard $ROW($k,cmd)]]
    if {[_dget $d output] ne ""} {
        lappend items "Copy output" [list ::vmdai::transcript::_clipboard [_dget $d output]]
    }
    if {[_dget $d error] ne ""} {
        lappend items "Copy error" [list ::vmdai::transcript::_clipboard [_dget $d error]]
    }
    lappend items [expr {$ROW($k,open) ? "Collapse" : "Expand"}] \
        [list ::vmdai::transcript::toggle_detail $k]
    return $items
}

proc ::vmdai::transcript::_run_menu {run} {
    variable RUN
    set req $RUN($run,req)
    return [list "Copy run Tcl" [list ::vmdai::transcript::_action copy_run_tcl $req] \
        "Save run .tcl…" [list ::vmdai::transcript::_action save_run_tcl $req] \
        [expr {$RUN($run,collapsed) ? "Expand" : "Collapse"}] \
        [list ::vmdai::transcript::_collapse $run [expr {!$RUN($run,collapsed)}]]]
}

proc ::vmdai::transcript::_do_copy_run_tcl {request_id} {
    if {[info commands ::vmdai::tclexport::run_tcl] eq ""} { return }
    _clipboard [::vmdai::tclexport::run_tcl $request_id]
}

proc ::vmdai::transcript::_do_save_run_tcl {request_id} {
    variable T
    if {[info commands ::vmdai::tclexport::run_tcl] eq ""} { return }
    set path [tk_getSaveFile -parent [winfo toplevel $T] -title "Save run .tcl" \
        -defaultextension .tcl -initialfile run.tcl]
    if {$path eq ""} { return }
    ::vmdai::tclexport::save $path [::vmdai::tclexport::run_tcl $request_id]
}
