# composer.tcl (P08-T08): Send and Stop in one cell, growth, placeholders,
# Return while busy, the draft. Adopts cards' composer-1.
# Run by tests/test_tk_composer.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched theme composer
::vmdai::theme::init light
wm geometry . 560x240

# The status bar is plan 08's T09 module; here a stub records flashes.
namespace eval ::vmdai::statusbar {}
proc ::vmdai::statusbar::flash {text ms} { lappend ::flashes [list $text $ms] }

set ::sent {}
set ::stops 0
set ::flashes {}
set C [::vmdai::composer::create .cb \
    -onsend [list apply {{s} {lappend ::sent $s}}] \
    -onstop [list apply {{} {incr ::stops; ::vmdai::composer::set_mode stopping}}]]
pack .cb -side bottom -fill x
update
set T $::vmdai::composer::T
set MOD [expr {[tk windowingsystem] eq "aqua" ? "⌘" : "Ctrl+"}]

proc fresh {{m idle}} {
    set ::sent {}
    set ::stops 0
    set ::flashes {}
    ::vmdai::composer::set_text ""
    ::vmdai::composer::set_mode $m
    update
}
proc managed {w} { return [expr {[winfo manager $w] ne ""}] }
proc ph_shown {} { return [expr {[winfo manager $::T.ph] eq "place"}] }

test composer-1 {Send becomes Stop while running; the placeholder explains queueing; Stop then reads Stopping…} -body {
    fresh idle
    set r [list [managed $C.act.send] [managed $C.act.stop]]
    ::vmdai::composer::set_mode busy
    update
    lappend r [managed $C.act.send] [managed $C.act.stop] \
        [string match "Reply once this run finishes*" [$T.ph cget -text]] [$C.act.stop cget -takefocus]
    ::vmdai::composer::_stop_clicked
    ::vmdai::composer::_stop_clicked
    lappend r $::stops [$C.act.stop itemcget label -text]
    ::vmdai::composer::set_mode idle
    update
    lappend r [managed $C.act.send] [managed $C.act.stop]
} -result {1 0 0 1 1 1 1 Stopping… 1 0}

test test_grows_1_to_6 {the input grows from 1 to 6 display lines, counting wrapped lines, and shrinks back} -body {
    fresh
    set r {}
    foreach n {1 2 3 6 9} {
        set lines {}
        for {set i 1} {$i <= $n} {incr i} { lappend lines "line $i" }
        ::vmdai::composer::set_text [join $lines "\n"]
        update
        lappend r [$T cget -height]
    }
    ::vmdai::composer::set_text [string repeat "wrap me " 40]
    update
    lappend r [expr {[$T cget -height] > 1}]
    ::vmdai::composer::set_text ""
    update
    lappend r [$T cget -height] [expr {[winfo reqheight $C.field] == [winfo reqheight $T] + 16}]
} -result {1 2 3 6 6 1 1 1}

test test_return_busy_noop {Return while busy sends nothing, keeps the draft and flashes "Press Esc to stop"; idle Return sends; blank never sends} -body {
    fresh busy
    ::vmdai::composer::set_text "follow-up"
    ::vmdai::composer::_on_return
    set r [list $::sent [::vmdai::composer::get_text] $::flashes]
    ::vmdai::composer::set_mode idle
    ::vmdai::composer::_newline
    lappend r [expr {[::vmdai::composer::get_text] eq "follow-up\n"}]
    ::vmdai::composer::_on_return
    lappend r [llength $::sent] [expr {[lindex $::sent 0] eq "follow-up\n"}]
    ::vmdai::composer::set_text "   "
    ::vmdai::composer::_on_return
    lappend r [llength $::sent] [$C.act.send instate disabled] [$C.act.send cget -default]
    ::vmdai::composer::set_text "go"
    lappend r [$C.act.send instate disabled] [$C.act.send cget -default]
} -result {{} follow-up {{{Press Esc to stop} 2000}} 1 1 1 1 1 normal 0 active}

test test_draft_survives {the draft survives busy, stopping, a disconnect and nomodel; the input stays editable; Send is off unless idle} -body {
    fresh
    ::vmdai::composer::set_text "half-typed prompt"
    set drafts {}
    set states {}
    set send {}
    foreach m {busy stopping disabled nomodel idle} {
        ::vmdai::composer::set_mode $m
        update
        lappend drafts [::vmdai::composer::get_text]
        lappend states [$T cget -state]
        if {[managed $C.act.send]} { lappend send $m [$C.act.send instate disabled] }
    }
    for {set i 0} {$i < 60} {incr i} { ::vmdai::composer::push_history "p$i" }
    list [lsort -unique $drafts] [lsort -unique $states] $send [::vmdai::composer::get_text] \
        [llength $::vmdai::composer::history] [lindex $::vmdai::composer::history 0]
} -result {{{half-typed prompt}} normal {disabled 1 nomodel 1 idle 0} {half-typed prompt} 50 p10}

test test_placeholders {one placeholder per mode, shown only while the draft is empty, never part of the text} -body {
    fresh
    set r {}
    foreach m {idle busy stopping nomodel disabled} {
        ::vmdai::composer::set_mode $m
        lappend r [$T.ph cget -text]
    }
    ::vmdai::composer::set_mode idle
    update
    lappend r [ph_shown] [::vmdai::composer::get_text]
    ::vmdai::composer::set_text "x"
    lappend r [ph_shown]
    ::vmdai::composer::set_text ""
    lappend r [ph_shown]
} -result [list "Ask VMD to load, show or measure something…" \
    "Reply once this run finishes — or press Esc to stop" \
    "Reply once this run finishes — or press Esc to stop" \
    "Set up a model to start — $MOD," \
    "Ask VMD to load, show or measure something…" 1 {} 0 1]

cleanupTests
exit
