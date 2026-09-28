# theme.tcl -- ChatVMD colour tokens, named fonts, paint registry, ttk styles.
#
#   ::vmdai::theme::init ?mode?        define fonts, load tokens, configure styles
#   ::vmdai::theme::c token            -> colour
#   ::vmdai::theme::paint w opt token ?opt token ...?   set and remember
#   ::vmdai::theme::on_repaint cmd     run cmd after every repaint
#   ::vmdai::theme::repaint            re-apply every registered colour
#   ::vmdai::theme::mode               -> light (dark lands in M3)
#   ::vmdai::theme::mono_family ?families?
#
# Part B V2. Only ChatVMD.* ttk styles are configured and the ttk theme is
# never switched (that would restyle QwikMD and every other VMD plugin).

namespace eval ::vmdai::theme {
    variable mode
    if {![info exists mode]} { set mode light }
    variable painted
    if {![info exists painted]} { set painted {} }
    variable hooks
    if {![info exists hooks]} { set hooks {} }
    variable T
}

# Light tokens (Part B V2); dark ones land in M3 (P10-T01).
proc ::vmdai::theme::_palettes {} {
    return {
        light {
            chrome    #ececec   surface   #ffffff   text      #1d1d1f
            text2     #3c3c43   muted     #636366   faint     #a1a1a6
            hairline  #d6d6da   accent    #0a66d8   ok        #1a7f37
            err       #c8262e   err_bg    #fdecec   warn      #835700
            warn_bg   #fff5df   warn_bd   #efd59b   warn_fg   #5c4300
            code_bg   #f4f4f6   icode_bg  #ececf0   hover     #f0f0f4
            stop_bg   #1d1d1f   stop_fg   #ffffff   dot_ok    #28c840
            dot_warn  #d88a00   dot_off   #ff5f57   sel       #b3d7ff
            field_bd  #c8c8cd   focus_ring #9ec1f5
            syn_cmd   #0550ae   syn_var   #953800   syn_str   #0a3069
            syn_num   #8250df   syn_brace #835700   syn_opt   #57606a
            syn_cmt   #636c76
        }
    }
}

proc ::vmdai::theme::aqua {} {
    return [expr {[tk windowingsystem] eq "aqua"}]
}

proc ::vmdai::theme::mode {} {
    variable mode
    return $mode
}

proc ::vmdai::theme::c {token} {
    variable T
    return $T($token)
}

proc ::vmdai::theme::mono_family {{families ""}} {
    if {$families eq ""} { set families [font families] }
    foreach pref {"SF Mono" Menlo "DejaVu Sans Mono"} {
        if {[lsearch -exact $families $pref] >= 0} { return $pref }
    }
    return [font actual TkFixedFont -family]
}

proc ::vmdai::theme::_fonts {} {
    set ui [font actual TkDefaultFont -family]
    set base [font actual TkDefaultFont -size]
    if {$base < 0} { set base [expr {-$base * 3 / 4}] }
    if {$base < 8} { set base 13 }
    set mono [mono_family]
    set spec [list \
        ChatBody      [list -family $ui -size $base] \
        ChatBodyBold  [list -family $ui -size $base -weight bold] \
        ChatBodyItal  [list -family $ui -size [expr {$base - 1}] -slant italic] \
        ChatRole      [list -family $ui -size [expr {$base - 1}] -weight bold] \
        ChatMeta      [list -family $ui -size [expr {$base - 2}]] \
        ChatMetaBold  [list -family $ui -size [expr {$base - 2}] -weight bold] \
        ChatH1        [list -family $ui -size [expr {$base + 7}] -weight bold] \
        ChatH2        [list -family $ui -size [expr {$base + 1}] -weight bold] \
        ChatCode      [list -family $mono -size [expr {$base - 1}]] \
        ChatCodeSmall [list -family $mono -size [expr {$base - 2}]] \
        ChatHair      [list -family $ui -size 1]]
    foreach {name opts} $spec {
        if {[lsearch -exact [font names] $name] >= 0} {
            font configure $name {*}$opts
        } else {
            font create $name {*}$opts
        }
    }
}

proc ::vmdai::theme::_styles {} {
    ttk::style configure ChatVMD.TFrame -background [c chrome]
    ttk::style configure ChatVMD.TLabel -background [c chrome] -foreground [c text] -font ChatBody
    ttk::style configure ChatVMD.Meta.TLabel -background [c chrome] -foreground [c muted] -font ChatMeta
    ttk::style configure ChatVMD.Title.TLabel -background [c chrome] -foreground [c text] -font ChatMetaBold
}

proc ::vmdai::theme::init {{m light}} {
    variable mode
    variable T
    set palettes [_palettes]
    if {![dict exists $palettes $m]} { set m light }
    set mode $m
    array unset T
    array set T [dict get $palettes $m]
    if {[aqua]} {
        set T(chrome) systemWindowBackgroundColor
        set T(sel) systemSelectedTextBackgroundColor
    }
    _fonts
    _styles
    repaint
    return $mode
}

proc ::vmdai::theme::_apply {w spec} {
    variable T
    set cfg {}
    foreach {opt tok} $spec { lappend cfg $opt $T($tok) }
    $w configure {*}$cfg
}

proc ::vmdai::theme::paint {w args} {
    variable painted
    lappend painted [list $w $args]
    _apply $w $args
    return $w
}

proc ::vmdai::theme::on_repaint {cmd} {
    variable hooks
    if {[lsearch -exact $hooks $cmd] < 0} { lappend hooks $cmd }
}

proc ::vmdai::theme::repaint {} {
    variable painted
    variable hooks
    set keep {}
    foreach p $painted {
        lassign $p w spec
        if {[winfo exists $w]} {
            _apply $w $spec
            lappend keep $p
        }
    }
    set painted $keep
    foreach cmd $hooks {
        if {[catch {uplevel #0 $cmd} err]} {
            catch {::vmdai::config::log "theme hook failed: $err"}
        }
    }
    _styles
}

proc ::vmdai::theme::painted_count {} {
    variable painted
    return [llength $painted]
}

# Canvas helpers shared by the toolbar, composer, banner and snapshot cards.
proc ::vmdai::theme::rrect {c x0 y0 x1 y1 r args} {
    set pts [list [expr {$x0+$r}] $y0 [expr {$x1-$r}] $y0 $x1 $y0 $x1 [expr {$y0+$r}] \
        $x1 [expr {$y1-$r}] $x1 $y1 [expr {$x1-$r}] $y1 [expr {$x0+$r}] $y1 \
        $x0 $y1 $x0 [expr {$y1-$r}] $x0 [expr {$y0+$r}] $x0 $y0]
    return [$c create polygon $pts -smooth 1 {*}$args]
}

# Truncate text to px with a trailing ellipsis (binary search, V1 fix).
proc ::vmdai::theme::fit {font px text {min 0}} {
    if {[font measure $font $text] <= $px} { return $text }
    set lo $min
    set hi [string length $text]
    while {$lo < $hi} {
        set mid [expr {($lo + $hi + 1) / 2}]
        if {[font measure $font "[string range $text 0 [expr {$mid - 1}]]…"] <= $px} {
            set lo $mid
        } else {
            set hi [expr {$mid - 1}]
        }
    }
    if {$lo < $min} { set lo $min }
    return "[string range $text 0 [expr {$lo - 1}]]…"
}

# Middle ellipsis for file names and chat titles.
proc ::vmdai::theme::fit_middle {font px text} {
    if {[font measure $font $text] <= $px} { return $text }
    set lo 2
    set hi [expr {[string length $text] - 1}]
    while {$lo < $hi} {
        set mid [expr {($lo + $hi + 1) / 2}]
        if {[font measure $font [_middle $text $mid]] <= $px} {
            set lo $mid
        } else {
            set hi [expr {$mid - 1}]
        }
    }
    if {$lo < 3} { return "\u2026" }
    return [_middle $text $lo]
}

# text with only keep characters left, split around a middle ellipsis.
proc ::vmdai::theme::_middle {text keep} {
    set head [expr {($keep + 1) / 2}]
    set tail [expr {$keep - $head}]
    return "[string range $text 0 [expr {$head - 1}]]\u2026[string range $text end-[expr {$tail - 1}] end]"
}

# ============================================================================
# M3 (plan 10): dark palette, the Appearance setting and system appearance
# events.  Spec Part B V2 and V7.  This section only adds to the M2 theme
# above; M2's init, c, paint, repaint, mode and mono_family keep their meaning.
# ============================================================================
namespace eval ::vmdai::theme {
    # token -> colour for both modes (Part B V2).  tests/test_theme_contrast.py
    # parses these blocks: keep exactly one "token #rrggbb" pair per line.
    # sel, field_bd, focus_ring, spin_hi and spin_lo are the native
    # prototype's extra tokens, kept so an M2 widget that uses them retints.
    # PALETTE is a constant table, not state, so it is set on every source
    # (a reload picks up edits); every stateful variable below is guarded.
    variable PALETTE
    set PALETTE {
        light {
            chrome     #ececec
            surface    #ffffff
            text       #1d1d1f
            text2      #3c3c43
            muted      #636366
            faint      #a1a1a6
            hairline   #d6d6da
            accent     #0a66d8
            ok         #1a7f37
            err        #c8262e
            err_bg     #fdecec
            warn       #835700
            warn_bg    #fff5df
            warn_bd    #efd59b
            warn_fg    #5c4300
            code_bg    #f4f4f6
            icode_bg   #ececf0
            hover      #f0f0f4
            stop_bg    #1d1d1f
            stop_fg    #ffffff
            dot_ok     #28c840
            dot_warn   #d88a00
            dot_off    #ff5f57
            syn_cmd    #0550ae
            syn_var    #953800
            syn_str    #0a3069
            syn_num    #8250df
            syn_brace  #835700
            syn_opt    #57606a
            syn_cmt    #636c76
            sel        #b3d7ff
            field_bd   #c8c8cd
            focus_ring #9ec1f5
            spin_hi    #3a3a3c
            spin_lo    #d8d8dc
        }
        dark {
            chrome     #2c2c2e
            surface    #1e1e1e
            text       #e6e6eb
            text2      #c9c9ce
            muted      #9a9aa1
            faint      #5f5f65
            hairline   #0c0c0d
            accent     #4ea1ff
            ok         #3bd16f
            err        #ff6b64
            err_bg     #3a1f1e
            warn       #e6aa3f
            warn_bg    #3a2f16
            warn_bd    #5a4820
            warn_fg    #f6d58f
            code_bg    #28282b
            icode_bg   #313135
            hover      #29292c
            stop_bg    #e6e6eb
            stop_fg    #1e1e1e
            dot_ok     #32d74b
            dot_warn   #ffb340
            dot_off    #ff453a
            syn_cmd    #79c0ff
            syn_var    #ffa657
            syn_str    #a5d6ff
            syn_num    #d2a8ff
            syn_brace  #e3b341
            syn_opt    #c3cad3
            syn_cmt    #8b949e
            sel        #3f638b
            field_bd   #48484c
            focus_ring #2f5f9f
            spin_hi    #e6e6eb
            spin_lo    #48484c
        }
    }
    if {![info exists ::vmdai::theme::HERE]} {
        set ::vmdai::theme::HERE [file dirname [file normalize [info script]]]
    }
    if {![info exists ::vmdai::theme::appearance]} { set ::vmdai::theme::appearance system }
    if {![info exists ::vmdai::theme::owned]} { set ::vmdai::theme::owned {} }
    if {![info exists ::vmdai::theme::system_pending]} { set ::vmdai::theme::system_pending 0 }
    if {![info exists ::vmdai::theme::known_styles]} { set ::vmdai::theme::known_styles {} }
    # Command prefix for ::tk::unsupported::MacWindowStyle; tests swap it.
    if {![info exists ::vmdai::theme::macstyle]} {
        set ::vmdai::theme::macstyle ::tk::unsupported::MacWindowStyle
    }
}

# The two places this section writes M2's storage (plan 10, contract row 1).
proc ::vmdai::theme::_set_token {tok value} {
    variable T
    set T($tok) $value
}
proc ::vmdai::theme::_set_mode {m} {
    variable mode
    set mode $m
}

# palette m -> token dict for light|dark.  On aqua, chrome and sel are the
# dynamic system colours, which follow each window's appearance.
proc ::vmdai::theme::palette {m} {
    variable PALETTE
    if {![dict exists $PALETTE $m]} {
        error "unknown mode \"$m\": must be light or dark"
    }
    set p [dict get $PALETTE $m]
    if {![catch {tk windowingsystem} ws] && $ws eq "aqua"} {
        dict set p chrome systemWindowBackgroundColor
        dict set p sel systemSelectedTextBackgroundColor
    }
    return $p
}

proc ::vmdai::theme::has_macwindowstyle {} {
    variable macstyle
    if {[catch {tk windowingsystem} ws] || $ws ne "aqua"} {
        return 0
    }
    return [expr {[llength [info commands $macstyle]] > 0}]
}

# The Appearance values Settings offers (V7: no System without MacWindowStyle).
proc ::vmdai::theme::appearance_choices {} {
    if {[has_macwindowstyle]} {
        return {System Light Dark}
    }
    return {Light Dark}
}

# The current setting: system, light or dark.
proc ::vmdai::theme::appearance {} {
    variable appearance
    return $appearance
}

proc ::vmdai::theme::system_is_dark {} {
    variable macstyle
    if {![has_macwindowstyle]} {
        return 0
    }
    if {[catch {{*}$macstyle isdark .} d]} {
        return 0
    }
    return [expr {[string is true -strict $d] ? 1 : 0}]
}

# effective setting -> light|dark
proc ::vmdai::theme::effective {setting} {
    switch -- $setting {
        light - dark {
            return $setting
        }
    }
    if {[system_is_dark]} {
        return dark
    }
    return light
}

# set_appearance system|light|dark (any case) -> the mode now in effect.
proc ::vmdai::theme::set_appearance {setting} {
    variable appearance
    variable system_pending
    set s [string tolower $setting]
    if {[lsearch -exact {system light dark} $s] < 0} {
        error "bad appearance \"$setting\": must be system, light or dark"
    }
    set appearance $s
    # A reload's sched::teardown may have cancelled a pending switch.
    set system_pending 0
    bind_system_events
    set eff [effective $s]
    _apply_mode $eff
    _force_windows
    return $eff
}

# saved_appearance -> plugin.json's appearance, or system.
proc ::vmdai::theme::saved_appearance {} {
    if {[catch {::vmdai::config::load_plugin_settings} s]} {
        return system
    }
    if {[catch {dict get $s appearance} a]} {
        return system
    }
    set a [string tolower $a]
    if {[lsearch -exact {system light dark} $a] < 0} {
        return system
    }
    return $a
}

# own w: count toplevel w as a ChatVMD window even if it uses no Chat* font.
proc ::vmdai::theme::own {w} {
    variable owned
    if {[lsearch -exact $owned $w] < 0} {
        lappend owned $w
    }
}

# Toplevels (including ".") whose widgets belong to ChatVMD: registered with
# own, named .vmd_ai* / .vmdai*, or using a Chat* named font or a ChatVMD.*
# ttk style.  Other plugins' windows (QwikMD, VMD's own) are never touched.
proc ::vmdai::theme::owned_toplevels {} {
    variable owned
    set out {}
    foreach w $owned {
        if {[winfo exists $w]} {
            lappend out $w
        }
    }
    foreach top [_toplevels .] {
        if {[lsearch -exact $out $top] >= 0} {
            continue
        }
        if {[_ours $top]} {
            lappend out $top
        }
    }
    return $out
}

proc ::vmdai::theme::_ours {top} {
    return [expr {[string match .vmd_ai* $top] || [string match .vmdai* $top]
        || [_uses_chat_look $top]}]
}

proc ::vmdai::theme::_toplevels {w} {
    set out {}
    if {[winfo toplevel $w] eq $w} {
        lappend out $w
    }
    foreach c [winfo children $w] {
        set out [concat $out [_toplevels $c]]
    }
    return $out
}

# _subtree top -> top and every descendant in the same toplevel.
proc ::vmdai::theme::_subtree {top} {
    set out [list $top]
    set queue [list $top]
    while {[llength $queue]} {
        set w [lindex $queue 0]
        set queue [lrange $queue 1 end]
        foreach c [winfo children $w] {
            if {[winfo toplevel $c] ne $top} {
                continue
            }
            lappend out $c
            lappend queue $c
        }
    }
    return $out
}

proc ::vmdai::theme::_uses_chat_look {top} {
    foreach w [_subtree $top] {
        if {![catch {$w cget -style} st] && [string match ChatVMD.* $st]} {
            return 1
        }
        if {![catch {$w cget -font} f] && [string match Chat* $f]} {
            return 1
        }
    }
    return 0
}

# _apply_mode m: make m the active palette and retint everything already
# drawn.  (Not "_apply": M2's _apply w spec is the paint helper.)
proc ::vmdai::theme::_apply_mode {m} {
    set new [palette $m]
    set old [dict create]
    dict for {tok val} $new {
        if {![catch {c $tok} cur]} {
            dict set old $tok $cur
        }
    }
    dict for {tok val} $new {
        _set_token $tok $val
    }
    _set_mode $m
    # Deliberately not M2's repaint: repaint's on_repaint hooks (toolbar's
    # icon buttons, the composer's stop control, the status dot, snapshot
    # cards) redraw by `delete all` + recreate, which would hand every canvas
    # item a fresh id on each switch. _retint below reconfigures every
    # already-drawn widget, tag, item and ChatVMD.* style in place instead,
    # by value, so nothing already on screen changes identity (P10-T01
    # dark-events_repaint_dialogs; adapted from the plan text, which called
    # repaint here).
    _retint $old $new
}

# _retint old new: M2 configured widgets, text tags, canvas items and ChatVMD.*
# styles with token values; swap each old value for the new one.  A colour two
# tokens share (warn and syn_brace are both #835700 in light) maps by the
# first token in PALETTE order, except that a text tag named after a token
# (syn_brace) maps by that token.
proc ::vmdai::theme::_retint {old new} {
    set vmap [dict create]
    dict for {tok val} $old {
        set lv [string tolower $val]
        set nv [dict get $new $tok]
        if {$lv eq [string tolower $nv] || [dict exists $vmap $lv]} {
            continue
        }
        dict set vmap $lv $nv
    }
    if {[dict size $vmap] == 0} {
        return
    }
    variable known_styles
    foreach top [owned_toplevels] {
        foreach w [_subtree $top] {
            _retint_options $w $vmap
            switch -- [winfo class $w] {
                Text {
                    _retint_tags $w $vmap $old $new
                }
                Canvas {
                    _retint_items $w $vmap
                }
            }
            if {![catch {$w cget -style} st] && [string match ChatVMD.* $st]
                    && [lsearch -exact $known_styles $st] < 0} {
                lappend known_styles $st
            }
        }
    }
    foreach st [_style_names] {
        _retint_style $st $vmap
    }
}

# Every ChatVMD.* style named in the plugin's sources, plus any seen on a
# widget, so styles of dialogs that are not open yet retint too.
proc ::vmdai::theme::_style_names {} {
    variable HERE
    variable known_styles
    set names $known_styles
    foreach f [glob -nocomplain -directory $HERE *.tcl] {
        if {[catch {open $f r} fh]} {
            continue
        }
        set src [read $fh]
        close $fh
        foreach st [regexp -all -inline {ChatVMD\.[A-Za-z0-9_.]*[A-Za-z0-9_]} $src] {
            if {[lsearch -exact $names $st] < 0} {
                lappend names $st
            }
        }
    }
    return $names
}

proc ::vmdai::theme::_retint_options {w vmap} {
    if {[catch {$w configure} specs]} {
        return
    }
    foreach spec $specs {
        if {[llength $spec] != 5} {
            continue
        }
        set cur [string tolower [lindex $spec 4]]
        if {[dict exists $vmap $cur]} {
            catch {$w configure [lindex $spec 0] [dict get $vmap $cur]}
        }
    }
}

proc ::vmdai::theme::_retint_tags {t vmap old new} {
    foreach tag [$t tag names] {
        if {[catch {$t tag configure $tag} specs]} {
            continue
        }
        foreach spec $specs {
            set cur [string tolower [lindex $spec 4]]
            if {$cur eq ""} {
                continue
            }
            set nv ""
            if {[dict exists $old $tag] && [string tolower [dict get $old $tag]] eq $cur} {
                set nv [dict get $new $tag]
            } elseif {[dict exists $vmap $cur]} {
                set nv [dict get $vmap $cur]
            }
            if {$nv ne ""} {
                catch {$t tag configure $tag [lindex $spec 0] $nv}
            }
        }
    }
}

proc ::vmdai::theme::_retint_items {c vmap} {
    foreach id [$c find all] {
        if {[catch {$c itemconfigure $id} specs]} {
            continue
        }
        foreach spec $specs {
            set cur [string tolower [lindex $spec 4]]
            if {$cur ne "" && [dict exists $vmap $cur]} {
                catch {$c itemconfigure $id [lindex $spec 0] [dict get $vmap $cur]}
            }
        }
    }
}

proc ::vmdai::theme::_retint_style {st vmap} {
    if {[catch {ttk::style configure $st} cfg]} {
        return
    }
    set changes {}
    foreach {opt val} $cfg {
        set lc [string tolower $val]
        if {[dict exists $vmap $lc]} {
            lappend changes $opt [dict get $vmap $lc]
        }
    }
    if {[llength $changes]} {
        catch {ttk::style configure $st {*}$changes}
    }
    if {[catch {ttk::style map $st} mp]} {
        return
    }
    set mchanges {}
    foreach {opt spec} $mp {
        set nspec {}
        set changed 0
        foreach {state val} $spec {
            set lc [string tolower $val]
            if {[dict exists $vmap $lc]} {
                set val [dict get $vmap $lc]
                set changed 1
            }
            lappend nspec $state $val
        }
        if {$changed} {
            lappend mchanges $opt $nspec
        }
    }
    if {[llength $mchanges]} {
        catch {ttk::style map $st {*}$mchanges}
    }
}

# Forced Light/Dark also sets each ChatVMD window's MacWindowStyle appearance
# so native controls match; System hands the window back to the OS (auto).
proc ::vmdai::theme::_force_windows {} {
    if {![has_macwindowstyle]} {
        return
    }
    foreach top [owned_toplevels] {
        _force_one $top
    }
}

proc ::vmdai::theme::_force_one {top} {
    variable appearance
    variable macstyle
    switch -- $appearance {
        light { set v aqua }
        dark { set v darkaqua }
        default { set v auto }
    }
    catch {{*}$macstyle appearance $top $v}
}

# A ChatVMD toplevel mapped after the switch (Settings, History, viewer).
proc ::vmdai::theme::_on_map {w} {
    variable appearance
    if {$appearance eq "system" || ![has_macwindowstyle]} {
        return
    }
    if {[catch {winfo toplevel $w} top] || $top ne $w} {
        return
    }
    if {[_ours $w]} {
        _force_one $w
    }
}

# Follow the OS while the setting is System.  Idempotent across reloads;
# each binding is wrapped in catch (V2).
proc ::vmdai::theme::bind_system_events {} {
    foreach {ev hint} {<<LightAqua>> light <<DarkAqua>> dark <<AppearanceChanged>> probe} {
        catch {
            if {[string first ::vmdai::theme::on_system_event [bind all $ev]] < 0} {
                bind all $ev [list +::vmdai::theme::on_system_event $hint]
            }
        }
    }
    catch {
        if {[string first ::vmdai::theme::_on_map [bind Toplevel <Map>]] < 0} {
            bind Toplevel <Map> {+::vmdai::theme::_on_map %W}
        }
    }
}

# The OS sends these events to every toplevel, and Tk also sends them when a
# window is first realized, so the event name is only a trigger: the switch
# runs once, when idle, and asks MacWindowStyle isdark for the real state.
proc ::vmdai::theme::on_system_event {hint} {
    variable appearance
    variable system_pending
    if {$appearance ne "system" || $system_pending} {
        return
    }
    set system_pending 1
    if {[llength [info commands ::vmdai::sched::after_idle]]} {
        ::vmdai::sched::after_idle ::vmdai::theme::_system_changed
    } else {
        after idle ::vmdai::theme::_system_changed
    }
}

proc ::vmdai::theme::_system_changed {} {
    variable appearance
    variable system_pending
    set system_pending 0
    if {$appearance ne "system"} {
        return
    }
    set eff [effective system]
    if {$eff ne [mode]} {
        _apply_mode $eff
    }
}

# syntax_tags t: the syn_* tags of text widget t, from the syn_* tokens (V2).
# A tag that dims text with muted or faint (the statements after a failure,
# V4 "Step detail") is raised above them, so dimmed code stays dimmed.
proc ::vmdai::theme::syntax_tags {t} {
    foreach cls {cmd var str num brace opt cmt} {
        $t tag configure syn_$cls -foreground [c syn_$cls]
        $t tag raise syn_$cls
    }
    set dim [list [string tolower [c muted]] [string tolower [c faint]]]
    foreach tag [$t tag names] {
        if {[string match syn_* $tag] || [catch {$t tag cget $tag -foreground} fg]} {
            continue
        }
        if {[lsearch -exact $dim [string tolower $fg]] >= 0} {
            $t tag raise $tag
        }
    }
    catch {$t tag raise sel}
}
