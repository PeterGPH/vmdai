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
