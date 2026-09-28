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

# M3 (plan 10): the step detail colours its command with syntax.tcl.  Sourced
# here so every file that sources transcript.tcl gets it; syntax.tcl is safe
# to source again.
source [file join [file dirname [info script]] syntax.tcl]
source [file join [file dirname [info script]] markdown.tcl]

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
    foreach hook {_clear_rows _clear_snaps} {
        if {[info commands ::vmdai::transcript::$hook] ne ""} { $hook }
    }
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
    ::vmdai::md::render_into $W $at $text $tags
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

# Tk %-substitutes every binding script; double each % so the payload
# (a command, a path) reaches the handler byte for byte.
proc ::vmdai::transcript::_bound {script} { return [string map {% %%} $script] }

proc ::vmdai::transcript::_link {args} {
    variable W
    variable S
    set tag act:[incr S(link)]
    $W tag bind $tag <ButtonRelease-1> [_bound [list ::vmdai::transcript::_action {*}$args]]
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
    set cmd [namespace which -command $target]
    if {$cmd eq ""} { return }
    uplevel #0 [list $cmd {*}$args]
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
            if {$text ne ""} { $W insert dins:$k $text [concat $base dcode $class dcmd:$k] }
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
    ::vmdai::syntax::highlight_tag $W dcmd:$k
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
    if {[catch {::vmdai::tclexport::save $path [::vmdai::tclexport::run_tcl $request_id]} err]} {
        _save_failed $path $err
    }
}

# A failed save is logged and noted in the transcript, never a bgerror.
proc ::vmdai::transcript::_save_failed {path err} {
    catch {::vmdai::config::log "transcript: save [file tail $path] failed: $err"}
    apply_ops [list [list notice warn "Couldn't save [file tail $path]: $err"]]
}

# ===========================================================================
# Snapshot cards, the 30-photo cap (P08-T07).
#
# Part B V4 "Snapshot card", §2c "Thumbnails", V7. A card is a canvas
# embedded on its own line (thumb, snap:$k) after the row's sections: the
# runtime's thumbnail with its uniform border cropped off (console's
# snap::autocrop: grid 12, tolerance 36, pad 26) and scaled down by an
# integer factor to fit 256×192, never cropped to fill; beside it (below it
# when narrow) the purpose, "W × H · renderer", the file name, "Saved to …",
# "Open · Reveal · Save PNG…" and whether the model saw it. At most
# opt(max_photos) photos stay loaded; older cards show "Show image". A PNG
# that cannot be decoded gives a text card and loads nothing.
# ===========================================================================

namespace eval ::vmdai::transcript {
    variable SNAP
    if {![info exists SNAP]} { array set SNAP {} }
    variable opt
    if {![info exists opt(max_photos)]} { set opt(max_photos) 30 }
}

proc ::vmdai::transcript::loaded_image_count {} {
    variable S
    return [llength $S(photos)]
}

proc ::vmdai::transcript::_tags_snaps {} {
    variable W
    variable SNAP
    $W tag configure thumb -lmargin1 24 -spacing1 6 -spacing3 10
    foreach key [array names SNAP *,card] { _draw_card [lindex [split $key ,] 0] }
}

proc ::vmdai::transcript::_clear_snaps {} {
    variable S
    variable SNAP
    foreach key [array names SNAP *,card] { catch {destroy $SNAP($key)} }
    foreach p $S(photos) { catch {image delete $p} }
    set S(photos) {}
    array unset SNAP
}

proc ::vmdai::transcript::_relayout_snaps {cw narrow} {
    variable SNAP
    foreach key [array names SNAP *,card] { _draw_card [lindex [split $key ,] 0] }
}

# Bounding box {x0 y0 x1 y1} of what differs from the corner colour, sampled
# on a grid and padded (console prototype, snap::autocrop).
proc ::vmdai::transcript::autocrop {img {step 12} {tol 36} {pad 26}} {
    set w [image width $img]
    set h [image height $img]
    lassign [$img get [expr {min(2, $w - 1)}] [expr {min(2, $h - 1)}]] br bg bb
    set x0 $w
    set y0 $h
    set x1 -1
    set y1 -1
    for {set y 0} {$y < $h} {incr y $step} {
        for {set x 0} {$x < $w} {incr x $step} {
            lassign [$img get $x $y] r g b
            if {abs($r - $br) + abs($g - $bg) + abs($b - $bb) > $tol} {
                if {$x < $x0} { set x0 $x }
                if {$x > $x1} { set x1 $x }
                if {$y < $y0} { set y0 $y }
                if {$y > $y1} { set y1 $y }
            }
        }
    }
    if {$x1 < 0} { return [list 0 0 $w $h] }
    return [list [expr {max(0, $x0 - $pad)}] [expr {max(0, $y0 - $pad)}] \
                 [expr {min($w, $x1 + $pad)}] [expr {min($h, $y1 + $pad)}]]
}

# A new photo: src autocropped, then subsampled by one integer factor so
# that it fits maxw×maxh with its aspect ratio kept.
proc ::vmdai::transcript::thumb_photo {src {maxw 256} {maxh 192}} {
    lassign [autocrop $src] x0 y0 x1 y1
    set cw [expr {$x1 - $x0}]
    set ch [expr {$y1 - $y0}]
    set f [expr {max(1, int(ceil(max(double($cw) / $maxw, double($ch) / $maxh))))}]
    set dst [image create photo]
    $dst copy $src -from $x0 $y0 $x1 $y1 -subsample $f $f
    return $dst
}

# Width and height from a PNG's IHDR (the text card; Tk 8.5 cannot decode PNG).
proc ::vmdai::transcript::_png_size {path} {
    set w ?
    set h ?
    catch {
        set fh [open $path rb]
        set head [read $fh 24]
        close $fh
        if {[string range $head 12 15] eq "IHDR"} {
            binary scan [string range $head 16 23] II w h
        }
    }
    return [list $w $h]
}

proc ::vmdai::transcript::op_snapshot {k thumb path w h saved_path sent_to_model {renderer TachyonInternal}} {
    variable W
    variable T
    variable S
    variable ROW
    variable RUN
    variable SNAP
    if {![info exists ROW($k,name)] || [info exists SNAP($k,card)]} { return }
    set run $ROW($k,run)
    set model ""
    if {$run ne "" && [info exists RUN($run,model)]} { set model $RUN($run,model) }
    array set SNAP [list $k,thumb $thumb $k,path $path $k,w $w $k,h $h $k,saved $saved_path \
        $k,sent $sent_to_model $k,renderer $renderer $k,run $run $k,model $model \
        $k,purpose [_first_line $ROW($k,cmd)] $k,photo "" $k,mode text $k,pw 0 $k,ph 0]
    set c $T.snap[incr S(link)]
    canvas $c -highlightthickness 0 -borderwidth 0 -width 10 -height 10
    ::vmdai::theme::paint $c -background surface
    _embed $c
    foreach seq [_menu_sequences] {
        bind $c $seq [list ::vmdai::transcript::_card_menu $k %X %Y]
    }
    set SNAP($k,card) $c
    _snap_load $k
    _draw_card $k
    set at rowend:$k
    foreach section {err prev detail} {
        set r [$W tag ranges $section:$k]
        if {[llength $r]} { set at [lindex $r end] }
    }
    set at [$W index $at]
    set tags [concat thumb snap:$k [_row_run_wl $k]]
    $W window create $at -window $c -align top
    $W insert "$at +1c" "\n" $tags
    foreach tag $tags { $W tag add $tag $at }
    # The run's newest card stays visible when the run collapses.
    if {$run ne "" && [info exists RUN($run,snaps)]} {
        foreach old $RUN($run,snaps) {
            set r [$W tag ranges snap:$old]
            if {[llength $r]} { $W tag add wl:$run {*}$r }
        }
        lappend RUN($run,snaps) $k
        set r [$W tag ranges snap:$k]
        $W tag remove wl:$run {*}$r
    }
}

# Load the card's photo: the thumbnail, or the full image subsampled when
# the thumbnail is missing (§2c fallbacks). An undecodable file leaves the
# card in text mode. Loading may free the oldest photo (the 30-photo cap).
proc ::vmdai::transcript::_snap_load {k} {
    variable S
    variable SNAP
    set file ""
    if {$SNAP($k,thumb) ne "" && [file readable $SNAP($k,thumb)]} {
        set file $SNAP($k,thumb)
    } elseif {[file readable $SNAP($k,path)]} {
        set file $SNAP($k,path)
    }
    if {$file eq "" || [catch {image create photo -file $file} src]} {
        set SNAP($k,mode) text
        return 0
    }
    set photo [thumb_photo $src 256 192]
    image delete $src
    array set SNAP [list $k,photo $photo $k,mode image \
        $k,pw [image width $photo] $k,ph [image height $photo]]
    lappend S(photos) $photo
    lappend S(photo_keys) $k
    _enforce_cap
    return 1
}

proc ::vmdai::transcript::_enforce_cap {} {
    variable S
    variable SNAP
    variable opt
    while {[llength $S(photos)] > $opt(max_photos)} {
        set p [lindex $S(photos) 0]
        set old [lindex $S(photo_keys) 0]
        set S(photos) [lrange $S(photos) 1 end]
        set S(photo_keys) [lrange $S(photo_keys) 1 end]
        catch {image delete $p}
        set SNAP($old,photo) ""
        set SNAP($old,mode) unloaded
        _draw_card $old
    }
}

# "Show image": reload a freed card; the oldest loaded one is freed instead.
proc ::vmdai::transcript::show_image {k} {
    variable SNAP
    if {![info exists SNAP($k,mode)] || $SNAP($k,mode) ne "unloaded"} { return 0 }
    _snap_load $k
    _draw_card $k
    return 1
}

proc ::vmdai::transcript::_narrow {} {
    variable T
    return [expr {[winfo width $T] > 1 && [winfo width $T] < 440}]
}

proc ::vmdai::transcript::_card_link {c x y text tag cmd} {
    set id [$c create text $x $y -anchor nw -text $text -font ChatMeta \
        -fill [::vmdai::theme::c accent] -tags [list link $tag]]
    $c bind $tag <ButtonRelease-1> [_bound $cmd]
    return [lindex [$c bbox $id] 2]
}

proc ::vmdai::transcript::_draw_card {k} {
    variable SNAP
    set c $SNAP($k,card)
    if {![winfo exists $c]} { return }
    set C ::vmdai::theme::c
    $c delete all
    $c configure -background [$C surface]
    set path $SNAP($k,path)
    set mode $SNAP($k,mode)
    set iw 0
    set ih 0
    if {$mode eq "image"} {
        set iw [expr {$SNAP($k,pw) + 2}]
        set ih [expr {$SNAP($k,ph) + 2}]
        $c create rectangle 0 0 [expr {$iw - 1}] [expr {$ih - 1}] -outline [$C hairline] \
            -fill [$C surface] -tags img
        $c create image 1 1 -anchor nw -image $SNAP($k,photo) -tags img
        $c bind img <ButtonRelease-1> [_bound [list ::vmdai::transcript::_action view_image $path]]
        $c bind img <Enter> [list $c configure -cursor hand2]
        $c bind img <Leave> [list $c configure -cursor arrow]
    } elseif {$mode eq "unloaded"} {
        set iw [expr {$SNAP($k,pw) + 2}]
        set ih [expr {$SNAP($k,ph) + 2}]
        $c create rectangle 0 0 [expr {$iw - 1}] [expr {$ih - 1}] -outline [$C hairline] \
            -fill [$C code_bg]
        set tw [font measure ChatMeta "Show image"]
        _card_link $c [expr {($iw - $tw) / 2}] [expr {$ih / 2 - 8}] "Show image" lk_show \
            [list ::vmdai::transcript::show_image $k]
    }
    set cw [_content_width]
    if {$mode eq "text" || [_narrow]} {
        set x 0
        set y [expr {$ih ? $ih + 8 : 0}]
    } else {
        set x [expr {$iw + 14}]
        set y 0
    }
    set capw [expr {max(120, $cw - 24 - $x)}]
    if {$mode ne "text" && ![_narrow] && $capw > 300} { set capw 300 }
    if {$mode eq "text"} {
        lassign [_png_size $path] pw ph
        set id [$c create text $x $y -anchor nw -width $capw -font ChatBody -fill [$C text] \
            -text "[file tail $path] · $pw × $ph"]
    } else {
        set id [$c create text $x $y -anchor nw -width $capw -font ChatBody -fill [$C text] \
            -text $SNAP($k,purpose)]
        set y [expr {[lindex [$c bbox $id] 3] + 2}]
        set id [$c create text $x $y -anchor nw -font ChatMeta -fill [$C muted] \
            -text "$SNAP($k,w) × $SNAP($k,h) · $SNAP($k,renderer)"]
        set y [expr {[lindex [$c bbox $id] 3] + 2}]
        set id [$c create text $x $y -anchor nw -font ChatCodeSmall -fill [$C text2] \
            -text [::vmdai::theme::fit_middle ChatCodeSmall $capw [file tail $path]]]
        if {$SNAP($k,saved) ne ""} {
            set y [expr {[lindex [$c bbox $id] 3] + 2}]
            set id [$c create text $x $y -anchor nw -font ChatMeta -fill [$C muted] \
                -text "Saved to [file tail $SNAP($k,saved)]"]
        }
    }
    set y [expr {[lindex [$c bbox $id] 3] + 6}]
    set lx [_card_link $c $x $y "Open" lk_open [list ::vmdai::transcript::_action open_file $path]]
    $c create text [expr {$lx + 4}] $y -anchor nw -text "·" -font ChatMeta -fill [$C muted]
    set lx [_card_link $c [expr {$lx + 14}] $y "Reveal" lk_reveal \
        [list ::vmdai::transcript::_action reveal_file $path]]
    if {$mode ne "text"} {
        $c create text [expr {$lx + 4}] $y -anchor nw -text "·" -font ChatMeta -fill [$C muted]
        _card_link $c [expr {$lx + 14}] $y "Save PNG…" lk_save \
            [list ::vmdai::transcript::_action save_png $path]
    }
    set y [expr {[lindex [$c bbox all] 3] + 4}]
    if {$SNAP($k,sent)} {
        $c create text $x $y -anchor nw -font ChatMeta -fill [$C ok] -text "✓ Sent to the model"
    } else {
        set who [expr {$SNAP($k,model) eq "" ? "this model" : $SNAP($k,model)}]
        $c create text $x $y -anchor nw -width $capw -font ChatMeta -fill [$C warn] \
            -text "✗ Not sent — $who is text-only"
    }
    $c bind link <Enter> [list $c configure -cursor hand2]
    $c bind link <Leave> [list $c configure -cursor arrow]
    lassign [$c bbox all] bx0 by0 bx1 by1
    $c configure -width [expr {$bx1 + 2}] -height [expr {max($ih, $by1) + 2}]
}

proc ::vmdai::transcript::card_texts {k} {
    variable SNAP
    set out {}
    set c $SNAP($k,card)
    foreach id [$c find all] {
        if {[$c type $id] eq "text"} { lappend out [$c itemcget $id -text] }
    }
    return $out
}

proc ::vmdai::transcript::_snap_menu {k} {
    variable SNAP
    set p $SNAP($k,path)
    return [list Open [list ::vmdai::transcript::_action open_file $p] \
        Reveal [list ::vmdai::transcript::_action reveal_file $p] \
        "Save PNG…" [list ::vmdai::transcript::_action save_png $p] \
        "Copy path" [list ::vmdai::transcript::_clipboard $p]]
}

proc ::vmdai::transcript::_card_menu {k rx ry} {
    variable T
    set m $T.menu
    catch {destroy $m}
    menu $m -tearoff 0
    foreach {label cmd} [_snap_menu $k] { $m add command -label $label -command $cmd }
    tk_popup $m $rx $ry
}

# Default targets of the file actions (the viewer module, P08-T07).
proc ::vmdai::transcript::_do_view_image {path} { _call ::vmdai::viewer::open $path }
proc ::vmdai::transcript::_do_open_file {path} { _call ::vmdai::viewer::open_external $path }
proc ::vmdai::transcript::_do_reveal_file {path} { _call ::vmdai::viewer::reveal $path }
proc ::vmdai::transcript::_do_save_png {path} {
    if {[catch {_call ::vmdai::viewer::save_copy $path} err]} { _save_failed $path $err }
}

# ===========================================================================
# Empty state (Part B V4 "Empty state"; P09-T02).
#
# A frame placed over the transcript text: the mark, the title, a lead line,
# four example cards (2x2 from 520 px, else one column), the bordered Ready
# group (Runtime, Model, the first-run servers, Folder, the trust notice) and
# the key hints. It never inserts into the text, so the op goldens and the
# dump are unaffected; the panel removes it before the first op it applies.
# ===========================================================================
namespace eval ::vmdai::transcript {
    variable EMPTY_TITLE "What should VMD do?"
    variable EMPTY_LEAD "Describe a view, a measurement or an analysis. ChatVMD writes the Tcl, runs it in this VMD session and checks the result."
    variable TRUST_TEXT "Model-written Tcl runs unsandboxed in this VMD session. Only load files you trust."
    variable EXAMPLES [list \
        [list load    "Load & style"      "Load PDB 1HCK as NewCartoon colored by secondary structure"] \
        [list pocket  "Binding pocket"    "Show residues within 5 \u00c5 of the ligand as Licorice"] \
        [list bfactor "Color by B-factor" "Color the protein by B-factor and render a snapshot"] \
        [list rmsd    "Trajectory RMSD"   "Measure the backbone RMSD over the loaded trajectory"]]
    variable PAIR_MIN_WIDTH 520
    if {![info exists ::vmdai::transcript::empty_host]} { variable empty_host "" }
    if {![info exists ::vmdai::transcript::empty_after]} { variable empty_after "" }
}

proc ::vmdai::transcript::_empty_get {d key default} {
    if {![dict exists $d $key]} { return $default }
    set value [dict get $d $key]
    if {$value eq "null"} { return $default }
    return $value
}

proc ::vmdai::transcript::_empty_tilde {path} {
    set home ""
    catch {set home [file normalize ~]}
    if {$home ne "" && [string first $home $path] == 0} {
        return "~[string range $path [string length $home] end]"
    }
    return $path
}

proc ::vmdai::transcript::_key_hints {} {
    if {[tk windowingsystem] eq "aqua"} {
        return "\u23ce send \u00b7 \u21e7\u23ce newline \u00b7 \u2191 last prompt \u00b7 esc stop"
    }
    return "Return send \u00b7 Shift-Return newline \u00b7 Up last prompt \u00b7 Esc stop"
}

# The Ready group's rows: {state name text action_label action_cmd}, where
# state is ok|off|info|warn.
proc ::vmdai::transcript::empty_rows {info} {
    variable TRUST_TEXT
    set rows {}
    set endpoint [_empty_get $info endpoint ""]
    if {[string is true -strict [_empty_get $info connected false]]} {
        set text [expr {$endpoint eq "" ? "running" : "running \u00b7 $endpoint"}]
        lappend rows [list ok Runtime $text "" ""]
    } else {
        lappend rows [list off Runtime "not connected" "" ""]
    }
    set model [_empty_get $info model ""]
    set settings_cmd [list ::vmdai::panel::open_settings model]
    if {$model ne "" && [string is true -strict [_empty_get $info agent_loop false]]} {
        set text "[::vmdai::panel::provider_label [_empty_get $info provider ""]] \u00b7 $model"
        set caps {}
        if {[llength [_empty_get $info tools {}]]} { lappend caps tools }
        if {[string is true -strict [_empty_get $info vision false]]} { lappend caps vision }
        if {[llength $caps]} { append text " \u00b7 [join $caps {, }]" }
        lappend rows [list ok Model $text Change $settings_cmd]
    } else {
        lappend rows [list off Model "No model configured" "Set up\u2026" $settings_cmd]
    }
    set servers {}
    catch {set servers [dict get $info first_run servers]}
    foreach server $servers {
        set url [_empty_get $server base_url ""]
        set models [_empty_get $server models {}]
        set n [llength $models]
        set text "Found Ollama [_empty_get $server version ?] at [::vmdai::panel::hostport $url] \u00b7 $n model[expr {$n == 1 ? "" : "s"}]"
        set prefill [dict create provider ollama base_url $url model [lindex $models 0]]
        lappend rows [list info "" $text "Use\u2026" [list ::vmdai::panel::open_settings model $prefill]]
    }
    set folder [_empty_get $info folder ""]
    if {$folder ne ""} {
        set runs [_empty_get $info runs 0]
        set text "[_empty_tilde $folder] \u00b7 $runs run[expr {$runs == 1 ? "" : "s"}] recorded"
        lappend rows [list ok Folder $text Change [list ::vmdai::panel::choose_folder]]
    }
    lappend rows [list warn "" $TRUST_TEXT "" ""]
    return $rows
}

proc ::vmdai::transcript::_empty_path {t} {
    return $t.empty
}

proc ::vmdai::transcript::show_empty_state {info {t ""}} {
    variable empty_host
    variable EMPTY_TITLE
    variable EMPTY_LEAD
    variable EXAMPLES
    if {$t eq ""} { set t $::vmdai::panel::text }
    if {$t eq "" || ![winfo exists $t]} { return "" }
    hide_empty_state $t
    set empty_host $t
    set C ::vmdai::theme::c
    set bg [$C surface]
    set e [_empty_path $t]
    frame $e -background $bg -borderwidth 0 -highlightthickness 0
    frame $e.col -background $bg
    grid $e.col -row 0 -column 0
    grid rowconfigure $e 0 -weight 1
    grid columnconfigure $e 0 -weight 1
    set col $e.col
    _empty_mark $col.mark
    label $col.title -text $EMPTY_TITLE -font ChatH1 -foreground [$C text] -background $bg
    label $col.lead -text $EMPTY_LEAD -font ChatBody -foreground [$C muted] -background $bg \
        -justify center -wraplength 420
    frame $col.cards -background $bg
    set i 0
    foreach example $EXAMPLES {
        lassign $example key title prompt
        _empty_card $col.cards.c$i $i $key $title $prompt
        incr i
    }
    frame $col.ready -background $bg -highlightthickness 1 \
        -highlightbackground [$C hairline] -highlightcolor [$C hairline]
    _empty_ready $col.ready $info
    label $col.keys -text [_key_hints] -font ChatMeta -foreground [$C muted] -background $bg
    grid $col.mark  -row 0 -column 0 -pady {0 6}
    grid $col.title -row 1 -column 0
    grid $col.lead  -row 2 -column 0 -pady {4 16}
    grid $col.cards -row 3 -column 0 -sticky ew
    grid $col.ready -row 4 -column 0 -sticky ew -pady {16 0}
    grid $col.keys  -row 5 -column 0 -pady {12 0}
    place $e -in $t -x 0 -y 0 -relwidth 1 -relheight 1
    bind $e <Configure> [list ::vmdai::transcript::_empty_configure $t %w]
    layout_empty_state [winfo width $t] $t
    return $e
}

proc ::vmdai::transcript::hide_empty_state {{t ""}} {
    variable empty_host
    variable empty_after
    if {$t eq ""} { set t $empty_host }
    if {$t eq ""} { return }
    if {$empty_after ne ""} {
        ::vmdai::sched::cancel $empty_after
        set empty_after ""
    }
    set e [_empty_path $t]
    if {[winfo exists $e]} { ::destroy $e }
}

proc ::vmdai::transcript::empty_state_shown {{t ""}} {
    variable empty_host
    if {$t eq ""} { set t $empty_host }
    return [expr {$t ne "" && [winfo exists [_empty_path $t]]}]
}

# Two columns from PAIR_MIN_WIDTH px of transcript width, else one.
proc ::vmdai::transcript::layout_empty_state {width {t ""}} {
    variable PAIR_MIN_WIDTH
    if {$t eq ""} { set t $::vmdai::panel::text }
    set cards [_empty_path $t].col.cards
    if {![winfo exists $cards]} { return "" }
    set pair [expr {$width >= $PAIR_MIN_WIDTH}]
    set inner [expr {$width > 96 ? $width - 64 : 360}]
    set card_w [expr {$pair ? ($inner - 12) / 2 : $inner}]
    if {$card_w > 320} { set card_w 320 }
    if {$card_w < 160} { set card_w 160 }
    for {set i 0} {$i < 4} {incr i} {
        set c $cards.c$i
        if {$pair} {
            grid $c -row [expr {$i / 2}] -column [expr {$i % 2}] -sticky nsew -padx 6 -pady 6
        } else {
            grid $c -row $i -column 0 -sticky ew -padx 6 -pady 6
        }
        $c.desc configure -wraplength [expr {$card_w - 48}]
    }
    grid columnconfigure $cards 0 -weight 1 -uniform card
    if {$pair} {
        grid columnconfigure $cards 1 -weight 1 -uniform card
    } else {
        grid columnconfigure $cards 1 -weight 0 -uniform ""
    }
    [_empty_path $t].col.lead configure -wraplength [expr {$inner < 480 ? $inner : 480}]
    set wrap [expr {$inner - 170}]
    if {$wrap > 300} { set wrap 300 }
    if {$wrap < 120} { set wrap 120 }
    set ready [_empty_path $t].col.ready
    for {set i 0} {[winfo exists $ready.v$i]} {incr i} {
        $ready.v$i configure -wraplength $wrap
    }
    return [expr {$pair ? "pair" : "column"}]
}

proc ::vmdai::transcript::_empty_configure {t width} {
    variable empty_after
    if {$empty_after ne ""} { ::vmdai::sched::cancel $empty_after }
    set empty_after [::vmdai::sched::after_idle [list ::vmdai::transcript::_empty_relayout $t $width]]
}

proc ::vmdai::transcript::_empty_relayout {t width} {
    variable empty_after
    set empty_after ""
    if {![winfo exists $t]} { return "" }
    # %w is the overlay's width: place -in $t sizes it to the text's inner
    # area, 2 x (padx + borderwidth + highlightthickness) narrower than the
    # transcript. The layout thresholds are in transcript width.
    set width [expr {$width + 2 * ([$t cget -padx] + [$t cget -borderwidth] + [$t cget -highlightthickness])}]
    return [layout_empty_state $width $t]
}

proc ::vmdai::transcript::example_clicked {index} {
    variable EXAMPLES
    set prompt [lindex [lindex $EXAMPLES $index] 2]
    ::vmdai::composer::set_text $prompt
    ::vmdai::composer::focus
    return $prompt
}

proc ::vmdai::transcript::_empty_mark {c} {
    set C ::vmdai::theme::c
    canvas $c -width 64 -height 46 -highlightthickness 0 -borderwidth 0 -background [$C surface]
    $c create line 16 30 38 14 50 34 -width 3 -fill [$C faint] -capstyle round -joinstyle round
    $c create oval 8 22 24 38 -fill [$C accent] -outline ""
    $c create oval 29 5 47 23 -fill [$C accent] -outline ""
    $c create oval 43 27 57 41 -fill [$C accent] -outline ""
}

proc ::vmdai::transcript::_empty_icon {c key color} {
    switch -- $key {
        load {
            foreach y {6 11 16} {
                $c create line 4 $y 18 $y -fill $color -width 2 -capstyle round
            }
        }
        pocket {
            $c create oval 3 3 19 19 -outline $color -width 2
            $c create oval 9 9 13 13 -fill $color -outline $color
        }
        bfactor {
            set x 3
            foreach h {6 10 14} {
                $c create rectangle $x [expr {19 - $h}] [expr {$x + 4}] 19 -fill $color -outline ""
                incr x 6
            }
        }
        rmsd {
            $c create line 3 17 8 10 12 13 19 4 -fill $color -width 2 -capstyle round -joinstyle round
        }
    }
}

proc ::vmdai::transcript::_empty_card {c index key title prompt} {
    set C ::vmdai::theme::c
    set bg [$C surface]
    set hairline [$C hairline]
    set accent [$C accent]
    frame $c -background $bg -highlightthickness 1 -highlightbackground $hairline \
        -highlightcolor $hairline -cursor hand2
    canvas $c.icon -width 22 -height 22 -highlightthickness 0 -borderwidth 0 -background $bg
    _empty_icon $c.icon $key $accent
    label $c.title -text $title -font ChatBodyBold -foreground [$C text] -background $bg -anchor w
    label $c.desc -text $prompt -font ChatMeta -foreground [$C muted] -background $bg \
        -anchor w -justify left -wraplength 220
    grid $c.icon  -row 0 -column 0 -rowspan 2 -sticky n -padx {10 8} -pady 10
    grid $c.title -row 0 -column 1 -sticky w -pady {9 0} -padx {0 10}
    grid $c.desc  -row 1 -column 1 -sticky w -pady {1 10} -padx {0 10}
    grid columnconfigure $c 1 -weight 1
    foreach w [list $c $c.icon $c.title $c.desc] {
        bind $w <ButtonRelease-1> [list ::vmdai::transcript::example_clicked $index]
        bind $w <Enter> [list $c configure -highlightbackground $accent]
        bind $w <Leave> [list $c configure -highlightbackground $hairline]
    }
}

proc ::vmdai::transcript::_empty_ready {f info} {
    set C ::vmdai::theme::c
    set bg [$C surface]
    set r 0
    set i 0
    foreach row [empty_rows $info] {
        lassign $row state name text action cmd
        if {$i > 0} {
            frame $f.sep$i -height 1 -background [$C hairline]
            grid $f.sep$i -row $r -column 0 -columnspan 4 -sticky ew -padx {34 0}
            incr r
        }
        switch -- $state {
            ok      { set glyph "\u2713"; set colour [$C ok] }
            warn    { set glyph "!";      set colour [$C warn] }
            default { set glyph "\u2022"; set colour [$C muted] }
        }
        label $f.g$i -text $glyph -font ChatMetaBold -foreground $colour -background $bg -width 2
        label $f.n$i -text $name -font ChatBody -foreground [$C text] -background $bg -anchor w
        label $f.v$i -text $text -font ChatMeta -foreground [$C muted] -background $bg \
            -anchor w -justify left -wraplength 300
        grid $f.g$i -row $r -column 0 -sticky nw -padx {10 4} -pady 6
        grid $f.n$i -row $r -column 1 -sticky nw -pady 6
        grid $f.v$i -row $r -column 2 -sticky nw -padx {8 8} -pady 6
        if {$action ne ""} {
            label $f.a$i -text $action -font ChatMeta -foreground [$C accent] -background $bg -cursor hand2
            # $cmd can carry a probed server's base_url/model verbatim (M5);
            # a literal % in it would otherwise be %-substituted by bind.
            bind $f.a$i <ButtonRelease-1> [string map {% %%} $cmd]
            grid $f.a$i -row $r -column 3 -sticky ne -padx {0 10} -pady 6
        }
        incr r
        incr i
    }
    grid columnconfigure $f 2 -weight 1
}

# ===========================================================================
# Reasoning display (Part B V4 "Reasoning"; P09-T08).
#
# While a turn streams, its reasoning is one muted italic line
# "Thinking... 00:03" that ticks every second; the text itself is collected,
# hidden, underneath. Sealed, the line becomes "Thought for 3 s >" and a
# click expands the muted, indented text. Reasoning is always its own
# lines, so it never shares a block with the answer. The tag `reasoning`
# covers every reasoning line, so set_reasoning_visible hides them all.
#
# Writes go through a hidden peer of the transcript text: the read-only
# proxy (Part B V4) rejects insert/delete but passes `peer`, and a peer
# shares the text, tags and marks.
# ===========================================================================
namespace eval ::vmdai::transcript {
    if {![array exists ::vmdai::transcript::R]} {
        variable R
        array set R {}
    }
    if {![info exists ::vmdai::transcript::reasoning_hidden]} { variable reasoning_hidden 0 }
}

proc ::vmdai::transcript::_rw {t} {
    set peer $t.__rw
    if {![winfo exists $peer]} { $t peer create $peer }
    return $peer
}

proc ::vmdai::transcript::_reasoning_tags {t} {
    set C ::vmdai::theme::c
    if {[lsearch -exact [font names] ChatMetaItal] < 0} {
        font create ChatMetaItal {*}[font actual ChatMeta] -slant italic
    }
    $t tag configure rhead -font ChatMetaItal -foreground [$C muted] -spacing1 6 -spacing3 4
    $t tag configure rbody -font ChatMeta -foreground [$C muted] -lmargin1 24 -lmargin2 24 -spacing3 6
}

proc ::vmdai::transcript::reasoning_open {t b turn {live 1}} {
    variable R
    variable reasoning_hidden
    _reasoning_tags $t
    set w [_rw $t]
    set bottom [expr {[lindex [$t yview] 1] >= 0.999}]
    if {[$w index "end -1c"] ne "1.0" && [$w get "end -2c"] ne "\n"} { $w insert end "\n" }
    set start [$w index "end -1c"]
    # Inside a run's work log the lines also carry wl:$run (plan 08's
    # _wl), so the run's collapse hides its reasoning with its rows.
    set wl {}
    catch {set wl [_wl]}
    set head_tags [concat reasoning rhead rhead:$b $wl]
    set body_tags [concat reasoning rbody rbody:$b $wl]
    $w insert end "Thinking\u2026 00:00" $head_tags "\n" $head_tags
    $w mark set rs:$b $start
    $w mark gravity rs:$b left
    $w mark set re:$b "$start lineend"
    $w mark gravity re:$b right
    set body [$w index "end -1c"]
    $w insert end "\n" $body_tags
    $w mark set rb:$b $body
    $w mark gravity rb:$b right
    $t tag configure rbody:$b -elide 1
    $t tag bind rhead:$b <ButtonRelease-1> [list ::vmdai::transcript::reasoning_toggle $t $b]
    $t tag bind rhead:$b <Enter> [list $t configure -cursor hand2]
    $t tag bind rhead:$b <Leave> [list $t configure -cursor arrow]
    array set R [list $b,t0 [clock seconds] $b,sealed 0 $b,open 0 $b,secs 0 $b,timer "" \
        $b,head $head_tags $b,body $body_tags]
    if {$live} {
        set R($b,timer) [::vmdai::sched::after 1000 [list ::vmdai::transcript::reasoning_tick $t $b]]
    }
    if {$reasoning_hidden} { $t tag raise reasoning }
    if {$bottom} { $t see end }
}

proc ::vmdai::transcript::reasoning_append {t b chunk} {
    variable R
    if {![info exists R($b,t0)]} { return }
    [_rw $t] insert rb:$b $chunk $R($b,body)
}

proc ::vmdai::transcript::reasoning_seal {t b duration_s} {
    variable R
    if {![info exists R($b,t0)]} { return }
    if {$R($b,timer) ne ""} {
        ::vmdai::sched::cancel $R($b,timer)
        set R($b,timer) ""
    }
    set secs 1
    if {[string is double -strict $duration_s]} { set secs [expr {int(round($duration_s))}] }
    if {$secs < 1} { set secs 1 }
    set R($b,secs) $secs
    set R($b,sealed) 1
    _set_head $t $b [_sealed_head $b]
}

proc ::vmdai::transcript::reasoning_tick {t b {now ""}} {
    variable R
    if {![info exists R($b,t0)] || $R($b,sealed) || ![winfo exists $t]} { return }
    if {$R($b,timer) ne ""} { ::vmdai::sched::cancel $R($b,timer) }
    if {$now eq ""} { set now [clock seconds] }
    set s [expr {$now - $R($b,t0)}]
    if {$s < 0} { set s 0 }
    _set_head $t $b [format "Thinking\u2026 %02d:%02d" [expr {$s / 60}] [expr {$s % 60}]]
    set R($b,timer) [::vmdai::sched::after 1000 [list ::vmdai::transcript::reasoning_tick $t $b]]
}

proc ::vmdai::transcript::reasoning_toggle {t b} {
    variable R
    if {![info exists R($b,sealed)] || !$R($b,sealed)} { return }
    set R($b,open) [expr {!$R($b,open)}]
    # Open: stop specifying -elide (not 0), so a collapsed run's wl:$run still hides it.
    $t tag configure rbody:$b -elide [expr {$R($b,open) ? "" : 1}]
    _set_head $t $b [_sealed_head $b]
}

proc ::vmdai::transcript::_sealed_head {b} {
    variable R
    return "Thought for $R($b,secs) s [expr {$R($b,open) ? "\u25be" : "\u25b8"}]"
}

proc ::vmdai::transcript::_set_head {t b label} {
    variable R
    set w [_rw $t]
    $w delete rs:$b re:$b
    $w insert rs:$b $label $R($b,head)
}

# Hidden: `reasoning` elides and outranks the per-block tags. Shown: it
# stops specifying -elide, so each block's own collapsed/expanded state holds.
proc ::vmdai::transcript::set_reasoning_visible {t on} {
    variable reasoning_hidden
    set reasoning_hidden [expr {$on ? 0 : 1}]
    if {$on} {
        $t tag configure reasoning -elide ""
    } else {
        $t tag configure reasoning -elide 1
        $t tag raise reasoning
    }
}

proc ::vmdai::transcript::reasoning_reset {{t ""}} {
    variable R
    foreach key [array names R *,timer] {
        if {$R($key) ne ""} { ::vmdai::sched::cancel $R($key) }
    }
    array unset R
    array set R {}
}
