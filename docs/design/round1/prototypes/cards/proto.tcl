# ChatVMD -- "Chat Cards" panel prototype / reference implementation
# ---------------------------------------------------------------------------
# Standalone: does NOT source the real plugin. Structured the way the production
# panel would be, so it doubles as a reference:
#
#   ::cv::theme   design tokens, one flat dict per mode (light / dark)
#   ::cv::fonts   named fonts derived from TkDefaultFont / TkFixedFont
#   ::cv::draw    canvas primitives: true-arc rounded rects, soft shadow, chips,
#                 line icons, spinner (antialiased by CoreGraphics on aqua)
#   ::cv::w       tiny token-aware widgets (button, field, segmented, toggle)
#                 because ttk 'aqua' ignores -background
#   ::cv::tr      transcript = ONE text widget (read-only proxy, still focusable
#                 so Cmd-C works). Prose/markdown are text tags; bubbles, tool
#                 steps, notes, snapshot and code cards are embedded canvases that
#                 re-render from their data dict on resize or theme change.
#   ::cv::md      minimal Markdown -> tags (bullets, **bold**, `code`, ``` fences)
#   ::cv::hl      Tcl token highlighter for code on canvases
#   ::cv::app     header, banner, composer (Send/Stop), settings popover, events
#   ::cv::demo    scripted events + state switch for screenshots
#
# usage: proto.tcl <A|B|C|D|E|F|G|A2|B2> <out.png> [WxH]
# Tk 8.5 notes: no lmap/try/string cat used; -lmargincolor etc. wrapped in catch;
# PNG load failure (8.5 without Img) degrades to a text-only snapshot card.
# ---------------------------------------------------------------------------
package require Tk 8.5

namespace eval ::cv {
    variable DESIGN [file normalize [file join [file dirname [info script]] ../..]]
    variable SNAP $DESIGN/assets/snap_1hck.png
}

# ============================================================ theme tokens
namespace eval ::cv::theme {
    variable P
    variable C
    variable mode light
    array set P {}
    set P(light) {
        bg #FFFFFF  hover #F2F3F5  hairline #ECEEF1  border #E3E6EA  border_strong #CED3DA
        text #1B1F24  muted #58606B  faint #8A919B
        accent #4C5FD5  accent_text #3747B5  accent_bg #EEF0FD  accent_ring #D5DAF8
        btn_bg #4C5FD5  btn_hover #3E50C4  on_btn #FFFFFF
        stop_bg #1B1F24  stop_hover #353A42  stop_fg #FFFFFF
        dis_bg #ECEEF1  dis_fg #A0A6AF
        user_bg #ECEFFD  user_fg #1B1F24
        card_bg #FFFFFF  card_head #F7F8FA  field_bg #FFFFFF
        seg_bg #EEF0F3  seg_sel #FFFFFF
        code_bg #F6F7F9  code_fg #24292F  icode_bg #EEF0F3
        ok #1B7F45  ok_bg #E4F4EA  err #C4372C  err_bg #FDEEEC  err_border #F2C7C2
        warn #975A00  warn_bg #FFF4DF
        rail #DDE1E6  scroll #C9CED5  shadow #EDEFF2  sel_bg #CCD4FA
        hl_cmd #3747B5  hl_var #9C2F7C  hl_num #975A00  hl_str #1B7A45  hl_com #8A919B  hl_br #6B7380
        pop_shadow #000000
    }
    set P(dark) {
        bg #1A1C20  hover #272A30  hairline #272A2F  border #32363C  border_strong #41464E
        text #E6E8EB  muted #A6ADB7  faint #747B86
        accent #8C98FF  accent_text #A9B2FF  accent_bg #262A47  accent_ring #343B6B
        btn_bg #5563DE  btn_hover #6371EA  on_btn #FFFFFF
        stop_bg #E6E8EB  stop_hover #FFFFFF  stop_fg #1A1C20
        dis_bg #2A2D33  dis_fg #6A717B
        user_bg #2B3052  user_fg #ECEEFF
        card_bg #202328  card_head #25282E  field_bg #202328
        seg_bg #16181B  seg_sel #33373F
        code_bg #16181B  code_fg #D6D9DF  icode_bg #2B2E35
        ok #58CB8E  ok_bg #1A3226  err #FF7F6E  err_bg #3A1F1C  err_border #5E2D27
        warn #E6AA3F  warn_bg #3A2D15
        rail #363A41  scroll #4A4F58  shadow #141619  sel_bg #3A4378
        hl_cmd #A9B2FF  hl_var #E68AD5  hl_num #E6AA3F  hl_str #6FD39C  hl_com #747B86  hl_br #8C939D
        pop_shadow #000000
    }
}
proc ::cv::theme::use {name} {
    variable P; variable C; variable mode
    set mode $name
    array unset C
    array set C $P($name)
}
proc ::cv::c {key} { return $::cv::theme::C($key) }

# ============================================================ fonts
namespace eval ::cv::fonts {}
proc ::cv::fonts::init {} {
    set sans [font actual TkDefaultFont -family]
    set mono [font actual TkFixedFont -family]
    # macOS reports TkDefaultFont = 13pt; scale everything relative to it elsewhere.
    set base [font actual TkDefaultFont -size]
    if {$base < 0} { set base [expr {int(-$base * 72.0 / [winfo fpixels . 1i] + 0.5)}] }
    if {$base <= 0} { set base 13 }
    set k [expr {$base / 13.0}]
    foreach {name fam size weight slant} {
        CV.body   sans 13 normal roman
        CV.bodyB  sans 13 bold   roman
        CV.ui     sans 12 normal roman
        CV.uiB    sans 12 bold   roman
        CV.uiI    sans 12 normal italic
        CV.small  sans 11 normal roman
        CV.smallB sans 11 bold   roman
        CV.tiny   sans 10 normal roman
        CV.tinyB  sans 10 bold   roman
        CV.title  sans 14 bold   roman
        CV.hero   sans 19 bold   roman
        CV.mono   mono 11 normal roman
        CV.monoIn mono 12 normal roman
        CV.gap    sans 2 normal roman
    } {
        set f [expr {$fam eq "sans" ? $sans : $mono}]
        set s [expr {max(8, int(round($size * $k)))}]
        catch {font delete $name}
        font create $name -family $f -size $s -weight $weight -slant $slant
    }
}

# ============================================================ drawing primitives
namespace eval ::cv::draw {
    variable spinners {}
    variable spin_angle 90
    variable nbtn 0
}
proc ::cv::draw::P {cx cy s args} {
    set out {}
    foreach {dx dy} $args { lappend out [expr {$cx + $dx*$s}] [expr {$cy + $dy*$s}] }
    return $out
}
# True circular-arc rounded rectangle. r = radius or {tl tr br bl}.
proc ::cv::draw::rr_points {x1 y1 x2 y2 r} {
    if {[llength $r] == 1} { set r [list $r $r $r $r] }
    foreach {tl tr br bl} $r break
    set pts {}
    foreach {cx cy rad a0} [list \
            [expr {$x1+$tl}] [expr {$y1+$tl}] $tl 180 \
            [expr {$x2-$tr}] [expr {$y1+$tr}] $tr 270 \
            [expr {$x2-$br}] [expr {$y2-$br}] $br 0 \
            [expr {$x1+$bl}] [expr {$y2-$bl}] $bl 90] {
        if {$rad <= 0} { lappend pts $cx $cy; continue }
        set n [expr {int($rad) + 3}]
        for {set i 0} {$i <= $n} {incr i} {
            set a [expr {($a0 + 90.0*$i/$n) * 0.017453292519943295}]
            lappend pts [expr {$cx + $rad*cos($a)}] [expr {$cy + $rad*sin($a)}]
        }
    }
    return $pts
}
proc ::cv::draw::rrect {c x1 y1 x2 y2 r args} {
    return [$c create polygon [rr_points $x1 $y1 $x2 $y2 $r] {*}$args]
}
# Paint the area outside a rounded corner (used to round an image's corners).
proc ::cv::draw::corner_mask {c x y r corner color {tags {}}} {
    if {$corner eq "tl"} {
        set cx [expr {$x+$r}]; set cy [expr {$y+$r}]; set a0 180
    } else {
        set cx [expr {$x-$r}]; set cy [expr {$y+$r}]; set a0 270
    }
    set pts [list $x $y]
    set n [expr {int($r)+3}]
    for {set i 0} {$i <= $n} {incr i} {
        set a [expr {($a0 + 90.0*$i/$n) * 0.017453292519943295}]
        lappend pts [expr {$cx + $r*cos($a)}] [expr {$cy + $r*sin($a)}]
    }
    $c create polygon $pts -fill $color -outline "" -tags $tags
}
proc ::cv::draw::blend {c1 c2 t} {
    foreach {r1 g1 b1} [winfo rgb . $c1] break
    foreach {r2 g2 b2} [winfo rgb . $c2] break
    format #%02x%02x%02x [expr {int(($r1+($r2-$r1)*$t)/257)}] \
        [expr {int(($g1+($g2-$g1)*$t)/257)}] [expr {int(($b1+($b2-$b1)*$t)/257)}]
}
# Soft drop shadow faked with concentric rounded rects (Tk has no alpha).
proc ::cv::draw::shadow {c x1 y1 x2 y2 r spread dy base strength} {
    for {set i $spread} {$i >= 1} {incr i -1} {
        set t [expr {$strength * pow(1.0 - double($i)/($spread+1), 2.2)}]
        rrect $c [expr {$x1-$i}] [expr {$y1-$i+$dy}] [expr {$x2+$i}] [expr {$y2+$i+$dy}] \
            [expr {$r+$i}] -fill [blend $base [::cv::c pop_shadow] $t] -outline ""
    }
}
proc ::cv::draw::spinner {c cx cy r color {tags {}}} {
    variable spinners; variable spin_angle
    set track [blend $color [$c cget -bg] 0.78]
    $c create oval [expr {$cx-$r}] [expr {$cy-$r}] [expr {$cx+$r}] [expr {$cy+$r}] \
        -outline $track -width 1.7 -tags $tags
    set id [$c create arc [expr {$cx-$r}] [expr {$cy-$r}] [expr {$cx+$r}] [expr {$cy+$r}] \
        -start $spin_angle -extent 110 -style arc -outline $color -width 1.9 -tags $tags]
    lappend spinners [list $c $id]
    return $id
}
proc ::cv::draw::spin_tick {} {
    variable spinners; variable spin_angle
    set spin_angle [expr {($spin_angle - 20) % 360}]
    set keep {}
    foreach s $spinners {
        foreach {c id} $s break
        if {[winfo exists $c] && [$c type $id] eq "arc"} {
            $c itemconfigure $id -start $spin_angle
            lappend keep $s
        }
    }
    set spinners $keep
    after 50 ::cv::draw::spin_tick
}
# Line icons drawn at (cx,cy) with nominal size s. Crisp at any scale; no glyph fallback.
proc ::cv::draw::icon {c name cx cy s color {tags {}}} {
    set w [expr {$s >= 15 ? 1.6 : 1.35}]
    set L [list -fill $color -width $w -capstyle round -joinstyle round -tags $tags]
    switch -- $name {
        check   { $c create line [P $cx $cy $s -0.30 0.02 -0.08 0.24 0.32 -0.24] {*}$L }
        cross   { $c create line [P $cx $cy $s -0.24 -0.24 0.24 0.24] {*}$L
                  $c create line [P $cx $cy $s 0.24 -0.24 -0.24 0.24] {*}$L }
        close   { $c create line [P $cx $cy $s -0.26 -0.26 0.26 0.26] {*}$L
                  $c create line [P $cx $cy $s 0.26 -0.26 -0.26 0.26] {*}$L }
        chev_r  { $c create line [P $cx $cy $s -0.10 -0.26 0.15 0 -0.10 0.26] {*}$L }
        chev_d  { $c create line [P $cx $cy $s -0.26 -0.10 0 0.15 0.26 -0.10] {*}$L }
        plus    { $c create line [P $cx $cy $s 0 -0.32 0 0.32] {*}$L
                  $c create line [P $cx $cy $s -0.32 0 0.32 0] {*}$L }
        compose { $c create line [P $cx $cy $s 0.02 -0.36 -0.36 -0.36 -0.36 0.38 0.38 0.38 0.38 0.0] {*}$L
                  $c create line [P $cx $cy $s -0.06 0.12 0.40 -0.34] {*}$L }
        gear    {
            set ro [expr {0.47*$s}]; set ri [expr {0.35*$s}]; set pts {}
            for {set k 0} {$k < 8} {incr k} {
                set a [expr {$k*45.0 + 22.5}]
                foreach {rad da} [list $ri -15 $ro -8 $ro 8 $ri 15] {
                    set t [expr {($a+$da)*0.017453292519943295}]
                    lappend pts [expr {$cx+$rad*cos($t)}] [expr {$cy+$rad*sin($t)}]
                }
            }
            $c create polygon $pts -fill "" -outline $color -width $w -joinstyle round -tags $tags
            set q [expr {0.14*$s}]
            $c create oval [expr {$cx-$q}] [expr {$cy-$q}] [expr {$cx+$q}] [expr {$cy+$q}] \
                -outline $color -width $w -tags $tags
        }
        clock   {
            set q [expr {0.42*$s}]
            $c create oval [expr {$cx-$q}] [expr {$cy-$q}] [expr {$cx+$q}] [expr {$cy+$q}] \
                -outline $color -width $w -tags $tags
            $c create line [P $cx $cy $s 0 -0.24 0 0 0.17 0.1] {*}$L
        }
        term    {
            rrect $c {*}[P $cx $cy $s -0.46 -0.38 0.46 0.38] [expr {0.12*$s}] -fill "" -outline $color -width 1.2 -tags $tags
            $c create line [P $cx $cy $s -0.24 -0.13 -0.08 0.01 -0.24 0.15] {*}$L
            $c create line [P $cx $cy $s 0.0 0.16 0.22 0.16] {*}$L
        }
        image   {
            rrect $c {*}[P $cx $cy $s -0.46 -0.38 0.46 0.38] [expr {0.12*$s}] -fill "" -outline $color -width 1.2 -tags $tags
            $c create line [P $cx $cy $s -0.38 0.28 -0.12 0.0 0.08 0.2 0.2 0.1 0.38 0.28] {*}$L
            set q [expr {0.07*$s}]; set ox [expr {$cx+0.17*$s}]; set oy [expr {$cy-0.14*$s}]
            $c create oval [expr {$ox-$q}] [expr {$oy-$q}] [expr {$ox+$q}] [expr {$oy+$q}] -fill $color -outline "" -tags $tags
        }
        copy    {
            rrect $c {*}[P $cx $cy $s -0.36 -0.18 0.2 0.40] [expr {0.08*$s}] -fill "" -outline $color -width 1.2 -tags $tags
            $c create line [P $cx $cy $s -0.16 -0.24 -0.16 -0.40 0.38 -0.40 0.38 0.18 0.26 0.18] {*}$L
        }
        play    { $c create polygon [P $cx $cy $s -0.2 -0.3 0.32 0 -0.2 0.3] -fill $color -outline $color -joinstyle round -width 1 -tags $tags }
        stop    { rrect $c {*}[P $cx $cy $s -0.26 -0.26 0.26 0.26] [expr {0.07*$s}] -fill $color -outline "" -tags $tags }
        arrow_up { $c create line [P $cx $cy $s 0 0.32 0 -0.30] {*}$L
                   $c create line [P $cx $cy $s -0.26 -0.05 0 -0.31 0.26 -0.05] {*}$L }
        open    { $c create line [P $cx $cy $s 0.04 -0.36 0.36 -0.36 0.36 -0.04] {*}$L
                  $c create line [P $cx $cy $s 0.36 -0.36 -0.04 0.04] {*}$L
                  $c create line [P $cx $cy $s -0.12 -0.36 -0.36 -0.36 -0.36 0.36 0.36 0.36 0.36 0.12] {*}$L }
        warn    { $c create polygon [P $cx $cy $s 0 -0.40 0.44 0.36 -0.44 0.36] -fill "" -outline $color -width $w -joinstyle round -tags $tags
                  $c create line [P $cx $cy $s 0 -0.12 0 0.1] {*}$L
                  set q [expr {0.045*$s + 0.6}]; set oy [expr {$cy+0.23*$s}]
                  $c create oval [expr {$cx-$q}] [expr {$oy-$q}] [expr {$cx+$q}] [expr {$oy+$q}] -fill $color -outline "" -tags $tags }
        info    { set q [expr {0.42*$s}]
                  $c create oval [expr {$cx-$q}] [expr {$cy-$q}] [expr {$cx+$q}] [expr {$cy+$q}] -outline $color -width $w -tags $tags
                  $c create line [P $cx $cy $s 0 -0.02 0 0.2] {*}$L
                  set q [expr {0.045*$s + 0.6}]; set oy [expr {$cy-0.18*$s}]
                  $c create oval [expr {$cx-$q}] [expr {$oy-$q}] [expr {$cx+$q}] [expr {$oy+$q}] -fill $color -outline "" -tags $tags }
        folder  { $c create polygon [P $cx $cy $s -0.44 -0.30 -0.12 -0.30 -0.02 -0.19 0.44 -0.19 0.44 0.32 -0.44 0.32] \
                      -fill "" -outline $color -width 1.2 -joinstyle round -tags $tags }
        refresh { set q [expr {0.34*$s}]
                  $c create arc [expr {$cx-$q}] [expr {$cy-$q}] [expr {$cx+$q}] [expr {$cy+$q}] -start 60 -extent 290 -style arc -outline $color -width $w -tags $tags
                  $c create line [P $cx $cy $s 0.06 -0.44 0.2 -0.3 0.04 -0.18] {*}$L }
        save    { $c create line [P $cx $cy $s 0 -0.38 0 0.14] {*}$L
                  $c create line [P $cx $cy $s -0.2 -0.06 0 0.14 0.2 -0.06] {*}$L
                  $c create line [P $cx $cy $s -0.38 0.18 -0.38 0.38 0.38 0.38 0.38 0.18] {*}$L }
        doc     { rrect $c {*}[P $cx $cy $s -0.34 -0.42 0.34 0.42] [expr {0.08*$s}] -fill "" -outline $color -width 1.2 -tags $tags
                  foreach yy {-0.16 0.02 0.2} { $c create line [P $cx $cy $s -0.16 $yy 0.16 $yy] {*}$L } }
        hex     { set pts {}
                  for {set k 0} {$k < 6} {incr k} {
                      set t [expr {($k*60 - 90)*0.017453292519943295}]
                      lappend pts [expr {$cx+0.42*$s*cos($t)}] [expr {$cy+0.42*$s*sin($t)}] }
                  $c create polygon $pts -fill "" -outline $color -width $w -joinstyle round -tags $tags }
        target  { foreach q {0.42 0.2} { set qq [expr {$q*$s}]
                      $c create oval [expr {$cx-$qq}] [expr {$cy-$qq}] [expr {$cx+$qq}] [expr {$cy+$qq}] -outline $color -width $w -tags $tags } }
        ruler   { rrect $c {*}[P $cx $cy $s -0.46 -0.18 0.46 0.18] [expr {0.06*$s}] -fill "" -outline $color -width 1.2 -tags $tags
                  foreach xx {-0.24 0.0 0.24} { $c create line [P $cx $cy $s $xx -0.18 $xx 0.0] {*}$L } }
        palette { set q [expr {0.42*$s}]
                  $c create oval [expr {$cx-$q}] [expr {$cy-$q}] [expr {$cx+$q}] [expr {$cy+$q}] -outline $color -width $w -tags $tags
                  foreach {dx dy} {-0.16 -0.12 0.12 -0.18 0.18 0.08} {
                      set ox [expr {$cx+$dx*$s}]; set oy [expr {$cy+$dy*$s}]; set qq [expr {0.06*$s+0.5}]
                      $c create oval [expr {$ox-$qq}] [expr {$oy-$qq}] [expr {$ox+$qq}] [expr {$oy+$qq}] -fill $color -outline "" -tags $tags } }
        bolt    { $c create polygon [P $cx $cy $s 0.08 -0.42 -0.24 0.06 -0.02 0.06 -0.08 0.42 0.24 -0.06 0.02 -0.06] \
                      -fill $color -outline $color -width 0.6 -joinstyle round -tags $tags }
        dot     { set q [expr {0.5*$s}]
                  $c create oval [expr {$cx-$q}] [expr {$cy-$q}] [expr {$cx+$q}] [expr {$cy+$q}] -fill $color -outline "" -tags $tags }
    }
}
# App mark: accent tile with a white benzene-style hexagon.
proc ::cv::draw::logo {c x y s {tags {}}} {
    rrect $c $x $y [expr {$x+$s}] [expr {$y+$s}] [expr {0.3*$s}] -fill [::cv::c accent] -outline "" -tags $tags
    set cx [expr {$x+$s/2.0}]; set cy [expr {$y+$s/2.0}]
    set pts {}
    for {set k 0} {$k < 6} {incr k} {
        set t [expr {($k*60 - 90)*0.017453292519943295}]
        lappend pts [expr {$cx+0.27*$s*cos($t)}] [expr {$cy+0.27*$s*sin($t)}]
    }
    $c create polygon $pts -fill "" -outline #FFFFFF -width [expr {$s > 24 ? 2.0 : 1.5}] -joinstyle round -tags $tags
    set q [expr {0.08*$s}]
    $c create oval [expr {$cx-$q}] [expr {$cy-$q}] [expr {$cx+$q}] [expr {$cy+$q}] -fill #FFFFFF -outline "" -tags $tags
}
# Rounded status chip anchored at x (w or e) and vertically centred on cy.
proc ::cv::draw::chip {c x cy text args} {
    array set o {-font CV.tinyB -fg "" -bg "" -outline "" -icon "" -anchor w -h 18 -padx 7 -tags {}}
    array set o $args
    set tw [expr {$text eq "" ? 0 : [font measure $o(-font) $text]}]
    set iw [expr {$o(-icon) eq "" ? 0 : ($text eq "" ? 10 : 14)}]
    set w [expr {$tw + $iw + 2*$o(-padx)}]
    if {$o(-anchor) eq "e"} { set x1 [expr {$x - $w}] } else { set x1 $x }
    set x2 [expr {$x1 + $w}]
    set y1 [expr {$cy - $o(-h)/2.0}]; set y2 [expr {$cy + $o(-h)/2.0}]
    rrect $c $x1 $y1 $x2 $y2 [expr {$o(-h)/2.0}] -fill $o(-bg) -outline $o(-outline) -tags $o(-tags)
    set tx [expr {$x1 + $o(-padx)}]
    if {$o(-icon) ne ""} {
        if {$o(-icon) eq "spinner"} {
            spinner $c [expr {$tx+4.5}] $cy 4.5 $o(-fg) $o(-tags)
        } else {
            icon $c $o(-icon) [expr {$tx+5}] $cy 11 $o(-fg) $o(-tags)
        }
        set tx [expr {$tx + $iw}]
    }
    if {$text ne ""} {
        $c create text $tx $cy -anchor w -text $text -font $o(-font) -fill $o(-fg) -tags $o(-tags)
    }
    return [list $x1 $y1 $x2 $y2]
}
# A button drawn onto an existing canvas, with hover + click. Returns {x1 x2}.
proc ::cv::draw::btn {c x cy text args} {
    variable nbtn
    array set o {-kind secondary -icon "" -anchor w -h 26 -font CV.smallB -padx 10 -command "" -base "" -outline ""}
    array set o $args
    set tag cvb[incr nbtn]
    set tw [expr {$text eq "" ? 0 : [font measure $o(-font) $text]}]
    set iw [expr {$o(-icon) eq "" ? 0 : ($text eq "" ? 14 : 19)}]
    set w [expr {$tw + $iw + 2*$o(-padx)}]
    if {$o(-anchor) eq "e"} { set x1 [expr {$x - $w}] } else { set x1 $x }
    set x2 [expr {$x1 + $w}]
    set base [expr {$o(-base) eq "" ? [$c cget -bg] : $o(-base)}]
    switch -- $o(-kind) {
        primary   { set fill [::cv::c btn_bg]; set hov [::cv::c btn_hover]; set line ""; set fg [::cv::c on_btn] }
        secondary { set fill [::cv::c card_bg]; set hov [::cv::c hover]; set line [::cv::c border_strong]; set fg [::cv::c text] }
        ghost     { set fill $base; set hov [::cv::c hover]; set line ""; set fg [::cv::c muted] }
        link      { set fill $base; set hov $base; set line ""; set fg [::cv::c accent_text] }
    }
    if {$o(-outline) ne ""} { set line $o(-outline) }
    set y1 [expr {$cy - $o(-h)/2.0}]; set y2 [expr {$cy + $o(-h)/2.0}]
    rrect $c $x1 $y1 $x2 $y2 7 -fill $fill -outline $line -tags [list $tag ${tag}bg]
    set tx [expr {$x1 + $o(-padx)}]
    if {$o(-icon) ne ""} {
        icon $c $o(-icon) [expr {$tx + 7}] $cy 13 $fg $tag
        set tx [expr {$tx + $iw}]
    }
    if {$text ne ""} {
        $c create text $tx $cy -anchor w -text $text -font $o(-font) -fill $fg -tags $tag
    }
    $c bind $tag <Enter> [list apply {{c t col} { $c itemconfigure ${t}bg -fill $col; $c configure -cursor hand2 }} $c $tag $hov]
    $c bind $tag <Leave> [list apply {{c t col} { $c itemconfigure ${t}bg -fill $col; $c configure -cursor "" }} $c $tag $fill]
    if {$o(-command) ne ""} { $c bind $tag <ButtonRelease-1> $o(-command) }
    return [list $x1 $x2]
}

# ============================================================ token-aware widgets
namespace eval ::cv::w { variable O }

proc ::cv::w::button {path args} {
    variable O
    array set o {-text "" -icon "" -kind secondary -command "" -bg "" -font CV.uiB -h 28 -padx 12}
    array set o $args
    if {$o(-bg) eq ""} { set o(-bg) [::cv::c card_bg] }
    canvas $path -highlightthickness 0 -bd 0 -bg $o(-bg) -height [expr {$o(-h)+1}] -width 10 -cursor hand2
    set O($path) [array get o]
    _btn_draw $path 0
    bind $path <Enter> [list ::cv::w::_btn_draw $path 1]
    bind $path <Leave> [list ::cv::w::_btn_draw $path 0]
    if {$o(-command) ne ""} { bind $path <ButtonRelease-1> $o(-command) }
    return $path
}
proc ::cv::w::_btn_draw {path hover} {
    variable O
    array set o $O($path)
    $path delete all
    set tw [font measure $o(-font) $o(-text)]
    set iw [expr {$o(-icon) eq "" ? 0 : ($o(-text) eq "" ? 16 : 21)}]
    set w [expr {$tw + $iw + 2*$o(-padx)}]
    set h $o(-h)
    $path configure -width [expr {$w+1}]
    switch -- $o(-kind) {
        primary   { set fill [::cv::c [expr {$hover ? "btn_hover" : "btn_bg"}]]; set line ""; set fg [::cv::c on_btn] }
        secondary { set fill [::cv::c [expr {$hover ? "hover" : "card_bg"}]]; set line [::cv::c border_strong]; set fg [::cv::c text] }
        ghost     { set fill [expr {$hover ? [::cv::c hover] : $o(-bg)}]; set line ""; set fg [::cv::c [expr {$hover ? "text" : "muted"}]] }
        disabled  { set fill [::cv::c dis_bg]; set line ""; set fg [::cv::c dis_fg] }
    }
    ::cv::draw::rrect $path 0.5 0.5 [expr {$w-0.5}] [expr {$h-0.5}] 7 -fill $fill -outline $line
    set x $o(-padx)
    if {$o(-icon) ne ""} {
        ::cv::draw::icon $path $o(-icon) [expr {$x+7}] [expr {$h/2.0}] 14 $fg
        set x [expr {$x+$iw}]
    }
    if {$o(-text) ne ""} {
        $path create text $x [expr {$h/2.0}] -anchor w -text $o(-text) -font $o(-font) -fill $fg
    }
}
proc ::cv::w::iconbtn {path icon args} {
    variable O
    array set o {-bg "" -command "" -size 26 -color ""}
    array set o $args
    canvas $path -highlightthickness 0 -bd 0 -bg $o(-bg) -width $o(-size) -height $o(-size) -cursor hand2
    set O($path) [array get o]
    set s $o(-size)
    ::cv::draw::rrect $path 0 0 $s $s 7 -fill $o(-bg) -outline "" -tags hov
    ::cv::draw::icon $path $icon [expr {$s/2.0}] [expr {$s/2.0}] 14 [::cv::c muted]
    bind $path <Enter> [list $path itemconfigure hov -fill [::cv::c hover]]
    bind $path <Leave> [list $path itemconfigure hov -fill $o(-bg)]
    if {$o(-command) ne ""} { bind $path <ButtonRelease-1> $o(-command) }
    return $path
}
proc ::cv::w::field {path args} {
    variable O
    array set o {-var "" -width 260 -show "" -trailing "" -state normal -bg "" -font CV.ui -h 30 -mono 0}
    array set o $args
    if {$o(-bg) eq ""} { set o(-bg) [::cv::c card_bg] }
    canvas $path -highlightthickness 0 -bd 0 -bg $o(-bg) -width [expr {$o(-width)+1}] -height [expr {$o(-h)+1}]
    set font [expr {$o(-mono) ? "CV.monoIn" : $o(-font)}]
    set dis [expr {$o(-state) ne "normal"}]
    set fbg [::cv::c [expr {$dis ? "card_head" : "field_bg"}]]
    entry $path.e -textvariable $o(-var) -relief flat -bd 0 -highlightthickness 0 \
        -bg $fbg -fg [::cv::c text] -font $font -insertbackground [::cv::c text] \
        -disabledbackground $fbg -disabledforeground [::cv::c faint] \
        -readonlybackground $fbg -selectbackground [::cv::c sel_bg] -show $o(-show) -insertwidth 1
    if {$dis} { $path.e configure -state disabled }
    set O($path) [array get o]
    set ew [expr {$o(-width) - 22 - ($o(-trailing) ne "" ? 18 : 0)}]
    $path create window 11 [expr {$o(-h)/2.0}] -window $path.e -anchor w -width $ew -tags win
    _field_draw $path 0
    bind $path.e <FocusIn>  [list ::cv::w::_field_draw $path 1]
    bind $path.e <FocusOut> [list ::cv::w::_field_draw $path 0]
    return $path
}
proc ::cv::w::_field_draw {path focus} {
    variable O
    array set o $O($path)
    $path delete deco
    set w $o(-width); set h $o(-h)
    set dis [expr {$o(-state) ne "normal"}]
    set fbg [::cv::c [expr {$dis ? "card_head" : "field_bg"}]]
    if {$focus} {
        ::cv::draw::rrect $path 0.5 0.5 [expr {$w-0.5}] [expr {$h-0.5}] 7 -fill $fbg -outline [::cv::c accent] -width 1.5 -tags deco
    } else {
        ::cv::draw::rrect $path 0.5 0.5 [expr {$w-0.5}] [expr {$h-0.5}] 7 -fill $fbg \
            -outline [::cv::c [expr {$dis ? "border" : "border_strong"}]] -tags deco
    }
    if {$o(-trailing) eq "chevron"} {
        ::cv::draw::icon $path chev_d [expr {$w-15}] [expr {$h/2.0}] 12 [::cv::c muted] deco
    }
    $path lower deco
}
proc ::cv::w::segmented {path args} {
    variable O
    array set o {-values {} -var "" -bg "" -font CV.small -h 28}
    array set o $args
    canvas $path -highlightthickness 0 -bd 0 -bg $o(-bg) -height $o(-h) -width 10
    set O($path) [array get o]
    _seg_draw $path
    return $path
}
proc ::cv::w::_seg_draw {path} {
    variable O
    array set o $O($path)
    upvar #0 $o(-var) cur
    $path delete all
    set pad 11; set h $o(-h)
    set ws {}
    foreach v $o(-values) { lappend ws [expr {[font measure CV.smallB $v] + 2*$pad}] }
    set total 6
    foreach w $ws { incr total $w }
    ::cv::draw::rrect $path 0 0 $total $h 8 -fill [::cv::c seg_bg] -outline ""
    $path configure -height [expr {$h+1}]
    set x 3; set i 0; set prevsel 0
    foreach v $o(-values) w $ws {
        set sel [expr {$v eq $cur}]
        if {$sel} {
            ::cv::draw::rrect $path $x 3 [expr {$x+$w}] [expr {$h-2.5}] 6 -fill [::cv::c border] -outline ""
            ::cv::draw::rrect $path $x 3 [expr {$x+$w}] [expr {$h-3}] 6 -fill [::cv::c seg_sel] -outline [::cv::c border]
        } elseif {$i > 0 && !$prevsel} {
            $path create line $x 9 $x [expr {$h-9}] -fill [::cv::c border_strong]
        }
        $path create text [expr {$x+$w/2.0}] [expr {$h/2.0}] -text $v \
            -font [expr {$sel ? "CV.smallB" : "CV.small"}] -fill [::cv::c [expr {$sel ? "text" : "muted"}]] -tags seg$i
        $path bind seg$i <ButtonRelease-1> [list apply {{p var v} { upvar #0 $var cur; set cur $v; ::cv::w::_seg_draw $p }} $path $o(-var) $v]
        set x [expr {$x+$w}]; incr i; set prevsel $sel
    }
    $path configure -width [expr {$total+1}]
}
proc ::cv::w::toggle {path args} {
    variable O
    array set o {-var "" -bg ""}
    array set o $args
    canvas $path -highlightthickness 0 -bd 0 -bg $o(-bg) -width 34 -height 20 -cursor hand2
    set O($path) [array get o]
    _tog_draw $path
    bind $path <ButtonRelease-1> [list apply {{p var} { upvar #0 $var v; set v [expr {!$v}]; ::cv::w::_tog_draw $p }} $path $o(-var)]
    return $path
}
proc ::cv::w::_tog_draw {path} {
    variable O
    array set o $O($path)
    upvar #0 $o(-var) on
    $path delete all
    ::cv::draw::rrect $path 0 0 34 20 10 -fill [::cv::c [expr {$on ? "btn_bg" : "border_strong"}]] -outline ""
    set kx [expr {$on ? 16 : 2}]
    $path create oval $kx 2 [expr {$kx+16}] 18 -fill #FFFFFF -outline ""
}

# ============================================================ image thumbnails
namespace eval ::cv::img { variable src; variable thumbs; array set src {}; array set thumbs {} }
# Center-crop tall renders to 3:2 and subsample to fit maxw. "" when the photo
# cannot be decoded (Tk 8.5 has no PNG) -> caller shows a text-only card.
proc ::cv::img::thumb {path maxw} {
    variable src; variable thumbs
    if {![info exists src($path)]} {
        if {[catch {image create photo -file $path} p]} { set src($path) "" } else { set src($path) $p }
    }
    set p $src($path)
    if {$p eq ""} { return "" }
    set w [image width $p]; set h [image height $p]
    set ch [expr {min($h, int($w*2/3.0))}]
    set y0 [expr {($h-$ch)/2}]
    set f [expr {int(ceil(double($w)/$maxw))}]
    if {$f < 1} { set f 1 }
    set key $path,$f
    if {![info exists thumbs($key)]} {
        set t [image create photo]
        $t copy $p -from 0 $y0 $w [expr {$y0+$ch}] -subsample $f $f
        set thumbs($key) $t
    }
    return $thumbs($key)
}
proc ::cv::img::size {path} {
    variable src
    if {![info exists src($path)] || $src($path) eq ""} { return {0 0} }
    return [list [image width $src($path)] [image height $src($path)]]
}

# ============================================================ Tcl highlighter
namespace eval ::cv::hl {
    variable map {plain code_fg cmd hl_cmd var hl_var str hl_str num hl_num br hl_br com hl_com}
}
proc ::cv::hl::tokens {line} {
    set out {}
    if {[regexp {^(\s*)(#.*)$} $line -> sp com]} { return [list $sp plain $com com] }
    set expect 1
    set s $line
    while {$s ne ""} {
        if {[regexp {^\s+} $s m]} {
            lappend out $m plain
        } elseif {[regexp {^\$(\{[^\}]*\}|[A-Za-z0-9_:]+)} $s m]} {
            lappend out $m var; set expect 0
        } elseif {[regexp {^"(?:[^"\\]|\\.)*"?} $s m]} {
            lappend out $m str; set expect 0
        } elseif {[string index $s 0] eq "\["} {
            set m "\["; lappend out $m br; set expect 1
        } elseif {[string first [string index $s 0] "\]\{\};"] >= 0} {
            set m [string index $s 0]; lappend out $m br
            if {$m eq ";"} { set expect 1 }
        } elseif {[regexp {^[^\s\[\]\{\}\$";]+} $s m]} {
            if {$expect} { lappend out $m cmd; set expect 0 } elseif {[string is double -strict $m]} { lappend out $m num } else { lappend out $m plain }
        } else {
            set m [string index $s 0]; lappend out $m plain
        }
        set s [string range $s [string length $m] end]
    }
    return $out
}
proc ::cv::hl::draw {c x y line font {tags {}}} {
    variable map
    foreach {tok cls} [tokens $line] {
        if {[string trim $tok] ne ""} {
            $c create text $x $y -anchor nw -text $tok -font $font -fill [::cv::c [dict get $map $cls]] -tags $tags
        }
        set x [expr {$x + [font measure $font $tok]}]
    }
}

# ============================================================ transcript
namespace eval ::cv::tr {
    variable T ""          ;# public widget path (read-only proxy)
    variable X ""          ;# real text widget command
    variable LM 16
    variable RM 18
    variable seq 0
    variable items {}
    variable item
    variable G
    variable S
    variable lastw 0
    array set item {}
    array set G {n 0 cur ""}
    array set S {}
}
proc ::cv::tr::create {path} {
    variable T; variable X
    text $path -wrap word -bd 0 -highlightthickness 0 -padx 0 -pady 12 -cursor arrow \
        -exportselection 1 -undo 0 -takefocus 1 -width 10 -height 10
    set T $path
    set X ::cv::tr::_txt
    rename $path $X
    # Read-only proxy: class bindings may select, copy and scroll, never edit.
    # Unlike -state disabled, the widget still takes focus, so Cmd/Ctrl-C works.
    proc ::$path {args} {
        if {[lindex $args 0] in {insert delete replace}} { return }
        uplevel 1 [list $::cv::tr::X {*}$args]
    }
    $X tag add tail end-1c end
    bind $path <1> {+focus %W}
    bind $path <Configure> {::cv::tr::_on_configure %w}
    bind CVScroll <MouseWheel> {::cv::tr::_wheel %D}
    config_tags
}
proc ::cv::tr::config_tags {} {
    variable X; variable LM; variable RM
    $X configure -bg [::cv::c bg] -fg [::cv::c text] -font CV.body -selectbackground [::cv::c sel_bg] \
        -selectforeground [::cv::c text] -inactiveselectbackground [::cv::c sel_bg] -insertwidth 0
    $X tag configure ln_user  -justify right -rmargin $RM -spacing1 10 -spacing3 12
    $X tag configure ln_hdr   -lmargin1 $LM -spacing1 2 -spacing3 6
    $X tag configure hdr_name -font CV.uiB -foreground [::cv::c text]
    $X tag configure hdr_meta -font CV.small -foreground [::cv::c faint]
    # Paragraph gaps are separate spacer lines (md_sp), not -spacing3: Tk fills a
    # line's spacing with its chunks' -background, which made inline code look tall.
    $X tag configure md_p     -lmargin1 $LM -lmargin2 $LM -rmargin $RM -spacing3 0 -spacing2 2 -font CV.body -foreground [::cv::c text]
    $X tag configure md_sp    -font CV.gap -spacing1 0 -spacing3 4
    $X tag configure md_li    -lmargin1 [expr {$LM+2}] -lmargin2 [expr {$LM+18}] -rmargin $RM \
        -tabs [list [expr {$LM+18}]] -spacing3 4 -spacing2 2 -font CV.body -foreground [::cv::c text]
    $X tag configure md_bullet -foreground [::cv::c faint]
    $X tag configure md_b     -font CV.bodyB
    $X tag configure md_code  -font CV.monoIn -background [::cv::c icode_bg] -foreground [::cv::c code_fg]
    $X tag configure md_codepad -font CV.tiny
    $X tag configure tail -elide 1
    $X tag configure ln_group -lmargin1 $LM -spacing1 2 -spacing3 0
    $X tag configure ln_step  -lmargin1 $LM -spacing1 0 -spacing3 0
    $X tag configure ln_block -lmargin1 $LM -spacing1 2 -spacing3 12
    $X tag configure ln_meta  -lmargin1 [expr {$LM-4}] -spacing1 0 -spacing3 14
    $X tag configure ln_center -justify center -spacing1 0 -spacing3 0
    $X tag configure ln_sect  -lmargin1 [expr {$LM+2}] -font CV.tinyB -foreground [::cv::c faint] -spacing1 14 -spacing3 8
    $X tag configure ln_pair  -lmargin1 $LM -spacing1 0 -spacing3 10
    foreach t {md_p md_li md_code} { catch {$X tag configure $t -lmargincolor [::cv::c bg] -rmargincolor [::cv::c bg]} }
}
proc ::cv::tr::_on_configure {w} {
    variable lastw
    if {$w != $lastw} {
        set lastw $w
        after cancel ::cv::tr::relayout
        after idle ::cv::tr::relayout
    }
}
proc ::cv::tr::_wheel {d} { variable X; $X yview scroll [expr {-$d}] units }
proc ::cv::tr::avail {} {
    variable T; variable LM; variable RM
    set w [winfo width $T]
    if {$w <= 1} { set w [winfo reqwidth $T] }
    return [expr {$w - $LM - $RM}]
}
# ---- insertion helpers (where = "end" or a mark name)
proc ::cv::tr::_pos {where} {
    variable X
    if {$where eq "end"} { return [$X index end-1c] }
    return [$X index $where]
}
proc ::cv::tr::_endpos {where} { if {$where eq "end"} { return end-1c }; return $where }
proc ::cv::tr::put {where text tags} { variable X; $X insert $where $text $tags }
proc ::cv::tr::_embed_line {where c linetags {align top}} {
    variable X
    set i0 [_pos $where]
    $X window create $where -window $c -align $align
    $X insert $where "\n"
    foreach t $linetags { $X tag add $t $i0 [_endpos $where] }
}
# Appends that must land AFTER open tool groups: pin group marks while inserting.
proc ::cv::tr::_pin_groups {gravity} {
    variable G; variable X
    foreach k [array names G *,mark] { $X mark gravity $G($k) $gravity }
}
# ---- item registry: every embedded canvas re-renders from its data dict
proc ::cv::tr::new_item {kind data} {
    variable T; variable seq; variable item; variable items
    set c $T.k[incr seq]
    canvas $c -highlightthickness 0 -bd 0 -bg [::cv::c bg] -width 20 -height 10
    bindtags $c [list $c CVScroll Canvas [winfo toplevel $c] all]
    set item($c,kind) $kind
    set item($c,data) $data
    lappend items $c
    return $c
}
proc ::cv::tr::redraw {c} {
    variable item
    if {![winfo exists $c]} return
    $c delete all
    $c configure -bg [::cv::c bg]
    draw_$item($c,kind) $c [avail]
}
proc ::cv::tr::relayout {} {
    variable items
    foreach c $items { redraw $c }
    ::cv::sb::redraw
}
proc ::cv::tr::getd {c key} { variable item; return [dict get $item($c,data) $key] }
proc ::cv::tr::setd {c key val} { variable item; dict set item($c,data) $key $val }

# ---- user bubble
proc ::cv::tr::user_message {text} {
    set c [new_item user [dict create text $text]]
    redraw $c
    _pin_groups left
    _embed_line end $c {ln_user}
    _pin_groups right
}
proc ::cv::tr::draw_user {c avail} {
    set text [getd $c text]
    set maxw [expr {int($avail * 0.84)}]
    set padx 13; set pady 9
    set tid [$c create text $padx $pady -anchor nw -text $text -font CV.body \
        -fill [::cv::c user_fg] -width [expr {$maxw - 2*$padx}]]
    foreach {x1 y1 x2 y2} [$c bbox $tid] break
    set w [expr {$x2 - $x1 + 2*$padx}]
    set h [expr {$y2 - $y1 + 2*$pady - 1}]
    set b [::cv::draw::rrect $c 0 0 $w $h {15 15 5 15} -fill [::cv::c user_bg] -outline ""]
    $c lower $b
    $c configure -width [expr {$w+1}] -height [expr {$h+1}]
}
# ---- assistant header (avatar + name + model)
proc ::cv::tr::assistant_header {model} {
    variable X
    set a [new_item avatar {}]
    redraw $a
    _pin_groups left
    set i0 [_pos end]
    $X window create end -window $a -align center
    put end "  ChatVMD" hdr_name
    if {$model ne ""} { put end "   $model" hdr_meta }
    put end "\n" {}
    $X tag add ln_hdr $i0 end-1c
    _pin_groups right
}
proc ::cv::tr::draw_avatar {c avail} {
    ::cv::draw::logo $c 0 0 20
    $c configure -width 20 -height 20
}
proc ::cv::tr::assistant_markdown {md} {
    _pin_groups left
    ::cv::md::render end $md
    _pin_groups right
}

# ---- tool groups ("Ran 5 steps") with a timeline rail
proc ::cv::tr::group_begin {} {
    variable G; variable X
    set gid g[incr G(n)]
    set G(cur) $gid
    set G($gid,steps) {}
    set G($gid,items) {}
    set G($gid,state) running
    set G($gid,collapsed) 0
    set G($gid,wall) ""
    set c [new_item group [dict create gid $gid hover 0]]
    set G($gid,hdr) $c
    redraw $c
    _pin_groups left
    _embed_line end $c {ln_group}
    _pin_groups right
    $X mark set cvm_$gid end-1c
    $X mark gravity cvm_$gid right
    set G($gid,mark) cvm_$gid
    $X tag configure $gid.body -elide 0
    bind $c <Enter> [list ::cv::tr::_group_hover $c 1]
    bind $c <Leave> [list ::cv::tr::_group_hover $c 0]
    bind $c <ButtonRelease-1> [list ::cv::tr::group_toggle $gid]
    $c configure -cursor hand2
    return $gid
}
proc ::cv::tr::_group_hover {c on} { setd $c hover $on; redraw $c }
proc ::cv::tr::_group_add {gid c} {
    variable G; variable X
    set m $G($gid,mark)
    set prev [lindex $G($gid,items) end]
    lappend G($gid,items) $c
    redraw $c
    set i0 [$X index $m]
    $X window create $m -window $c -align top
    $X insert $m "\n"
    $X tag add ln_step $i0 $m
    $X tag add $gid.body $i0 $m
    if {$prev ne ""} { redraw $prev }
    redraw $G($gid,hdr)
}
proc ::cv::tr::step_start {id tool title command {t0 ""}} {
    variable G; variable S
    set gid $G(cur)
    if {$gid eq ""} { set gid [group_begin] }
    set n [expr {[llength $G($gid,steps)] + 1}]
    if {$t0 eq ""} { set t0 [clock seconds] }
    set c [new_item step [dict create id $id gid $gid n $n tool $tool title $title command $command \
        status running output "" error "" elapsed "" expanded 0 t0 $t0 meta ""]]
    lappend G($gid,steps) $c
    set S($id) $c
    _group_add $gid $c
    bind $c <ButtonRelease-1> [list ::cv::tr::step_toggle $c]
    return $c
}
proc ::cv::tr::step_result {id ok output elapsed {meta ""}} {
    variable S; variable G
    set c $S($id)
    if {$ok} { setd $c status ok; setd $c output $output } else { setd $c status fail; setd $c error $output }
    setd $c elapsed $elapsed
    setd $c meta $meta
    redraw $c
    redraw $G([getd $c gid],hdr)
}
proc ::cv::tr::step_toggle {c} {
    if {[llength [split [getd $c command] \n]] <= 4} return
    setd $c expanded [expr {![getd $c expanded]}]
    redraw $c
}
proc ::cv::tr::note {text} {
    variable G
    set gid $G(cur)
    if {$gid eq ""} { assistant_markdown $text; return }
    set c [new_item note [dict create gid $gid text $text]]
    _group_add $gid $c
}
proc ::cv::tr::group_end {wall} {
    variable G; variable X
    set gid $G(cur)
    if {$gid eq ""} return
    set G($gid,state) done
    set G($gid,wall) $wall
    set lastok 1
    set last [lindex $G($gid,steps) end]
    if {$last ne "" && [getd $last status] ne "ok"} { set lastok 0 }
    # Collapse finished runs unless the run ended on a failure.
    if {$lastok} {
        set G($gid,collapsed) 1
        $X tag configure $gid.body -elide 1
    }
    set G(cur) ""
    redraw $G($gid,hdr)
}
proc ::cv::tr::group_toggle {gid} {
    variable G; variable X
    set G($gid,collapsed) [expr {!$G($gid,collapsed)}]
    $X tag configure $gid.body -elide $G($gid,collapsed)
    redraw $G($gid,hdr)
    ::cv::sb::redraw
}
proc ::cv::tr::_status_style {status} {
    switch -- $status {
        ok      { return [list [::cv::c ok] [::cv::c ok_bg] check] }
        fail    { return [list [::cv::c err] [::cv::c err_bg] cross] }
        default { return [list [::cv::c accent] [::cv::c accent_bg] spinner] }
    }
}
proc ::cv::tr::draw_group {c W} {
    variable G
    set gid [getd $c gid]
    set H 34; set cy 17
    set running [expr {$G($gid,state) eq "running"}]
    set collapsed $G($gid,collapsed)
    set hov [getd $c hover]
    ::cv::draw::rrect $c 0 1 $W [expr {$H-1}] 9 -fill [::cv::c [expr {$hov ? "hover" : "bg"}]] -outline ""
    if {!$collapsed && [llength $G($gid,items)]} {
        $c create line 11 $cy 11 $H -fill [::cv::c rail] -width 2
    }
    # head node: chevron (done) or spinner (running)
    $c create oval 1 [expr {$cy-10}] 21 [expr {$cy+10}] -fill [::cv::c [expr {$hov ? "bg" : "hover"}]] -outline [::cv::c border]
    if {$running} {
        ::cv::draw::spinner $c 11 $cy 5 [::cv::c accent]
    } else {
        ::cv::draw::icon $c [expr {$collapsed ? "chev_r" : "chev_d"}] 11 $cy 12 [::cv::c muted]
    }
    set steps $G($gid,steps)
    set n [llength $steps]
    set nfail 0
    foreach s $steps { if {[getd $s status] eq "fail"} { incr nfail } }
    if {$running} {
        set label "Working · step $n"
    } else {
        set label "Ran $n step[expr {$n == 1 ? "" : "s"}]"
    }
    set tid [$c create text 30 $cy -anchor w -text $label -font CV.uiB -fill [::cv::c text]]
    set x [expr {[lindex [$c bbox $tid] 2] + 10}]
    # right-hand summary
    set right [expr {$W - 8}]
    if {!$running && $G($gid,wall) ne ""} {
        set rid [$c create text $right $cy -anchor e -text $G($gid,wall) -font CV.small -fill [::cv::c faint]]
        set right [expr {[lindex [$c bbox $rid] 0] - 8}]
        if {$nfail} {
            set rid [$c create text $right $cy -anchor e -text "$nfail failed ·" -font CV.small -fill [::cv::c err]]
            set right [expr {[lindex [$c bbox $rid] 0] - 8}]
        }
    }
    # per-step status chips (icon, not colour alone)
    foreach s $steps {
        if {$x + 22 > $right} break
        foreach {fg bg ic} [_status_style [getd $s status]] break
        ::cv::draw::rrect $c $x [expr {$cy-9}] [expr {$x+20}] [expr {$cy+9}] 6 -fill $bg -outline ""
        if {$ic eq "spinner"} {
            ::cv::draw::spinner $c [expr {$x+10}] $cy 4.5 $fg
        } else {
            ::cv::draw::icon $c $ic [expr {$x+10}] $cy 12 $fg
        }
        set x [expr {$x + 24}]
    }
    $c configure -width $W -height $H
}
proc ::cv::tr::_rail {c gid H nodey} {
    variable G
    set last [expr {[lindex $G($gid,items) end] eq $c}]
    set y2 [expr {$last ? $nodey : $H}]
    $c create line 11 0 11 $y2 -fill [::cv::c rail] -width 2
}
proc ::cv::tr::_code_lines {command expanded maxch} {
    set lines [split $command \n]
    set nl [llength $lines]
    set show $lines; set more 0
    if {!$expanded && $nl > 4} { set show [lrange $lines 0 2]; set more [expr {$nl - 3}] }
    set vis {}
    foreach ln $show {
        if {[string length $ln] <= $maxch} { lappend vis $ln; continue }
        if {$expanded} {
            while {[string length $ln] > $maxch} {
                lappend vis [string range $ln 0 [expr {$maxch-1}]]
                set ln "  [string range $ln $maxch end]"
            }
            lappend vis $ln
        } else {
            lappend vis "[string range $ln 0 [expr {$maxch-2}]]…"
        }
    }
    return [list $vis $more $nl]
}
proc ::cv::tr::draw_step {c W} {
    set d $::cv::tr::item($c,data)
    foreach k {gid n tool title command status output error elapsed expanded t0 meta} { set $k [dict get $d $k] }
    set x0 28; set x1 [expr {$W - 1}]; set pad 11
    set top 4
    set y [expr {$top + $pad}]
    set rowc [expr {$y + 8}]
    # status chip (right)
    foreach {fg bg ic} [_status_style $status] break
    switch -- $status {
        ok      { set ct "$elapsed s" }
        fail    { set ct "Failed · $elapsed s" }
        default { set ct "Running · [::cv::app::mmss [expr {[clock seconds] - $t0}]]" }
    }
    foreach {cx1 - - -} [::cv::draw::chip $c [expr {$x1-$pad}] $rowc $ct -anchor e -fg $fg -bg $bg -icon $ic] break
    # tool icon + title
    set tic [expr {$tool eq "capture_vmd_snapshot" ? "image" : "term"}]
    ::cv::draw::icon $c $tic [expr {$x0+$pad+7}] $rowc 14 [::cv::c muted]
    set tx [expr {$x0+$pad+21}]
    set tid [$c create text $tx $y -anchor nw -text $title -font CV.uiB -fill [::cv::c text] \
        -width [expr {max(60, $cx1 - 10 - $tx)}]]
    set y [expr {max($y + 17, [lindex [$c bbox $tid] 3]) + 7}]
    set bx0 [expr {$x0+$pad}]; set bx1 [expr {$x1-$pad}]
    if {$command ne ""} {
        set cw [font measure CV.mono 0]
        set maxch [expr {max(10, int(($bx1-$bx0-18)/$cw))}]
        foreach {vis more nl} [_code_lines $command $expanded $maxch] break
        set lh [expr {[font metrics CV.mono -linespace] + 3}]
        set bh [expr {[llength $vis]*$lh + 12}]
        ::cv::draw::rrect $c $bx0 $y $bx1 [expr {$y+$bh}] 6 -fill [::cv::c code_bg] -outline ""
        set ly [expr {$y + 7}]
        foreach ln $vis { ::cv::hl::draw $c [expr {$bx0+9}] $ly $ln CV.mono; incr ly $lh }
        set y [expr {$y + $bh + 6}]
        if {$more} {
            $c create text [expr {$bx0+1}] $y -anchor nw -text "Show all $nl lines" -font CV.small -fill [::cv::c accent_text] -tags more
            ::cv::draw::icon $c chev_d [expr {$bx0 + [font measure CV.small "Show all $nl lines"] + 9}] [expr {$y+7}] 10 [::cv::c accent_text] more
            set y [expr {$y + 20}]
        } elseif {$expanded} {
            $c create text [expr {$bx0+1}] $y -anchor nw -text "Show less" -font CV.small -fill [::cv::c accent_text] -tags more
            set y [expr {$y + 20}]
        }
    }
    if {$status eq "fail" && $error ne ""} {
        set eid [$c create text [expr {$bx0+26}] [expr {$y+7}] -anchor nw -text $error -font CV.mono \
            -fill [::cv::c err] -width [expr {$bx1-$bx0-36}]]
        set eh [expr {[lindex [$c bbox $eid] 3] - $y + 7}]
        set b [::cv::draw::rrect $c $bx0 $y $bx1 [expr {$y+$eh}] 6 -fill [::cv::c err_bg] -outline [::cv::c err_border]]
        $c lower $b $eid
        ::cv::draw::icon $c warn [expr {$bx0+13}] [expr {$y+14}] 13 [::cv::c err]
        set y [expr {$y + $eh + 6}]
    } elseif {$status eq "ok" && $output ne ""} {
        $c create text [expr {$bx0+1}] $y -anchor nw -text "Result" -font CV.small -fill [::cv::c faint]
        $c create text [expr {$bx0+48}] [expr {$y}] -anchor nw -text $output -font CV.monoIn -fill [::cv::c text]
        set y [expr {$y + 20}]
    } elseif {$status eq "ok" && $meta ne ""} {
        $c create text [expr {$bx0+1}] $y -anchor nw -text $meta -font CV.small -fill [::cv::c muted]
        set y [expr {$y + 20}]
    }
    set y2 [expr {$y - 6 + $pad}]
    set card [::cv::draw::rrect $c $x0 $top $x1 $y2 10 -fill [::cv::c card_bg] \
        -outline [::cv::c [expr {$status eq "running" ? "accent_ring" : "border"}]]]
    $c lower $card
    set H [expr {$y2 + 4}]
    _rail $c $gid $H $rowc
    # rail node
    $c create oval 6 [expr {$rowc-5}] 16 [expr {$rowc+5}] -fill $fg -outline [::cv::c bg] -width 2
    $c configure -width $W -height $H
    $c bind more <Enter> [list $c configure -cursor hand2]
    $c bind more <Leave> [list $c configure -cursor ""]
}
proc ::cv::tr::draw_note {c W} {
    set gid [getd $c gid]
    set tid [$c create text 30 7 -anchor nw -text [getd $c text] -font CV.ui \
        -fill [::cv::c muted] -width [expr {$W - 40}]]
    set H [expr {[lindex [$c bbox $tid] 3] + 9}]
    _rail $c $gid $H 15
    $c create oval 7 11 15 19 -fill [::cv::c bg] -outline [::cv::c faint] -width 1.4
    $c configure -width $W -height $H
}

# ---- snapshot card (thumbnail + caption, click to enlarge)
proc ::cv::tr::snapshot_card {path purpose step {saved ""}} {
    set c [new_item snapshot [dict create path $path purpose $purpose step $step saved $saved]]
    redraw $c
    _pin_groups left
    _embed_line end $c {ln_block}
    _pin_groups right
}
proc ::cv::tr::draw_snapshot {c W} {
    set path [getd $c path]
    set purpose [getd $c purpose]
    set step [getd $c step]
    set wide [expr {$W >= 440}]
    set t [::cv::img::thumb $path [expr {$wide ? 258 : min($W - 2, 290)}]]
    set r 11
    foreach {iw ih} [::cv::img::size $path] break
    if {$t eq ""} { set tw 0; set th 0 } else { set tw [image width $t]; set th [image height $t] }
    set title "[string toupper [string index $purpose 0]][string range $purpose 1 end]"
    set meta [expr {$iw > 0 ? "$iw \u00d7 $ih PNG \u00b7 click to enlarge" : "Snapshot saved (preview needs Tk 8.6)"}]
    if {$t eq ""} {
        # Tk 8.5 (no PNG photo) or undecodable file: compact text card, opens in the OS viewer
        set cw [expr {min($W, 380)}]; set H 58
        ::cv::draw::rrect $c 0 0 $cw $H $r -fill [::cv::c card_bg] -outline [::cv::c border]
        $c create oval 12 13 44 45 -fill [::cv::c accent_bg] -outline ""
        ::cv::draw::icon $c image 28 29 16 [::cv::c accent_text]
        $c create text 56 18 -anchor w -text $title -font CV.uiB -fill [::cv::c text] -width [expr {$cw - 130}]
        $c create text 56 38 -anchor w -text "Snapshot \u00b7 step $step \u00b7 preview needs Tk 8.6" -font CV.small -fill [::cv::c faint] -width [expr {$cw - 130}]
        ::cv::draw::btn $c [expr {$cw-10}] 29 "Open" -kind secondary -icon open -anchor e -base [::cv::c card_bg] \
            -command [list ::cv::app::open_viewer $path]
        $c configure -width [expr {$cw+1}] -height [expr {$H+3}]
        return
    }
    if {$wide} {
        # image left, caption column right; card spans the column width
        set cw $W; set H [expr {$th + 2}]
        set tx [expr {$tw + 18}]
    } else {
        set cw [expr {$tw + 2}]
        # caption height follows the wrapped text
        set probe [$c create text 14 0 -anchor nw -width [expr {$cw - 28}] -font CV.small \
            -text "Snapshot \u00b7 step $step \u00b7 $iw \u00d7 $ih"]
        set H [expr {$th + 2 + 38 + [lindex [$c bbox $probe] 3]}]
        $c delete $probe
        set tx 14
    }
    ::cv::draw::rrect $c 0 1.5 $cw [expr {$H+1.5}] $r -fill [::cv::c shadow] -outline ""
    ::cv::draw::rrect $c 0 0 $cw $H $r -fill [::cv::c card_bg] -outline ""
    if {$t ne ""} {
        $c create image 1 1 -image $t -anchor nw -tags img
        ::cv::draw::corner_mask $c 0 0 $r tl [::cv::c bg]
        if {$wide} {
            # round the image's bottom-left too (mirror of tl, drawn as a polygon)
            set pts [list 0 $H]
            set n [expr {int($r)+3}]
            for {set i 0} {$i <= $n} {incr i} {
                set a [expr {(90 + 90.0*$i/$n) * 0.017453292519943295}]
                lappend pts [expr {$r + $r*cos($a)}] [expr {$H - $r + $r*sin($a)}]
            }
            $c create polygon $pts -fill [::cv::c bg] -outline ""
            $c create line [expr {$tw+1.5}] 1 [expr {$tw+1.5}] [expr {$H-1}] -fill [::cv::c border]
        } else {
            ::cv::draw::corner_mask $c $cw 0 $r tr [::cv::c bg]
            $c create line 1 [expr {$th+1.5}] [expr {$cw-1}] [expr {$th+1.5}] -fill [::cv::c border]
        }
        ::cv::draw::rrect $c [expr {$tw-30}] 9 [expr {$tw-7}] 32 7 -fill #000000 -outline #3A3A3A -tags img
        ::cv::draw::icon $c open [expr {$tw-18.5}] 20.5 12 #FFFFFF img
    }
    if {$wide} {
        set y 16
        $c create text $tx $y -anchor nw -text "SNAPSHOT \u00b7 STEP $step" -font CV.tinyB -fill [::cv::c faint]
        set tid [$c create text $tx [expr {$y+18}] -anchor nw -text $title -font CV.bodyB -fill [::cv::c text] -width [expr {$cw - $tx - 14}]]
        set y [expr {[lindex [$c bbox $tid] 3] + 5}]
        set mid [$c create text $tx $y -anchor nw -text $meta -font CV.small -fill [::cv::c muted] -width [expr {$cw - $tx - 14}]]
        set y [expr {[lindex [$c bbox $mid] 3] + 8}]
        set saved [getd $c saved]
        if {$saved ne ""} {
            set maxc [expr {int(($cw - $tx - 14) / [font measure CV.mono 0])}]
            if {[string length $saved] > $maxc} {
                set saved "\u2026[string range $saved end-[expr {$maxc-2}] end]"
            }
            $c create text $tx $y -anchor nw -text $saved -font CV.mono -fill [::cv::c faint]
        }
        set by [expr {$H - 26}]
        foreach {a b} [::cv::draw::btn $c $tx $by "Open" -kind secondary -icon open -base [::cv::c card_bg] \
            -command [list ::cv::app::open_viewer $path]] break
        ::cv::draw::btn $c [expr {$b + 6}] $by "Save PNG" -kind ghost -icon save -base [::cv::c card_bg]
    } else {
        set y0 [expr {$th + 2}]
        $c create text $tx [expr {$y0+12}] -anchor nw -text $title -font CV.uiB -fill [::cv::c text] -width [expr {$cw - 28}]
        $c create text $tx [expr {$y0+31}] -anchor nw -text "Snapshot \u00b7 step $step \u00b7 $iw \u00d7 $ih" -font CV.small -fill [::cv::c faint] -width [expr {$cw - 28}]
    }
    ::cv::draw::rrect $c 0.5 0.5 [expr {$cw-0.5}] [expr {$H-0.5}] $r -fill "" -outline [::cv::c border]
    $c bind img <ButtonRelease-1> [list ::cv::app::open_viewer $path]
    $c bind img <Enter> [list $c configure -cursor hand2]
    $c bind img <Leave> [list $c configure -cursor ""]
    $c configure -width [expr {$cw+1}] -height [expr {$H+3}]
}

# ---- fenced code card (Copy / Run)
proc ::cv::tr::code_card {where lang code} {
    set c [new_item code [dict create lang $lang code $code flash ""]]
    redraw $c
    _embed_line $where $c {ln_block}
}
proc ::cv::tr::draw_code {c W} {
    set code [getd $c code]; set lang [getd $c lang]
    set lines [split $code \n]
    set lh [expr {[font metrics CV.mono -linespace] + 4}]
    set hh 30
    set H [expr {$hh + [llength $lines]*$lh + 18}]
    set r 9
    ::cv::draw::rrect $c 0 0 $W $H $r -fill [::cv::c code_bg] -outline ""
    ::cv::draw::rrect $c 0 0 $W $hh [list $r $r 0 0] -fill [::cv::c card_head] -outline ""
    $c create line 1 $hh [expr {$W-1}] $hh -fill [::cv::c border]
    set label [expr {$lang eq "" ? "code" : $lang}]
    $c create text 13 [expr {$hh/2.0}] -anchor w -text $label -font CV.smallB -fill [::cv::c muted]
    set base [::cv::c card_head]
    set cp [expr {[getd $c flash] eq "copy" ? "Copied" : "Copy"}]
    foreach {bx1 bx2} [::cv::draw::btn $c [expr {$W-6}] [expr {$hh/2.0}] $cp -kind ghost -icon copy -anchor e -h 22 -padx 7 \
        -font CV.small -base $base -command [list ::cv::tr::code_copy $c]] break
    ::cv::draw::btn $c [expr {$bx1-2}] [expr {$hh/2.0}] "Run in VMD" -kind ghost -icon play -anchor e -h 22 -padx 7 \
        -font CV.small -base $base -command [list ::cv::app::run_snippet $code]
    set y [expr {$hh + 9}]
    foreach ln $lines { ::cv::hl::draw $c 13 $y $ln CV.mono; incr y $lh }
    ::cv::draw::rrect $c 0.5 0.5 [expr {$W-0.5}] [expr {$H-0.5}] $r -fill "" -outline [::cv::c border]
    $c configure -width [expr {$W+1}] -height [expr {$H+1}]
}
proc ::cv::tr::code_copy {c} {
    clipboard clear; clipboard append [getd $c code]
    setd $c flash copy; redraw $c
    after 1400 [list apply {{c} { if {[winfo exists $c]} { ::cv::tr::setd $c flash ""; ::cv::tr::redraw $c } }} $c]
}

# ---- answer footer: meta + actions
proc ::cv::tr::answer_meta {text} {
    set c [new_item meta [dict create text $text]]
    redraw $c
    _pin_groups left
    _embed_line end $c {ln_meta}
    _pin_groups right
}
proc ::cv::tr::draw_meta {c W} {
    set cy 12
    set x 0
    foreach {ic cmd} {copy {} save {} refresh {}} {
        foreach {a b} [::cv::draw::btn $c $x $cy "" -kind ghost -icon $ic -h 24 -padx 5] break
        set x [expr {$b + 2}]
    }
    $c create text [expr {$x + 6}] $cy -anchor w -text [getd $c text] -font CV.small -fill [::cv::c faint]
    $c configure -width $W -height 24
}

# ---- empty state (hero, example prompts, setup checklist)
proc ::cv::tr::welcome {examples checks} {
    variable X
    set c [new_item hero {}]
    redraw $c
    _embed_line end $c {ln_center}
    set i0 [_pos end]; put end "TRY AN EXAMPLE\n" {}; $X tag add ln_sect $i0 end-1c
    set W [avail]
    set pair [expr {$W >= 400}]
    set k 0
    foreach ex $examples {
        set pc [new_item prompt [dict create title [lindex $ex 0] body [lindex $ex 1] icon [lindex $ex 2] hover 0 pair $pair mate ""]]
        if {$pair && $k % 2 == 1} { setd $pc mate $prevpc; setd $prevpc mate $pc; redraw $prevpc }
        set prevpc $pc
        redraw $pc
        bind $pc <Enter> [list apply {{c} { ::cv::tr::setd $c hover 1; ::cv::tr::redraw $c; $c configure -cursor hand2 }} $pc]
        bind $pc <Leave> [list apply {{c} { ::cv::tr::setd $c hover 0; ::cv::tr::redraw $c }} $pc]
        bind $pc <ButtonRelease-1> [list ::cv::app::fill_composer [lindex $ex 1]]
        if {!$pair || $k % 2 == 0} { set i0 [_pos end] }
        if {$pair && $k % 2} {
            set sp [frame $::cv::tr::T.sp$k -width 10 -height 1 -bg [::cv::c bg]]
            $X window create end -window $sp -align top
        }
        $X window create end -window $pc -align top
        if {!$pair || $k % 2 == 1} { put end "\n" {}; $X tag add ln_pair $i0 end-1c }
        incr k
    }
    set i0 [_pos end]; put end "SETUP\n" {}; $X tag add ln_sect $i0 end-1c
    set cc [new_item checklist [dict create rows $checks]]
    redraw $cc
    _embed_line end $cc {ln_block}
}
proc ::cv::tr::draw_hero {c W} {
    set cx [expr {$W/2.0 + 0}]
    ::cv::draw::logo $c [expr {$cx-24}] 14 48
    $c create text $cx 84 -anchor n -text "What should we look at?" -font CV.hero -fill [::cv::c text]
    set sid [$c create text $cx 114 -anchor n -justify center -width [expr {min($W-40, 380)}] \
        -text "Ask in plain language. ChatVMD writes the Tcl, runs it in this VMD session and shows you every step." \
        -font CV.ui -fill [::cv::c muted]]
    set H [expr {[lindex [$c bbox $sid] 3] + 6}]
    $c configure -width [expr {$W + 16}] -height $H
}
proc ::cv::tr::_prompt_h {c body w} {
    set t [$c create text 44 31 -anchor nw -text $body -font CV.small -width [expr {$w - 56}]]
    set h [expr {max(66, [lindex [$c bbox $t] 3] + 13)}]
    $c delete $t
    return $h
}
proc ::cv::tr::draw_prompt {c W} {
    set pair [getd $c pair]
    set w [expr {$pair ? ($W - 10)/2 : $W}]
    set hov [getd $c hover]
    $c create text 44 12 -anchor nw -text [getd $c title] -font CV.uiB -fill [::cv::c text]
    $c create text 44 31 -anchor nw -text [getd $c body] -font CV.small -fill [::cv::c muted] -width [expr {$w - 56}]
    # a row of two cards shares one height
    set H [_prompt_h $c [getd $c body] $w]
    set mate [getd $c mate]
    if {$pair && $mate ne ""} { set H [expr {max($H, [_prompt_h $c [getd $mate body] $w])}] }
    set card [::cv::draw::rrect $c 0.5 0.5 [expr {$w-0.5}] [expr {$H-0.5}] 11 \
        -fill [::cv::c [expr {$hov ? "hover" : "card_bg"}]] -outline [::cv::c [expr {$hov ? "accent" : "border"}]]]
    $c lower $card
    ::cv::draw::rrect $c 12 12 34 34 8 -fill [::cv::c accent_bg] -outline ""
    ::cv::draw::icon $c [getd $c icon] 23 23 14 [::cv::c accent_text]
    $c configure -width [expr {$w+1}] -height [expr {$H+1}]
}
proc ::cv::tr::draw_checklist {c W} {
    set rows [getd $c rows]
    set rh 40; set y 0
    set n [llength $rows]
    set H [expr {$n * $rh + 2}]
    ::cv::draw::rrect $c 0.5 0.5 [expr {$W-0.5}] [expr {$H-0.5}] 11 -fill [::cv::c card_bg] -outline [::cv::c border]
    set i 0
    foreach row $rows {
        foreach {state label value action} $row break
        set cy [expr {$y + $rh/2.0 + 1}]
        if {$state eq "ok"} {
            $c create oval 13 [expr {$cy-9}] 31 [expr {$cy+9}] -fill [::cv::c ok_bg] -outline ""
            ::cv::draw::icon $c check 22 $cy 12 [::cv::c ok]
        } else {
            ::cv::draw::icon $c info 22 $cy 15 [::cv::c faint]
        }
        if {$label ne ""} {
            $c create text 42 $cy -anchor w -text $label -font CV.uiB -fill [::cv::c text]
            set vx 112
        } else { set vx 42 }
        set ax [expr {$W - 12}]
        if {$action ne ""} {
            foreach {ax -} [::cv::draw::btn $c $ax $cy $action -kind link -anchor e -h 22 -padx 2 -font CV.small -base [::cv::c card_bg]] break
            set ax [expr {$ax - 8}]
        }
        $c create text $vx $cy -anchor w -text $value -font CV.small \
            -fill [::cv::c [expr {$state eq "ok" ? "muted" : "faint"}]] -width [expr {$ax - $vx}]
        if {$i < $n - 1} { $c create line 42 [expr {$y+$rh}] [expr {$W-1}] [expr {$y+$rh}] -fill [::cv::c hairline] }
        set y [expr {$y + $rh}]; incr i
    }
    $c configure -width [expr {$W+1}] -height [expr {$H+1}]
}

# ============================================================ markdown
namespace eval ::cv::md {}
proc ::cv::md::render {where md} {
    set X $::cv::tr::X
    set lines [split [string trimright $md] \n]
    set n [llength $lines]
    set i 0; set para {}; set inlist 0; set lastli ""
    while {$i < $n} {
        set ln [lindex $lines $i]
        if {[regexp {^\s*```\s*([A-Za-z0-9_+-]*)\s*$} $ln -> lang]} {
            _flush para $where
            if {$inlist} { _gap $where; set inlist 0 }
            set code {}
            incr i
            while {$i < $n && ![regexp {^\s*```\s*$} [lindex $lines $i]]} { lappend code [lindex $lines $i]; incr i }
            incr i
            ::cv::tr::code_card $where $lang [join $code \n]
            continue
        }
        if {[regexp {^\s*[-*+]\s+(.*)$} $ln -> body]} {
            _flush para $where
            set lastli [::cv::tr::_pos $where]
            ::cv::tr::put $where "•\t" md_bullet
            inline $where $body {}
            ::cv::tr::put $where "\n" {}
            $X tag add md_li $lastli [::cv::tr::_endpos $where]
            set inlist 1
            incr i; continue
        }
        if {$inlist} { _gap $where; set inlist 0 }
        if {[string trim $ln] eq ""} { _flush para $where; incr i; continue }
        lappend para [string trim $ln]
        incr i
    }
    _flush para $where
    if {$inlist} { _gap $where }
}
proc ::cv::md::_gap {where} {
    set i0 [::cv::tr::_pos $where]
    ::cv::tr::put $where "\n" md_sp
}
proc ::cv::md::_flush {varName where} {
    upvar 1 $varName para
    if {![llength $para]} return
    set i0 [::cv::tr::_pos $where]
    inline $where [join $para " "] {}
    ::cv::tr::put $where "\n" {}
    $::cv::tr::X tag add md_p $i0 [::cv::tr::_endpos $where]
    set para {}
    _gap $where
}
proc ::cv::md::inline {where s base} {
    while {[regexp -indices {\*\*([^*]+)\*\*|`([^`]+)`} $s m b k]} {
        foreach {m0 m1} $m break
        if {$m0 > 0} { ::cv::tr::put $where [string range $s 0 [expr {$m0-1}]] $base }
        if {[lindex $b 0] >= 0} {
            ::cv::tr::put $where [string range $s [lindex $b 0] [lindex $b 1]] [concat $base md_b]
        } else {
            # NBSPs keep the span on one line: Tk paints the last chunk of a display
            # line out to the right margin, so a wrapped code span would smear its
            # background. (Separate padding chunks break Tk's word wrap - tested.)
            set code [string map [list " " "\u00a0"] [string range $s [lindex $k 0] [lindex $k 1]]]
            ::cv::tr::put $where $code [concat $base md_code]
        }
        set s [string range $s [expr {$m1+1}] end]
    }
    if {$s ne ""} { ::cv::tr::put $where $s $base }
}

# ============================================================ slim scrollbar
namespace eval ::cv::sb { variable C ""; variable first 0.0; variable last 1.0; variable grab 0 }
proc ::cv::sb::create {path} {
    variable C $path
    canvas $path -width 10 -highlightthickness 0 -bd 0 -bg [::cv::c bg]
    bind $path <Configure> ::cv::sb::redraw
    bind $path <Button-1> {::cv::sb::_press %y}
    bind $path <B1-Motion> {::cv::sb::_drag %y}
    return $path
}
proc ::cv::sb::yset {f l} { variable first $f; variable last $l; redraw }
proc ::cv::sb::redraw {} {
    variable C; variable first; variable last
    if {$C eq "" || ![winfo exists $C]} return
    $C delete all
    $C configure -bg [::cv::c bg]
    if {$first <= 0.0 && $last >= 1.0} return
    set h [winfo height $C]
    set y1 [expr {$first * $h}]; set y2 [expr {max($y1 + 28, $last * $h)}]
    ::cv::draw::rrect $C 2.5 [expr {$y1+2}] 7.5 [expr {$y2-2}] 2.5 -fill [::cv::c scroll] -outline ""
}
proc ::cv::sb::_press {y} { variable grab; variable first; variable C; set grab [expr {$y - $first*[winfo height $C]}] }
proc ::cv::sb::_drag {y} {
    variable grab; variable C
    $::cv::tr::X yview moveto [expr {double($y - $grab)/[winfo height $C]}]
}

# ============================================================ app shell
namespace eval ::cv::app {
    variable S
    array set S {
        running 0 offline 0 lines 2 activity "" focus 0 ph 0 footer 0 pinfocus 0
        placeholder "Message ChatVMD…"
        provider Ollama model qwen3.8:27b folder ~/proj/cdk2 runs 12
        retry_in 8
    }
}
proc ::cv::app::mmss {s} { format %02d:%02d [expr {$s/60}] [expr {$s%60}] }
proc ::cv::app::build {} {
    . configure -bg [::cv::c bg]
    canvas .hdr -height 56 -highlightthickness 0 -bd 0 -bg [::cv::c bg]
    bind .hdr <Configure> ::cv::app::draw_header
    canvas .ban -height 1 -highlightthickness 0 -bd 0 -bg [::cv::c bg]
    bind .ban <Configure> ::cv::app::draw_banner
    ::cv::tr::create .tr
    ::cv::sb::create .sb
    $::cv::tr::X configure -yscrollcommand ::cv::sb::yset
    build_composer
    grid .hdr -row 0 -column 0 -columnspan 2 -sticky ew
    grid .tr  -row 2 -column 0 -sticky nsew
    grid .sb  -row 2 -column 1 -sticky ns
    grid .cmp -row 3 -column 0 -columnspan 2 -sticky ew
    grid rowconfigure . 2 -weight 1
    grid columnconfigure . 0 -weight 1
    wm minsize . 380 460
    bind . <Escape> ::cv::app::stop
}
# ---- header: logo, title, folder; status pill, history, new chat, settings
proc ::cv::app::draw_header {} {
    variable S
    set c .hdr
    set W [winfo width $c]
    if {$W <= 1} return
    $c delete all
    $c configure -bg [::cv::c bg]
    set H 56
    ::cv::draw::logo $c 16 14 28
    $c create text 54 12 -anchor nw -text "ChatVMD" -font CV.title -fill [::cv::c text]
    ::cv::draw::icon $c folder 60 [expr {$H-16}] 11 [::cv::c faint] folder
    set fid [$c create text 69 [expr {$H-16}] -anchor w -text $S(folder) -font CV.small -fill [::cv::c muted] -tags folder]
    set fx [lindex [$c bbox $fid] 2]
    set rid [$c create text [expr {$fx+2}] [expr {$H-16}] -anchor w -text " · $S(runs) runs" -font CV.small -fill [::cv::c faint] -tags runs]
    set leftend [lindex [$c bbox $rid] 2]
    set leftend [expr {max($leftend, [lindex [$c bbox all] 2])}]
    # icon buttons (right to left)
    set x [expr {$W - 12}]
    set cy [expr {$H/2.0}]
    foreach {name icon cmd} {settings gear ::cv::app::toggle_settings  newchat compose {}  history clock {}} {
        set cx [expr {$x - 14}]
        ::cv::draw::rrect $c [expr {$cx-14}] [expr {$cy-14}] [expr {$cx+14}] [expr {$cy+14}] 8 \
            -fill [::cv::c bg] -outline "" -tags [list hb_$name hb_${name}_bg]
        ::cv::draw::icon $c $icon $cx $cy 17 [::cv::c muted] hb_$name
        $c bind hb_$name <Enter> [list $c itemconfigure hb_${name}_bg -fill [::cv::c hover]]
        $c bind hb_$name <Leave> [list $c itemconfigure hb_${name}_bg -fill [::cv::c bg]]
        if {$cmd ne ""} { $c bind hb_$name <ButtonRelease-1> $cmd }
        set S(hb_$name) $cx
        set x [expr {$x - 30}]
    }
    # status pill; compacts at narrow widths
    if {$S(offline)} {
        set dot [::cv::c err]; set full "Runtime offline"; set compact "Offline"
    } else {
        set dot [::cv::c ok]; set full "$S(provider) · $S(model)"; set compact $S(model)
    }
    set right [expr {$x + 2}]
    set txt $full
    foreach cand [list $full $compact ""] {
        set txt $cand
        set pw [expr {($txt eq "" ? 0 : [font measure CV.small $txt] + 6) + 30}]
        if {$right - $pw > $leftend + 12} break
    }
    set px1 [expr {$right - $pw}]
    ::cv::draw::rrect $c $px1 [expr {$cy-13}] $right [expr {$cy+13}] 13 -fill [::cv::c bg] -outline [::cv::c border_strong] -tags [list pill pill_bg]
    set dx [expr {$px1 + 15}]
    $c create oval [expr {$dx-4}] [expr {$cy-4}] [expr {$dx+4}] [expr {$cy+4}] -fill $dot -outline "" -tags pill
    if {!$S(offline)} {
        $c create oval [expr {$dx-7}] [expr {$cy-7}] [expr {$dx+7}] [expr {$cy+7}] -fill "" -outline [::cv::draw::blend $dot [::cv::c bg] 0.72] -width 2 -tags pill
    }
    if {$txt ne ""} { $c create text [expr {$dx + 11}] $cy -anchor w -text $txt -font CV.small -fill [::cv::c text] -tags pill }
    $c bind pill <Enter> [list $c itemconfigure pill_bg -fill [::cv::c hover]]
    $c bind pill <Leave> [list $c itemconfigure pill_bg -fill [::cv::c bg]]
    $c bind pill <ButtonRelease-1> ::cv::app::toggle_settings
    $c create line 0 [expr {$H-0.5}] $W [expr {$H-0.5}] -fill [::cv::c hairline]
}
# ---- one actionable banner instead of per-poll error spam
proc ::cv::app::draw_banner {} {
    variable S
    set c .ban
    set W [winfo width $c]
    $c delete all
    $c configure -bg [::cv::c bg]
    if {!$S(offline) || $W <= 1} { $c configure -height 1; return }
    set x0 12; set x1 [expr {$W - 12}]; set y0 10
    set tid [$c create text [expr {$x0+42}] [expr {$y0+13}] -anchor nw -text "Runtime not reachable" -font CV.uiB -fill [::cv::c text]]
    set bid [$c create text [expr {$x0+42}] [expr {$y0+33}] -anchor nw -width [expr {$x1-$x0-58}] -font CV.small -fill [::cv::c muted] \
        -text "No answer from 127.0.0.1:8765 (connection refused). Your conversation is safe."]
    set by [expr {[lindex [$c bbox $bid] 3] + 22}]
    set bg [::cv::c err_bg]
    foreach {a b} [::cv::draw::btn $c [expr {$x0+42}] $by "Retry now" -kind secondary -icon refresh -outline [::cv::c err_border]] break
    foreach {a b} [::cv::draw::btn $c [expr {$b+6}] $by "Open log" -kind ghost -icon doc -base $bg] break
    $c create text [expr {$x1-14}] $by -anchor e -text "Retrying in $S(retry_in) s" -font CV.small -fill [::cv::c faint]
    set y1 [expr {$by + 23}]
    set card [::cv::draw::rrect $c $x0 $y0 $x1 $y1 11 -fill $bg -outline [::cv::c err_border]]
    $c lower $card
    $c create oval [expr {$x0+11}] [expr {$y0+11}] [expr {$x0+33}] [expr {$y0+33}] -fill [::cv::c card_bg] -outline [::cv::c err_border]
    ::cv::draw::icon $c warn [expr {$x0+22}] [expr {$y0+21.5}] 14 [::cv::c err]
    $c configure -height [expr {$y1 + 1}]
}
# ---- composer: auto-growing text in a rounded box, Send <-> Stop, approval hook
proc ::cv::app::build_composer {} {
    canvas .cmp -highlightthickness 0 -bd 0 -bg [::cv::c bg] -height 120
    text .cmp.t -height 2 -wrap word -bd 0 -highlightthickness 0 -padx 0 -pady 0 -font CV.body \
        -bg [::cv::c field_bg] -fg [::cv::c text] -insertbackground [::cv::c text] -insertwidth 1 \
        -spacing2 3 -undo 1 -selectbackground [::cv::c sel_bg] -width 10
    .cmp.t tag configure ph -foreground [::cv::c faint]
    bind .cmp <Configure> ::cv::app::draw_composer
    bind .cmp.t <FocusIn>  {set ::cv::app::S(focus) 1; ::cv::app::_ph_clear; ::cv::app::draw_composer}
    bind .cmp.t <FocusOut> {set ::cv::app::S(focus) 0; ::cv::app::_ph_show; ::cv::app::draw_composer}
    bind .cmp.t <Return> {::cv::app::send; break}
    bind .cmp.t <Shift-Return> {%W insert insert "\n"; ::cv::app::_grow; break}
    bind .cmp.t <KeyRelease> ::cv::app::_grow
}
proc ::cv::app::_ph_show {} {
    variable S
    if {[string trim [.cmp.t get 1.0 end-1c]] eq ""} {
        .cmp.t delete 1.0 end
        .cmp.t insert 1.0 $S(placeholder) ph
        set S(ph) 1
    }
}
proc ::cv::app::_ph_clear {} { variable S; if {$S(ph)} { .cmp.t delete 1.0 end; set S(ph) 0 } }
proc ::cv::app::_empty {} {
    variable S
    expr {$S(ph) || [string trim [.cmp.t get 1.0 end-1c]] eq ""}
}
proc ::cv::app::_grow {} {
    variable S
    set n [.cmp.t count -displaylines 1.0 end-1c]
    incr n
    set n [expr {max(2, min(6, $n))}]
    if {$n != $S(lines)} { set S(lines) $n; draw_composer }
}
proc ::cv::app::draw_composer {} {
    variable S
    set c .cmp
    set W [winfo width $c]
    if {$W <= 1} return
    $c delete deco
    $c configure -bg [::cv::c bg]
    set lh [expr {[font metrics CV.body -linespace] + 3}]
    set y 4
    if {$S(running)} {
        set cy [expr {$y + 12}]
        ::cv::draw::spinner $c 24 $cy 6 [::cv::c accent] deco
        $c create text 38 $cy -anchor w -text $S(activity) -font CV.small -fill [::cv::c muted] -tags deco
        $c create text [expr {$W-16}] $cy -anchor e -text "Esc to stop" -font CV.tiny -fill [::cv::c faint] -tags deco
        set y [expr {$y + 26}]
    }
    set bx0 12; set bx1 [expr {$W-12}]; set by0 [expr {$y + 2}]
    set th [expr {$S(lines) * $lh}]
    set by1 [expr {$by0 + 12 + $th + 6 + 38}]
    set r 14
    if {($S(focus) || $S(pinfocus)) && !$S(offline)} {
        ::cv::draw::rrect $c [expr {$bx0-3}] [expr {$by0-3}] [expr {$bx1+3}] [expr {$by1+3}] [expr {$r+3}] -fill [::cv::c accent_ring] -outline "" -tags deco
        ::cv::draw::rrect $c $bx0 $by0 $bx1 $by1 $r -fill [::cv::c field_bg] -outline [::cv::c accent] -width 1 -tags deco
    } else {
        ::cv::draw::rrect $c $bx0 [expr {$by0+1.5}] $bx1 [expr {$by1+1.5}] $r -fill [::cv::c shadow] -outline "" -tags deco
        ::cv::draw::rrect $c $bx0 $by0 $bx1 $by1 $r -fill [::cv::c field_bg] -outline [::cv::c border_strong] -tags deco
    }
    if {[$c find withtag txt] eq ""} { $c create window 0 0 -window .cmp.t -anchor nw -tags txt }
    $c coords txt [expr {$bx0+15}] [expr {$by0+12}]
    $c itemconfigure txt -width [expr {$bx1-$bx0-30}] -height $th
    # bottom row
    set cy [expr {$by1 - 22}]
    # left: execution-mode chip = the hook for a future approval mode
    set lx [expr {$bx0 + 9}]
    set ctext "Auto-run Tcl"
    set cw [expr {[font measure CV.small $ctext] + 44}]
    ::cv::draw::rrect $c $lx [expr {$cy-12}] [expr {$lx+$cw}] [expr {$cy+12}] 12 -fill [::cv::c field_bg] -outline [::cv::c border] -tags [list deco mode mode_bg]
    ::cv::draw::icon $c bolt [expr {$lx+14}] $cy 12 [::cv::c warn] [list deco mode]
    $c create text [expr {$lx+24}] $cy -anchor w -text $ctext -font CV.small -fill [::cv::c muted] -tags [list deco mode]
    ::cv::draw::icon $c chev_d [expr {$lx+$cw-12}] $cy 10 [::cv::c faint] [list deco mode]
    $c bind mode <Enter> [list $c itemconfigure mode_bg -fill [::cv::c hover]]
    $c bind mode <Leave> [list $c itemconfigure mode_bg -fill [::cv::c field_bg]]
    # right: primary button (Send / Stop / disabled)
    set empty [_empty]
    if {$S(running)} {
        set kind stop; set btxt "Stop"; set bic stop
    } elseif {$S(offline) || $empty} {
        set kind disabled; set btxt "Send"; set bic arrow_up
    } else {
        set kind primary; set btxt "Send"; set bic arrow_up
    }
    switch -- $kind {
        primary  { set bf [::cv::c btn_bg]; set bh [::cv::c btn_hover]; set bfg [::cv::c on_btn] }
        stop     { set bf [::cv::c stop_bg]; set bh [::cv::c stop_hover]; set bfg [::cv::c stop_fg] }
        disabled { set bf [::cv::c dis_bg]; set bh $bf; set bfg [::cv::c dis_fg] }
    }
    set bw [expr {[font measure CV.uiB $btxt] + 42}]
    set bxr [expr {$bx1 - 8}]; set bxl [expr {$bxr - $bw}]
    ::cv::draw::rrect $c $bxl [expr {$cy-14}] $bxr [expr {$cy+14}] 9 -fill $bf -outline "" -tags [list deco pbtn pbtn_bg]
    ::cv::draw::icon $c $bic [expr {$bxl+16}] $cy 13 $bfg [list deco pbtn]
    $c create text [expr {$bxl+28}] $cy -anchor w -text $btxt -font CV.uiB -fill $bfg -tags [list deco pbtn]
    $c bind pbtn <Enter> [list $c itemconfigure pbtn_bg -fill $bh]
    $c bind pbtn <Leave> [list $c itemconfigure pbtn_bg -fill $bf]
    $c bind pbtn <ButtonRelease-1> [expr {$S(running) ? "::cv::app::stop" : "::cv::app::send"}]
    if {!$S(running) && !$S(offline) && $W >= 470} {
        $c create text [expr {$bxl - 10}] $cy -anchor e -text "⏎ send  ·  ⇧⏎ new line" -font CV.tiny -fill [::cv::c faint] -tags deco
    }
    if {$S(footer)} {
        set fy [expr {$by1 + 14}]
        $c create text [expr {$W/2.0}] $fy -text "ChatVMD runs model-written Tcl directly in this VMD session." -font CV.tiny -fill [::cv::c faint] -tags deco
        $c configure -height [expr {$fy + 12}]
    } else {
        $c configure -height [expr {$by1 + 10}]
    }
}
proc ::cv::app::set_running {on {activity ""}} {
    variable S
    set S(running) $on
    set S(activity) $activity
    if {$on} { set S(placeholder) "Reply once this run finishes — or press Esc to stop" } else { set S(placeholder) "Message ChatVMD…" }
    draw_composer
}
proc ::cv::app::set_offline {on} {
    variable S
    set S(offline) $on
    if {$on} { set S(placeholder) "Reconnect to send messages" }
    draw_header; draw_banner; draw_composer
    if {$on} { grid .ban -row 1 -column 0 -columnspan 2 -sticky ew } else { grid forget .ban }
}
proc ::cv::app::fill_composer {text} { _ph_clear; .cmp.t delete 1.0 end; .cmp.t insert 1.0 $text; focus .cmp.t; _grow; draw_composer }
proc ::cv::app::send {} {}
proc ::cv::app::stop {} {}
proc ::cv::app::run_snippet {code} {}
proc ::cv::app::open_viewer {path} {
    set t .viewer
    destroy $t
    if {[catch {image create photo -file $path} p]} return
    toplevel $t -bg #000000
    wm title $t "Snapshot — [file tail $path]"
    set f [expr {int(ceil(max([image width $p]/900.0, [image height $p]/800.0)))}]
    set v [image create photo]; $v copy $p -subsample $f $f; image delete $p
    label $t.l -image $v -bd 0 -bg #000000; pack $t.l
}
# ---- settings popover (anchored to the gear, faux shadow)
namespace eval ::cv::settings {
    variable V
    array set V {provider Ollama host http://127.0.0.1:11435 model qwen3.8:27b think 1 ctx 32768 key sk-or-v1-0000000000000000a41f}
}
proc ::cv::app::toggle_settings {} {
    if {[winfo exists .pop]} { destroy .pop } else { ::cv::settings::open }
}
proc ::cv::settings::_label {f r text {pady 7}} {
    label $f.l$r -text $text -font CV.uiB -bg [::cv::c card_bg] -fg [::cv::c text] -anchor w
    grid $f.l$r -row $r -column 0 -sticky nw -pady [list $pady 0] -padx {0 16}
}
proc ::cv::settings::_help {f r text {col faint}} {
    label $f.h$r -text $text -font CV.tiny -bg [::cv::c card_bg] -fg [::cv::c $col] -anchor w -justify left -wraplength 360
    grid $f.h$r -row $r -column 1 -sticky w -pady {4 0}
}
# Popover sheet under the header. Full panel width so the (opaque) shadow margin
# never slices through transcript text; Tk has no alpha, so the shadow is a few
# blended rounded rects over the surface colour.
proc ::cv::settings::open {} {
    set cb [::cv::c card_bg]
    set p .pop
    destroy $p
    canvas $p -highlightthickness 0 -bd 0 -bg [::cv::c bg]
    set f $p.f
    frame $f -bg $cb
    frame $f.hd -bg $cb
    label $f.hd.t -text "Model & connection" -font CV.title -bg $cb -fg [::cv::c text]
    ::cv::w::iconbtn $f.hd.x close -bg $cb -command {destroy .pop}
    pack $f.hd.t -side left
    pack $f.hd.x -side right
    grid $f.hd -row 0 -column 0 -columnspan 2 -sticky ew
    label $f.sub -text "Where prompts go. Changes apply from your next message." -font CV.small -bg $cb -fg [::cv::c muted] -anchor w
    grid $f.sub -row 1 -column 0 -columnspan 2 -sticky w -pady {0 14}
    ::cv::w::segmented $f.prov -values {Ollama OpenAI-compatible Anthropic OpenRouter} -var ::cv::settings::V(provider) -bg $cb
    set W [expr {[winfo reqwidth $f.prov] - 1}]
    _label $f 2 "Provider" 6
    grid $f.prov -row 2 -column 1 -sticky w
    _label $f 4 "Host" 19
    ::cv::w::field $f.host -var ::cv::settings::V(host) -width $W -bg $cb -mono 1
    grid $f.host -row 4 -column 1 -sticky w -pady {12 0}
    _help $f 5 "Ollama server or SSH tunnel · default http://127.0.0.1:11434"
    _label $f 6 "Model" 19
    ::cv::w::field $f.model -var ::cv::settings::V(model) -width $W -bg $cb -trailing chevron
    grid $f.model -row 6 -column 1 -sticky w -pady {12 0}
    _help $f 7 "4 models on this server · qwen3.8:27b: tools ✓  vision ✓  thinking ✓"
    _label $f 8 "Thinking" 16
    frame $f.th -bg $cb
    ::cv::w::toggle $f.th.t -var ::cv::settings::V(think) -bg $cb
    label $f.th.l -text "Better multi-step plans · ~2.5 s/turn (off: ~1.2 s)" -font CV.small -bg $cb -fg [::cv::c muted]
    pack $f.th.t -side left
    pack $f.th.l -side left -padx {10 0}
    grid $f.th -row 8 -column 1 -sticky w -pady {14 0}
    _label $f 9 "Context" 19
    frame $f.cx -bg $cb
    ::cv::w::field $f.cx.f -var ::cv::settings::V(ctx) -width 116 -bg $cb -trailing chevron
    label $f.cx.l -text "tokens (num_ctx)" -font CV.small -bg $cb -fg [::cv::c muted]
    pack $f.cx.f -side left
    pack $f.cx.l -side left -padx {10 0}
    grid $f.cx -row 9 -column 1 -sticky w -pady {12 0}
    _label $f 10 "API key" 19
    ::cv::w::field $f.key -var ::cv::settings::V(key) -width $W -bg $cb -show "•" -state disabled
    grid $f.key -row 10 -column 1 -sticky w -pady {12 0}
    _help $f 11 "Cloud providers only, never sent to Ollama \u00b7 OpenRouter key saved"
    frame $f.sep -bg [::cv::c hairline] -height 1
    grid $f.sep -row 12 -column 0 -columnspan 2 -sticky ew -pady {16 14}
    frame $f.ft -bg $cb
    ::cv::w::button $f.ft.b -text "Test connection" -icon refresh -kind secondary -bg $cb
    canvas $f.ft.r -highlightthickness 0 -bd 0 -bg $cb -width 190 -height 34
    $f.ft.r create oval 2 1 20 19 -fill [::cv::c ok_bg] -outline ""
    ::cv::draw::icon $f.ft.r check 11 10 12 [::cv::c ok]
    $f.ft.r create text 28 10 -anchor w -text "Connected · 212 ms" -font CV.smallB -fill [::cv::c ok]
    $f.ft.r create text 28 27 -anchor w -text "Model answered with a tool call" -font CV.tiny -fill [::cv::c muted]
    ::cv::w::button $f.ft.save -text "Save" -kind primary -bg $cb -padx 18
    ::cv::w::button $f.ft.cancel -text "Cancel" -kind ghost -bg $cb -command {destroy .pop}
    pack $f.ft.b -side left -anchor n
    pack $f.ft.r -side left -padx {12 0} -anchor n
    pack $f.ft.save -side right -anchor n
    pack $f.ft.cancel -side right -padx {0 4} -anchor n
    grid $f.ft -row 13 -column 0 -columnspan 2 -sticky ew
    grid columnconfigure $f 1 -weight 1
    update idletasks
    set sh 6; set caret 8; set pad 18
    set top [winfo width .]
    set x1 $sh
    set x2 [expr {$top - 16 + $sh}]
    set cw [expr {$x2 - $x1}]
    set fh [winfo reqheight $f]
    set y1 [expr {$sh + $caret}]
    set y2 [expr {$y1 + $fh + 2*$pad}]
    set strength [expr {$::cv::theme::mode eq "dark" ? 0.55 : 0.10}]
    ::cv::draw::shadow $p $x1 $y1 $x2 $y2 14 $sh 3 [::cv::c bg] $strength
    ::cv::draw::rrect $p $x1 $y1 $x2 $y2 14 -fill $cb -outline [::cv::c border_strong]
    # caret points at the gear
    set gx [expr {$::cv::app::S(hb_settings) - 8 + $sh}]
    $p create polygon [expr {$gx-9}] [expr {$y1+0.5}] $gx [expr {$y1-$caret}] [expr {$gx+9}] [expr {$y1+0.5}] \
        -fill $cb -outline [::cv::c border_strong]
    $p create line [expr {$gx-8.5}] [expr {$y1+1}] [expr {$gx+8.5}] [expr {$y1+1}] -fill $cb -width 2
    $p create window [expr {$x1+$pad}] [expr {$y1+$pad}] -window $f -anchor nw -width [expr {$cw - 2*$pad}]
    $p configure -width [expr {$x2 + $sh}] -height [expr {$y2 + $sh + 4}]
    place $p -in . -x [expr {8 - $sh}] -y [expr {56 - $sh}]
    raise $p
    # Tk/aqua sometimes skips painting entries nested in canvas windows that were
    # mapped during the same idle pass; poke them once after the popover settles.
    after idle [list after 50 [list apply {{f} {
        foreach e [list $f.host.e $f.model.e $f.cx.f.e $f.key.e] {
            if {[winfo exists $e]} { $e configure -insertwidth [$e cget -insertwidth]; $e xview 0 }
        }
    }} $f]]
}

# ============================================================ event dispatch
# Events mirror the runtime's poll stream (role/type + metadata) so the same
# renderer serves live runs and history replay.
proc ::cv::app::on_event {ev} {
    set type [dict get $ev type]
    switch -- $type {
        user_message   { ::cv::tr::user_message [dict get $ev text] }
        run_start      { ::cv::tr::assistant_header [dict get $ev model] }
        assistant_text {
            if {$::cv::tr::G(cur) ne ""} { ::cv::tr::note [dict get $ev text] } else { ::cv::tr::assistant_markdown [dict get $ev text] }
        }
        tool_start {
            set t0 [expr {[dict exists $ev t0] ? [dict get $ev t0] : ""}]
            set c [::cv::tr::step_start [dict get $ev id] [dict get $ev tool] [dict get $ev title] [dict get $ev command] $t0]
            set n [::cv::tr::getd $c n]
            set what [expr {[dict get $ev tool] eq "capture_vmd_snapshot" ? "capturing snapshot" : "running VMD command"}]
            set_running 1 "Step $n · $what · [mmss [expr {[clock seconds] - [::cv::tr::getd $c t0]}]]"
        }
        tool_result {
            set meta [expr {[dict exists $ev meta] ? [dict get $ev meta] : ""}]
            ::cv::tr::step_result [dict get $ev id] [dict get $ev ok] [dict get $ev output] [dict get $ev elapsed] $meta
            if {[dict exists $ev image]} {
                set c $::cv::tr::S([dict get $ev id])
                set saved [expr {[dict exists $ev saved] ? [dict get $ev saved] : ""}]
                ::cv::tr::snapshot_card [dict get $ev image] [dict get $ev purpose] [::cv::tr::getd $c n] $saved
            }
        }
        assistant_final {
            ::cv::tr::group_end [dict get $ev wall]
            ::cv::tr::assistant_markdown [dict get $ev markdown]
        }
        run_end {
            ::cv::tr::answer_meta [dict get $ev meta]
            set_running 0
        }
    }
}

# ============================================================ demo script
namespace eval ::cv::demo {}
proc ::cv::demo::events {upto} {
    set cmd1 "mol new 1hck.pdb\nmol delrep 0 top\nmol representation NewCartoon\nmol color Structure\nmol selection protein\nmol addrep top\nmol representation Licorice\nmol selection {resname ATP}\nmol addrep top"
    set cmd4 "set sel \[atomselect top protein\]\nmeasure rgyr \$sel"
    set md {- **Protein** — NewCartoon, colored by secondary structure
- **ATP** — Licorice, colored by element

The radius of gyration is **20.84 Å**. To reproduce it, select the protein and call `measure rgyr`:

```tcl
set sel [atomselect top protein]
measure rgyr $sel
```}
    set E {}
    lappend E [dict create type user_message text "Load CDK2 with ATP bound (PDB 1HCK). Show the protein as NewCartoon colored by secondary structure and ATP as Licorice, then tell me the radius of gyration."]
    lappend E [dict create type run_start model qwen3.8:27b]
    lappend E [dict create type assistant_text text "I'll load 1HCK and set up the two representations."]
    lappend E [dict create type tool_start id t1 tool run_vmd_command title "Load structure and build reps" command $cmd1]
    lappend E [dict create type tool_result id t1 ok 1 output 0 elapsed 0.4]
    lappend E [dict create type tool_start id t2 tool run_vmd_command title "Set a white background" command "display backgroundcolor white"]
    lappend E [dict create type tool_result id t2 ok 0 output {invalid command name "display backgroundcolor"} elapsed 0.1]
    lappend E [dict create type assistant_text text "That command doesn't exist; using the color command instead."]
    lappend E [dict create type tool_start id t3 tool run_vmd_command title "Set background with the color command" command "color Display Background white"]
    lappend E [dict create type tool_result id t3 ok 1 output "" elapsed 0.1]
    if {$upto eq "midrun"} {
        lappend E [dict create type tool_start id t4 tool run_vmd_command title "Measure radius of gyration" command $cmd4 t0 [expr {[clock seconds] - 12}]]
        return $E
    }
    lappend E [dict create type tool_start id t4 tool run_vmd_command title "Measure radius of gyration" command $cmd4]
    lappend E [dict create type tool_result id t4 ok 1 output 20.843 elapsed 0.3]
    lappend E [dict create type tool_start id t5 tool capture_vmd_snapshot title "Snapshot · verify cartoon + ATP licorice" command ""]
    lappend E [dict create type tool_result id t5 ok 1 output "" elapsed 0.9 meta "1280 × 1547 PNG · preview below" image $::cv::SNAP purpose "verify cartoon + ATP licorice" saved ".vmdai_runs/0012/snapshots/step05.png"]
    lappend E [dict create type assistant_final wall "14.6 s" markdown $md]
    lappend E [dict create type run_end meta "qwen3.8:27b · 5 steps · 14.6 s"]
    return $E
}
# Region capture of our own window. The prototype floats (-topmost) so another
# app's window cannot cover it, and the PNG is verified by reading back the logo
# pixel; a capture of anything else is deleted, never kept.
proc ::cv::demo::capture {out {attempt 1}} {
    wm attributes . -topmost 1
    raise .; update
    set x [winfo rootx .]; set y [winfo rooty .]; set w [winfo width .]; set h [winfo height .]
    exec /usr/sbin/screencapture -x -o -R$x,[expr {$y-28}],$w,[expr {$h+28}] $out
    set ok 0
    if {![catch {image create photo -file $out} chk]} {
        # inside the logo tile, clear of the hexagon: window (22,18) -> png 2x incl. 28pt title bar
        foreach {r g b} [$chk get 44 [expr {2*(28+18)}]] break
        set ::cv::demo::px [list $r $g $b]
        image delete $chk
        set ok [expr {($b > 190 && $r < 170 && $g < 175 && $b - $r > 60)}]
    }
    if {!$ok} {
        file delete -force $out
        if {$attempt < 3} { after 700 [list ::cv::demo::capture $out [incr attempt]]; return }
        ::cv::log "capture of $out rejected (pixel [expr {[info exists ::cv::demo::px] ? $::cv::demo::px : {?}}]); file deleted"
        exit 2
    }
    exit
}
proc ::cv::demo::run {state out geom} {
    # extra variants: <state>d = same state in the dark palette; A85 = Tk 8.5 simulation
    set dark [expr {$state in {B B2} || ([string length $state] == 2 && [string index $state 1] eq "d")}]
    if {[string index $state 1] eq "d"} { set state [string index $state 0] }
    if {$state eq "A85"} {
        set ::cv::SNAP /nonexistent/tk85_cannot_decode_png.png
        set state A
    }
    ::cv::theme::use [expr {$dark ? "dark" : "light"}]
    if {$dark} { catch {::tk::unsupported::MacWindowStyle appearance . darkaqua} } else { catch {::tk::unsupported::MacWindowStyle appearance . aqua} }
    ::cv::fonts::init
    wm geometry . $geom+80+70
    wm title . [expr {$state eq "D" ? "ChatVMD" : "ChatVMD — CDK2 + ATP (1HCK)"}]
    ::cv::app::build
    update
    set X $::cv::tr::X
    if {$state eq "D"} {
        ::cv::tr::welcome {
            {"Load & style" "Load PDB 1HCK and show the protein as NewCartoon colored by secondary structure" hex}
            {"Color by property" "Color the protein by B-factor from blue to red" palette}
            {"Binding pocket" "Show residues within 5 Å of the ligand as Licorice" target}
            {"Render" "Render a 1600 × 1200 image with a white background" image}
        } {
            {ok Runtime "Connected · 127.0.0.1:8765" ""}
            {ok Model "qwen3.8:27b via Ollama · tunnel :11435" "Change"}
            {ok Folder "~/proj/cdk2 · 12 runs recorded" "Change"}
            {info "" "Tcl from the model runs unsandboxed in this VMD session." "Learn more"}
        }
        ::cv::app::_ph_show
        ::cv::app::draw_composer
    } else {
        foreach ev [events [expr {$state eq "C" ? "midrun" : "full"}]] { ::cv::app::on_event $ev }
        if {$state in {A2 B2}} {
            ::cv::tr::group_toggle g1
        }
        if {$state eq "C"} {
            ::cv::app::_ph_show
            ::cv::app::draw_composer
        } elseif {$state eq "G"} {
            ::cv::app::set_offline 1
            ::cv::app::_ph_show
            ::cv::app::draw_composer
        } else {
            .cmp.t insert 1.0 "Now zoom on the binding pocket\nand make the protein transparent"
            # screenshots are taken while another app is active: pin the focus ring
            set ::cv::app::S(pinfocus) [expr {$state ne "E"}]
            ::cv::app::draw_composer
        }
    }
    update
    ::cv::tr::relayout
    update
    if {$state in {A2 B2}} {
        $X yview moveto 0
    } else {
        $X yview moveto 1.0
        update
        # don't leave a sliver of a line at the top edge
        set top [$X index @0,0]
        set dl [$X dlineinfo $top]
        # (lines above -pady are clipped, so "partially hidden" means y < pady)
        if {[llength $dl] && [lindex $dl 1] < 12 && [lindex $dl 1] > -40} { $X yview $top }
    }
    if {$state eq "E"} { ::cv::settings::open }
    if {$::cv::app::S(focus)} { focus .cmp.t; .cmp.t mark set insert end }
    ::cv::draw::spin_tick
    update
    after 900 [list ::cv::demo::capture $out]
}

if {[info exists ::cv_lib_only]} { proc ::cv::log {msg} {}; return }
set ::cv::LOG [file join /tmp chatvmd_proto_cards.log]
proc ::cv::log {msg} { set fh [open $::cv::LOG a]; puts $fh $msg; close $fh }
proc bgerror {msg} { ::cv::log "BGERROR: $msg\n$::errorInfo"; exit 1 }
set state [lindex $argv 0]
set out [lindex $argv 1]
set geom [lindex $argv 2]
if {$geom eq ""} { set geom [expr {$state eq "F" ? "420x700" : "560x780"}] }
if {[catch {::cv::demo::run $state $out $geom} err]} { ::cv::log "ERROR: $err\n$::errorInfo"; exit 1 }
