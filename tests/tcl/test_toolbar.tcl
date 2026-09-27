# toolbar.tcl (P08-T10): icons, title, the ⋯ menu, tooltips, busy state.
# Run by tests/test_tk_toolbar.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched theme toolbar
::vmdai::theme::init light
set ::vmdai::toolbar::opt(tip_map) 0
wm geometry . 560x120

set ::actions {}
proc record {args} { lappend ::actions $args }
::vmdai::toolbar::create .tb -onaction record
pack .tb -side top -fill x
update
set M .tb.more.m
set KEY [expr {[tk windowingsystem] eq "aqua" ? "⌘" : "Ctrl+"}]

proc fresh {} {
    set ::actions {}
    ::vmdai::toolbar::set_busy 0
    ::vmdai::toolbar::_tip_leave
    update
}
proc glyph_colour {w} { return [$w itemcget [lindex [$w find withtag glyph] 0] -fill] }

test test_menu_items {the ⋯ menu lists the V4 items in order; each runs its action; the check item toggles expand} -body {
    fresh
    set items [::vmdai::toolbar::menu_items]
    for {set i 0} {$i <= [$M index end]} {incr i} {
        if {[$M type $i] ne "separator"} { $M invoke $i }
    }
    namespace eval ::vmdai::transcript { variable expand_all 0 }
    ::vmdai::toolbar::_sync_menu
    $M invoke [$M index "Expand all steps"]
    list $items $::actions [$M entrycget [$M index "New chat"] -accelerator] [$M type [$M index "Expand all steps"]]
} -result [list {{{New chat} new_chat} {History… open_history} - {{Copy chat Tcl} copy_chat_tcl} {{Save chat .tcl…} save_chat_tcl} - {{Open runs folder} open_runs_folder} - {{Expand all steps} set_expand_all} {{Collapse older runs} collapse_older} - {Settings… open_settings} {{Open runtime log} open_log} {{Quit AI runtime} quit_runtime}} \
    {new_chat open_history copy_chat_tcl save_chat_tcl open_runs_folder {set_expand_all 1} collapse_older open_settings open_log quit_runtime {set_expand_all 1}} \
    [expr {[tk windowingsystem] eq "aqua" ? "Command-N" : "Control-N"}] checkbutton]

test icons-keys {icons take focus and run their action on click, Space and Return} -body {
    fresh
    set r {}
    foreach w {.tb.new .tb.hist .tb.gear .tb.more} { lappend r [$w cget -takefocus] }
    foreach w {.tb.new .tb.hist .tb.gear} {
        foreach seq {<ButtonRelease-1> <space> <Return>} { uplevel #0 [bind $w $seq] }
    }
    list $r [lsort -unique $::actions] [llength $::actions]
} -result {{1 1 1 1} {new_chat open_history open_settings} 9}

test test_tooltips_600ms {a tooltip shows 600 ms after the pointer enters, not before; leaving hides it} -body {
    fresh
    set t0 [clock milliseconds]
    ::vmdai::toolbar::_tip_enter .tb.new
    after 450
    update
    set r [list [expr {[clock milliseconds] - $t0 < 600 ? [::vmdai::toolbar::tip_shown] : ""}]]
    after 200
    update
    lappend r [::vmdai::toolbar::tip_shown] [.vmd_ai_tip.l cget -text] [wm state .vmd_ai_tip]
    ::vmdai::toolbar::_tip_leave
    lappend r [::vmdai::toolbar::tip_shown] [llength [::vmdai::sched::pending]]
    label .other
    ::vmdai::toolbar::tooltip .other "Anything"
    ::vmdai::toolbar::_tip_show .other
    lappend r [.vmd_ai_tip.l cget -text]
    destroy .other
    set r
} -result [list {} .tb.new "New chat (${KEY}N)" withdrawn {} 0 Anything]

test test_disabled_while_busy {while a request runs, New chat and History are dimmed, ignore clicks and are off in the menu} -body {
    fresh
    ::vmdai::toolbar::set_busy 1
    foreach w {.tb.new .tb.hist .tb.gear} { uplevel #0 [bind $w <ButtonRelease-1>] }
    set r [list $::actions [$M entrycget 0 -state] [$M entrycget 1 -state] \
        [expr {[glyph_colour .tb.new] eq [::vmdai::theme::c faint]}] \
        [expr {[glyph_colour .tb.more] eq [::vmdai::theme::c muted]}]]
    ::vmdai::toolbar::set_busy 0
    uplevel #0 [bind .tb.new <ButtonRelease-1>]
    lappend r $::actions [$M entrycget 0 -state] [expr {[glyph_colour .tb.new] eq [::vmdai::theme::c muted]}]
} -result {open_settings disabled disabled 1 1 {open_settings new_chat} normal 1}

test title-fit {the title is centred, ellipsized to fit, and a short one is left alone} -body {
    fresh
    ::vmdai::toolbar::set_title "Load 1HCK"
    set r [list [.tb.title cget -text]]
    ::vmdai::toolbar::set_title [string repeat "a very long chat title " 12]
    set shown [.tb.title cget -text]
    lappend r [string match *… $shown] [expr {[font measure ChatMetaBold $shown] <= [winfo width .tb] - 152}] \
        [.tb.title cget -anchor]
} -result {{Load 1HCK} 1 1 center}

cleanupTests
exit
