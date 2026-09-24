# Headless tcltest for the Native Minimal renderer (window withdrawn, never mapped).
#   run: capture_locked.sh proto_test.tcl   (or any tclsh with Tk 8.6)
package require tcltest
namespace import ::tcltest::*
set D [file dirname [file normalize [info script]]]
wm withdraw .
# Tk on macOS swallows stdout from a GUI tclsh, so results go to a file.
::tcltest::configure -verbose {pass error} -outfile /tmp/chatvmd_proto_test.out -errfile /tmp/chatvmd_proto_test.out
set ::argv {}
source $D/proto.tcl
::chatvmd::theme::init light
wm geometry . 560x780
::chatvmd::ui::build
update idletasks
::chatvmd::demo::conversation all
set t [::chatvmd::ui::path .tx.t]

proc rowtext {t id} { $t get "$id.rowend -1l linestart" "$id.rowend -1c" }

test glue-1 {every tool row starts on its own line (no "…text.SYSTEM:" glue)} -body {
    set bad 0
    foreach id {t1 t2 t3 t4 t5} {
        if {[$t compare [lindex [$t tag ranges row:$id] 0] != "[lindex [$t tag ranges row:$id] 0] linestart"]} { incr bad }
    }
    set bad
} -result 0

test status-1 {glyphs reflect metadata.ok} -body {
    lmap id {t1 t2 t3 t4 t5} { $t get [lindex [$t tag ranges glyph:$id] 0] }
} -result {✓ ✗ ✓ ✓ ✓}

test err-1 {failed call shows its error inline, right under the row} -body {
    string trim [$t get t2.rowend "t2.rowend lineend"]
} -result {invalid command name "display backgroundcolor"}

test out-1 {informative output inline, trivial output hidden} -body {
    list [string match "*→ 20.843*" [rowtext $t t4]] [string match "*→*" [rowtext $t t1]]
} -result {1 0}

test md-1 {markdown is rendered, not shown raw} -body {
    set all [$t get 1.0 end]
    list [string first "**" $all] [string first "```" $all] \
        [$t get {*}[lrange [$t tag ranges b] end-1 end]]
} -result {-1 -1 {20.84 Å}}

test md-2 {fenced block lines are tagged code} -body {
    llength [lsearch -all [lmap {a b} [$t tag ranges code] {$t get $a $b}] *measure*]
} -result 1

test expand-1 {row expands to the full command and collapses again} -body {
    ::chatvmd::tx::toggle t1
    set n [expr {[llength [split [string trim [$t get {*}[$t tag ranges detail:t1]]] "\n"]]}]
    ::chatvmd::tx::toggle t1
    list $n [llength [$t tag ranges detail:t1]]
} -result {11 0}

test fit-1 {rows stay one display line at 380 px} -body {
    wm geometry . 380x700; update
    ::chatvmd::tx::relayout; update idletasks
    set wrapped 0
    foreach id {t1 t2 t3 t4 t5} {
        lassign [$t tag ranges row:$id] a b
        if {[$t count -update -displaylines $a "$b -1c"] > 0} { incr wrapped }
    }
    set wrapped
} -result 0

test tk85-1 {thumbnail degrades to "" when the image cannot be decoded} -body {
    ::chatvmd::thumb::make $D/proto.tcl 232 146
} -result {}

cleanupTests
exit
