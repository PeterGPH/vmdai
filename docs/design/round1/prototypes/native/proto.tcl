# ChatVMD panel -- "Native Minimal" direction: high-fidelity reference prototype.
#
#   usage (via capture_locked.sh):  proto.tcl <A|B|C|D|E|F|G> <abs-out.png> [WxH]
#
# Written the way the production plugin should be structured, so it doubles as a
# reference implementation:
#   ::chatvmd::theme      palette tokens (light/dark) + named fonts
#   ::chatvmd::icon       crisp canvas-drawn toolbar icons + spinner
#   ::chatvmd::ui         window skeleton: toolbar / banner / transcript / composer / status
#   ::chatvmd::tx         transcript renderer: one proc per runtime event kind
#   ::chatvmd::md         lightweight Markdown -> text tags (fences, bullets, **b**, `code`)
#   ::chatvmd::thumb      PNG snapshot -> cover-cropped, subsampled inline thumbnail
#   ::chatvmd::settings   settings sheet (override-redirect toplevel below the toolbar)
#   ::chatvmd::demo       scripted events per state (A..G) and the screen capture
# It never sources the real plugin and never talks to the runtime.

package require Tk 8.5

# Prototype-only diagnostics: background errors go to a log file and exit.
set ::LOG [file join /tmp chatvmd_proto_native.log]
proc ::bgerror {msg} {
    set f [open $::LOG a]; puts $f "BGERROR: $msg\n$::errorInfo"; close $f
    exit 3
}

namespace eval ::chatvmd {
    variable aqua [expr {[tk windowingsystem] eq "aqua"}]
    variable tk86 [expr {[package vsatisfies [package provide Tk] 8.6]}]
    variable ASSETS [file normalize [file join [file dirname [info script]] ../..]]/assets
}

# =============================================================================
# Theme: tokens + fonts
# =============================================================================
namespace eval ::chatvmd::theme {
    variable mode light
    variable T              ;# array: token -> color
    # Chrome (toolbar, composer bar, status bar, sheet) is drawn by native ttk frames
    # on aqua, so its token is the *dynamic* system color: any tk canvas/label placed
    # on chrome blends with ttk in both appearances.  Content surfaces use our own hex.
    variable palettes {
        light {
            chrome     #ececec
            surface    #ffffff
            text       #1d1d1f
            text2      #3c3c43
            code_fg    #7a2e8e
            muted      #6e6e73
            faint      #a1a1a6
            hairline   #d6d6da
            accent     #0a66d8
            ok         #1f8a3b
            err        #c8262e
            code_bg    #f4f4f6
            inline_bg  #ececf0
            hover      #f0f0f4
            sel        #b3d7ff
            field_bd   #c8c8cd
            focus_ring #9ec1f5
            warn_bg    #fff5df
            warn_bd    #efd59b
            warn_fg    #5c4300
            warn_icon  #d88a00
            thumb_bd   #d6d6da
            dot_ok     #28c840
            dot_off    #ff5f57
            spin_hi    #3a3a3c
            spin_lo    #d8d8dc
        }
        dark {
            chrome     #2c2c2e
            surface    #1e1e1e
            text       #e6e6eb
            text2      #c9c9ce
            code_fg    #d9a6f0
            muted      #9a9aa1
            faint      #5f5f65
            hairline   #0c0c0d
            accent     #4ea1ff
            ok         #3bd16f
            err        #ff6b64
            code_bg    #28282b
            inline_bg  #313135
            hover      #29292c
            sel        #3f638b
            field_bd   #48484c
            focus_ring #2f5f9f
            warn_bg    #3a2f16
            warn_bd    #5a4820
            warn_fg    #f6d58f
            warn_icon  #ffb340
            thumb_bd   #3a3a3c
            dot_ok     #32d74b
            dot_off    #ff453a
            spin_hi    #e6e6eb
            spin_lo    #48484c
        }
    }
}

proc ::chatvmd::theme::init {m} {
    variable mode $m
    variable T
    variable palettes
    array set T [dict get $palettes $m]
    if {$::chatvmd::aqua} {
        set T(chrome) systemWindowBackgroundColor
        set T(sel)    systemSelectedTextBackgroundColor
    }
    fonts
}

proc ::chatvmd::theme::c {tok} { variable T; return $T($tok) }

# Named fonts: prose in the platform UI font, code in a real monospace.  Everything
# derives from TkDefaultFont/TkFixedFont so Linux (Tk 8.5, no Menlo) degrades sanely.
proc ::chatvmd::theme::fonts {} {
    set ui   [font actual TkDefaultFont -family]
    set base [font actual TkDefaultFont -size]
    if {$base < 0} { set base 10 }                   ;# pixel-sized on some X11 setups
    set mono [font actual TkFixedFont -family]
    foreach pref {"SF Mono" Menlo "DejaVu Sans Mono"} {
        if {[lsearch -exact [font families] $pref] >= 0} { set mono $pref; break }
    }
    set spec [list \
        ChatBody      [list -family $ui -size $base] \
        ChatBodyBold  [list -family $ui -size $base -weight bold] \
        ChatBodyItal  [list -family $ui -size $base -slant italic] \
        ChatRole      [list -family $ui -size [expr {$base-1}] -weight bold] \
        ChatMeta      [list -family $ui -size [expr {$base-2}]] \
        ChatMetaBold  [list -family $ui -size [expr {$base-2}] -weight bold] \
        ChatSmall     [list -family $ui -size [expr {$base-3}]] \
        ChatH1        [list -family $ui -size [expr {$base+7}] -weight bold] \
        ChatH2        [list -family $ui -size [expr {$base+1}] -weight bold] \
        ChatCode      [list -family $mono -size [expr {$base-1}]] \
        ChatCodeSmall [list -family $mono -size [expr {$base-2}]] \
        ChatTiny      [list -family $ui -size 4] \
    ]
    foreach {name opts} $spec {
        if {$name in [font names]} { font configure $name {*}$opts } else { font create $name {*}$opts }
    }
}

# =============================================================================
# Icons: drawn on canvases so they are crisp on Retina and follow the theme.
# =============================================================================
namespace eval ::chatvmd::icon {}

proc ::chatvmd::icon::rrect {c x0 y0 x1 y1 r args} {
    set pts [list [expr {$x0+$r}] $y0 [expr {$x1-$r}] $y0 $x1 $y0 $x1 [expr {$y0+$r}] \
        $x1 [expr {$y1-$r}] $x1 $y1 [expr {$x1-$r}] $y1 [expr {$x0+$r}] $y1 \
        $x0 $y1 $x0 [expr {$y1-$r}] $x0 [expr {$y0+$r}] $x0 $y0]
    return [$c create polygon $pts -smooth 1 {*}$args]
}

proc ::chatvmd::icon::draw {c kind cx cy col} {
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
                $c create oval [expr {$cx+$dx-1.3}] [expr {$cy-1.3}] [expr {$cx+$dx+1.3}] [expr {$cy+1.3}] \
                    -fill $col -outline "" -tags glyph
            }
        }
        gear {
            set pts {}
            set n 8
            for {set i 0} {$i < $n*4} {incr i} {
                set a [expr {($i/double($n*4))*6.2831853 - 1.5707963 - 3.1415926/($n*4)}]
                set r [expr {($i%4)==1 || ($i%4)==2 ? 7.4 : 5.5}]
                lappend pts [expr {$cx + $r*cos($a)}] [expr {$cy + $r*sin($a)}]
            }
            $c create polygon $pts -fill "" -outline $col -width 1.3 -joinstyle round -tags glyph
            $c create oval [expr {$cx-2.3}] [expr {$cy-2.3}] [expr {$cx+2.3}] [expr {$cy+2.3}] \
                -outline $col -width 1.3 -tags glyph
        }
        warn {
            $c create polygon $cx [expr {$cy-7}] [expr {$cx+8}] [expr {$cy+7}] [expr {$cx-8}] [expr {$cy+7}] \
                -fill $col -outline $col -width 1.5 -joinstyle round -tags glyph
            $c create line $cx [expr {$cy-2}] $cx [expr {$cy+2.5}] -width 1.6 -fill #ffffff -capstyle round -tags glyph
            $c create oval [expr {$cx-0.9}] [expr {$cy+4.2}] [expr {$cx+0.9}] [expr {$cy+6}] -fill #ffffff -outline "" -tags glyph
        }
    }
}

# Borderless toolbar button: icon + rounded hover plate, like a macOS toolbar item.
proc ::chatvmd::icon::button {w kind tip cmd} {
    set bg [::chatvmd::theme::c chrome]
    canvas $w -width 30 -height 26 -highlightthickness 0 -bd 0 -background $bg -cursor hand2
    rrect $w 1 1 29 25 6 -fill "" -outline "" -tags plate
    draw $w $kind 15 13 [::chatvmd::theme::c muted]
    bind $w <Enter>    [list $w itemconfigure plate -fill [::chatvmd::theme::c hover]]
    bind $w <Leave>    [list $w itemconfigure plate -fill ""]
    bind $w <1>        $cmd
    ::chatvmd::ui::tooltip $w $tip
    return $w
}

proc ::chatvmd::icon::pressed {w on} {
    set theme_hover [expr {$::chatvmd::theme::mode eq "dark" ? "#3a3a3d" : "#dcdce0"}]
    $w itemconfigure plate -fill [expr {$on ? $theme_hover : ""}]
}

# NSProgressIndicator-style spinner: 12 spokes, brightness rotates every 80 ms.
proc ::chatvmd::icon::spinner {w size bg} {
    canvas $w -width $size -height $size -highlightthickness 0 -bd 0 -background $bg
    set c [expr {$size/2.0}]
    set r0 [expr {$size*0.24}]; set r1 [expr {$size*0.47}]
    for {set i 0} {$i < 12} {incr i} {
        set a [expr {$i*0.5235988 - 1.5707963}]
        $w create line [expr {$c+$r0*cos($a)}] [expr {$c+$r0*sin($a)}] \
            [expr {$c+$r1*cos($a)}] [expr {$c+$r1*sin($a)}] \
            -width [expr {$size >= 14 ? 1.6 : 1.3}] -capstyle round -tags s$i
    }
    spin_step $w 0
    return $w
}

proc ::chatvmd::icon::spin_step {w k} {
    if {![winfo exists $w]} return
    set hi [::chatvmd::theme::c spin_hi]; set lo [::chatvmd::theme::c spin_lo]
    for {set i 0} {$i < 12} {incr i} {
        set age [expr {($k - $i + 12) % 12}]           ;# 0 = newest spoke
        $w itemconfigure s$i -fill [::chatvmd::ui::mix $hi $lo [expr {min(1.0, $age/8.0)}]]
    }
    after 80 [list ::chatvmd::icon::spin_step $w [expr {($k+1) % 12}]]
}

# =============================================================================
# UI skeleton
# =============================================================================
namespace eval ::chatvmd::ui {
    variable W .                       ;# the panel toplevel (production: .vmd_ai)
    variable state
    array set state {busy 0 connected 1 title "" provider Ollama model qwen3.8:27b
                     host 127.0.0.1:11435 folder ~/proj/cdk2 runs 12}
}

proc ::chatvmd::ui::mix {a b t} {
    lassign [winfo rgb . $a] r1 g1 b1
    lassign [winfo rgb . $b] r2 g2 b2
    format #%02x%02x%02x [expr {int(($r1+($r2-$r1)*$t)/257)}] \
        [expr {int(($g1+($g2-$g1)*$t)/257)}] [expr {int(($b1+($b2-$b1)*$t)/257)}]
}

proc ::chatvmd::ui::tooltip {w text} {
    bind $w <Enter> +[list set ::chatvmd::ui::tip($w) $text]
}

proc ::chatvmd::ui::hairline {w} {
    frame $w -height 1 -background [::chatvmd::theme::c hairline] -bd 0 -highlightthickness 0
    return $w
}

proc ::chatvmd::ui::build {} {
    variable W
    set top $W
    set p [expr {$top eq "." ? "" : $top}]
    wm title $top "ChatVMD"
    wm minsize $top 380 420
    if {$::chatvmd::aqua} {
        catch {::tk::unsupported::MacWindowStyle appearance $top \
            [expr {$::chatvmd::theme::mode eq "dark" ? "darkaqua" : "aqua"}]}
    }
    grid columnconfigure $top 0 -weight 1

    # --- toolbar --------------------------------------------------------------
    ttk::frame $p.tb -padding {8 5 8 5}
    ::chatvmd::icon::button $p.tb.new compose "New chat  (⌘N)" {::chatvmd::ui::new_chat}
    ::chatvmd::icon::button $p.tb.hist history "History" {::chatvmd::ui::history}
    label $p.tb.title -text "" -font ChatMetaBold -foreground [::chatvmd::theme::c text] \
        -background [::chatvmd::theme::c chrome] -anchor center
    ::chatvmd::icon::button $p.tb.more more "More" {::chatvmd::ui::more_menu}
    ::chatvmd::icon::button $p.tb.gear gear "Settings  (⌘,)" {::chatvmd::settings::open}
    grid $p.tb.new $p.tb.hist $p.tb.title $p.tb.more $p.tb.gear -sticky ns
    grid configure $p.tb.title -sticky ew -padx 8
    grid columnconfigure $p.tb 2 -weight 1
    grid $p.tb -row 0 -sticky ew
    hairline $p.tbline
    grid $p.tbline -row 1 -sticky ew

    # --- banner slot (connection problems only) ---------------------------------
    frame $p.banner -background [::chatvmd::theme::c warn_bg] -bd 0 -highlightthickness 0
    grid $p.banner -row 2 -sticky ew
    grid remove $p.banner

    # --- transcript -------------------------------------------------------------
    frame $p.tx -background [::chatvmd::theme::c surface] -bd 0 -highlightthickness 0
    text $p.tx.t -wrap word -bd 0 -highlightthickness 0 -padx 22 -pady 14 \
        -background [::chatvmd::theme::c surface] -foreground [::chatvmd::theme::c text] -font ChatBody \
        -spacing1 0 -spacing2 3 -spacing3 0 -insertwidth 0 -cursor arrow \
        -selectbackground [::chatvmd::theme::c sel] -inactiveselectbackground [::chatvmd::theme::c sel] \
        -selectforeground [::chatvmd::theme::c text] -tabstyle wordprocessor \
        -yscrollcommand [list ::chatvmd::ui::autohide_sb $p.tx.sb]
    ttk::scrollbar $p.tx.sb -orient vertical -command [list $p.tx.t yview]
    grid $p.tx.t $p.tx.sb -sticky nsew
    grid columnconfigure $p.tx 0 -weight 1
    grid rowconfigure $p.tx 0 -weight 1
    grid $p.tx -row 3 -sticky nsew
    grid rowconfigure $top 3 -weight 1
    # A disabled text does not take focus on click (tk text.tcl), which breaks Cmd-C.
    bind $p.tx.t <1> {+focus %W}
    ::chatvmd::tx::init $p.tx.t

    # --- composer bar -------------------------------------------------------------
    hairline $p.cbline
    grid $p.cbline -row 4 -sticky ew
    ttk::frame $p.cb -padding {12 8 12 4}
    grid $p.cb -row 5 -sticky ew
    grid columnconfigure $p.cb 0 -weight 1
    # activity strip (hidden unless a run is active)
    ttk::frame $p.cb.act
    ::chatvmd::icon::spinner $p.cb.act.spin 14 [::chatvmd::theme::c chrome]
    label $p.cb.act.l -text "" -font ChatMeta -foreground [::chatvmd::theme::c text] -background [::chatvmd::theme::c chrome]
    label $p.cb.act.hint -text "Esc to stop" -font ChatMeta -foreground [::chatvmd::theme::c muted] -background [::chatvmd::theme::c chrome]
    pack $p.cb.act.spin -side left -padx {2 7}
    pack $p.cb.act.l -side left
    pack $p.cb.act.hint -side right
    grid $p.cb.act -row 0 -column 0 -columnspan 2 -sticky ew -pady {0 7}
    grid remove $p.cb.act
    # rounded field: canvas plate + borderless text
    canvas $p.cb.field -height 34 -highlightthickness 0 -bd 0 -background [::chatvmd::theme::c chrome]
    text $p.cb.field.t -height 1 -wrap word -bd 0 -highlightthickness 0 -font ChatBody \
        -background [::chatvmd::theme::c surface] -foreground [::chatvmd::theme::c text] -insertbackground [::chatvmd::theme::c text] \
        -spacing2 3 -undo 1 -selectbackground [::chatvmd::theme::c sel] -padx 0 -pady 0
    $p.cb.field.t tag configure placeholder -foreground [::chatvmd::theme::c muted]
    $p.cb.field create window 0 0 -anchor nw -window $p.cb.field.t -tags txt
    grid $p.cb.field -row 1 -column 0 -sticky ew
    ttk::button $p.cb.send -text "Send" -default active -width 6 -command ::chatvmd::ui::send_or_stop
    grid $p.cb.send -row 1 -column 1 -sticky se -padx {10 0} -pady {0 4}
    bind $p.cb.field <Configure> [list ::chatvmd::ui::layout_field $p.cb.field]
    bind $p.cb.field.t <<Modified>> [list ::chatvmd::ui::composer_changed $p.cb.field]
    bind $p.cb.field.t <FocusIn>  [list ::chatvmd::ui::field_focus $p.cb.field 1]
    bind $p.cb.field.t <FocusOut> [list ::chatvmd::ui::field_focus $p.cb.field 0]
    bind $p.cb.field.t <Return> {::chatvmd::ui::send_or_stop; break}
    bind $p.cb.field.t <Shift-Return> {%W insert insert "\n"; break}
    bind $top <Escape> {::chatvmd::ui::stop}

    # --- status bar -----------------------------------------------------------------
    ttk::frame $p.sb -padding {14 1 14 5}
    canvas $p.sb.dot -width 8 -height 8 -highlightthickness 0 -bd 0 -background [::chatvmd::theme::c chrome]
    $p.sb.dot create oval 0.5 0.5 7.5 7.5 -outline "" -tags dot
    label $p.sb.l -font ChatMeta -foreground [::chatvmd::theme::c muted] -background [::chatvmd::theme::c chrome] -anchor w -cursor hand2
    label $p.sb.r -font ChatMeta -foreground [::chatvmd::theme::c muted] -background [::chatvmd::theme::c chrome] -anchor e -cursor hand2
    grid $p.sb.dot $p.sb.l $p.sb.r -sticky ew
    grid configure $p.sb.dot -sticky w -padx {0 6}
    grid columnconfigure $p.sb 2 -weight 1
    grid $p.sb -row 6 -sticky ew
    bind $p.sb.l <1> ::chatvmd::settings::open
    bind $p.sb <Configure> ::chatvmd::ui::refresh_status
    refresh_status
}

proc ::chatvmd::ui::path {sub} { variable W; return [expr {$W eq "." ? "" : $W}]$sub }

proc ::chatvmd::ui::autohide_sb {sb first last} {
    if {$first <= 0.0 && $last >= 1.0} { grid remove $sb } else { grid $sb }
    $sb set $first $last
}

proc ::chatvmd::ui::set_title {s} {
    variable state; set state(title) $s
    [path .tb.title] configure -text $s
}

# Status bar: provider/model on the left, working folder on the right.  Text is
# chosen from progressively shorter variants so it never clips at narrow widths.
proc ::chatvmd::ui::refresh_status {} {
    variable state
    set sb [path .sb]
    if {![winfo exists $sb]} return
    set avail [expr {[winfo width $sb] - 28 - 14}]
    if {$avail < 50} { set avail 520 }
    if {$state(connected)} {
        $sb.dot itemconfigure dot -fill [::chatvmd::theme::c dot_ok]
        set lv [list "$state(provider) · $state(model) · tunnel $state(host)" "$state(provider) · $state(model)" $state(model)]
        $sb.l configure -foreground [::chatvmd::theme::c text]
    } else {
        $sb.dot itemconfigure dot -fill [::chatvmd::theme::c dot_off]
        set lv [list "Runtime offline · reconnecting" "Offline"]
        $sb.l configure -foreground [::chatvmd::theme::c text]
    }
    set folder [file tail $state(folder)]
    set rv [list "$state(folder) · $state(runs) runs" "$folder · $state(runs) runs" $folder]
    foreach l $lv {
        foreach r $rv {
            if {[font measure ChatMeta $l] + [font measure ChatMeta $r] + 48 <= $avail} {
                $sb.l configure -text $l; $sb.r configure -text $r
                return
            }
        }
    }
    $sb.l configure -text [lindex $lv end]; $sb.r configure -text [lindex $rv end]
}

# --- composer --------------------------------------------------------------------
proc ::chatvmd::ui::layout_field {c} {
    variable focus_on
    set w [winfo width $c]; set h [winfo height $c]
    $c delete plate
    set on [expr {[info exists focus_on] && $focus_on}]
    if {$on} {
        ::chatvmd::icon::rrect $c 0.5 0.5 [expr {$w-0.5}] [expr {$h-0.5}] 11 -fill "" -outline [::chatvmd::theme::c focus_ring] -width 3 -tags plate
    }
    ::chatvmd::icon::rrect $c 2 2 [expr {$w-2}] [expr {$h-2}] 9 -fill [::chatvmd::theme::c surface] \
        -outline [expr {$on ? [::chatvmd::theme::c accent] : [::chatvmd::theme::c field_bd]}] -width 1 -tags plate
    $c lower plate
    $c coords txt 12 8
    $c itemconfigure txt -width [expr {$w-24}] -height [expr {$h-14}]
}

proc ::chatvmd::ui::field_focus {c on} {
    variable focus_on $on
    layout_field $c
    placeholder [expr {!$on}]
}

proc ::chatvmd::ui::composer_changed {c} {
    set t $c.t
    $t edit modified 0
    # auto-grow 1..6 display lines
    set n [$t count -displaylines 1.0 "end -1c"]
    if {$n eq ""} { set n 0 }
    incr n
    if {$n > 6} { set n 6 }
    set lh [expr {[font metrics ChatBody -linespace] + 3}]
    $c configure -height [expr {$n*$lh + 16}]
    set_send_enabled
}

proc ::chatvmd::ui::composer_text {} {
    set t [path .cb.field.t]
    if {[$t tag ranges placeholder] ne ""} { return "" }
    return [string trim [$t get 1.0 "end -1c"]]
}

proc ::chatvmd::ui::placeholder {show {msg ""}} {
    variable ph_msg
    if {$msg ne ""} { set ph_msg $msg }
    if {![info exists ph_msg]} { set ph_msg "Ask VMD to load, show, or measure something…" }
    set t [path .cb.field.t]
    if {$show} {
        if {[string trim [$t get 1.0 "end -1c"]] eq ""} {
            $t delete 1.0 end
            $t insert 1.0 $ph_msg placeholder
        }
    } else {
        if {[$t tag ranges placeholder] ne ""} { $t delete 1.0 end }
    }
}

proc ::chatvmd::ui::set_composer {text} {
    set t [path .cb.field.t]
    $t delete 1.0 end
    $t insert 1.0 $text
    composer_changed [path .cb.field]
}

proc ::chatvmd::ui::set_send_enabled {} {
    variable state
    set b [path .cb.send]
    if {$state(busy)} { $b state !disabled; $b configure -default normal; return }
    if {!$state(connected) || [composer_text] eq ""} {
        $b state disabled; $b configure -default normal
    } else {
        $b state !disabled; $b configure -default active
    }
}

proc ::chatvmd::ui::set_busy {on {label ""}} {
    variable state
    set state(busy) $on
    set b [path .cb.send]
    if {$on} {
        $b configure -text "Stop" -default normal
        [path .cb.act.l] configure -text $label
        grid [path .cb.act]
    } else {
        $b configure -text "Send" -default active
        grid remove [path .cb.act]
    }
    set_send_enabled
}

proc ::chatvmd::ui::set_connected {on} {
    variable state
    set state(connected) $on
    refresh_status
    set_send_enabled
}

# Single actionable banner for connection problems (replaces per-poll error spam).
proc ::chatvmd::ui::banner {title detail actions} {
    set b [path .banner]
    foreach c [winfo children $b] { destroy $c }
    set bg [::chatvmd::theme::c warn_bg]
    frame $b.in -background $bg
    canvas $b.in.ic -width 20 -height 18 -highlightthickness 0 -bd 0 -background $bg
    ::chatvmd::icon::draw $b.in.ic warn 10 9 [::chatvmd::theme::c warn_icon]
    label $b.in.t -text $title -font ChatBodyBold -foreground [::chatvmd::theme::c warn_fg] -background $bg -anchor w
    label $b.in.d -text $detail -font ChatMeta -foreground [::chatvmd::theme::c warn_fg] -background $bg \
        -anchor w -justify left -wraplength 300
    frame $b.in.btns -background $bg
    set i 0
    foreach {txt cmd} $actions {
        pill $b.in.btns.b$i $txt $cmd [expr {$i == 0}]
        pack $b.in.btns.b$i -side left -padx {0 6}
        incr i
    }
    grid $b.in.ic -row 0 -column 0 -rowspan 2 -sticky n -padx {0 8} -pady {1 0}
    grid $b.in.t -row 0 -column 1 -sticky w
    grid $b.in.d -row 1 -column 1 -sticky w
    grid $b.in.btns -row 0 -column 2 -rowspan 2 -sticky e -padx {12 0}
    grid columnconfigure $b.in 1 -weight 1
    pack $b.in -fill x -padx 16 -pady 10
    frame $b.line -height 1 -background [::chatvmd::theme::c warn_bd]
    pack $b.line -fill x -side bottom
    bind $b.in <Configure> [list apply {{b} {
        set w [expr {[winfo width $b] - [winfo reqwidth $b.btns] - 60}]
        if {$w > 120} { $b.d configure -wraplength $w }
    }} $b.in]
    grid $b
}

# Compact rounded button drawn on a canvas, for tinted surfaces where aqua ttk
# buttons would paint a grey window-coloured box around themselves.
proc ::chatvmd::ui::pill {w text cmd primary} {
    set bg [[string range $w 0 [expr {[string last . $w]-1}]] cget -background]
    set f ChatMetaBold
    set tw [font measure $f $text]
    set wd [expr {$tw + 22}]; set ht 24
    canvas $w -width $wd -height $ht -highlightthickness 0 -bd 0 -background $bg -cursor hand2
    if {$primary} {
        set fill [::chatvmd::theme::c warn_fg]; set fg $bg; set ol $fill
    } else {
        set fill $bg; set fg [::chatvmd::theme::c warn_fg]; set ol [::chatvmd::theme::c warn_bd]
    }
    ::chatvmd::icon::rrect $w 1 1 [expr {$wd-1}] [expr {$ht-1}] 7 -fill $fill -outline $ol -width 1 -tags plate
    $w create text [expr {$wd/2.0}] [expr {$ht/2.0}] -text $text -font $f -fill $fg
    bind $w <1> $cmd
    return $w
}

proc ::chatvmd::ui::send_or_stop {} {
    variable state
    if {$state(busy)} { stop; return }
    set msg [composer_text]
    if {$msg eq ""} return
    # production: ::vmdai::bridge::send_chat $msg  (returns ok/err; start busy only on ok)
}
proc ::chatvmd::ui::stop {} { # production: ::vmdai::bridge::cancel }
proc ::chatvmd::ui::new_chat {} {}
proc ::chatvmd::ui::history {} {}
proc ::chatvmd::ui::more_menu {} {}

# =============================================================================
# Transcript renderer
# =============================================================================
namespace eval ::chatvmd::tx {
    variable t
    variable tools          ;# dict id -> {name cmd first nlines state dur output ...}
    variable stream_open 0
    variable run_open 0
    variable seq 0
}

proc ::chatvmd::tx::init {w} {
    variable t $w
    variable tools [dict create]
    set C ::chatvmd::theme::c
    $t tag configure role    -font ChatRole -foreground [$C text] -spacing1 20 -spacing3 5
    $t tag configure first   -spacing1 2
    $t tag configure rolemeta -font ChatMeta -foreground [$C muted]
    $t tag configure p       -spacing3 9
    $t tag configure user    -spacing3 4
    $t tag configure prose   -spacing1 4 -spacing3 7
    $t tag configure muted   -foreground [$C muted]
    $t tag configure b       -font ChatBodyBold
    $t tag configure i       -font ChatBodyItal
    $t tag configure ic      -font ChatCode -foreground [$C code_fg]
    $t tag configure bullet  -lmargin1 2 -lmargin2 18 -spacing3 4
    $t tag configure h       -font ChatH2 -spacing1 8 -spacing3 4
    # tool rows
    $t tag configure row     -spacing1 3 -spacing3 3 -lmargin1 0 -lmargin2 24
    $t tag configure snapcmd -font ChatBody -foreground [$C text]
    $t tag configure g_ok    -foreground [$C ok] -font ChatMetaBold
    $t tag configure g_err   -foreground [$C err] -font ChatMetaBold
    $t tag configure cmd     -font ChatCodeSmall -foreground [$C text2]
    $t tag configure extra   -font ChatMeta -foreground [$C muted]
    $t tag configure meta    -font ChatMeta -foreground [$C muted]
    $t tag configure chev    -font ChatMeta -foreground [$C faint]
    $t tag configure errline -font ChatCodeSmall -foreground [$C err] -lmargin1 24 -lmargin2 24 -spacing3 5
    $t tag configure detail  -font ChatCodeSmall -foreground [$C text] -background [$C code_bg] \
                             -lmargin1 24 -lmargin2 24 -rmargin 10
    $t tag configure dfirst  -spacing1 7
    $t tag configure dlast   -spacing3 7
    $t tag configure dnote   -font ChatMeta -foreground [$C muted]
    $t tag configure dout    -foreground [$C muted]
    $t tag configure thumb   -lmargin1 24 -spacing1 5 -spacing3 8
    # fenced code blocks
    $t tag configure code    -font ChatCode -background [$C code_bg] -lmargin1 12 -lmargin2 12 -rmargin 12
    $t tag configure codehdr -font ChatSmall -foreground [$C muted] -spacing1 7 -spacing3 3
    $t tag configure codelast -spacing3 9
    $t tag configure link    -foreground [$C accent] -font ChatMeta
    $t tag configure gap     -font ChatTiny
    $t tag configure sysnote -font ChatMeta -foreground [$C muted] -justify center -spacing1 16 -spacing3 4
    # empty state
    $t tag configure h0      -justify center -spacing1 22
    $t tag configure h1      -font ChatH1 -spacing1 8 -spacing3 6 -justify center
    $t tag configure lead    -foreground [$C muted] -justify center -spacing3 20 -lmargin1 20 -lmargin2 20 -rmargin 20
    $t tag configure sect    -font ChatMetaBold -foreground [$C muted] -spacing1 16 -spacing3 7
    $t tag configure check   -spacing1 3 -spacing3 3
    $t tag configure ckname  -font ChatBody
    $t tag configure ckval   -foreground [$C muted] -font ChatMeta
    $t tag configure example -background [$C code_bg] -lmargin1 12 -lmargin2 12 -rmargin 12 \
                             -spacing1 8 -spacing3 8
    $t tag configure note    -font ChatMeta -foreground [$C muted] -spacing1 22 -justify center \
                             -lmargin1 12 -lmargin2 12 -rmargin 12
    catch {
        $t tag configure detail  -lmargincolor [$C code_bg]
        $t tag configure code    -lmargincolor [$C code_bg] -rmargincolor [$C code_bg]
        $t tag configure example -lmargincolor [$C code_bg] -rmargincolor [$C code_bg]
    }
    foreach tg {link} {
        $t tag bind $tg <Enter> [list $t configure -cursor hand2]
        $t tag bind $tg <Leave> [list $t configure -cursor arrow]
    }
    $t tag raise sel
    bind $t <Configure> ::chatvmd::tx::relayout
    $t configure -state disabled
}

proc ::chatvmd::tx::edit {script} {
    variable t
    $t configure -state normal
    set rc [catch {uplevel 1 $script} res]
    $t configure -state disabled
    if {$rc} { return -code $rc $res }
    return $res
}

proc ::chatvmd::tx::width {} {
    variable t
    set w [expr {[winfo width $t] - 2*[$t cget -padx] - 2}]
    if {$w < 100} { set w 480 }
    return $w
}

# Right-aligned metadata (timestamps, durations, links) uses a right tab stop at the
# content edge; recomputed whenever the transcript is resized.
proc ::chatvmd::tx::relayout {} {
    variable t
    center_empty
    set w [width]
    $t tag configure role    -tabs [list $w right]
    $t tag configure row     -tabs [list 24 left [expr {$w-2}] right]
    $t tag configure codehdr -tabs [list [expr {$w-12}] right]
    $t tag configure check   -tabs [list 24 left 92 left [expr {$w-2}] right]
    refit_rows
}

# Empty state sits in the optical centre of the transcript (recomputed on resize).
proc ::chatvmd::tx::center_empty {} {
    variable t
    if {[$t tag ranges h0] eq ""} return
    $t tag configure h0 -spacing1 0
    set content [$t count -update -ypixels 1.0 end]
    set avail [expr {[winfo height $t] - 2*[$t cget -pady]}]
    $t tag configure h0 -spacing1 [expr {max(12, ($avail - $content)/2 - 24)}]
}

proc ::chatvmd::tx::stamp {} { return "2:41 PM" }

proc ::chatvmd::tx::sep_if_needed {} {
    variable t
    # Every block starts on a fresh line (fixes the "…representations.SYSTEM:" glue).
    if {[$t index "end -1c"] ne "1.0" && [$t get "end -2c"] ne "\n"} { $t insert end "\n" }
}

proc ::chatvmd::tx::role {who meta} {
    variable t
    edit {
        sep_if_needed
        set tags role
        if {[$t index "end -1c"] eq "1.0"} { lappend tags first }
        $t insert end $who $tags "\t" $tags $meta [concat $tags rolemeta] "\n" $tags
    }
}

# ---- event kinds ---------------------------------------------------------------------
proc ::chatvmd::tx::user_message {text} {
    variable run_open 0
    variable t
    role "You" [stamp]
    edit { $t insert end $text {p user} "\n" {p user} }
}

proc ::chatvmd::tx::run_begin {} {
    variable run_open 1
    variable t
    role "VMD AI" ""
    $t mark set runmeta "end -2c"
}

proc ::chatvmd::tx::run_end {steps secs} {
    variable t
    edit { $t insert runmeta "$steps steps · $secs s" {role rolemeta} }
}

proc ::chatvmd::tx::stream_begin {} {
    variable stream_open 1
    variable t
    edit {
        sep_if_needed
        $t mark set s.start "end -1c"
        $t mark gravity s.start left
    }
}
proc ::chatvmd::tx::stream_chunk {s} {
    variable t
    edit { $t insert end $s prose }
    catch {$t see end}
}
# On close, the raw streamed text is replaced by its Markdown rendering.
proc ::chatvmd::tx::stream_end {} {
    variable stream_open
    variable t
    if {!$stream_open} return
    set stream_open 0
    edit {
        set raw [$t get s.start "end -1c"]
        $t delete s.start "end -1c"
        ::chatvmd::md::render $t $raw
    }
}

proc ::chatvmd::tx::assistant_text {text} {
    stream_begin
    foreach chunk [regexp -all -inline {.{1,24}} $text] { stream_chunk $chunk }
    stream_end
}

proc ::chatvmd::tx::first_line {cmd} {
    set lines [split [string trim $cmd] "\n"]
    return [list [string trim [lindex $lines 0]] [llength $lines]]
}

proc ::chatvmd::tx::tool_start {id name input} {
    variable tools
    variable t
    stream_end
    if {$name eq "capture_vmd_snapshot"} {
        set first "Snapshot"
        set extra [dict get $input purpose]
    } else {
        lassign [first_line [dict get $input command]] first n
        set extra [expr {$n > 1 ? "+[expr {$n-1}] line[expr {$n > 2 ? "s" : ""}]" : ""}]
    }
    dict set tools $id [dict create name $name input $input first $first extra $extra \
        state running meta "running…" out "" expanded 0]
    edit {
        sep_if_needed
        # glyph slot: a live spinner while the Tcl runs (replaced by ✓/✗ on result)
        set sp $t.spin_[string map {. _} $id]
        ::chatvmd::icon::spinner $sp 12 [::chatvmd::theme::c surface]
        $t window create end -window $sp -align center -padx 1
        $t tag add glyph:$id "end -2c"
        $t tag add row "end -2c"
        $t tag add row:$id "end -2c"
        $t insert end "\n" [list row row:$id]
        $t mark set $id.rowend "end -1c"; $t mark gravity $id.rowend left
    }
    render_row $id
    $t tag bind row:$id <Enter> [list ::chatvmd::tx::row_hover $id 1]
    $t tag bind row:$id <Leave> [list ::chatvmd::tx::row_hover $id 0]
    $t tag bind row:$id <1>     [list ::chatvmd::tx::toggle $id]
}

proc ::chatvmd::tx::row_hover {id on} {
    variable t
    $t tag configure row:$id -background [expr {$on ? [::chatvmd::theme::c hover] : ""}]
    catch {$t tag configure row:$id -lmargincolor [expr {$on ? [::chatvmd::theme::c hover] : ""}]}
    $t configure -cursor [expr {$on ? "hand2" : "arrow"}]
}

# (Re)draw everything after the glyph: "\t<cmd>  <extra>\t<meta>".  Called on start,
# on result and on every resize, so a row is always exactly one display line:
# the "+N lines" hint is dropped first, then the command is ellipsized.
proc ::chatvmd::tx::render_row {id} {
    variable tools
    variable t
    set d [dict get $tools $id]
    set snap [expr {[dict get $d name] eq "capture_vmd_snapshot"}]
    set cfont [expr {$snap ? "ChatBody" : "ChatCodeSmall"}]
    set meta [dict get $d meta]
    set chev [expr {[dict get $d expanded] ? "  ▾" : "  ▸"}]
    set avail [expr {[width] - 24 - [font measure ChatMeta "$meta$chev"] - 18}]
    set s [dict get $d first]
    set extra [dict get $d extra]
    set ex [expr {$extra eq "" ? "" : "  $extra"}]
    if {[font measure $cfont $s] + [font measure ChatMeta $ex] > $avail} {
        if {$snap} {
            while {[font measure ChatMeta $ex] > $avail - [font measure $cfont $s] && [string length $ex] > 6} {
                set ex "[string range $ex 0 end-2]…"
            }
        } else {
            set ex ""
        }
    }
    while {[font measure $cfont $s] + [font measure ChatMeta $ex] > $avail && [string length $s] > 4} {
        set s "[string trimright [string range $s 0 end-2] " …"]…"
    }
    set rt [list row row:$id]
    edit {
        set g [lindex [$t tag ranges glyph:$id] 1]
        $t delete $g "$id.rowend -1c"
        $t insert $g "\t" $rt $s [concat $rt [expr {$snap ? "snapcmd" : "cmd"}]] \
            $ex [concat $rt extra] "\t" $rt $meta [concat $rt meta] $chev [concat $rt chev]
    }
}

proc ::chatvmd::tx::refit_rows {} {
    variable tools
    foreach id [dict keys $tools] { render_row $id }
}

proc ::chatvmd::tx::tool_result {id ok output dur {error ""}} {
    variable tools
    variable t
    set o [string trim $output]
    # short, informative output goes inline (→ 20.843); trivial values stay hidden
    set m "$dur s"
    if {$ok && $o ne "" && ![regexp {^(0|1|atomselect\d+)$} $o]
            && [string length $o] <= 18 && ![string match *\n* $o]} {
        set m "→ $o    $m"
    }
    dict set tools $id state [expr {$ok ? "ok" : "err"}]
    dict set tools $id meta $m
    dict set tools $id out $output
    edit {
        set g [lindex [$t tag ranges glyph:$id] 0]
        $t delete $g
        set tags [list row row:$id glyph:$id [expr {$ok ? "g_ok" : "g_err"}]]
        $t insert $g [expr {$ok ? "✓" : "✗"}] $tags
        if {!$ok} { $t insert $id.rowend $error {errline} "\n" {errline} }
    }
    render_row $id
}

proc ::chatvmd::tx::toggle {id} {
    variable tools
    variable t
    set d [dict get $tools $id]
    if {[dict get $d expanded]} {
        edit { $t delete {*}[$t tag ranges detail:$id] }
        dict set tools $id expanded 0
        render_row $id
        return
    }
    dict set tools $id expanded 1
    render_row $id
    set in [dict get $d input]
    edit {
        set at [$t index $id.rowend]
        set tg [list detail detail:$id]
        set lines {}
        if {[dict exists $in rationale] && [dict get $in rationale] ne ""} {
            lappend lines [list [dict get $in rationale] dnote]
        }
        foreach l [split [string trim [dict get $in command]] "\n"] { lappend lines [list [string trim $l] {}] }
        set o [string trim [dict get $d out]]
        if {$o ne ""} { lappend lines [list "→ $o" dout] }
        set i 0; set n [llength $lines]
        foreach pair $lines {
            lassign $pair txt extra
            set tags [concat $tg $extra]
            if {$i == 0} { lappend tags dfirst }
            if {$i == $n-1} { lappend tags dlast }
            $t insert $at $txt $tags "\n" $tags
            set at [$t index "$at +1l linestart"]
            incr i
        }
    }
}

proc ::chatvmd::tx::snapshot {id path} {
    variable t
    set img [::chatvmd::thumb::make $path 232 146]
    edit {
        set at [$t index $id.rowend]
        if {$img eq ""} {
            $t insert $at "Open snapshot" [list link thumb] "\n" thumb
            return
        }
        set f $t.thumb_[string map {. _} $id]
        frame $f -background [::chatvmd::theme::c thumb_bd] -bd 0 -cursor hand2
        label $f.l -image $img -bd 0 -highlightthickness 0 -cursor hand2
        pack $f.l -padx 1 -pady 1
        bind $f.l <1> [list ::chatvmd::thumb::open_full $path]
        $t window create $at -window $f -align top
        $t tag add thumb $at
        $t insert "$at +1c" "\n" thumb
    }
}

proc ::chatvmd::tx::system_note {text} {
    variable t
    edit {
        sep_if_needed
        $t insert end $text sysnote "\n" sysnote
    }
}

# Code-block actions.  "Run" goes through the same (future) approval hook as tools.
proc ::chatvmd::tx::copy_code {code} {
    clipboard clear; clipboard append $code
}
proc ::chatvmd::tx::run_code {code} {
    # production: ::vmdai::approval::request "Run code block" $code \
    #                 [list ::vmdai::bridge::run_user_tcl $code]
}

# =============================================================================
# Markdown (subset): ```fences```, - / * / 1. lists, # headings, **bold**, `code`
# =============================================================================
namespace eval ::chatvmd::md {}

proc ::chatvmd::md::inline {t s base} {
    while {$s ne ""} {
        if {![regexp -indices {\*\*([^*]+)\*\*|`([^`]+)`} $s all b c]} {
            $t insert end $s $base
            return
        }
        lassign $all a0 a1
        if {$a0 > 0} { $t insert end [string range $s 0 [expr {$a0-1}]] $base }
        if {[lindex $b 0] >= 0} {
            $t insert end [string range $s {*}$b] [concat $base b]
        } else {
            # No background tint: Tk paints a tagged background to the right margin when
            # the run ends a wrapped display line, and U+00A0 is a break point for Tk.
            $t insert end [string range $s {*}$c] [concat $base ic]
        }
        set s [string range $s [expr {$a1+1}] end]
    }
}

proc ::chatvmd::md::render {t raw} {
    set lines [split [string trimright $raw] "\n"]
    set n [llength $lines]
    set para {}
    set flush {
        if {[llength $para]} {
            inline $t [join $para " "] prose
            $t insert end "\n" prose
            set para {}
        }
    }
    for {set k 0} {$k < $n} {incr k} {
        set line [lindex $lines $k]
        if {[regexp {^```\s*(\S*)} $line -> lang]} {
            eval $flush
            set body {}
            for {incr k} {$k < $n && ![string match "```*" [lindex $lines $k]]} {incr k} {
                lappend body [lindex $lines $k]
            }
            code_block $t $lang [join $body "\n"]
            continue
        }
        if {[regexp {^\s*[-*]\s+(.*)$} $line -> item] || [regexp {^\s*\d+[.)]\s+(.*)$} $line -> item]} {
            eval $flush
            set tags {prose bullet}
            $t insert end "•\t" [concat $tags muted]
            inline $t $item $tags
            $t insert end "\n" $tags
            continue
        }
        if {[regexp {^#{1,4}\s+(.*)$} $line -> head]} {
            eval $flush
            inline $t $head h
            $t insert end "\n" h
            continue
        }
        if {[string trim $line] eq ""} { eval $flush; continue }
        lappend para [string trim $line]
    }
    eval $flush
    $t tag configure bullet -tabs {18 left}
}

proc ::chatvmd::md::code_block {t lang code} {
    set id cb[incr ::chatvmd::tx::seq]
    set hdr [list code codehdr]
    $t insert end [expr {$lang eq "" ? "code" : $lang}] $hdr "\t" $hdr \
        "Copy" [concat $hdr link copy:$id] "      " $hdr "Run in VMD" [concat $hdr link run:$id] "\n" $hdr
    set lines [split $code "\n"]
    set i 0
    foreach l $lines {
        set tags code
        if {[incr i] == [llength $lines]} { lappend tags codelast }
        $t insert end $l $tags "\n" $tags
    }
    $t tag bind copy:$id <1> [list ::chatvmd::tx::copy_code $code]
    $t tag bind run:$id  <1> [list ::chatvmd::tx::run_code $code]
}

# =============================================================================
# Thumbnails (Tk 8.6 PNG; Tk 8.5 falls back to an "Open snapshot" link)
# =============================================================================
namespace eval ::chatvmd::thumb {}

proc ::chatvmd::thumb::make {path maxw maxh} {
    if {[catch {image create photo -file $path} src]} { return "" }
    set sw [image width $src]; set sh [image height $src]
    # cover-crop to the target aspect, centred, then integer-subsample
    set ta [expr {double($maxw)/$maxh}]
    if {double($sw)/$sh > $ta} {
        set cw [expr {int($sh*$ta)}]; set ch $sh
    } else {
        set cw $sw; set ch [expr {int($sw/$ta)}]
    }
    set x0 [expr {($sw-$cw)/2}]; set y0 [expr {($sh-$ch)/2}]
    set f [expr {int(ceil(double($cw)/$maxw))}]
    set dst [image create photo]
    $dst copy $src -from $x0 $y0 [expr {$x0+$cw}] [expr {$y0+$ch}] -subsample $f $f
    image delete $src
    return $dst
}

proc ::chatvmd::thumb::open_full {path} {
    if {$::chatvmd::aqua} { catch {exec open $path &} } else { catch {exec xdg-open $path &} }
}

# =============================================================================
# Settings sheet
# =============================================================================
namespace eval ::chatvmd::settings {
    variable v
    array set v {provider ollama host http://127.0.0.1:11435 model qwen3.8:27b think 1
                 ctx 32768 anthropic_key sk-ant-XXXXXXXXXXXXXX openrouter_key ""}
}

proc ::chatvmd::settings::open {} {
    variable v
    set main $::chatvmd::ui::W
    set s .settings
    catch {destroy $s}
    toplevel $s
    wm withdraw $s
    # Override-redirect + transient reads as a macOS sheet: no title bar, real window
    # shadow, key focus still works (verified in Tk 8.6.12).  X11: plain transient dialog.
    if {$::chatvmd::aqua} {
        wm overrideredirect $s 1
        catch {::tk::unsupported::MacWindowStyle appearance $s \
            [expr {$::chatvmd::theme::mode eq "dark" ? "darkaqua" : "aqua"}]}
    } else {
        wm title $s "ChatVMD Settings"
    }
    wm transient $s $main
    set C ::chatvmd::theme::c
    ttk::frame $s.f -padding {20 16 20 16}
    pack $s.f -fill both -expand 1
    set f $s.f
    ttk::label $f.title -text "Model provider" -font ChatH2
    ttk::label $f.sub -text "Where ChatVMD sends your prompts. Changes apply to the next message." \
        -font ChatMeta -foreground [$C muted]
    grid $f.title -row 0 -column 0 -columnspan 3 -sticky w
    grid $f.sub -row 1 -column 0 -columnspan 3 -sticky w -pady {1 12}

    # provider = segmented control (aqua notebook tabs), provider-specific form inside
    ttk::notebook $f.nb -padding 0
    foreach {key label} {ollama Ollama openai "OpenAI-compatible" anthropic Anthropic openrouter OpenRouter} {
        ttk::frame $f.nb.$key -padding {14 12 14 10}
        $f.nb add $f.nb.$key -text $label
    }
    set p $f.nb.ollama
    set r 0
    ttk::label $p.hl -text "Server"
    ttk::entry $p.host -textvariable ::chatvmd::settings::v(host) -width 30
    ttk::label $p.hh -text "Ollama or an SSH tunnel to it. The local default is :11434." -font ChatSmall -foreground [$C muted]
    grid $p.hl -row $r -column 0 -sticky e -padx {0 10}
    grid $p.host -row $r -column 1 -columnspan 2 -sticky ew
    grid $p.hh -row [incr r] -column 1 -columnspan 2 -sticky w -pady {2 8}
    ttk::label $p.ml -text "Model"
    ttk::combobox $p.model -textvariable ::chatvmd::settings::v(model) \
        -values {qwen3.8:27b qwen3.8:8b qwen3-vl:32b llama3.3:70b gemma3:27b}
    ttk::button $p.refresh -text "Refresh" -width 7
    grid $p.ml -row [incr r] -column 0 -sticky e -padx {0 10}
    grid $p.model -row $r -column 1 -sticky ew
    grid $p.refresh -row $r -column 2 -sticky w -padx {8 0}
    ttk::label $p.mh -text "5 models on this server · tools ✓ · vision ✓" -font ChatSmall -foreground [$C muted]
    grid $p.mh -row [incr r] -column 1 -columnspan 2 -sticky w -pady {2 8}
    ttk::label $p.cl -text "Context"
    ttk::frame $p.cf
    ttk::combobox $p.cf.ctx -textvariable ::chatvmd::settings::v(ctx) -values {8192 16384 32768 65536 131072} -width 8
    ttk::label $p.cf.u -text "tokens" -foreground [$C muted]
    pack $p.cf.ctx -side left
    pack $p.cf.u -side left -padx {6 0}
    grid $p.cl -row [incr r] -column 0 -sticky e -padx {0 10}
    grid $p.cf -row $r -column 1 -columnspan 2 -sticky w
    ttk::checkbutton $p.think -text "Thinking" -variable ::chatvmd::settings::v(think)
    grid $p.think -row [incr r] -column 1 -columnspan 2 -sticky w -pady {10 0}
    ttk::label $p.th -text "More reliable tool use; roughly 2.5 s per turn instead of 1.2 s." -font ChatSmall -foreground [$C muted]
    grid $p.th -row [incr r] -column 1 -columnspan 2 -sticky w -padx {20 0} -pady {0 2}
    grid columnconfigure $p 1 -weight 1
    grid $f.nb -row 2 -column 0 -columnspan 3 -sticky ew

    # connection test
    ttk::frame $f.test
    ttk::button $f.test.b -text "Test connection"
    label $f.test.r -text "✓  Connected · tool call returned in 1.2 s" \
        -font ChatMeta -foreground [$C ok] -background [$C chrome]
    pack $f.test.b -side left
    pack $f.test.r -side left -padx {10 0}
    grid $f.test -row 3 -column 0 -columnspan 3 -sticky w -pady {12 4}

    # API keys (cloud providers)
    ttk::separator $f.sep
    grid $f.sep -row 4 -column 0 -columnspan 3 -sticky ew -pady {12 12}
    ttk::label $f.kt -text "API keys" -font ChatBodyBold
    ttk::label $f.ks -text "Only needed for Anthropic and OpenRouter. Saved in the macOS Keychain." \
        -font ChatSmall -foreground [$C muted]
    grid $f.kt -row 5 -column 0 -columnspan 3 -sticky w
    grid $f.ks -row 6 -column 0 -columnspan 3 -sticky w -pady {1 8}
    ttk::label $f.k1l -text "Anthropic"
    ttk::entry $f.k1 -textvariable ::chatvmd::settings::v(anthropic_key) -show "•"
    label $f.k1s -text "✓ Saved" -font ChatMeta -foreground [$C ok] -background [$C chrome]
    ttk::label $f.k2l -text "OpenRouter"
    ttk::entry $f.k2 -textvariable ::chatvmd::settings::v(openrouter_key) -show "•"
    label $f.k2s -text "Not set" -font ChatMeta -foreground [$C muted] -background [$C chrome]
    grid $f.k1l -row 7 -column 0 -sticky e -padx {0 10}
    grid $f.k1 -row 7 -column 1 -sticky ew
    grid $f.k1s -row 7 -column 2 -sticky w -padx {10 0}
    grid $f.k2l -row 8 -column 0 -sticky e -padx {0 10} -pady {6 0}
    grid $f.k2 -row 8 -column 1 -sticky ew -pady {6 0}
    grid $f.k2s -row 8 -column 2 -sticky w -padx {10 0} -pady {6 0}
    grid columnconfigure $f 1 -weight 1

    # footer
    ttk::frame $f.foot
    ttk::button $f.foot.cancel -text "Cancel" -command [list destroy $s]
    ttk::button $f.foot.save -text "Save" -default active -command [list destroy $s]
    pack $f.foot.save $f.foot.cancel -side right -padx {8 0}
    grid $f.foot -row 9 -column 0 -columnspan 3 -sticky ew -pady {18 0}
    bind $s <Escape> [list destroy $s]
    bind $s <Return> [list $f.foot.save invoke]

    # place under the toolbar, centred, like a sheet
    update idletasks
    set mw [winfo width $main]
    set sw [expr {min(470, $mw - 32)}]
    set sh [winfo reqheight $s]
    set x [expr {[winfo rootx $main] + ($mw - $sw)/2}]
    set y [expr {[winfo rooty $main] + [winfo height [::chatvmd::ui::path .tb]]}]
    wm geometry $s ${sw}x${sh}+$x+$y
    wm deiconify $s
    ::chatvmd::icon::pressed [::chatvmd::ui::path .tb.gear] 1
    bind $s <Destroy> [list ::chatvmd::icon::pressed [::chatvmd::ui::path .tb.gear] 0]
    return $s
}

# =============================================================================
# Empty / first-run state
# =============================================================================
proc ::chatvmd::tx::empty_state {} {
    variable t
    set C ::chatvmd::theme::c
    edit {
        set mk $t.mark
        canvas $mk -width 64 -height 46 -highlightthickness 0 -bd 0 -background [$C surface]
        set a [$C accent]; set s2 [::chatvmd::ui::mix $a [$C surface] 0.35]; set s3 [::chatvmd::ui::mix $a [$C surface] 0.6]
        $mk create line 16 30 38 14 50 34 -width 3 -fill $s3 -capstyle round -joinstyle round
        $mk create line 38 14 38 14 -width 1
        $mk create oval 8 22 24 38 -fill $s2 -outline ""
        $mk create oval 29 5 47 23 -fill $a -outline ""
        $mk create oval 43 27 57 41 -fill $s3 -outline ""
        $t insert end "" h0
        $t window create end -window $mk -align center
        $t tag add h0 "end -2c"
        $t insert end "\n" h0
        $t insert end "What should VMD do?" h1 "\n" h1
        $t insert end "Describe a view, a measurement or an analysis. ChatVMD writes the Tcl, runs it in this VMD session and checks the result with a snapshot." lead "\n" lead
        $t insert end "Ready" sect "\n" sect
        foreach {name val act} {
            Runtime "running · 127.0.0.1:8765" ""
            Model   "Ollama · qwen3.8:27b · tools, vision" "Change"
            Folder  "~/proj/cdk2 · 12 runs recorded" "Change"
        } {
            $t insert end "✓" {check g_ok} "\t" check $name {check ckname} "\t" check $val {check ckval}
            if {$act ne ""} { $t insert end "\t" check $act {check link} }
            $t insert end "\n" check
        }
        $t insert end "Try" sect "\n" sect
        set i 0
        foreach ex {
            "Load PDB 1HCK as NewCartoon colored by secondary structure"
            "Show residues within 5 Å of the ligand as Licorice"
            "Color the protein by B-factor and render a snapshot"
            "Measure the backbone RMSD over the loaded trajectory"
        } {
            set tg [list example ex$i]
            $t insert end $ex $tg "\n" $tg
            $t insert end " " gap "\n" gap
            $t tag bind ex$i <Enter> [list apply {{t tg} {
                $t tag configure $tg -background [::chatvmd::theme::c hover]
                catch {$t tag configure $tg -lmargincolor [::chatvmd::theme::c hover] -rmargincolor [::chatvmd::theme::c hover]}
                $t configure -cursor hand2 }} $t ex$i]
            $t tag bind ex$i <Leave> [list apply {{t tg} {
                $t tag configure $tg -background "" ; catch {$t tag configure $tg -lmargincolor "" -rmargincolor ""}
                $t configure -cursor arrow }} $t ex$i]
            $t tag bind ex$i <1> [list ::chatvmd::ui::set_composer $ex]
            incr i
        }
        $t insert end "ChatVMD runs model-written Tcl with your permissions. Only load files you trust." note "\n" note
    }
}

# =============================================================================
# Demo script: the scripted conversation, fed through the same event procs
# =============================================================================
namespace eval ::chatvmd::demo {
    variable USER1 "Load CDK2 with ATP bound (PDB 1HCK). Show the protein as NewCartoon colored by secondary structure and ATP as Licorice, then tell me the radius of gyration."
    variable CMD1 "mol new 1hck.pdb\nmol delrep 0 top\nmol representation NewCartoon\nmol color Structure\nmol selection protein\nmol addrep top\nmol representation Licorice\nmol selection {resname ATP}\nmol addrep top"
    variable FINAL "- **Protein** — NewCartoon, colored by secondary structure\n- **ATP** — Licorice, colored by element\n\nThe radius of gyration is **20.84 Å**. To reproduce it, run `measure rgyr` on a protein selection:\n\n```tcl\nset sel \[atomselect top protein\]\nmeasure rgyr \$sel\n```"
    variable FOLLOW "Now zoom on the binding pocket\nand make the protein transparent"
}

proc ::chatvmd::demo::conversation {upto {expand {}}} {
    variable USER1; variable CMD1; variable FINAL
    set T ::chatvmd::tx
    ::chatvmd::ui::set_title "CDK2 with ATP (1HCK)"
    ${T}::user_message $USER1
    ${T}::run_begin
    ${T}::assistant_text "I'll load 1HCK and set up the two representations."
    ${T}::tool_start t1 run_vmd_command [dict create command $CMD1 rationale "Load structure and build reps"]
    ${T}::tool_result t1 1 "0" 0.4
    ${T}::tool_start t2 run_vmd_command [dict create command "display backgroundcolor white"]
    ${T}::tool_result t2 0 "" 0.1 {invalid command name "display backgroundcolor"}
    ${T}::assistant_text "That command doesn't exist; using the color command instead."
    ${T}::tool_start t3 run_vmd_command [dict create command "color Display Background white"]
    ${T}::tool_result t3 1 "" 0.1
    ${T}::tool_start t4 run_vmd_command [dict create command "set sel \[atomselect top protein\]\nmeasure rgyr \$sel"]
    foreach id $expand { ${T}::toggle $id }
    if {$upto eq "t4-running"} return
    ${T}::tool_result t4 1 "20.843" 0.2
    ${T}::tool_start t5 capture_vmd_snapshot [dict create command "" purpose "verify cartoon + ATP licorice"]
    ${T}::tool_result t5 1 "" 1.8
    ${T}::snapshot t5 $::chatvmd::ASSETS/snap_1hck.png
    ${T}::assistant_text $FINAL
    ${T}::run_end 5 16
}

proc ::chatvmd::demo::capture {out {target ""}} {
    set top $::chatvmd::ui::W
    if {$target eq ""} { set target $top }
    focus -force $target
    raise $top
    if {[winfo exists .settings]} { raise .settings; focus -force .settings.f.nb.ollama.host }
    update
    after 250
    update
    set x [winfo rootx $top]; set y [winfo rooty $top]
    set w [winfo width $top]; set h [winfo height $top]
    exec /usr/sbin/screencapture -x -o -R$x,[expr {$y-28}],$w,[expr {$h+28}] $out
    exit
}

proc ::chatvmd::demo::run {st out geom} {
    variable FOLLOW
    after 14000 exit                              ;# hard stop: never outlive the lock
    set mode [expr {$st eq "B" ? "dark" : "light"}]
    ::chatvmd::theme::init $mode
    if {$geom eq ""} { set geom [expr {$st eq "F" ? "420x700" : "560x780"}] }
    wm geometry . $geom+80+70
    ::chatvmd::ui::build
    update idletasks
    update
    ::chatvmd::tx::relayout
    set t [::chatvmd::ui::path .tx.t]
    set field [::chatvmd::ui::path .cb.field]
    switch -- $st {
        A - B - F - E {
            conversation all
            ::chatvmd::ui::set_composer $FOLLOW
            if {$st ne "E"} { focus $field.t; ::chatvmd::ui::field_focus $field 1 }
            $field.t mark set insert end
        }
        C {
            conversation t4-running t1
            ::chatvmd::ui::set_busy 1 "Step 4 · running VMD command · 00:12"
            ::chatvmd::ui::placeholder 1 "Draft your next message…"
            ::chatvmd::ui::composer_changed $field
        }
        D {
            ::chatvmd::ui::set_title "New chat"
            ::chatvmd::tx::empty_state
            ::chatvmd::ui::placeholder 1
            ::chatvmd::ui::composer_changed $field
        }
        G {
            conversation all
            ::chatvmd::ui::set_connected 0
            ::chatvmd::tx::system_note "Connection lost at 2:43 PM · your draft is kept"
            ::chatvmd::ui::banner "Runtime not reachable" \
                "Nothing answered on 127.0.0.1:8765. Retrying in 8 s." \
                [list "Retry" {} "Open log" {}]
            ::chatvmd::ui::set_composer $FOLLOW
        }
    }
    update idletasks
    ::chatvmd::tx::relayout
    ::chatvmd::ui::refresh_status
    ::chatvmd::ui::set_send_enabled
    if {$st ne "D"} { $t see end; $t yview moveto 1.0 }
    if {$st eq "E"} { after 300 ::chatvmd::settings::open }
    set target [expr {$st in {A B F} ? "$field.t" : ""}]
    after 1000 [list ::chatvmd::demo::capture $out $target]
}

# ---------------------------------------------------------------------------------
if {[info exists ::argv] && [llength $::argv] >= 2} {
    if {[catch {::chatvmd::demo::run [lindex $::argv 0] [lindex $::argv 1] [lindex $::argv 2]} err]} {
        set f [open $::LOG a]; puts $f "ERROR: $err\n$::errorInfo"; close $f
        exit 2
    }
}
