# Headless tcltest for the Chat Cards reference implementation (window withdrawn).
# Run: capture_locked.sh <this file>   (loads VMD's Tk 8.6 into tclsh; no screenshot)
package require tcltest
namespace import ::tcltest::*
set here [file dirname [file normalize [info script]]]
::tcltest::configure -outfile $here/test_proto.out -errfile $here/test_proto.out -verbose {pass fail error}
wm withdraw .
set ::cv_lib_only 1
source $here/proto.tcl
::cv::theme::use light
::cv::fonts::init
wm geometry . 560x780
::cv::app::build
update idletasks
set X $::cv::tr::X

proc tagtext {tag} {
    set out {}
    foreach {a b} [$::cv::tr::X tag ranges $tag] { lappend out [$::cv::tr::X get $a $b] }
    return $out
}

test hl-1 {Tcl highlighter classifies commands, brackets and variables} -body {
    ::cv::hl::tokens {set sel [atomselect top protein]}
} -result {set cmd { } plain sel plain { } plain {[} br atomselect cmd { } plain top plain { } plain protein plain \] br}

test hl-2 {variables and numbers} -body {
    ::cv::hl::tokens {mol delrep 0 $molid}
} -result {mol cmd { } plain delrep plain { } plain 0 num { } plain {$molid} var}

test md-1 {bullets, bold and unbreakable inline code become tags} -body {
    ::cv::md::render end "- **Protein** — NewCartoon\n\nThe Rg is **20.84 Å**. Call `measure rgyr`:"
    list [tagtext md_b] [tagtext md_code] [llength [$X tag ranges md_li]]
} -result [list {Protein {20.84 Å}} [list "measure rgyr"] 2]

test md-2 {fenced block becomes a code card item with its source} -body {
    ::cv::md::render end "```tcl\nset sel \[atomselect top protein\]\nmeasure rgyr \$sel\n```"
    set c [lindex $::cv::tr::items end]
    list $::cv::tr::item($c,kind) [::cv::tr::getd $c lang] [llength [split [::cv::tr::getd $c code] \n]]
} -result {code tcl 2}

test ro-1 {transcript proxy ignores edits from bindings but stays focusable} -body {
    set before [$X get 1.0 end]
    .tr insert end "INJECTED"
    .tr delete 1.0 end
    list [expr {[$X get 1.0 end] eq $before}] [.tr cget -takefocus]
} -result {1 1}

test group-1 {finished run collapses and elides its steps; chips keep status} -body {
    ::cv::tr::step_start s1 run_vmd_command "Load" "mol new 1hck.pdb"
    ::cv::tr::step_result s1 1 0 0.4
    ::cv::tr::step_start s2 run_vmd_command "Bad" "display backgroundcolor white"
    ::cv::tr::step_result s2 0 {invalid command name "display backgroundcolor"} 0.1
    ::cv::tr::note "retrying"
    ::cv::tr::step_start s3 run_vmd_command "Fix" "color Display Background white"
    ::cv::tr::step_result s3 1 "" 0.1
    set gid $::cv::tr::G(cur)
    ::cv::tr::group_end "3.2 s"
    set st {}
    foreach c $::cv::tr::G($gid,steps) { lappend st [::cv::tr::getd $c status] }
    list $st $::cv::tr::G($gid,collapsed) [$X tag cget $gid.body -elide] [llength $::cv::tr::G($gid,items)]
} -result {{ok fail ok} 1 1 4}

test group-2 {a run that ends on a failure stays expanded} -body {
    ::cv::tr::step_start s9 run_vmd_command "Bad" "nope"
    ::cv::tr::step_result s9 0 {invalid command name "nope"} 0.1
    set gid $::cv::tr::G(cur)
    ::cv::tr::group_end "1.0 s"
    list $::cv::tr::G($gid,collapsed) [$X tag cget $gid.body -elide]
} -result {0 0}

test group-3 {appends after a group land below it, steps insert inside it} -body {
    set gid [::cv::tr::group_begin]
    ::cv::tr::step_start t1 run_vmd_command "One" "puts 1"
    ::cv::tr::assistant_markdown "AFTER"
    ::cv::tr::step_start t2 run_vmd_command "Two" "puts 2"
    set c2 $::cv::tr::S(t2)
    expr {[$X compare [$X index $c2] < [lindex [$X tag ranges md_p] end]]}
} -result 1

test thumb-1 {snapshot thumbnail: 3:2 centre crop, integer subsample to fit} -body {
    set t [::cv::img::thumb $::cv::SNAP 258]
    list [image width $t] [image height $t]
} -result {256 171}

test thumb-2 {undecodable image degrades to "" (Tk 8.5 path)} -body {
    ::cv::img::thumb /nonexistent/x.png 258
} -result {}

test composer-1 {Send becomes Stop while running; placeholder explains queueing} -body {
    ::cv::app::set_running 1 "Step 4 · running VMD command · 00:12"
    set r [list $::cv::app::S(running) [string match "Reply once*" $::cv::app::S(placeholder)]]
    ::cv::app::set_running 0
    lappend r $::cv::app::S(running)
} -result {1 1 0}

test offline-1 {offline shows exactly one banner and disables send} -body {
    ::cv::app::set_offline 1
    set r [list [winfo manager .ban] $::cv::app::S(offline)]
    ::cv::app::set_offline 0
    lappend r [winfo manager .ban]
} -result {grid 1 {}}

test theme-1 {dark palette swaps tokens; every item re-renders without error} -body {
    ::cv::theme::use dark
    ::cv::tr::config_tags
    ::cv::tr::relayout
    set r [list [::cv::c bg] [$X cget -bg]]
    ::cv::theme::use light
    set r
} -result [list #1A1C20 #1A1C20]

cleanupTests
exit
