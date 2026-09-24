# ============================================================================
#  ChatVMD -- "Lab Console" panel.  High-fidelity prototype + reference renderer
# ============================================================================
#  usage (always through capture_locked.sh):
#     proto.tcl <state>[:light|:dark] <abs-out.png> [WxH]
#  states
#     A  full conversation, light          B  same, dark
#     C  mid-run (step 4 running)          D  empty / first run
#     E  settings dialog over B            F  narrow 420x700 of A
#     G  runtime disconnected              T  (extra) A scrolled to the top
#
#  Written the way the production plugin would be:
#    * theme tokens  -> ::cv::theme  (one dict per variant, `paint` registry)
#    * named fonts   -> ::cv::fonts  (derived from TkDefaultFont / TkFixedFont)
#    * one render proc per runtime event (role,type) -> ::cv::tr::event
#    * marks + per-item tags so a run is updated in place as results stream in
#  All non-ASCII glyphs are written as \u escapes (source encoding independent).
#  Nothing here sources the real plugin.
# ============================================================================

package require Tk 8.5

namespace eval ::cv {
    variable DESIGN [file normalize [file join [file dirname [info script]] ../..]]
    variable SNAP   $DESIGN/assets/snap_1hck.png
    variable TK86   [package vsatisfies [package provide Tk] 8.6]
    # CV_SIM85=1: exercise the Tk 8.5 code paths (no margin colours, no PNG thumbnails)
    if {[info exists ::env(CV_SIM85)] && $::env(CV_SIM85)} { set TK86 0 }
    variable LOGCH  [open [file join /tmp chatvmd_proto_console.log] a]
    variable OUT    ""
}
proc ::cv::log {msg} {
    variable LOGCH
    puts $LOGCH "[clock format [clock seconds] -format %T] $msg"
    flush $LOGCH
}

# ---------------------------------------------------------------------------
#  Theme tokens.  Everything visual reads a token; nothing hard-codes a colour.
# ---------------------------------------------------------------------------
namespace eval ::cv::theme {
    namespace export C
    variable name dark
    variable T
    variable painted {}
    variable P
    set P(dark) {
        bg         #0f1216
        chrome     #0a0c0f
        surface    #151a20
        field      #0c0f13
        band       #161b22
        code       #161c24
        code_hdr   #1d242e
        chip       #212a36
        rule       #232a33
        rule2      #313a46
        fg         #e3e7ec
        fg2        #c3cad3
        muted      #8d96a2
        faint      #5f6975
        accent     #5aa9ff
        on_accent  #06111e
        ok         #46c35b
        err        #ff6b61
        err_bg     #2b1517
        warn       #e3b341
        warn_bg    #262012
        user_bg    #121c29
        sel        #26496f
        hover      #1b222b
        syn_cmd    #79c0ff
        syn_brace  #e3b341
        syn_var    #ffa657
        syn_str    #a5d6ff
        syn_num    #d2a8ff
        syn_opt    #c3cad3
        syn_cmt    #6e7781
        shot_bg    #000000
    }
    set P(light) {
        bg         #fbfbfa
        chrome     #f1f2f4
        surface    #ffffff
        field      #ffffff
        band       #f0f3f6
        code       #f3f5f8
        code_hdr   #e8ecf1
        chip       #e1e7ee
        rule       #dde2e8
        rule2      #c9d1da
        fg         #1d2125
        fg2        #2f363d
        muted      #59636e
        faint      #8a939d
        accent     #0969da
        on_accent  #ffffff
        ok         #1a7f37
        err        #cf222e
        err_bg     #ffefed
        warn       #8a5d00
        warn_bg    #fff7dc
        user_bg    #edf3fb
        sel        #c8defa
        hover      #e9edf1
        syn_cmd    #0550ae
        syn_brace  #9a6700
        syn_var    #bc4c00
        syn_str    #0a3069
        syn_num    #8250df
        syn_opt    #2f363d
        syn_cmt    #6e7781
        shot_bg    #000000
    }
}
proc ::cv::theme::use {n} {
    variable T; variable P; variable name
    set name $n
    array unset T
    array set T $P($n)
    repaint
}
proc ::cv::theme::C {k} { variable T; return $T($k) }
# Register a widget's colour options against tokens so a theme switch
# (<<LightAqua>>/<<DarkAqua>> on macOS, a Settings toggle elsewhere) repaints it.
proc ::cv::theme::paint {w args} {
    variable painted
    lappend painted [list $w $args]
    apply_one $w $args
    return $w
}
proc ::cv::theme::apply_one {w spec} {
    variable T
    set cfg {}
    foreach {opt tok} $spec { lappend cfg $opt $T($tok) }
    $w configure {*}$cfg
}
proc ::cv::theme::repaint {} {
    variable painted
    set keep {}
    foreach p $painted {
        lassign $p w spec
        if {[winfo exists $w]} { apply_one $w $spec; lappend keep $p }
    }
    set painted $keep
}
# Title bar + native (ttk/aqua) controls follow the panel's palette, not the OS setting.
proc ::cv::theme::mac_appearance {w} {
    variable name
    catch {::tk::unsupported::MacWindowStyle appearance $w \
               [expr {$name eq "dark" ? "darkaqua" : "aqua"}]}
}

# ---------------------------------------------------------------------------
#  Named fonts.  Families come from the platform's own named fonts, so Linux/X11
#  gets DejaVu (or whatever fontconfig maps) instead of a missing "Menlo".
# ---------------------------------------------------------------------------
namespace eval ::cv::fonts {}
proc ::cv::fonts::init {} {
    set ui   [font actual TkDefaultFont -family]
    set mono [font actual TkFixedFont -family]
    foreach {nm fam size opts} [list \
        CV.ui     $ui   12 {} \
        CV.uiB    $ui   12 {-weight bold} \
        CV.uiS    $ui   11 {} \
        CV.uiSB   $ui   11 {-weight bold} \
        CV.prose  $ui   13 {} \
        CV.proseB $ui   13 {-weight bold} \
        CV.proseI $ui   12 {-slant italic} \
        CV.h1     $ui   19 {-weight bold} \
        CV.mono   $mono 11 {} \
        CV.monoB  $mono 11 {-weight bold} \
        CV.monoS  $mono 10 {} \
        CV.monoSB $mono 10 {-weight bold} \
        CV.hair   $mono -1 {} ] {
        catch {font delete $nm}
        font create $nm -family $fam -size $size {*}$opts
    }
}

# ---------------------------------------------------------------------------
#  Small utilities
# ---------------------------------------------------------------------------
namespace eval ::cv::util {}
# Rounded rectangle as a smoothed polygon (works on every Tk canvas, 8.5+).
proc ::cv::util::rrect {c x0 y0 x1 y1 r args} {
    set pts [list \
        [expr {$x0+$r}] $y0 [expr {$x0+$r}] $y0 [expr {$x1-$r}] $y0 [expr {$x1-$r}] $y0 \
        $x1 $y0 $x1 [expr {$y0+$r}] $x1 [expr {$y0+$r}] $x1 [expr {$y1-$r}] $x1 [expr {$y1-$r}] \
        $x1 $y1 [expr {$x1-$r}] $y1 [expr {$x1-$r}] $y1 [expr {$x0+$r}] $y1 [expr {$x0+$r}] $y1 \
        $x0 $y1 $x0 [expr {$y1-$r}] $x0 [expr {$y1-$r}] $x0 [expr {$y0+$r}] $x0 [expr {$y0+$r}] $x0 $y0]
    return [$c create polygon $pts -smooth 1 {*}$args]
}
# Truncate to a pixel width with a trailing ellipsis (binary search on font measure).
proc ::cv::util::fit {font px text} {
    if {[font measure $font $text] <= $px} { return $text }
    set lo 0; set hi [string length $text]
    while {$lo < $hi} {
        set mid [expr {($lo + $hi + 1) / 2}]
        if {[font measure $font "[string range $text 0 [expr {$mid-1}]]\u2026"] <= $px} {
            set lo $mid
        } else { set hi [expr {$mid - 1}] }
    }
    return "[string trimright [string range $text 0 [expr {$lo-1}]]]\u2026"
}
proc ::cv::util::secs {ms} { return [format "%.1f s" [expr {$ms / 1000.0}]] }
proc ::cv::util::clock {s} { return [format "%02d:%02d" [expr {$s / 60}] [expr {$s % 60}]] }

# ---------------------------------------------------------------------------
#  Tcl syntax tinting (per line; no packages).  Commands, braces/brackets,
#  $vars, "strings", numbers, -options, comments.
# ---------------------------------------------------------------------------
namespace eval ::cv::syntax {}
proc ::cv::syntax::tokens {line} {
    set out {}
    set cmdpos 1
    while {$line ne ""} {
        if {[regexp {^\s+} $line m]} {
            lappend out $m {}
        } elseif {$cmdpos && [regexp {^#.*} $line m]} {
            lappend out $m syn_cmt
        } elseif {[regexp {^\$(\{[^\}]*\}|[A-Za-z0-9_:]+(\([^\)]*\))?)} $line m]} {
            lappend out $m syn_var; set cmdpos 0
        } elseif {[regexp {^\[} $line m]} {
            lappend out $m syn_brace; set cmdpos 1
        } elseif {[regexp {^[\]\{\}]} $line m]} {
            lappend out $m syn_brace; set cmdpos 0
        } elseif {[regexp {^;} $line m]} {
            lappend out $m {}; set cmdpos 1
        } elseif {[regexp {^"(?:[^"\\]|\\.)*"?} $line m]} {
            lappend out $m syn_str; set cmdpos 0
        } elseif {!$cmdpos && [regexp {^-?[0-9]+(?:\.[0-9]+)?(?=[\s\]\};]|$)} $line m]} {
            lappend out $m syn_num
        } elseif {!$cmdpos && [regexp {^-[A-Za-z][A-Za-z0-9_]*} $line m]} {
            lappend out $m syn_opt
        } elseif {[regexp {^[^\s\[\]\{\}\$;"]+} $line m]} {
            lappend out $m [expr {$cmdpos ? "syn_cmd" : ""}]; set cmdpos 0
        } else {
            set m [string index $line 0]; lappend out $m {}; set cmdpos 0
        }
        set line [string range $line [string length $m] end]
    }
    return $out
}

# ---------------------------------------------------------------------------
#  Custom widgets (canvas based so colours are honoured on aqua and X11 alike)
# ---------------------------------------------------------------------------
namespace eval ::cv::w { namespace import ::cv::theme::C }

# Push button.  kind: primary | ghost | danger | disabled.  on: parent bg token.
proc ::cv::w::pill {w text args} {
    array set o {-kind primary -font CV.uiB -h 28 -padx 14 -command {} -on bg -icon {} -r 6}
    array set o $args
    set iw [expr {$o(-icon) ne "" ? 14 : 0}]
    set W [expr {[font measure $o(-font) $text] + 2*$o(-padx) + $iw}]
    canvas $w -width $W -height $o(-h) -highlightthickness 0 -bd 0
    ::cv::theme::paint $w -background $o(-on)
    switch -- $o(-kind) {
        primary  { set fill [C accent]; set line [C accent]; set fg [C on_accent] }
        danger   { set fill [C err];    set line [C err];    set fg [C on_accent] }
        ghost    { set fill [C $o(-on)]; set line [C rule2]; set fg [C fg] }
        disabled { set fill [C hover];  set line [C rule];   set fg [C faint] }
    }
    ::cv::util::rrect $w 1 1 [expr {$W-1}] [expr {$o(-h)-1}] $o(-r) -fill $fill -outline $line
    set tx [expr {$W/2 + $iw/2}]
    if {$o(-icon) eq "stop"} {
        set x0 [expr {$tx - [font measure $o(-font) $text]/2 - 13}]
        set cy [expr {$o(-h)/2}]
        ::cv::util::rrect $w $x0 [expr {$cy-4}] [expr {$x0+8}] [expr {$cy+4}] 1.5 -fill $fg -outline $fg
    }
    $w create text $tx [expr {$o(-h)/2}] -text $text -font $o(-font) -fill $fg
    if {$o(-kind) ne "disabled" && $o(-command) ne ""} {
        bind $w <1> $o(-command)
        $w configure -cursor hand2
    }
    return $w
}

# 26x24 icon button drawn with canvas primitives (theme-able, crisp at 2x).
proc ::cv::w::iconbtn {w icon args} {
    array set o {-on chrome -command {} -tip {}}
    array set o $args
    canvas $w -width 28 -height 24 -highlightthickness 0 -bd 0 -cursor hand2
    ::cv::theme::paint $w -background $o(-on)
    set bgid [::cv::util::rrect $w 1 1 27 23 5 -fill [C $o(-on)] -outline [C $o(-on)]]
    set f [C muted]
    switch -- $icon {
        new {
            $w create line 14 6.5 14 17.5 -fill $f -width 1.6 -capstyle round
            $w create line 8.5 12 19.5 12 -fill $f -width 1.6 -capstyle round
        }
        history {
            $w create oval 8 6 20 18 -outline $f -width 1.4
            $w create line 14 8.8 14 12.2 17 13.8 -fill $f -width 1.4 -capstyle round -joinstyle round
        }
        settings {
            $w create line 8 9 20 9 -fill $f -width 1.4 -capstyle round
            $w create line 8 15 20 15 -fill $f -width 1.4 -capstyle round
            $w create oval 9 6.5 14 11.5 -fill [C $o(-on)] -outline $f -width 1.4
            $w create oval 14 12.5 19 17.5 -fill [C $o(-on)] -outline $f -width 1.4
        }
        more {
            foreach x {9 14 19} { $w create oval [expr {$x-1.3}] 10.7 [expr {$x+1.3}] 13.3 -fill $f -outline $f }
        }
    }
    bind $w <Enter> [list $w itemconfigure $bgid -fill [C hover] -outline [C hover]]
    bind $w <Leave> [list $w itemconfigure $bgid -fill [C $o(-on)] -outline [C $o(-on)]]
    if {$o(-command) ne ""} { bind $w <1> $o(-command) }
    return $w
}

# ChatVMD mark: three "atoms" and two bonds.
proc ::cv::w::logo {w {on chrome}} {
    canvas $w -width 20 -height 20 -highlightthickness 0 -bd 0
    ::cv::theme::paint $w -background $on
    $w create line 5 14 10 6 15 14 -fill [C faint] -width 1.6 -joinstyle round
    $w create oval 2 11 8 17 -fill [C accent] -outline ""
    $w create oval 7 3 13 9 -fill [C ok] -outline ""
    $w create oval 12 11 18 17 -fill [C syn_brace] -outline ""
    return $w
}

# Activity spinner (arc).  animate=1 rotates it with `after`; static for screenshots.
proc ::cv::w::spinner {w {on bg} {size 12} {animate 1}} {
    canvas $w -width $size -height $size -highlightthickness 0 -bd 0
    ::cv::theme::paint $w -background $on
    set p 1.5
    $w create oval $p $p [expr {$size-$p}] [expr {$size-$p}] -outline [C rule2] -width 1.6
    $w create arc  $p $p [expr {$size-$p}] [expr {$size-$p}] -start 90 -extent -110 \
        -style arc -outline [C accent] -width 1.8 -tags a
    if {$animate} { after 60 [list ::cv::w::spin_step $w 90] }
    return $w
}
proc ::cv::w::spin_step {w a} {
    if {![winfo exists $w]} return
    set a [expr {($a - 30) % 360}]
    $w itemconfigure a -start $a
    after 60 [list ::cv::w::spin_step $w $a]
}

proc ::cv::w::dot {w color {on chrome}} {
    canvas $w -width 8 -height 8 -highlightthickness 0 -bd 0
    ::cv::theme::paint $w -background $on
    $w create oval 1 1 7 7 -fill [C $color] -outline ""
    return $w
}

# Thin overlay-style vertical scrollbar (canvas).  Hidden when everything fits.
proc ::cv::w::vscroll {w target} {
    canvas $w -width 9 -highlightthickness 0 -bd 0
    ::cv::theme::paint $w -background bg
    ::cv::util::rrect $w 2 0 7 10 2.5 -fill [C rule2] -outline [C rule2] -tags thumb
    bind $w <B1-Motion> [list ::cv::w::vscroll_drag $w $target %y]
    bind $w <1>         [list ::cv::w::vscroll_drag $w $target %y]
    return $w
}
proc ::cv::w::vscroll_set {w first last} {
    if {![winfo exists $w]} return
    set h [winfo height $w]
    if {$first <= 0.0 && $last >= 1.0} { $w itemconfigure thumb -state hidden; return }
    $w itemconfigure thumb -state normal
    set y0 [expr {$first * $h}]; set y1 [expr {$last * $h}]
    if {$y1 - $y0 < 24} { set y1 [expr {$y0 + 24}] }
    $w delete thumb
    ::cv::util::rrect $w 2.5 [expr {$y0+2}] 6.5 [expr {$y1-2}] 2 -fill [C rule2] -outline [C rule2] -tags thumb
}
proc ::cv::w::vscroll_drag {w target y} {
    set h [winfo height $w]
    $target yview moveto [expr {double($y) / $h - 0.05}]
}

# Segmented control (provider picker).
proc ::cv::w::segmented {w items sel args} {
    array set o {-font CV.uiS -h 26 -on surface -padx 11}
    array set o $args
    set widths {}
    set W 0
    foreach it $items {
        set iw [expr {[font measure $o(-font) $it] + 2*$o(-padx)}]
        lappend widths $iw; incr W $iw
    }
    canvas $w -width [expr {$W+2}] -height $o(-h) -highlightthickness 0 -bd 0
    ::cv::theme::paint $w -background $o(-on)
    ::cv::util::rrect $w 1 1 [expr {$W+1}] [expr {$o(-h)-1}] 6 -fill [C field] -outline [C rule2]
    set x 1
    set i 0
    foreach it $items iw $widths {
        if {$it eq $sel} {
            ::cv::util::rrect $w [expr {$x+2}] 3 [expr {$x+$iw-2}] [expr {$o(-h)-3}] 4 \
                -fill [C accent] -outline [C accent]
            set fg [C on_accent]
        } else {
            set fg [C fg2]
            if {$i > 0 && [lindex $items [expr {$i-1}]] ne $sel} {
                $w create line $x 7 $x [expr {$o(-h)-7}] -fill [C rule2]
            }
        }
        $w create text [expr {$x + $iw/2}] [expr {$o(-h)/2}] -text $it -font $o(-font) -fill $fg
        incr x $iw; incr i
    }
    return $w
}

# On/off switch.
proc ::cv::w::toggle {w on_ {bg surface}} {
    canvas $w -width 36 -height 20 -highlightthickness 0 -bd 0 -cursor hand2
    ::cv::theme::paint $w -background $bg
    if {$on_} {
        ::cv::util::rrect $w 1 1 35 19 9 -fill [C accent] -outline [C accent]
        $w create oval 18 3 33 17 -fill #ffffff -outline ""
    } else {
        ::cv::util::rrect $w 1 1 35 19 9 -fill [C rule2] -outline [C rule2]
        $w create oval 3 3 18 17 -fill #ffffff -outline ""
    }
    return $w
}

# Flat entry with a 1px themed border (classic tk entry honours colours everywhere).
proc ::cv::w::field {w args} {
    array set o {-text {} -font CV.mono -width 24 -show {} -state normal}
    array set o $args
    entry $w -relief flat -bd 4 -highlightthickness 1 -font $o(-font) -width $o(-width)
    ::cv::theme::paint $w -background field -foreground fg -insertbackground fg \
        -highlightbackground rule2 -highlightcolor accent -selectbackground sel \
        -disabledbackground surface -disabledforeground faint -readonlybackground field
    if {$o(-show) ne ""} { $w configure -show $o(-show) }
    $w insert 0 $o(-text)
    $w configure -state $o(-state)
    return $w
}

# Combobox look-alike: entry + chevron that posts a menu of choices.
proc ::cv::w::combo {w value choices args} {
    array set o {-width 22 -on surface}
    array set o $args
    frame $w -highlightthickness 1 -bd 0
    ::cv::theme::paint $w -background field -highlightbackground rule2 -highlightcolor accent
    entry $w.e -relief flat -bd 4 -highlightthickness 0 -font CV.mono -width $o(-width)
    ::cv::theme::paint $w.e -background field -foreground fg -insertbackground fg -selectbackground sel
    $w.e insert 0 $value
    canvas $w.c -width 22 -height 20 -highlightthickness 0 -bd 0 -cursor hand2
    ::cv::theme::paint $w.c -background field
    $w.c create line 7 8 11 12 15 8 -fill [C muted] -width 1.5 -capstyle round -joinstyle round
    menu $w.m -tearoff 0
    foreach ch $choices { $w.m add command -label $ch -command [list ::cv::w::combo_pick $w $ch] }
    bind $w.c <1> [list tk_popup $w.m %X %Y]
    pack $w.c -side right -fill y
    pack $w.e -side left -fill x -expand 1
    return $w
}
proc ::cv::w::combo_pick {w v} { $w.e delete 0 end; $w.e insert 0 $v }

# ---------------------------------------------------------------------------
#  Snapshot thumbnails.  Tk 8.6 decodes PNG natively; `copy -subsample` makes a
#  nearest-neighbour thumbnail.  The black viewport margin is auto-trimmed by
#  sampling a coarse grid (~14k `get`s for a 1280x1547 render, a few ms).
# ---------------------------------------------------------------------------
namespace eval ::cv::snap { namespace import ::cv::theme::C }
proc ::cv::snap::autocrop {img {step 12} {tol 36} {pad 26}} {
    set W [image width $img]; set H [image height $img]
    lassign [$img get 2 2] br bgc bb
    set x0 $W; set y0 $H; set x1 -1; set y1 -1
    for {set y 0} {$y < $H} {incr y $step} {
        for {set x 0} {$x < $W} {incr x $step} {
            lassign [$img get $x $y] r g b
            if {abs($r-$br) + abs($g-$bgc) + abs($b-$bb) > $tol} {
                if {$x < $x0} {set x0 $x}
                if {$x > $x1} {set x1 $x}
                if {$y < $y0} {set y0 $y}
                if {$y > $y1} {set y1 $y}
            }
        }
    }
    if {$x1 < 0} { return [list 0 0 $W $H] }
    set x0 [expr {max(0, $x0 - $pad)}];  set y0 [expr {max(0, $y0 - $pad)}]
    set x1 [expr {min($W, $x1 + $pad)}]; set y1 [expr {min($H, $y1 + $pad)}]
    return [list $x0 $y0 $x1 $y1]
}
proc ::cv::snap::thumb {path maxw maxh} {
    if {!$::cv::TK86} { return {} }          ;# Tk 8.5: no PNG photo -> caller shows a link
    if {[catch {image create photo -file $path} src]} { return {} }
    lassign [autocrop $src] x0 y0 x1 y1
    set cw [expr {$x1 - $x0}]; set ch [expr {$y1 - $y0}]
    set f [expr {max(1, int(ceil(max(double($cw)/$maxw, double($ch)/$maxh))))}]
    set th [image create photo]
    $th copy $src -from $x0 $y0 $x1 $y1 -subsample $f $f
    set dims [list [image width $src] [image height $src]]
    image delete $src
    return [list $th {*}$dims]
}
# Canvas card: thumbnail + caption column.  Embedded into the transcript with
# `$text window create`, so it scrolls with the run and is clickable.
proc ::cv::snap::card {w path file purpose sent} {
    set info [thumb $path 150 118]
    set W ?; set H ?
    canvas $w -highlightthickness 0 -bd 0 -cursor hand2
    ::cv::theme::paint $w -background bg
    if {$info eq ""} {
        # Tk 8.5 (no PNG photo) / decode failure: text-only card; "Open" hands the
        # file to the OS viewer.  (Runtime could also emit a GIF/PPM thumbnail.)
        set tw 0; set th 0
        catch {
            set f [open $path rb]; set hdr [read $f 24]; close $f
            binary scan [string range $hdr 16 23] II W H
        }
    } else {
        lassign $info img W H
        set tw [image width $img]; set th [image height $img]
        $w create rectangle 0 0 [expr {$tw+2}] [expr {$th+2}] -fill [C shot_bg] -outline [C rule2]
        $w create image 1 1 -anchor nw -image $img
    }
    set x [expr {$tw ? $tw + 14 : 0}]
    set y 2
    $w create text $x $y -anchor nw -text $file -font CV.mono -fill [C fg];            incr y 18
    $w create text $x $y -anchor nw -text "${W}\u00D7${H} \u00B7 TachyonInternal" \
        -font CV.monoS -fill [C muted];                                                   incr y 16
    $w create text $x $y -anchor nw -text $purpose -font CV.proseI -fill [C muted] -width 190
    incr y 20
    if {$sent} {
        $w create text $x $y -anchor nw -text "\u2713 seen by model" -font CV.monoS -fill [C ok]
        incr y 16
    }
    set ly [expr {max($y + 6, $th - 12)}]
    $w create text $x $ly -anchor nw -text "Open \u2197" -font CV.monoS -fill [C accent] -tags lk_open
    $w create text [expr {$x + 62}] $ly -anchor nw -text "Reveal" -font CV.monoS -fill [C accent] -tags lk_rev
    set bb [$w bbox all]
    $w configure -width [expr {[lindex $bb 2] + 4}] -height [expr {max($th + 3, [lindex $bb 3] + 2)}]
    $w bind lk_open <1> [list ::cv::log "open $path"]
    bind $w <1> [list ::cv::log "enlarge $path"]
    return $w
}

# ---------------------------------------------------------------------------
#  Transcript renderer.  One text widget; every run is a tagged region.
#
#  columns (px):  PAD  gutter glyph (status)   NUM step no.   CONTENT text
#                 CODE left edge of code bands (text starts one mono space in)
# ---------------------------------------------------------------------------
namespace eval ::cv::tr {
    namespace import ::cv::theme::C
    variable PAD 14
    variable NUM 30
    variable CONTENT 46
    variable CODE 40
    variable NARROW 400
    variable t ""
    variable pin ""
    variable sb ""
    variable cur ""
    variable run
    variable calls
    variable stream_open 0
    variable pin_run ""
    array set run {}
    array set calls {}
}

proc ::cv::tr::build {p} {
    variable t; variable pin; variable sb
    frame $p
    ::cv::theme::paint $p -background bg
    set t [text $p.t -wrap word -relief flat -bd 0 -highlightthickness 0 -padx 0 -pady 0 \
               -cursor arrow -insertwidth 0 -width 10 -height 10 -spacing1 0 -spacing3 0 \
               -yscrollcommand ::cv::tr::on_scroll]
    set sb [::cv::w::vscroll $p.sb $t]
    frame $p.pinf -height 40 -bd 0
    ::cv::theme::paint $p.pinf -background band
    set pin [text $p.pinf.t -wrap none -relief flat -bd 0 -highlightthickness 0 -padx 0 -pady 0 \
                 -cursor arrow -insertwidth 0 -height 2 -width 10]
    pack propagate $p.pinf 0
    pack $pin -fill both -expand 1
    frame $p.pinrule -height 1
    ::cv::theme::paint $p.pinrule -background rule
    grid $t  -row 2 -column 0 -sticky nsew
    grid $sb -row 2 -column 1 -sticky ns
    grid columnconfigure $p 0 -weight 1
    grid rowconfigure $p 2 -weight 1
    style_tags $t
    style_tags $pin
    # A disabled text widget cannot take focus on aqua/X11, so Cmd/Ctrl-C would go to
    # the composer.  Keep it read-only by state, but give it focus on click.
    bind $t <1> {+focus %W}
    bind $t <Configure> ::cv::tr::relayout
    return $p
}

# All transcript styling in one place; re-run on theme change.
proc ::cv::tr::style_tags {t} {
    variable PAD; variable NUM; variable CONTENT; variable CODE
    set m86 $::cv::TK86
    $t configure -background [C bg] -foreground [C fg2] -font CV.prose \
        -selectbackground [C sel] -selectforeground [C fg] -inactiveselectbackground [C sel]
    # full-bleed bands: margins painted in the band colour (Tk >= 8.6.6)
    proc bleed {t tag color} {
        if {$::cv::TK86} { $t tag configure $tag -lmargincolor $color -rmargincolor $color }
    }
    $t tag configure hair -font CV.hair -background [C rule] -spacing1 0 -spacing3 0
    bleed $t hair [C rule]
    # run header
    $t tag configure rh -font CV.monoS -foreground [C muted] -background [C band] \
        -lmargin1 $PAD -lmargin2 $PAD -rmargin $PAD -spacing1 0 -spacing3 0 -wrap none
    bleed $t rh [C band]
    # 1px-font "pad lines" give the band vertical padding without letting tag
    # backgrounds (chips) grow to the full band height
    $t tag configure rhpad -font CV.hair -spacing1 5 -spacing3 0 -background [C band]
    bleed $t rhpad [C band]
    $t tag configure rh_id     -font CV.monoSB -foreground [C fg]
    $t tag configure rh_toggle -foreground [C faint]
    $t tag configure rh_live   -foreground [C accent]
    $t tag configure rh_fail   -foreground [C err]
    $t tag configure sep       -foreground [C faint]
    # the user's request
    $t tag configure prompt -font CV.prose -foreground [C fg] -background [C user_bg] \
        -lmargin1 $PAD -lmargin2 $CONTENT -rmargin $PAD -spacing1 7 -spacing2 2 -spacing3 8
    bleed $t prompt [C user_bg]
    $t tag configure prompt_glyph -font CV.monoB -foreground [C accent]
    # assistant prose between steps
    $t tag configure prose -font CV.prose -foreground [C fg2] -lmargin1 $CONTENT -lmargin2 $CONTENT \
        -rmargin $PAD -spacing1 8 -spacing2 2 -spacing3 2
    # step rows
    $t tag configure step -font CV.mono -foreground [C muted] -lmargin1 $PAD -lmargin2 $CONTENT \
        -rmargin $PAD -spacing1 9 -spacing3 4 -wrap none
    $t tag configure step_ok   -font CV.monoB -foreground [C ok]
    $t tag configure step_err  -font CV.monoB -foreground [C err]
    $t tag configure step_num  -foreground [C faint]
    $t tag configure step_tool -foreground [C fg2]
    $t tag configure step_why  -font CV.proseI -foreground [C muted]
    $t tag configure step_time -font CV.monoS -foreground [C faint]
    $t tag configure step_live -font CV.monoS -foreground [C accent]
    $t tag configure step_note -font CV.monoS -foreground [C err]
    # code bands (exact Tcl)
    $t tag configure code -font CV.mono -foreground [C fg] -background [C code] \
        -lmargin1 $CODE -lmargin2 [expr {$CODE + 20}] -rmargin $PAD -spacing1 1 -spacing3 1
    $t tag configure code_top -spacing1 6
    $t tag configure code_bot -spacing3 6
    foreach s {cmd brace var str num opt cmt} { $t tag configure syn_$s -foreground [C syn_$s] }
    # Tk paints a tag's -background into the left/right margins too; for inset
    # blocks (code cells, error cells, fence headers) paint the margins with bg.
    proc inset {t tag} {
        if {$::cv::TK86} { $t tag configure $tag -lmargincolor [C bg] -rmargincolor [C bg] }
    }
    # results
    $t tag configure out -font CV.mono -foreground [C muted] -lmargin1 $CONTENT \
        -lmargin2 [expr {$CONTENT + 16}] -rmargin $PAD -spacing1 4 -spacing3 1
    $t tag configure out_arrow -foreground [C faint]
    $t tag configure out_val   -foreground [C fg]
    $t tag configure out_err -font CV.mono -foreground [C err] -background [C err_bg] \
        -lmargin1 $CODE -lmargin2 [expr {$CODE + 20}] -rmargin $PAD -spacing1 5 -spacing3 6
    inset $t code; inset $t out_err
    $t tag configure snap -lmargin1 $CONTENT -lmargin2 $CONTENT -spacing1 7 -spacing3 2
    # markdown
    $t tag configure md_b    -font CV.proseB -foreground [C fg]
    $t tag configure md_code -font CV.mono -foreground [C syn_cmd]
    $t tag configure md_li   -font CV.prose -foreground [C fg2] -lmargin1 [expr {$CONTENT + 2}] \
        -lmargin2 [expr {$CONTENT + 16}] -rmargin $PAD -spacing1 3 -spacing2 2 -spacing3 1
    $t tag configure md_dot  -foreground [C faint]
    $t tag configure fence_hdr -font CV.monoS -foreground [C muted] -background [C code_hdr] \
        -lmargin1 $CODE -lmargin2 $CODE -rmargin $PAD -spacing1 10 -spacing3 3 -wrap none
    inset $t fence_hdr
    # pinned-header prompt line
    $t tag configure pinprompt -font CV.ui -foreground [C fg2] -background [C user_bg] \
        -lmargin1 $PAD -lmargin2 $PAD -rmargin $PAD -spacing1 3 -spacing3 5 -wrap none
    bleed $t pinprompt [C user_bg]
    # welcome / empty state
    $t tag configure w_h1  -font CV.h1 -foreground [C fg] -lmargin1 $PAD -lmargin2 $PAD -spacing1 22 -spacing3 4
    $t tag configure w_p   -font CV.prose -foreground [C muted] -lmargin1 $PAD -lmargin2 $PAD \
        -rmargin [expr {$PAD + 10}] -spacing2 2 -spacing3 2
    $t tag configure w_sec -font CV.monoSB -foreground [C faint] -lmargin1 $PAD -spacing1 18 -spacing3 5
    $t tag configure w_row -font CV.mono -foreground [C fg2] -lmargin1 $PAD \
        -lmargin2 [expr {$PAD + 84}] -rmargin $PAD -spacing1 3 -spacing3 2 -wrap none
    $t tag configure w_key -foreground [C muted]
    $t tag configure w_dim -foreground [C faint] -font CV.monoS
    $t tag configure w_ex  -font CV.prose -foreground [C fg] -lmargin1 $PAD -lmargin2 [expr {$PAD+20}] \
        -rmargin $PAD -spacing1 4 -spacing3 4
    $t tag configure w_exg -font CV.monoB -foreground [C accent]
    $t tag configure w_ok  -font CV.monoB -foreground [C ok]
    $t tag configure w_hot -background [C hover]
    bleed $t w_hot [C hover]
    $t tag configure w_warn -font CV.ui -foreground [C fg2] -background [C warn_bg] \
        -lmargin1 $PAD -lmargin2 [expr {$PAD + 20}] -rmargin $PAD -spacing1 9 -spacing2 2 -spacing3 9
    bleed $t w_warn [C warn_bg]
    $t tag configure w_warng -font CV.uiB -foreground [C warn]
    # links (declared last = highest priority for foreground)
    $t tag configure chip -background [C chip] -foreground [C accent]
    $t tag configure link -foreground [C accent]
    $t tag configure link_dis -foreground [C faint]
    $t tag configure link_hot -underline 1
    $t tag configure link_stop -foreground [C err]
    $t tag configure wide
    $t tag configure narrow -elide 1
    $t tag bind link <Enter> {::cv::tr::link_hover %W 1}
    $t tag bind link <Leave> {::cv::tr::link_hover %W 0}
}

proc ::cv::tr::link_hover {w on} {
    $w tag remove link_hot 1.0 end
    if {$on} {
        set r [$w tag prevrange link "current + 1c"]
        if {[llength $r]} { $w tag add link_hot {*}$r }
        $w configure -cursor hand2
    } else { $w configure -cursor arrow }
}

# Width-dependent layout: right-aligned tab stops and optional (wide-only) fields.
proc ::cv::tr::relayout {} {
    variable t; variable pin; variable PAD; variable NUM; variable CONTENT; variable NARROW
    set w [winfo width $t]
    if {$w < 60} return
    set R [expr {$w - $PAD}]
    set narrow [expr {$w < $NARROW}]
    variable run
    foreach k [array names run *,state] {
        set id [lindex [split $k ,] 0]
        set txt ""
        foreach {s tags} [header_segments $id] {
            if {"narrow" ni $tags && $s ni {"\t" "\n"}} { append txt $s }
        }
        if {[font measure CV.monoSB $txt] + 2*$PAD + 10 > $w} { set narrow 1 }
    }
    foreach tw [list $t $pin] {
        $tw tag configure rh     -tabs [list $R right]
        $tw tag configure prompt -tabs [list $CONTENT left]
        $tw tag configure pinprompt -tabs [list $CONTENT left]
        $tw tag configure step   -tabs [list $NUM left $CONTENT left $R right]
        $tw tag configure md_li  -tabs [list [expr {$CONTENT + 16}] left]
        $tw tag configure fence_hdr -tabs [list [expr {$R - 8}] right]
        $tw tag configure w_row  -tabs [list [expr {$PAD + 18}] left [expr {$PAD + 84}] left $R right]
        $tw tag configure w_ex   -tabs [list [expr {$PAD + 20}] left]
        $tw tag configure w_warn -tabs [list [expr {$PAD + 20}] left]
        $tw tag configure wide   -elide $narrow
        $tw tag configure narrow -elide [expr {!$narrow}]
    }
    variable pin_run
    set pin_run ""
    update_pin
}

proc ::cv::tr::ro {script} {
    variable t
    $t configure -state normal
    uplevel 1 $script
    $t configure -state disabled
}

# ---- event dispatch: one proc per (role,type) the runtime emits ------------
proc ::cv::tr::event {ev} {
    set role [dict get $ev role]
    set type [dict get $ev type]
    ro {
        switch -- $role,$type {
            user,message        { on_user $ev }
            assistant,chunk     { on_chunk $ev }
            assistant,message   { on_final $ev }
            tool_start,message  { on_tool_start $ev }
            tool_result,message { on_tool_result $ev }
            system,lifecycle    { on_lifecycle $ev }
            default             { }
        }
    }
}

proc ::cv::tr::close_prose {} {
    variable t; variable stream_open; variable cur
    if {$stream_open} {
        $t insert end "\n" [list prose body$cur]
        set stream_open 0
    }
}

# Run header: "\u25BE RUN 12  14:32:07 \u00B7 qwen3.8:27b \u00B7 5 steps \u00B7 1 failed \u00B7 21.4 s   [toolbar]"
proc ::cv::tr::header_segments {id {collapsible 1}} {
    variable run
    set st $run($id,state)
    set n  $run($id,steps)
    set segs [list "\n" {rh rhpad}]
    if {$collapsible} {
        lappend segs [expr {$run($id,open) ? "\u25BE " : "\u25B8 "}] [list rh rh_toggle link tg$id]
    }
    lappend segs "RUN $id" {rh rh_id} "  " rh
    lappend segs [string range $run($id,ts) 0 4] {rh wide} " \u00B7 " {rh sep wide} \
        $run($id,model) {rh wide} " \u00B7 " {rh sep wide}
    if {$st eq "live"} {
        lappend segs "step $n" rh " \u00B7 " {rh sep} [::cv::util::clock $run($id,elapsed)] {rh rh_live}
        lappend segs "\t" rh "\u25CF live" {rh rh_live} "   " rh "Stop" [list rh link link_stop lk_stop$id]
    } else {
        lappend segs "$n step[expr {$n == 1 ? "" : "s"}]" rh
        if {$run($id,failed)} {
            lappend segs " \u00B7 " {rh sep} "$run($id,failed) \u2717" {rh rh_fail}
        }
        lappend segs " \u00B7 " {rh sep} [::cv::util::secs $run($id,dur)] rh
        lappend segs "\t" rh
        foreach {a label more} {copy Copy " Tcl" save Save " .tcl" replay Replay ""} {
            lappend segs " " {rh chip} $label [list rh chip link lk_$a$id]
            if {$more ne ""} { lappend segs $more [list rh chip link wide lk_$a$id] }
            lappend segs " " {rh chip}
            if {$a ne "replay"} { lappend segs " " rh }
        }
    }
    lappend segs "\n" rh "\n" {rh rhpad}
    return $segs
}

proc ::cv::tr::render_header {id} {
    variable t
    set segs {}
    foreach {s tags} [header_segments $id] { lappend segs $s [concat $tags rhl$id] }
    set r [$t tag ranges rhl$id]
    if {[llength $r]} {
        set at [lindex $r 0]
        $t delete [lindex $r 0] [lindex $r end]
        $t insert $at {*}$segs
    } else {
        $t insert end {*}$segs
    }
    $t tag bind tg$id <1> [list ::cv::tr::toggle_run $id]
    foreach a {copy save replay stop} {
        $t tag bind lk_$a$id <1> [list ::cv::log "run $id: $a"]
    }
}

proc ::cv::tr::toggle_run {id} {
    variable run; variable t
    set run($id,open) [expr {!$run($id,open)}]
    $t tag configure body$id -elide [expr {!$run($id,open)}]
    ro { render_header $id }
}

# role=user type=message -> opens a run block
proc ::cv::tr::on_user {ev} {
    variable t; variable run; variable cur
    close_prose
    set md [dict get $ev metadata]
    set id [dict get $md run]
    set cur $id
    set run($id,ts)      [dict get $md ts]
    set run($id,model)   [dict get $md model]
    set run($id,steps)   0
    set run($id,failed)  0
    set run($id,state)   live
    set run($id,elapsed) 0
    set run($id,dur)     0
    set run($id,open)    1
    set run($id,prompt)  [dict get $ev text]
    if {[$t index end-1c] ne "1.0"} {
        $t insert end "\n" [list hair]
    }
    $t mark set run$id "end - 1c"
    $t mark gravity run$id left
    render_header $id
    $t insert end "\u276F" {prompt prompt_glyph} "\t" prompt [dict get $ev text] prompt "\n" prompt
}

# role=assistant type=chunk -> streamed prose (never glued to a tool line)
proc ::cv::tr::on_chunk {ev} {
    variable t; variable stream_open; variable cur
    if {!$stream_open} {
        $t mark set ps "end - 1c"
        $t mark gravity ps left
        set stream_open 1
    }
    $t insert end [dict get $ev text] [list prose body$cur]
}

# role=assistant type=message -> final answer; replace the raw stream with Markdown
proc ::cv::tr::on_final {ev} {
    variable t; variable stream_open; variable cur; variable run
    if {$stream_open} {
        $t delete ps "end - 1c"
        set stream_open 0
    }
    ::cv::md::render $t [dict get $ev text] [list body$cur]
    set md [dict get $ev metadata]
    set run($cur,state) done
    set run($cur,dur) [dict get $md elapsed_ms]
    render_header $cur
}

proc ::cv::tr::on_lifecycle {ev} {
    # session_started / chat_resumed are protocol noise -> not rendered.
    # "cancelled" would render as a muted "Stopped." line and close the run.
}

# role=tool_start -> numbered step row + exact Tcl
proc ::cv::tr::on_tool_start {ev} {
    variable t; variable run; variable cur; variable calls
    close_prose
    set md [dict get $ev metadata]
    set n [incr run($cur,steps)]
    set k $cur.$n
    set calls([dict get $md tool_call_id]) $n
    set name [dict get $md tool_name]
    set in   [dict get $md tool_input]
    set B [list step body$cur]
    set i [$t index "end - 1c"]
    set sp [::cv::w::spinner $t.sp[string map {. _} $k] bg 12]
    $t window create end -window $sp -align center -padx 0
    foreach tg [concat $B sg$k] { $t tag add $tg $i }
    $t insert end "\t" $B "$n" [concat $B step_num] "\t" $B $name [concat $B step_tool]
    set why ""
    if {[dict exists $in rationale]} { set why [dict get $in rationale] }
    if {[dict exists $in purpose]}   { set why [dict get $in purpose] }
    if {$why ne ""} {
        $t insert end "  " [concat $B sep wide] $why [concat $B step_why wide]
    }
    $t insert end "\t" $B "running\u2026" [concat $B step_live st$k] "\n" $B
    if {$name eq "run_vmd_command"} {
        code_lines $t [dict get $in command] [list body$cur code$k]
    }
    $t mark set se$k "end - 1c"
    $t mark gravity se$k left
}

# role=tool_result -> \u2713/\u2717 in the gutter, duration, output under the code
proc ::cv::tr::on_tool_result {ev} {
    variable t; variable run; variable cur; variable calls
    set md [dict get $ev metadata]
    set n $calls([dict get $md tool_call_id])
    set k $cur.$n
    set ok [string is true -strict [dict get $md ok]]
    set B [list step body$cur]
    # gutter glyph
    lassign [$t tag ranges sg$k] a b
    $t delete $a $b
    $t insert $a [expr {$ok ? "\u2713" : "\u2717"}] [concat $B [expr {$ok ? "step_ok" : "step_err"}] sg$k]
    # duration (+ note that failed commands are not recorded into Save .tcl)
    lassign [$t tag ranges st$k] a b
    $t delete $a $b
    set segs {}
    if {!$ok} {
        incr run($cur,failed)
        lappend segs "not in .tcl" [concat $B step_note wide st$k] "  " [concat $B step_time wide st$k]
    }
    lappend segs [::cv::util::secs [dict get $md elapsed_ms]] [concat $B step_time st$k]
    $t insert $a {*}$segs
    # result body, inserted at the step's end mark (correct even if prose followed)
    set O [list body$cur]
    if {!$ok} {
        # error band sits flush under the code band: reads as "this cell failed"
        $t tag remove code_bot "se$k - 1 line linestart" se$k
        $t insert se$k " [dict get $md error]" [concat out_err $O] "\n" [concat out_err $O]
    } elseif {[dict exists $md snapshot_png]} {
        $t insert se$k "\n" [concat snap $O]
        set c [::cv::snap::card $t.snap[string map {. _} $k] [dict get $md snapshot_png] \
                   [dict get $md snapshot_name] [dict get $md purpose] [dict get $md image_sent]]
        $t window create se$k -window $c -align top
        foreach tg [concat snap $O] { $t tag add $tg se$k "se$k + 1c" }
    } elseif {[string trim [dict get $md output]] ne ""} {
        set lines [split [string trimright [dict get $md output]] \n]
        set shown [lrange $lines 0 5]
        set segs [list "\u2192 " [concat out out_arrow $O] [join $shown \n] [concat out out_val $O]]
        if {[llength $lines] > 6} {
            lappend segs "\n\u2026 [expr {[llength $lines]-6}] more lines" [concat out link $O]
        }
        lappend segs "\n" [concat out $O]
        $t insert se$k {*}$segs
    }
}

# Code band: one mono space of inner padding, syntax tinted, top/bottom padding tags.
proc ::cv::tr::code_lines {t code extra} {
    set lines [split [string trimright $code \n] \n]
    set last [expr {[llength $lines] - 1}]
    set i 0
    foreach ln $lines {
        set tags [concat code $extra]
        if {$i == 0}     { lappend tags code_top }
        if {$i == $last} { lappend tags code_bot }
        set segs [list " " $tags]
        foreach {s syn} [::cv::syntax::tokens $ln] {
            lappend segs $s [expr {$syn eq "" ? $tags : [concat $tags $syn]}]
        }
        lappend segs "\n" $tags
        $t insert end {*}$segs
        incr i
    }
}

# ---- sticky ("pinned") run header ------------------------------------------
# When a run's header scrolls off the top, a copy (header + one-line prompt) is
# placed over the transcript so the toolbar and the question stay in view.
proc ::cv::tr::on_scroll {first last} {
    variable sb
    ::cv::w::vscroll_set $sb $first $last
    after idle ::cv::tr::update_pin
}
# Trailing spacer: breathing room above the composer.  Tk clamps the view at the
# end of content, so to avoid a half-cut line under the pinned header we grow the
# spacer by the hidden remainder of the top line (cosmetic; used when pinned to end).
proc ::cv::tr::snap_top {{base 14}} {
    variable t
    ro {
        if {![llength [$t tag ranges tail]]} { $t insert end "\n" tail }
    }
    $t tag configure tail -font CV.hair -spacing1 $base -spacing3 0
    $t yview moveto 1.0
    update idletasks
    set d [$t dlineinfo @0,0]
    if {[llength $d] && [lindex $d 1] < 0} {
        $t tag configure tail -spacing1 [expr {$base + [lindex $d 3] + [lindex $d 1]}]
        $t yview moveto 1.0
    }
}
proc ::cv::tr::update_pin {} {
    variable t; variable pin; variable run; variable pin_run; variable PAD; variable CONTENT
    if {![winfo exists $pin]} return
    set top [$t index @0,0]
    set id ""
    foreach m [lsort -dictionary [$t mark names]] {
        if {![string match run* $m]} continue
        if {[$t compare $m <= $top]} { set id [string range $m 3 end] }
    }
    # visible header?  then no pin
    set P [winfo parent [winfo parent $pin]]
    if {$id eq "" || [llength [$t bbox "run$id + 1 line"]] || !$run($id,open)} {
        if {$pin_run ne ""} { grid remove $P.pinf $P.pinrule }
        set pin_run ""
        return
    }
    if {$pin_run eq $id} return
    $pin configure -state normal
    $pin delete 1.0 end
    $pin insert end {*}[header_segments $id]
    set avail [expr {[winfo width $t] - $CONTENT - $PAD}]
    $pin insert end "\u276F" {pinprompt prompt_glyph} "\t" pinprompt \
        [::cv::util::fit CV.ui $avail $run($id,prompt)] pinprompt
    $pin configure -state disabled
    set h [$pin count -update -ypixels 1.0 end]
    $P.pinf configure -height $h
    grid $P.pinf    -row 0 -column 0 -columnspan 2 -sticky ew
    grid $P.pinrule -row 1 -column 0 -columnspan 2 -sticky ew
    set pin_run $id
}

# ---- empty / first-run state -----------------------------------------------
proc ::cv::tr::render_welcome {} {
    variable t
    ro {
        $t insert end "ChatVMD\n" w_h1
        $t insert end "Ask in plain language. Each request becomes a run: the exact Tcl it executes in\
this VMD session, its output, and a snapshot \u2014 recorded to your folder and replayable.\n" w_p
        $t insert end "SETUP\n" w_sec
        $t insert end "\u2713" {w_row w_ok} "\t" w_row "runtime" {w_row w_key} "\t" w_row \
            "127.0.0.1:8765 \u00B7 ready" w_row "\n" w_row
        $t insert end "\u2713" {w_row w_ok} "\t" w_row "model" {w_row w_key} "\t" w_row \
            "qwen3.8:27b" w_row " \u00B7 Ollama" {w_row wide} "\t" w_row "change" {w_row link lk_model} "\n" w_row
        $t insert end "" w_row "\t\t" w_row "127.0.0.1:11435 \u00B7 tools \u00B7 vision \u00B7 thinking" {w_row w_dim} "\n" w_row
        $t insert end "\u2713" {w_row w_ok} "\t" w_row "folder" {w_row w_key} "\t" w_row \
            "~/proj/cdk2 \u00B7 12 runs" w_row "\t" w_row "change" {w_row link lk_folder} "\n" w_row
        $t insert end "TRY\n" w_sec
        set i 0
        foreach ex [list \
            "Load 1HCK; show the protein as NewCartoon and ATP as Licorice" \
            "Color the protein by B-factor and render a 1600 px image" \
            "Show residues within 5 \u00C5 of ATP and label them" \
            "Measure backbone RMSD across the loaded trajectory" \
        ] {
            incr i
            $t insert end "\u276F" [list w_ex w_exg ex$i] "\t" [list w_ex ex$i] $ex [list w_ex ex$i] "\n" [list w_ex ex$i]
            $t tag bind ex$i <Enter> [list ::cv::tr::ex_hot ex$i 1]
            $t tag bind ex$i <Leave> [list ::cv::tr::ex_hot ex$i 0]
            $t tag bind ex$i <1> [list ::cv::ui::fill_composer $ex]
        }
        $t insert end "KEYS\n" w_sec
        $t insert end "\u23CE" {w_row w_key} " send   " w_row "\u21E7\u23CE" {w_row w_key} " newline   " w_row \
            "\u2191" {w_row w_key} " last prompt   " w_row "esc" {w_row w_key} " stop" w_row "\n" w_row
        $t insert end "\n" w_p
        $t insert end "!" {w_warn w_warng} "\t" w_warn \
            "Model-written Tcl runs unsandboxed in this VMD session, with your permissions \u2014 treat it like a shell and don't open untrusted files.  " w_warn \
            "Got it" {w_warn link lk_ack} "\n" w_warn
    }
}
proc ::cv::tr::ex_hot {tag on} {
    variable t
    if {$on} {
        lassign [$t tag ranges $tag] a b
        $t tag add w_hot $a $b
        $t configure -cursor hand2
    } else {
        $t tag remove w_hot 1.0 end
        $t configure -cursor arrow
    }
}

# ---------------------------------------------------------------------------
#  Lightweight Markdown: **bold**, `code`, - bullets, ```fences``` (Copy / Run)
# ---------------------------------------------------------------------------
namespace eval ::cv::md {}
proc ::cv::md::render {t text extra} {
    set lines [split $text \n]
    set n [llength $lines]
    set i 0
    set fid 0
    while {$i < $n} {
        set ln [lindex $lines $i]
        if {[regexp {^```\s*(\w*)\s*$} $ln -> lang]} {
            set code {}
            incr i
            while {$i < $n && ![regexp {^```\s*$} [lindex $lines $i]]} {
                lappend code [lindex $lines $i]; incr i
            }
            incr i
            fence $t $lang [join $code \n] $extra [incr fid]
            continue
        }
        if {[string trim $ln] eq ""} { incr i; continue }
        if {[regexp {^\s*[-*]\s+(.*)$} $ln -> item]} {
            set base [concat md_li $extra]
            $t insert end "\u2022" [concat $base md_dot] "\t" $base
            inline $t $item $base
            $t insert end "\n" $base
        } else {
            set base [concat prose $extra]
            inline $t $ln $base
            $t insert end "\n" $base
        }
        incr i
    }
}
proc ::cv::md::inline {t s base} {
    while {$s ne ""} {
        if {[regexp -indices {\*\*(.+?)\*\*|`([^`]+)`} $s all b c]} {
            lassign $all a0 a1
            if {$a0 > 0} { $t insert end [string range $s 0 [expr {$a0-1}]] $base }
            if {[lindex $b 0] >= 0} {
                $t insert end [string range $s {*}$b] [concat $base md_b]
            } else {
                $t insert end [string range $s {*}$c] [concat $base md_code]
            }
            set s [string range $s [expr {$a1+1}] end]
        } else {
            $t insert end $s $base
            break
        }
    }
}
proc ::cv::md::fence {t lang code extra fid} {
    set H [concat fence_hdr $extra]
    set L [expr {$lang eq "" ? "code" : $lang}]
    $t insert end " $L" $H "\t" $H "Copy" [concat $H link lk_fc$fid] "   " $H \
        "Run in VMD" [concat $H link lk_fr$fid] "\n" $H
    set lines [split $code \n]
    set last [expr {[llength $lines]-1}]
    set i 0
    foreach ln $lines {
        set tags [concat code $extra]
        if {$i == $last} { lappend tags code_bot }
        set segs [list " " $tags]
        foreach {s syn} [::cv::syntax::tokens $ln] {
            lappend segs $s [expr {$syn eq "" || $lang ne "tcl" ? $tags : [concat $tags $syn]}]
        }
        lappend segs "\n" $tags
        $t insert end {*}$segs
        incr i
    }
}

# ---------------------------------------------------------------------------
#  Panel chrome: title bar, composer, status line, banner
# ---------------------------------------------------------------------------
namespace eval ::cv::ui {
    namespace import ::cv::theme::C
    variable top .
    variable input ""
    variable mode connected
}

proc ::cv::ui::topbar {p title {runs "2 runs"}} {
    frame $p -height 38
    ::cv::theme::paint $p -background chrome
    ::cv::w::logo $p.logo chrome
    label $p.name -text $title -font CV.uiB -bd 0 -padx 0
    ::cv::theme::paint $p.name -background chrome -foreground fg
    label $p.slash -text "  $runs" -font CV.uiS -bd 0 -padx 0
    ::cv::theme::paint $p.slash -background chrome -foreground faint
    label $p.title -text "" -font CV.ui -bd 0 -padx 0 -anchor w
    ::cv::theme::paint $p.title -background chrome -foreground muted
    ::cv::w::iconbtn $p.more     more     -on chrome
    ::cv::w::iconbtn $p.settings settings -on chrome -command {::cv::log settings}
    ::cv::w::iconbtn $p.history  history  -on chrome -command {::cv::log history}
    ::cv::w::iconbtn $p.new      new      -on chrome -command {::cv::log new}
    grid $p.logo  -row 0 -column 0 -padx {12 7} -pady 8
    grid $p.name  -row 0 -column 1
    grid $p.slash -row 0 -column 2
    grid $p.title -row 0 -column 3 -sticky w
    grid $p.new      -row 0 -column 5 -padx 1
    grid $p.history  -row 0 -column 6 -padx 1
    grid $p.settings -row 0 -column 7 -padx 1
    grid $p.more     -row 0 -column 8 -padx {1 8}
    grid columnconfigure $p 4 -weight 1
    return $p
}

proc ::cv::ui::hrule {p {tok rule}} {
    frame $p -height 1
    ::cv::theme::paint $p -background $tok
    return $p
}

# Composer: multi-line (Return sends, Shift-Return = newline), grows 2..6 lines.
proc ::cv::ui::composer {p state {text ""}} {
    variable input
    frame $p
    ::cv::theme::paint $p -background bg
    frame $p.box -bd 0 -padx 1 -pady 1
    ::cv::theme::paint $p.box -background [expr {$state eq "live" ? "rule2" : "rule2"}]
    frame $p.box.in -bd 0
    ::cv::theme::paint $p.box.in -background surface
    label $p.box.in.g -text "\u276F" -font CV.monoB -bd 0 -padx 0
    ::cv::theme::paint $p.box.in.g -background surface -foreground [expr {$state eq "offline" ? "faint" : "accent"}]
    set input [text $p.box.in.t -height 2 -wrap word -font CV.prose -relief flat -bd 0 \
                   -highlightthickness 0 -padx 2 -pady 7 -width 10 -spacing2 2]
    ::cv::theme::paint $input -background surface -foreground fg -insertbackground fg \
        -selectbackground sel -selectforeground fg
    $input tag configure ph -foreground [C faint]
    switch -- $state {
        live    { set b [::cv::w::pill $p.box.in.b "Stop" -kind danger -on surface -icon stop -command {::cv::log stop}] }
        offline { set b [::cv::w::pill $p.box.in.b "Send" -kind disabled -on surface] }
        default { set b [::cv::w::pill $p.box.in.b "Send" -kind primary -on surface -command {::cv::log send}] }
    }
    if {$text ne ""} {
        $input insert end $text
    } else {
        set phs [list \
            live      "Esc or Stop cancels \u00B7 you can draft your next request" \
            empty     "Ask VMD to load, show, measure or render\u2026" \
            connected "Ask a follow-up\u2026" \
            offline   "Runtime offline \u2014 your draft is kept"]
        set ph [dict get $phs $state]
        $input insert end $ph ph
    }
    set lines [$input count -displaylines 1.0 end]
    grid $p.box.in.g -row 0 -column 0 -sticky nw -padx {11 3} -pady 8
    grid $input      -row 0 -column 1 -sticky nsew
    grid $b          -row 0 -column 2 -sticky se -padx 7 -pady 7
    grid columnconfigure $p.box.in 1 -weight 1
    pack $p.box.in -fill both -expand 1
    pack $p.box -fill x -padx 10 -pady {8 9}
    bind $input <Return> {::cv::log "send"; break}
    bind $input <Shift-Return> {%W insert insert "\n"; break}
    bind $input <<Modified>> {::cv::ui::grow %W}
    return $p
}
proc ::cv::ui::grow {w} {
    $w edit modified 0
    set n [$w count -update -displaylines 1.0 "end - 1c"]
    $w configure -height [expr {max(2, min(6, $n))}]
}
proc ::cv::ui::fill_composer {s} {
    variable input
    $input delete 1.0 end
    $input insert end $s
    focus $input
}

# Status line: a terminal-prompt-like strip of segments; low-priority segments drop
# out as the window narrows (priority = order in the `drop` list).
proc ::cv::ui::status {p mode args} {
    frame $p -height 24
    ::cv::theme::paint $p -background chrome
    set segs {}
    proc seg {p name text fg {font CV.monoS}} {
        label $p.$name -text $text -font $font -bd 0 -padx 0 -pady 1
        ::cv::theme::paint $p.$name -background chrome -foreground $fg
        return $p.$name
    }
    switch -- $mode {
        connected {
            ::cv::w::dot $p.dot ok chrome
            seg $p prov  "ollama" muted
            seg $p model " qwen3.8:27b" fg
            seg $p host  " @127.0.0.1:11435 \u21C4" faint
            seg $p bar   "  \u2502  " rule2
            seg $p dir   "~/proj/cdk2" muted
            seg $p runs  " \u00B7 12 runs" faint
            seg $p keys  "\u23CE send  \u21E7\u23CE newline" faint
            set left  {dot prov model host bar dir runs}
            set right {keys}
            set drop  {keys host runs}
        }
        live {
            ::cv::w::spinner $p.dot chrome 11
            seg $p what  " step 4 \u00B7 running VMD command" fg
            seg $p el    " \u00B7 00:12" accent
            seg $p bar   "  \u2502  " rule2
            seg $p model "qwen3.8:27b" muted
            seg $p keys  "esc stop" faint
            set left  {dot what el bar model}
            set right {keys}
            set drop  {model bar keys}
        }
        offline {
            ::cv::w::dot $p.dot err chrome
            seg $p what  "offline" err
            seg $p host  " \u00B7 runtime 127.0.0.1:8765" muted
            seg $p el    " \u00B7 retry in 8 s" faint
            seg $p bar   "  \u2502  " rule2
            seg $p dir   "~/proj/cdk2" muted
            seg $p keys  "log: ~/.vmdai/runtime.log" faint
            set left  {dot what host el bar dir}
            set right {keys}
            set drop  {keys dir bar el}
        }
    }
    set col 0
    foreach s $left {
        grid $p.$s -row 0 -column $col -sticky w -pady 5 -padx [expr {$col == 0 ? "12 6" : 0}]
        incr col
    }
    grid columnconfigure $p $col -weight 1
    incr col
    foreach s $right { grid $p.$s -row 0 -column $col -sticky e -padx {0 12}; incr col }
    bind $p <Configure> [list ::cv::ui::status_fit $p $drop]
    return $p
}
proc ::cv::ui::status_fit {p drop} {
    # re-show everything, then hide in priority order until the request fits
    foreach s $drop { grid $p.$s }
    update idletasks
    foreach s $drop {
        if {[winfo reqwidth $p] <= [winfo width $p]} break
        grid remove $p.$s
        update idletasks
    }
}

# One actionable banner instead of a stream of red transport errors.
proc ::cv::ui::banner {p} {
    frame $p
    ::cv::theme::paint $p -background err_bg
    canvas $p.ic -width 18 -height 18 -highlightthickness 0 -bd 0
    ::cv::theme::paint $p.ic -background err_bg
    $p.ic create oval 1 1 17 17 -fill [C err] -outline ""
    $p.ic create line 9 5 9 10.5 -fill [C err_bg] -width 2 -capstyle round
    $p.ic create oval 7.9 12.3 10.1 14.5 -fill [C err_bg] -outline ""
    frame $p.txt
    ::cv::theme::paint $p.txt -background err_bg
    label $p.txt.h -text "Runtime not reachable" -font CV.uiB -bd 0 -padx 0 -anchor w
    ::cv::theme::paint $p.txt.h -background err_bg -foreground fg
    label $p.txt.d -text "127.0.0.1:8765 refused the connection. Your conversation and\
Tcl are safe; sending is paused. Retrying in 8 s." -font CV.uiS -bd 0 -padx 0 -anchor w -justify left
    ::cv::theme::paint $p.txt.d -background err_bg -foreground fg2
    pack $p.txt.h -anchor w
    pack $p.txt.d -anchor w -fill x
    bind $p.txt.d <Configure> {%W configure -wraplength [expr {%w - 2}]}
    frame $p.btn
    ::cv::theme::paint $p.btn -background err_bg
    ::cv::w::pill $p.btn.retry "Retry" -kind primary -on err_bg -h 26 -padx 12 -command {::cv::log retry}
    ::cv::w::pill $p.btn.log "Open log" -kind ghost -on err_bg -h 26 -padx 12 -font CV.ui -command {::cv::log openlog}
    pack $p.btn.retry -side left
    pack $p.btn.log -side left -padx {6 0}
    grid $p.ic  -row 0 -column 0 -sticky n -padx {12 9} -pady {11 0}
    grid $p.txt -row 0 -column 1 -sticky ew -pady 9
    grid $p.btn -row 1 -column 1 -sticky w -pady {0 10}
    grid columnconfigure $p 1 -weight 1
    return $p
}

# ---------------------------------------------------------------------------
#  Settings dialog (compact form).  Uses the same tokens; no ttk theme switch
#  (a global `ttk::style theme use` would restyle other VMD plugins, e.g. QwikMD).
# ---------------------------------------------------------------------------
namespace eval ::cv::settings { namespace import ::cv::theme::C }
proc ::cv::settings::open {parent} {
    set d .settings
    toplevel $d
    wm title $d "ChatVMD Settings"
    wm transient $d $parent
    wm resizable $d 0 0
    ::cv::theme::mac_appearance $d
    ::cv::theme::paint $d -background surface
    set f [frame $d.f -padx 20 -pady 6]
    ::cv::theme::paint $f -background surface
    pack $f -fill both -expand 1

    proc lbl {f name text {row 0}} {
        label $f.$name -text $text -font CV.ui -bd 0 -anchor e
        ::cv::theme::paint $f.$name -background surface -foreground muted
        return $f.$name
    }
    proc hint {f name text {tok faint}} {
        label $f.$name -text $text -font CV.uiS -bd 0 -anchor w -justify left
        ::cv::theme::paint $f.$name -background surface -foreground $tok
        return $f.$name
    }
    proc section {f name text} {
        label $f.$name -text $text -font CV.monoSB -bd 0 -anchor w
        ::cv::theme::paint $f.$name -background surface -foreground faint
        return $f.$name
    }
    set r 0
    grid [section $f s1 "MODEL PROVIDER"] -row $r -column 0 -columnspan 2 -sticky w -pady {12 8}; incr r
    grid [lbl $f l_prov "Provider"] -row $r -column 0 -sticky e -padx {0 12}
    grid [::cv::w::segmented $f.prov {Ollama OpenAI-compatible Anthropic OpenRouter} Ollama] \
        -row $r -column 1 -sticky w -pady 3; incr r

    grid [lbl $f l_url "Base URL"] -row $r -column 0 -sticky e -padx {0 12} -pady {10 0}
    grid [::cv::w::field $f.url -text "http://127.0.0.1:11435" -width 30] -row $r -column 1 -sticky ew -pady {10 0}; incr r
    grid [hint $f h_url "SSH tunnel to the GPU server \u00B7 the Mac's Ollama.app keeps :11434"] \
        -row $r -column 1 -sticky w -pady {3 0}; incr r

    grid [lbl $f l_model "Model"] -row $r -column 0 -sticky e -padx {0 12} -pady {10 0}
    frame $f.mrow
    ::cv::theme::paint $f.mrow -background surface
    ::cv::w::combo $f.mrow.c "qwen3.8:27b" {qwen3.8:27b qwen3.8:27b-q8_0 qwen3:14b llama3.3:70b} -width 20
    label $f.mrow.r -text "\u21BB refresh" -font CV.uiS -bd 0 -cursor hand2
    ::cv::theme::paint $f.mrow.r -background surface -foreground accent
    pack $f.mrow.c -side left -fill x -expand 1
    pack $f.mrow.r -side left -padx {10 0}
    grid $f.mrow -row $r -column 1 -sticky ew -pady {10 0}; incr r
    grid [hint $f h_model "4 models on server \u00B7 tools \u2713  vision \u2713  thinking \u2713"] \
        -row $r -column 1 -sticky w -pady {3 0}; incr r

    grid [lbl $f l_think "Thinking"] -row $r -column 0 -sticky e -padx {0 12} -pady {12 0}
    frame $f.trow
    ::cv::theme::paint $f.trow -background surface
    ::cv::w::toggle $f.trow.t 1 surface
    label $f.trow.l -text "On \u00B7 better tool use, ~2.5 s/turn  (off \u2248 1.2 s)" -font CV.uiS -bd 0
    ::cv::theme::paint $f.trow.l -background surface -foreground fg2
    pack $f.trow.t -side left
    pack $f.trow.l -side left -padx {9 0}
    grid $f.trow -row $r -column 1 -sticky w -pady {12 0}; incr r

    grid [lbl $f l_ctx "Context"] -row $r -column 0 -sticky e -padx {0 12} -pady {12 0}
    frame $f.crow
    ::cv::theme::paint $f.crow -background surface
    ::cv::w::combo $f.crow.c "32768" {8192 16384 32768 65536 131072} -width 8
    label $f.crow.l -text "tokens (num_ctx)" -font CV.uiS -bd 0
    ::cv::theme::paint $f.crow.l -background surface -foreground muted
    pack $f.crow.c -side left
    pack $f.crow.l -side left -padx {9 0}
    grid $f.crow -row $r -column 1 -sticky w -pady {12 0}; incr r

    grid [lbl $f l_key "API key"] -row $r -column 0 -sticky e -padx {0 12} -pady {12 0}
    frame $f.krow
    ::cv::theme::paint $f.krow -background surface
    ::cv::w::field $f.krow.e -text "sk-ant-api03-xxxxxxxxxxxxxxxx" -show "\u2022" -width 22 -state disabled
    label $f.krow.s -text "Show" -font CV.uiS -bd 0
    ::cv::theme::paint $f.krow.s -background surface -foreground faint
    pack $f.krow.e -side left -fill x -expand 1
    pack $f.krow.s -side left -padx {10 0}
    grid $f.krow -row $r -column 1 -sticky ew -pady {12 0}; incr r
    grid [hint $f h_key "Only for Anthropic / OpenRouter \u00B7 stored in ~/.vmdai (0600)"] \
        -row $r -column 1 -sticky w -pady {3 0}; incr r

    ::cv::ui::hrule $f.rule1
    grid $f.rule1 -row $r -column 0 -columnspan 2 -sticky ew -pady {16 12}; incr r

    frame $f.test
    ::cv::theme::paint $f.test -background surface
    ::cv::w::pill $f.test.b "Test connection" -kind ghost -on surface -h 26 -padx 12 -font CV.ui
    frame $f.test.res
    ::cv::theme::paint $f.test.res -background surface
    label $f.test.res.a -text "\u2713 Connected in 1.2 s" -font CV.uiSB -bd 0 -anchor w
    ::cv::theme::paint $f.test.res.a -background surface -foreground ok
    label $f.test.res.b -text "Ollama 0.34.4 \u00B7 qwen3.8:27b loaded \u00B7 tool call OK" -font CV.uiS -bd 0 -anchor w
    ::cv::theme::paint $f.test.res.b -background surface -foreground muted
    pack $f.test.res.a $f.test.res.b -anchor w
    pack $f.test.b -side left -anchor n
    pack $f.test.res -side left -padx {12 0}
    grid $f.test -row $r -column 0 -columnspan 2 -sticky w; incr r

    ::cv::ui::hrule $f.rule2
    grid $f.rule2 -row $r -column 0 -columnspan 2 -sticky ew -pady {14 0}; incr r
    frame $f.foot
    ::cv::theme::paint $f.foot -background surface
    ::cv::w::pill $f.foot.save "Save" -kind primary -on surface -h 28 -padx 18
    ::cv::w::pill $f.foot.cancel "Cancel" -kind ghost -on surface -h 28 -padx 14 -font CV.ui
    label $f.foot.note -text "Applies to the next request" -font CV.uiS -bd 0
    ::cv::theme::paint $f.foot.note -background surface -foreground faint
    pack $f.foot.save -side right
    pack $f.foot.cancel -side right -padx {0 8}
    pack $f.foot.note -side left
    grid $f.foot -row $r -column 0 -columnspan 2 -sticky ew -pady {12 14}; incr r
    grid columnconfigure $f 1 -weight 1
    return $d
}

# ---------------------------------------------------------------------------
#  Scripted demo content (identical across design directions)
# ---------------------------------------------------------------------------
namespace eval ::cv::demo {}
proc ::cv::demo::ev {role type text {md {}}} {
    return [dict create role $role type $type text $text metadata $md]
}
proc ::cv::demo::events {upto} {
    set E {}
    # an earlier run in the same chat (rendered collapsed)
    lappend E [ev user message "What's loaded in VMD right now?" {run 11 ts 14:31:12 model qwen3.8:27b}]
    lappend E [ev tool_start message "\[VMD\] molinfo list" \
        {tool_call_id c11 tool_name run_vmd_command tool_input {command {molinfo list}}}]
    lappend E [ev tool_result message "" {tool_call_id c11 ok true output "" elapsed_ms 30}]
    lappend E [ev assistant message "Nothing is loaded yet." {elapsed_ms 3100}]

    lappend E [ev user message "Load CDK2 with ATP bound (PDB 1HCK). Show the protein as NewCartoon\
colored by secondary structure and ATP as Licorice, then tell me the radius of gyration." \
        {run 12 ts 14:32:07 model qwen3.8:27b}]
    lappend E [ev assistant chunk "I'll load 1HCK and set up the two representations."]
    lappend E [ev tool_start message "" [dict create tool_call_id t1 tool_name run_vmd_command \
        tool_input [dict create rationale "Load structure and build reps" command \
"mol new 1hck.pdb
mol delrep 0 top
mol representation NewCartoon
mol color Structure
mol selection protein
mol addrep top
mol representation Licorice
mol selection {resname ATP}
mol addrep top"]]]
    lappend E [ev tool_result message "0" {tool_call_id t1 ok true output 0 elapsed_ms 400}]
    lappend E [ev tool_start message "" {tool_call_id t2 tool_name run_vmd_command \
        tool_input {command {display backgroundcolor white}}}]
    lappend E [ev tool_result message "" {tool_call_id t2 ok false output {}
        error {invalid command name "display backgroundcolor"} elapsed_ms 100}]
    lappend E [ev assistant chunk "That command doesn't exist; using the color command instead."]
    lappend E [ev tool_start message "" {tool_call_id t3 tool_name run_vmd_command \
        tool_input {command {color Display Background white}}}]
    lappend E [ev tool_result message "" {tool_call_id t3 ok true output {} elapsed_ms 100}]
    lappend E [ev tool_start message "" {tool_call_id t4 tool_name run_vmd_command \
        tool_input {command {set sel [atomselect top protein]
measure rgyr $sel}}}]
    if {$upto eq "midrun"} { return $E }
    lappend E [ev tool_result message "" {tool_call_id t4 ok true output 20.843 elapsed_ms 200}]
    lappend E [ev tool_start message "" {tool_call_id t5 tool_name capture_vmd_snapshot \
        tool_input {purpose {verify cartoon + ATP licorice}}}]
    lappend E [ev tool_result message "" [dict create tool_call_id t5 ok true output "" \
        elapsed_ms 1800 snapshot_png $::cv::SNAP snapshot_name "run_012/snap_05.png" \
        purpose "verify cartoon + ATP licorice" image_sent 1]]
    set final [string map [list @A \u00C5 @M \u2014] {Done @M here's the scene:
- **Protein** @M NewCartoon, colored by secondary structure
- **ATP** @M Licorice, colored by element

The radius of gyration is **20.84 @A**. You can reproduce it with `measure rgyr`:
```tcl
set sel [atomselect top protein]
measure rgyr $sel
```}]
    lappend E [ev assistant chunk $final]
    lappend E [ev assistant message $final {elapsed_ms 21400}]
    return $E
}

# ---------------------------------------------------------------------------
#  Main: build the panel for one state and screenshot it
# ---------------------------------------------------------------------------
proc ::cv::main {argv} {
    variable OUT
    lassign $argv spec OUT geom
    lassign [split $spec :] st variant
    set defaults {A {light 560x780} B {dark 560x780} C {dark 560x780} D {light 560x780}
                  E {dark 560x780}  F {light 420x700} G {dark 560x780} T {dark 560x780}}
    lassign [dict get $defaults $st] dvar dgeom
    if {$variant eq ""} { set variant $dvar }
    if {$geom eq ""}    { set geom $dgeom }
    ::cv::log "state=$st variant=$variant geom=$geom tk=[package provide Tk]"

    ::cv::theme::use $variant
    ::cv::fonts::init
    wm geometry . ${geom}+80+70
    wm minsize . 380 420
    wm attributes . -topmost 1       ;# capture harness only: stay above other apps
    ::cv::theme::mac_appearance .
    ::cv::theme::paint . -background bg

    set title [expr {$st eq "D" ? "New chat" : "CDK2 \u00B7 ATP (1HCK)"}]
    wm title . "ChatVMD"
    set mode [dict get {A connected B connected C live D connected E connected F connected G offline T connected} $st]
    set cstate [dict get {A connected B connected C live D empty E connected F connected G offline T connected} $st]
    set draft ""
    if {$st in {A B E F G T}} { set draft "Now zoom on the binding pocket\nand make the protein transparent" }

    ::cv::ui::topbar .top $title ""
    ::cv::ui::hrule .r1
    ::cv::tr::build .tx
    ::cv::ui::composer .cmp $cstate $draft
    ::cv::ui::hrule .r2
    ::cv::ui::status .st $mode
    grid .top -row 0 -sticky ew
    grid .r1  -row 1 -sticky ew
    grid .tx  -row 2 -sticky nsew
    if {$st eq "G"} {
        ::cv::ui::banner .ban
        ::cv::ui::hrule .r3 err
        grid .r3  -row 3 -sticky ew
        grid .ban -row 4 -sticky ew
    }
    grid .cmp -row 5 -sticky ew
    grid .r2  -row 6 -sticky ew
    grid .st  -row 7 -sticky ew
    grid columnconfigure . 0 -weight 1
    grid rowconfigure . 2 -weight 1

    if {$st eq "D"} {
        ::cv::tr::render_welcome
    } else {
        set evs [::cv::demo::events [expr {$st eq "C" ? "midrun" : "all"}]]
        foreach ev $evs { ::cv::tr::event $ev }
        # collapse the earlier run
        ::cv::tr::toggle_run 11
        if {$st eq "C"} {
            set ::cv::tr::run(12,elapsed) 12
            ::cv::tr::ro { ::cv::tr::render_header 12 }
        }
    }
    update idletasks
    ::cv::tr::relayout
    update
    if {$st ne "T" && $st ne "D"} { $::cv::tr::t yview moveto 1.0 }
    update
    ::cv::tr::update_pin
    update
    if {$st ne "T" && $st ne "D"} {
        $::cv::tr::t yview moveto 1.0
        update
        ::cv::tr::snap_top
    }
    if {$st eq "D"} {
        # sit the welcome block a little above the optical centre
        set t $::cv::tr::t
        set free [expr {[winfo height $t] - [$t count -update -ypixels 1.0 end]}]
        $t tag configure w_h1 -spacing1 [expr {max(22, int($free * 0.38))}]
    }
    update
    if {$st eq "E"} {
        ::cv::settings::open .
        update idletasks
        wm geometry .settings +[expr {[winfo rootx .] + 28}]+[expr {[winfo rooty .] + 58}]
        wm attributes .settings -topmost 1
    }
    after 1100 ::cv::capture
    after 14000 exit
}

proc ::cv::capture {} {
    variable OUT
    # tclsh is not the active app, so `raise` alone leaves it under other apps' windows:
    # float the panel (and the dialog above it) for the duration of the capture.
    wm attributes . -topmost 1
    raise .
    focus -force .
    if {[winfo exists .settings]} { wm attributes .settings -topmost 1; raise .settings }
    update
    after 250
    raise .
    if {[winfo exists .settings]} { raise .settings }
    update
    ::cv::tr::update_pin
    update
    set x [winfo rootx .]; set y [winfo rooty .]
    set w [winfo width .]; set h [winfo height .]
    if {[catch {exec /usr/sbin/screencapture -x -o -R$x,[expr {$y-28}],$w,[expr {$h+28}] $OUT} err]} {
        ::cv::log "capture failed: $err"
    }
    ::cv::log "captured $OUT ($w x $h)"
    foreach q {.top .tx .cmp .r2 .st .st.model .st.dot} {
        if {[winfo exists $q]} { ::cv::log "  $q geom=[winfo geometry $q] req=[winfo reqwidth $q]x[winfo reqheight $q]" }
    }
    set tt $::cv::tr::t
    ::cv::log "  text y=[winfo y $tt] h=[winfo height $tt] top=[$tt index @0,0] dl=[$tt dlineinfo @0,0] yview=[$tt yview] pinf=[winfo geometry .tx.pinf] mapped=[winfo ismapped .tx.pinf]"
    ::cv::log "  screen=[winfo screenwidth .]x[winfo screenheight .] vroot=[winfo vrootheight .] rooty=[winfo rooty .]"
    exit
}

if {[catch {::cv::main $::argv} err]} {
    ::cv::log "ERROR: $err\n$::errorInfo"
    exit 1
}
