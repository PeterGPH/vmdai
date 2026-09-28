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
