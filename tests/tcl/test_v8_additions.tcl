# P10-T06: final Tk goldens and the V8 additions (Part B V8; Part A section 6
# "Tk golden transcripts").  Dumps are written to $M3_OUT; the pytest wrapper
# tests/test_tk_v8_additions.py compares them with tests/fixtures/tk/.
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
source [file join $env(VMDAI_REPO) tests tcl m3_helpers.tcl]
::harness::stub_bridge
::harness::stub_desktop

namespace eval ::v8 {
    variable dark_dump ""
    variable dark_colours ""
}

# with ev key value -> ev with metadata.key set to value.
proc ::v8::with {ev key value} {
    dict set ev metadata $key $value
    return $ev
}

# first name kind -> the first event of fixture name whose metadata.kind is kind.
proc ::v8::first {name kind} {
    foreach ev [::m3::events $name] {
        if {![catch {dict get $ev metadata kind} k] && $k eq $kind} {
            return $ev
        }
    }
    error "$name has no $kind event"
}

# last_final evs -> the index of the last assistant message with final true.
proc ::v8::last_final {evs} {
    set last -1
    set i 0
    foreach ev $evs {
        if {[dict get $ev role] eq "assistant" && [dict get $ev type] eq "message"
                && ![catch {dict get $ev metadata final} f] && [string is true -strict $f]} {
            set last $i
        }
        incr i
    }
    return $last
}

# replay_03 -> 03_conversation through the panel with step 1's detail open,
# so a dump holds rendered Markdown, the usage lines and syntax colours.
proc ::v8::replay_03 {} {
    set t [::m3::replay 03_conversation]
    ::vmdai::transcript::toggle_detail [::m3::call_key_of 03_conversation 1]
    ::harness::settle
    return $t
}

# golden name -> replay fixture name in Light and write its portable dump.
proc ::v8::golden {name} {
    ::m3::use_mws
    ::m3::save_appearance light
    ::m3::replay $name
    set d [::m3::portable [::vmdai::transcript::dump]]
    ::m3::write_dump $name $d
    return [list [::vmdai::theme::mode] [regexp {^images [0-9]+\n} $d]]
}

# snapshot_request n png -> one request with n snapshot steps, cloned from
# 03_conversation's first request and its snapshot (call 4); every image
# (path and thumbnail) is png.
proc ::v8::snapshot_request {n png} {
    set k [::m3::call_key_of 03_conversation 4]
    set rid req_000000000555
    foreach ev [::m3::events 03_conversation] {
        if {[catch {dict get $ev metadata kind} kind]} {
            continue
        }
        if {$kind in {request.started request.finished} && ![info exists got($kind)]} {
            set got($kind) [with $ev request_id $rid]
        } elseif {$kind in {tool.started tool.finished} && [dict get $ev metadata call_key] eq $k} {
            set got($kind) [with $ev request_id $rid]
        }
    }
    dict set got(tool.finished) metadata image path $png
    dict set got(tool.finished) metadata image thumb_path $png
    set out [list $got(request.started)]
    for {set i 1} {$i <= $n} {incr i} {
        set key [format 9%011d $i]
        lappend out [with $got(tool.started) call_key $key] [with $got(tool.finished) call_key $key]
    }
    lappend out $got(request.finished)
    return $out
}

# ---- goldens for the three scenarios plan 08 left without one --------------

test v8-golden-loop_guard {loop_guard through the panel: nudge, stop, wrap-up, usage line} -body {
    ::v8::golden loop_guard
} -result {light 1}

test v8-golden-turn_retry {turn_retry through the panel: the retried partial block is gone} -body {
    ::v8::golden turn_retry
} -result {light 1}

test v8-golden-11_dead_runtime {11_dead_runtime through the panel: connection notices, no footer} -body {
    ::v8::golden 11_dead_runtime
} -result {light 1}

# ---- 03_conversation in Dark --------------------------------------------------

test v8-dark-fresh {03_conversation opened with Appearance Dark: dark tokens everywhere} -setup {
    ::m3::use_mws
    ::m3::save_appearance dark
} -body {
    set t [::v8::replay_03]
    set ::v8::dark_dump [::m3::portable [::vmdai::transcript::dump]]
    set ::v8::dark_colours [::m3::colour_section $t]
    ::m3::write_dump 03_conversation_dark [::m3::with_colours $::v8::dark_dump $::v8::dark_colours]
    list [::vmdai::theme::mode] [$t cget -background] [$t tag cget syn_cmd -foreground] \
        [$t tag cget md_code -background] [::m3::light_left [list $::vmdai::panel::win]]
} -cleanup {
    ::m3::save_appearance light
} -result {dark #1e1e1e #79c0ff #313135 {}}

test v8-dark-same_text {Dark changes colours only: the Light dump is the same text} -setup {
    ::m3::use_mws
    ::m3::save_appearance light
} -body {
    ::v8::replay_03
    list [::vmdai::theme::mode] [::m3::line_diff [::m3::portable [::vmdai::transcript::dump]] $::v8::dark_dump]
} -result {light {}}

# Continues from the Light panel v8-dark-same_text left open.
test v8-dark-switch_matches_fresh {switching that Light panel to Dark gives exactly the fresh Dark tags and text} -body {
    ::vmdai::theme::set_appearance dark
    ::vmdai::transcript::relayout
    ::harness::settle
    list [::m3::line_diff [::m3::colour_section $::vmdai::panel::text] $::v8::dark_colours] \
        [::m3::line_diff [::m3::portable [::vmdai::transcript::dump]] $::v8::dark_dump]
} -cleanup {
    ::vmdai::theme::set_appearance light
} -result {{} {}}

# ---- the V8 "Add" list, re-run on the finished M3 panel -----------------------

test v8-add-unknown_call_key {V8 add: an unknown call_key, a repeated tool.started and a second tool.finished change nothing} -setup {
    ::m3::use_mws
    ::m3::save_appearance dark
    ::v8::replay_03
    set before [::vmdai::transcript::dump]
} -body {
    set errs {}
    foreach ev [list \
            [::v8::with [::v8::first 03_conversation tool.finished] call_key ffffffffffff] \
            [::v8::first 03_conversation tool.started] \
            [::v8::first 03_conversation tool.finished]] {
        if {[catch {::m3::render $ev} err]} {
            lappend errs $err
        }
    }
    ::harness::settle
    list $errs [expr {[::vmdai::transcript::dump] eq $before}] [::vmdai::theme::mode]
} -cleanup {
    ::m3::save_appearance light
} -result {{} 1 dark}

test v8-add-failing_statement_dark {V8 add: in Dark, err_bg marks the executor's failing statement, under syntax colours} -setup {
    ::m3::use_mws
    ::m3::save_appearance dark
    set t [::v8::replay_03]
    set k [::m3::call_key_of 03_conversation 2]
    # A failed multi-statement step opens by itself (V4); open it if a
    # collapse closed it.
    if {![llength [$t tag ranges detail:$k]]} {
        ::vmdai::transcript::toggle_detail $k
        ::harness::settle
    }
} -body {
    set stmts [dict get [::vmdai::executor::split_statements \
        "color Display Background white\ndisplay backgroundcolor white"] statements]
    set err ""
    foreach tag [$t tag names] {
        if {[catch {$t tag cget $tag -background} bg] || $bg ne [::vmdai::theme::c err_bg]} {
            continue
        }
        foreach {a b} [$t tag ranges $tag] {
            if {"detail:$k" in [$t tag names $a]} {
                append err [$t get $a $b]
            }
        }
    }
    set syn {}
    foreach {a b} [$t tag ranges syn_cmd] {
        if {"dcmd:$k" in [$t tag names $a]} {
            lappend syn [$t get $a $b]
        }
    }
    list [expr {[string first [string trim [lindex $stmts 1]] $err] >= 0}] \
        [expr {[string first [string trim [lindex $stmts 0]] $err] < 0}] $syn [::vmdai::theme::c err_bg]
} -cleanup {
    ::m3::save_appearance light
} -result {1 1 {color display} #3a1f1e}

test v8-add-photo_cap_after_switch {V8 add: at most 30 images stay loaded, also after a Dark switch and a relayout} -setup {
    ::m3::use_mws
    ::m3::save_appearance light
    ::harness::fresh_panel
    set png [file join $::env(HOME) v8_thumb.png]
    set img [image create photo -width 64 -height 48]
    $img put #336699 -to 0 0 64 48
    $img put #ffcc00 -to 16 12 48 36
    $img write $png -format png
    image delete $img
} -body {
    foreach ev [::v8::snapshot_request 32 $png] {
        ::m3::render $ev
    }
    ::harness::settle
    set n1 [::vmdai::transcript::loaded_image_count]
    ::vmdai::theme::set_appearance dark
    ::vmdai::transcript::relayout
    ::harness::settle
    set n2 [::vmdai::transcript::loaded_image_count]
    list [expr {$n1 > 0 && $n1 <= 30}] [expr {$n2 > 0 && $n2 <= 30}]
} -cleanup {
    ::vmdai::theme::set_appearance light
} -result {1 1}

# The last two cases need real geometry, so the transcript is created in the
# withdrawn root window (plan constraint) and fed by its own view-model.
test v8-add-sticky_on_seal {V8 add: a scrolled-up view stays put while the final answer is sealed and rendered} -setup {
    ::m3::use_mws
    ::vmdai::theme::set_appearance light
    set t [::m3::root_transcript 560x240]
    set evs [::m3::events 03_conversation]
    set last [::v8::last_final $evs]
    ::m3::feed [lrange $evs 0 [expr {$last - 1}]]
    ::harness::settle
    $t yview moveto 0.0
    ::harness::settle
    set before [$t yview]
} -body {
    ::m3::feed [lrange $evs $last end]
    ::harness::settle
    list [lindex $before 0] [expr {[lindex $before 1] < 1.0}] [lindex [$t yview] 0] \
        [string match {*20.84*} [lindex [::m3::ranges_text $t md_p] end]]
} -cleanup {
    ::harness::settle
    destroy .m3tx
} -result {0.0 1 0.0 1}

test v8-add-inline_code_nowrap {V8 add: the inline code in loop_guard's wrap-up never wraps, 380 to 560 px} -setup {
    ::m3::use_mws
    ::vmdai::theme::set_appearance light
    set t [::m3::root_transcript 380x700]
    ::m3::feed [::m3::events loop_guard]
    ::harness::settle
} -body {
    set spans {}
    set wrapped {}
    set para_wraps 0
    for {set w 380} {$w <= 560} {incr w 20} {
        wm geometry . ${w}x700
        update
        ::vmdai::transcript::relayout
        ::harness::settle
        foreach {a b} [$t tag ranges md_code] {
            set s [::vmdai::md::plain_text [$t get $a $b]]
            lappend spans $s
            if {[$t count -update -displaylines $a "$b - 1c"] != 0} {
                lappend wrapped $w:$s
            }
        }
        if {$w == 380} {
            # The paragraph itself wraps at 380 px, so the sweep moves the
            # spans across line ends.
            set first [lindex [$t tag ranges md_code] 0]
            set para_wraps [expr {[$t count -update -displaylines "$first linestart" "$first lineend"] > 0}]
        }
    }
    list [lsort -unique $spans] $wrapped $para_wraps
} -cleanup {
    ::harness::settle
    destroy .m3tx
} -result {{ResType {mol modcolor 0 top ResType} {mol modcolor 0 top ResidueType}} {} 1}

cleanupTests
