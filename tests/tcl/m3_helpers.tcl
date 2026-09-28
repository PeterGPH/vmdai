# tests/tcl/m3_helpers.tcl - shared helpers for the plan-10 (M3) Tk tests and
# the P10-T07 capture tool.  Source it after tests/tcl/panel_harness.tcl.
#
#   ::m3::mws args            recording stand-in for MacWindowStyle
#   ::m3::use_mws             install it; "isdark" answers $::m3::os_dark
#   ::m3::events name         envelopes of tests/fixtures/events/<name>.jsonl
#   ::m3::replay name ?upto?  fresh headless panel, events 0..upto rendered
#   ::m3::ev ... / render ev  one synthetic §2c event through the panel
#   ::m3::call_key_of name n  call_key of the n-th tool.started of a fixture
#   ::m3::root_text ?geom?    a Text packed in "." (real size while withdrawn)
#   ::m3::colours roots       every #rrggbb on widgets, tags, items, styles
#   ::m3::colour_section t / write_dump name text   golden dumps

namespace eval ::m3 {
    variable os_dark 0
    variable mws_calls {}
    variable m2_tokens {}
}

proc ::m3::mws {args} {
    variable mws_calls
    variable os_dark
    lappend mws_calls $args
    if {[lindex $args 0] eq "isdark"} {
        return $os_dark
    }
    return ""
}

proc ::m3::use_mws {} {
    set ::m3::os_dark 0
    set ::m3::mws_calls {}
    set ::vmdai::theme::macstyle ::m3::mws
}

# The fixture's @REPO@/@WORK@ placeholders become this checkout and $HOME.
proc ::m3::events {name} {
    set esc [list "\\" "\\\\" "\"" "\\\""]
    set repo [string map $esc $::env(VMDAI_REPO)]
    set work [string map $esc $::env(HOME)]
    set fh [open [file join $::env(VMDAI_REPO) tests fixtures events $name.jsonl] r]
    fconfigure $fh -encoding utf-8
    set out {}
    while {[gets $fh line] >= 0} {
        if {[string trim $line] eq ""} {
            continue
        }
        lappend out [::json::json2dict [string map [list @REPO@ $repo @WORK@ $work] $line]]
    }
    close $fh
    return $out
}

proc ::m3::render {ev} {
    ::vmdai::panel::render [::vmdai::vm::apply ::vmdai::panel::vm $ev]
}

proc ::m3::replay {name {upto end}} {
    ::harness::fresh_panel
    foreach ev [lrange [events $name] 0 $upto] {
        render $ev
    }
    ::harness::settle
    return $::vmdai::panel::text
}

proc ::m3::ev {role type text meta} {
    return [dict create seq 0 ts 1790208000.0 role $role type $type text $text \
        metadata [dict merge [dict create v 2] $meta]]
}

proc ::m3::call_key_of {name n} {
    set i 0
    foreach ev [events $name] {
        set meta [dict get $ev metadata]
        if {[dict exists $meta kind] && [dict get $meta kind] eq "tool.started" && [incr i] == $n} {
            return [dict get $meta call_key]
        }
    }
    error "$name has fewer than $n tool.started events"
}

# Only "." gets its real size while withdrawn (a withdrawn child toplevel
# stays 1x1 on aqua), so wrapping and tab-stop checks use a Text in ".".
proc ::m3::root_text {{geom 560x780}} {
    foreach w [winfo children .] {
        if {[winfo toplevel $w] eq "."} {
            destroy $w
        }
    }
    wm geometry . $geom
    text .m3md -wrap word -font ChatBody -padx 20 -pady 14 -width 10 -height 10 \
        -background [::vmdai::theme::c surface] -foreground [::vmdai::theme::c text]
    pack .m3md -fill both -expand 1
    ::harness::settle
    return .m3md
}

proc ::m3::ranges_text {t tag} {
    set out {}
    foreach {a b} [$t tag ranges $tag] {
        lappend out [$t get $a $b]
    }
    return $out
}

proc ::m3::_colour_entries {where specs} {
    set out {}
    foreach s $specs {
        if {[llength $s] == 5 && [regexp {^#[0-9a-fA-F]{6}$} [lindex $s 4]]} {
            lappend out [list "$where [lindex $s 0]" [string tolower [lindex $s 4]]]
        }
    }
    return $out
}

# colours roots -> {where value} for every #rrggbb on the widgets, text tags,
# canvas items and ChatVMD.* styles of the toplevels in roots.
proc ::m3::colours {roots} {
    set out {}
    set styles {}
    foreach top $roots {
        foreach w [::vmdai::theme::_subtree $top] {
            if {![catch {$w configure} specs]} {
                set out [concat $out [_colour_entries $w $specs]]
            }
            switch -- [winfo class $w] {
                Text {
                    foreach tag [$w tag names] {
                        set out [concat $out [_colour_entries "$w tag:$tag" [$w tag configure $tag]]]
                    }
                }
                Canvas {
                    foreach id [$w find all] {
                        set out [concat $out [_colour_entries "$w item:$id" [$w itemconfigure $id]]]
                    }
                }
            }
            if {![catch {$w cget -style} st] && [string match ChatVMD.* $st]
                    && [lsearch -exact $styles $st] < 0} {
                lappend styles $st
            }
        }
    }
    foreach st $styles {
        foreach {opt val} [ttk::style configure $st] {
            if {[regexp {^#[0-9a-fA-F]{6}$} $val]} {
                lappend out [list "style:$st $opt" [string tolower $val]]
            }
        }
    }
    return $out
}

# Light values that differ from their dark value and are no dark value at all.
proc ::m3::light_only {} {
    set p $::vmdai::theme::PALETTE
    set darkvals [dict values [dict get $p dark]]
    set out {}
    dict for {tok v} [dict get $p light] {
        if {$v ne [dict get $p dark $tok] && [lsearch -exact $darkvals $v] < 0} {
            lappend out $v
        }
    }
    return [lsort -unique $out]
}

# repaint_report before after -> {moved left notdark}: how many light-only
# colours `before` had, the places still light-only after, and the moved
# places whose new value is not a dark palette colour.
proc ::m3::repaint_report {before after} {
    set lo [light_only]
    set dv [lsort -unique [dict values [dict get $::vmdai::theme::PALETTE dark]]]
    set moved {}
    foreach e $before {
        if {[lsearch -exact $lo [lindex $e 1]] >= 0} {
            lappend moved [lindex $e 0]
        }
    }
    set left {}
    foreach e $after {
        if {[lsearch -exact $lo [lindex $e 1]] >= 0} {
            lappend left [lindex $e 0]
        }
    }
    set notdark {}
    foreach k $moved {
        set i [lsearch -exact -index 0 $after $k]
        if {$i < 0 || [lsearch -exact $dv [lindex $after $i 1]] < 0} {
            lappend notdark $k
        }
    }
    return [list [llength $moved] $left $notdark]
}

proc ::m3::colour_section {t} {
    set lines {}
    foreach tag [lsort [$t tag names]] {
        if {$tag eq "sel"} {
            continue
        }
        foreach opt {-foreground -background -lmargincolor -rmargincolor} {
            if {[catch {$t tag cget $tag $opt} v] || $v eq ""} {
                continue
            }
            lappend lines "$tag $opt $v"
        }
    }
    return "# tag colours\n[join $lines \n]\n"
}

proc ::m3::write_dump {name text} {
    set fh [open [file join $::env(M3_OUT) $name.txt] w]
    fconfigure $fh -encoding utf-8 -translation lf
    puts -nonewline $fh $text
    close $fh
}

# The tokens M2's theme defines, before any set_appearance adds M3's.
if {![llength $::m3::m2_tokens]} {
    ::vmdai::theme::init light
    set ::m3::m2_tokens [lsort [array names ::vmdai::theme::T]]
}

# ---- P10-T06 (also used by docs/design/round1/tools/capture_panel.tcl) --------

# save_appearance a ?geom?: plugin.json with Appearance a, read by the next
# ::vmdai::panel::build (P10-T01 applies it there).
proc ::m3::save_appearance {a {geom 560x780}} {
    ::vmdai::config::save_plugin_settings [dict create version 1 python "" appearance $a \
        expand_steps 0 geometry $geom]
}

# index_of events kind n -> the index of the n-th event whose metadata.kind is kind.
proc ::m3::index_of {events kind n} {
    set i 0
    set seen 0
    foreach ev $events {
        if {![catch {dict get $ev metadata kind} k] && $k eq $kind && [incr seen] == $n} {
            return $i
        }
        incr i
    }
    error "fewer than $n $kind events"
}

# portable text -> text with this checkout and $HOME written as the fixture
# placeholders @REPO@ and @WORK@ (::m3::events did the reverse), longest
# path first, so goldens do not depend on temp directories.
proc ::m3::portable {text} {
    set pairs {}
    foreach {path ph} [list $::env(VMDAI_REPO) @REPO@ $::env(HOME) @WORK@] {
        foreach p [lsort -unique [list $path [file normalize $path]]] {
            lappend pairs [list $p $ph]
        }
    }
    set map {}
    foreach pair [lsort -decreasing -command ::m3::_by_length $pairs] {
        lappend map {*}$pair
    }
    return [string map $map $text]
}

proc ::m3::_by_length {a b} {
    return [expr {[string length [lindex $a 0]] - [string length [lindex $b 0]]}]
}

# with_colours dump colours -> the dump, a newline if it lacks one, then colours.
proc ::m3::with_colours {dump colours} {
    if {$dump ne "" && [string index $dump end] ne "\n"} {
        append dump "\n"
    }
    return $dump$colours
}

# line_diff a b -> {} when a eq b, else up to five "line N: <a> | <b>".
proc ::m3::line_diff {a b} {
    set la [split $a "\n"]
    set lb [split $b "\n"]
    set n [expr {max([llength $la], [llength $lb])}]
    set out {}
    for {set i 0} {$i < $n && [llength $out] < 5} {incr i} {
        if {[lindex $la $i] ne [lindex $lb $i]} {
            lappend out "line [expr {$i + 1}]: [lindex $la $i] | [lindex $lb $i]"
        }
    }
    return $out
}

# light_left roots -> the places under roots that still hold a light-only colour.
proc ::m3::light_left {roots} {
    set lo [light_only]
    set left {}
    foreach e [colours $roots] {
        if {[lsearch -exact $lo [lindex $e 1]] >= 0} {
            lappend left [lindex $e 0]
        }
    }
    return $left
}

# root_transcript ?geom? -> the Text of a transcript created in the withdrawn
# root window "." (real size while withdrawn, unlike the panel's toplevel),
# with a fresh view-model ::m3::vm for ::m3::feed.  It replaces the panel's
# transcript (one per interpreter), so the next ::m3::replay rebuilds it.
# A panel left over from an earlier ::m3::replay is a *toplevel* child of ".",
# so the plain child-window sweep below never reaches it; dispose of it first
# (::harness::fresh_panel's own cleanup) or its loaded images and timers sit
# around for the rest of the process and make every later ``update``/settle
# far slower.
proc ::m3::root_transcript {{geom 560x780}} {
    catch {::vmdai::panel::dispose}
    foreach top {.vmd_ai .vmd_ai_settings .vmd_ai_history} {
        if {[winfo exists $top]} {
            destroy $top
        }
    }
    foreach w [winfo children .] {
        if {[winfo toplevel $w] eq "."} {
            destroy $w
        }
    }
    wm geometry . $geom
    set t [::vmdai::transcript::create .m3tx]
    pack .m3tx -fill both -expand 1
    ::vmdai::vm::init ::m3::vm
    update idletasks
    update
    ::vmdai::transcript::relayout
    update
    return $t
}

# feed events: events through ::m3::vm into the root transcript.  Status ops
# go to the status bar in the panel, so they are dropped here.
proc ::m3::feed {events} {
    foreach ev $events {
        set ops {}
        foreach op [::vmdai::vm::apply ::m3::vm $ev] {
            if {[lindex $op 0] ne "status"} {
                lappend ops $op
            }
        }
        if {[llength $ops]} {
            ::vmdai::transcript::apply_ops $ops
        }
    }
}
