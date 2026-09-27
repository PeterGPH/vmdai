# Tool rows, step detail, run headers, chips, footers, collapse (P08-T06).
# Adopted from native's proto_test (glue-1, status-1, err-1, out-1, expand-1,
# fit-1) and cards' test_proto (group-1..3). Run by tests/test_tk_tool_rows.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched config net executor theme viewmodel transcript
::vmdai::theme::init light
set ::vmdai::transcript::opt(animate) 0
wm geometry . 560x780
set t [::vmdai::transcript::create .tx]
pack .tx -fill both -expand 1
update

set ::actions {}
set ::vmdai::transcript::on_action [list apply {{args} {lappend ::actions $args}}]

# Events, as in test_viewmodel.tcl, fed through the real view-model.
proc st {kind md {ts 1790208000}} {
    return [dict create seq 0 ts $ts role system type state text "" \
        metadata [dict merge [dict create kind $kind] $md]]
}
proc started {req {extra {}}} {
    return [st request.started [dict merge [dict create request_id $req model qwen3.8:27b \
        max_turns 28 vision true] $extra]]
}
proc tstart {req k cmd {why ""} {name run_vmd_command}} {
    set input [dict create command $cmd rationale $why]
    if {$name eq "capture_vmd_snapshot"} { set input [dict create purpose $why] }
    return [st tool.started [dict create request_id $req turn 1 call_key $k tool_name $name \
        executor tcl origin model input $input]]
}
proc tfin {req k {extra {}}} {
    return [st tool.finished [dict merge [dict create request_id $req call_key $k \
        tool_name run_vmd_command ok true executed yes output "" error "" duration_ms 412 \
        statements null blocked null output_path null image null saved_path null late false] $extra]]
}
proc finished {req status {extra {}}} {
    return [st request.finished [dict merge [dict create request_id $req status $status \
        wrapped_up false tool_calls 1 final_text_empty false duration_ms 16000] $extra] 1790208016]
}
proc feed {args} {
    foreach e $args { ::vmdai::transcript::apply_ops [::vmdai::vm::apply ::S $e] }
}
proc fresh {} {
    set ::actions {}
    ::vmdai::transcript::clear
    ::vmdai::transcript::set_expand_all 0
    ::vmdai::vm::init ::S
    wm geometry . 560x780
    update
    ::vmdai::transcript::relayout
}
proc rowtext {k} { return [$::t get "rowend:$k -1l linestart" "rowend:$k -1c"] }
proc glyph {k} { return [$::t get [lindex [$::t tag ranges glyph:$k] 0]] }
proc tagtext {tag} {
    set out {}
    foreach {a b} [$::t tag ranges $tag] { lappend out [$::t get $a $b] }
    return $out
}
proc shown {a b} { return [$::t count -displaychars $a $b] }
proc click_link {label} {
    set at [$::t search -backwards -exact $label end 1.0]
    foreach tag [$::t tag names $at] {
        if {[string match act:* $tag]} { uplevel #0 [$::t tag bind $tag <ButtonRelease-1>] }
    }
}

set CMD1 "mol new 1hck.pdb\nmol delrep 0 top\nmol representation NewCartoon\nmol addrep top"
set CMD2 "color Display Background white\ndisplay backgroundcolor white"
set CMD4 "set sel \[atomselect top protein\]\nmeasure rgyr \$sel"
set FAIL2 [dict create index 2 text "display backgroundcolor white" error_info x]

# The five-step run of native's demo: load, a failing line, the fix, a
# measurement with an inline result, a restyle; then the answer.
proc five_steps {} {
    feed [started req_1] \
        [tstart req_1 k1 $::CMD1 "Load the structure and draw it as a cartoon."] \
        [tfin req_1 k1 {statements {total 4 applied 4 failed null}}] \
        [tstart req_1 k2 $::CMD2 "Make the background white."] \
        [tfin req_1 k2 [dict create ok false error "display: invalid option \"backgroundcolor\"" \
            duration_ms 38 statements [dict create total 2 applied 1 failed $::FAIL2]]] \
        [tstart req_1 k3 "color Display Background white" "Set the background."] \
        [tfin req_1 k3 {duration_ms 12}] \
        [tstart req_1 k4 $::CMD4 "Radius of gyration."] \
        [tfin req_1 k4 {output 20.8431 duration_ms 25}] \
        [tstart req_1 k5 "mol modstyle 0 top NewCartoon 0.3 30 4.1" "Thicker cartoon."] \
        [tfin req_1 k5] \
        [dict create seq 0 ts 1790208015 role assistant type message text "Done." \
            metadata {request_id req_1 turn 6 final true}] \
        [finished req_1 complete {tool_calls 5}]
}

test glue-1 {every tool row starts on its own line} -body {
    fresh
    five_steps
    set bad 0
    foreach k {k1 k2 k3 k4 k5} {
        set a [lindex [$t tag ranges row:$k] 0]
        if {[$t compare $a != "$a linestart"]} { incr bad }
    }
    set bad
} -result 0

test status-1 {glyphs follow the tool state; running and not-run rows; a hex call key that starts with a digit} -body {
    fresh
    five_steps
    set r {}
    foreach k {k1 k2 k3 k4 k5} { lappend r [glyph $k] }
    feed [started req_2] [tstart req_2 77c0d2e9ab15 "mol new x.pdb"]
    lappend r [glyph 77c0d2e9ab15] [string match "*running…*" [rowtext 77c0d2e9ab15]]
    feed [tfin req_2 77c0d2e9ab15 {ok false executed no error {Not run: exec is never run by ChatVMD.} \
        blocked {{id cmd_exec word exec text {exec ls}}}}]
    lappend r [glyph 77c0d2e9ab15] [string match "*not run · blocked: exec*" [rowtext 77c0d2e9ab15]]
} -result {✓ ✗ ✓ ✓ ✓ • 1 – 1}

test err-1 {a failed call shows its error right under the row, and its failing statement in the row} -body {
    fresh
    five_steps
    list [string trim [$t get rowend:k2 "rowend:k2 lineend"]] \
        [string match "*display backgroundcolor white*" [rowtext k2]] \
        [string match "*color Display*" [rowtext k2]]
} -result {{display: invalid option "backgroundcolor"} 1 0}

test out-1 {informative output inline next to the last statement; trivial output hidden} -body {
    fresh
    five_steps
    list [string match "*… measure rgyr \$sel*→ 20.8431*" [rowtext k4]] [string match "*→*" [rowtext k1]]
} -result {1 0}

test expand-1 {a row expands to its exact command and collapses again} -body {
    fresh
    five_steps
    set open [::vmdai::transcript::toggle_detail k1]
    set lines [split [string trimright [$t get {*}[$t tag ranges detail:k1]] "\n"] "\n"]
    set code {}
    foreach l $lines { if {[string match "  mol *" $l]} { lappend code [string range $l 2 end] } }
    set r [list $open [llength $lines] [expr {[join $code "\n"] eq $::CMD1}] [lindex $lines 0] [lindex $lines end]]
    lappend r [::vmdai::transcript::toggle_detail k1] [llength [$t tag ranges detail:k1]]
} -result {1 6 1 {Load the structure and draw it as a cartoon.} Copy 0 0}

test fit-1 {at 380 px every row, even a 10 KB one-line command, stays one display line} -body {
    fresh
    five_steps
    set long "puts [string repeat {atomselect top "resid 1 to 99" } 330]"
    feed [started req_2] [tstart req_2 k9 $long "A very long command."] [tfin req_2 k9]
    ::vmdai::transcript::set_expand_all 1
    wm geometry . 380x700
    update
    ::vmdai::transcript::relayout
    update
    set wrapped 0
    set outside 0
    foreach k {k1 k2 k3 k4 k5 k9} {
        lassign [$t tag ranges row:$k] a b
        if {[$t count -update -displaylines $a "$b -1c"] > 0} { incr wrapped }
        $t see "$b -2c"
        update
        set box [$t bbox "$b -2c"]
        if {$box eq "" || [lindex $box 0] + [lindex $box 2] > [winfo width $t]} { incr outside }
    }
    set cmd [lindex [tagtext cmd] end]
    list $wrapped $outside [expr {[string length $cmd] >= 13}] [string match "*…" $cmd] \
        [expr {[string length $long] > 10000}]
} -result {0 0 1 1 1}

test group-1 {a finished run collapses when the next starts; chips and the failed row stay visible} -body {
    fresh
    five_steps
    feed [dict create seq 0 ts 1790208020 role user type message text "next" metadata {request_id req_2}] \
        [started req_2]
    lassign [$t tag ranges row:k1] a1 b1
    lassign [$t tag ranges row:k2] a2 b2
    set hdr [$t get {*}[$t tag ranges hdr:r1]]
    list [$t tag cget wl:r1 -elide] [shown $a1 $b1] [expr {[shown $a2 $b2] > 0}] \
        [expr {[shown rowend:k2 "rowend:k2 lineend"] > 0}] [string match "*✓ ✗ ✓ ✓ ✓*" $hdr] \
        [string match "*1 failed, recovered · 16 s*" $hdr]
} -result {1 0 1 1 1 1}

test group-2 {a run that ends on an unrecovered failure stays expanded} -body {
    fresh
    feed [started req_1] [tstart req_1 k1 "nope" "Try it."] \
        [tfin req_1 k1 {ok false error {invalid command name "nope"}}] \
        [finished req_1 complete] [started req_2]
    list [$t tag cget wl:r1 -elide] [expr {[string first "1 failed · 16 s" [$t get {*}[$t tag ranges hdr:r1]]] >= 0}]
} -result {{} 1}

test group-3 {a late result updates its row in place, inside its own run, after the next run started} -body {
    fresh
    feed [started req_1] [tstart req_1 k1 "mol new big.pdb"] \
        [tfin req_1 k1 {ok false executed unknown error {stopped while running}}] \
        [finished req_1 cancelled] [started req_2] [tstart req_2 k2 "mol list"]
    set before [glyph k1]
    feed [tfin req_1 k1 {ok true late true output 7.5}]
    lassign [$t tag ranges row:k1] a b
    list $before [glyph k1] [string match "*(finished late)*" [rowtext k1]] \
        [$t compare $a < [lindex [$t tag ranges hdr:r2] 0]] \
        [string match "*✓*" [$t get {*}[$t tag ranges hdr:r1]]]
} -result {! ✓ 1 1 1}

test highlight-split {the failing statement highlight matches executor::split_statements} -body {
    fresh
    set cmd "mol new a.pdb\nset x \{\n 1\n\}\nbad_cmd 1\nmol delrep 0 top"
    set stmts [dict get [::vmdai::executor::split_statements $cmd] statements]
    feed [started req_1] [tstart req_1 k1 $cmd "Four statements."] \
        [tfin req_1 k1 [dict create ok false error {invalid command name "bad_cmd"} \
            statements [dict create total 4 applied 2 failed [dict create index 3 text "bad_cmd 1"]]]]
    set lines {}
    foreach l [split [$t get {*}[$t tag ranges detail:k1]] "\n"] { lappend lines $l }
    set code {}
    foreach l [lrange $lines 1 6] { lappend code [string range $l 2 end] }
    list [expr {[string trim [join [tagtext dfail] ""]] eq [string trim [lindex $stmts 2]]}] \
        [expr {[string trim [join [tagtext dmuted] ""]] eq [string trim [lindex $stmts 3]]}] \
        [string trim [join [tagtext dgutx] ""]] [expr {[join $code "\n"] eq $cmd}] \
        [expr {"Statements 1–2 ran and are kept in Save .tcl; the rest is commented out" in $lines}]
} -result {1 1 ✗ 1 1}

test full-output-link {C5: output_path adds "Open full output · Reveal" to the detail} -body {
    fresh
    feed [started req_1] [tstart req_1 k1 {puts [$sel get {x y z}]}] \
        [tfin req_1 k1 {output "1 2 3\n4 5 6\n7 8 9\n10 11 12\n13 14 15" output_path /w/outputs/k1.txt}]
    ::vmdai::transcript::toggle_detail k1
    set detail [$t get {*}[$t tag ranges detail:k1]]
    click_link "Open full output"
    click_link "Reveal"
    list [string match "*→ 1 2 3\n4 5 6*Open full output · Reveal*" $detail] $::actions \
        [llength [split [string trimright [join [tagtext preview] ""] "\n"] "\n"]]
} -result {1 {{open_file /w/outputs/k1.txt} {reveal_file /w/outputs/k1.txt}} 4}

test chip-jump {clicking a chip expands the run, shows the row and flashes it} -body {
    fresh
    five_steps
    feed [started req_2]
    set was [$t tag cget wl:r1 -elide]
    set chip [lsearch -inline [$t tag names] chip:k3]
    uplevel #0 [$t tag bind $chip <ButtonRelease-1>]
    update
    lassign [$t tag ranges row:k3] a b
    list $was [$t tag cget wl:r1 -elide] [expr {[$t bbox $a] ne ""}] \
        [expr {[$t tag nextrange flash $a $b] ne ""}]
} -result {1 0 1 1}

test unknown-key {tool.close, run.chip and snapshot for a row never opened do nothing} -body {
    fresh
    five_steps
    set before [::vmdai::transcript::dump]
    ::vmdai::transcript::apply_ops [list \
        [list tool.close k_nope ok "0.1 s" [dict create label "" error "" inline 1.5 preview {} \
            output 1.5 output_path "" total 1 applied 1 failed_index "" failed_text "" late 0] ""] \
        {run.chip r1 k_nope ok} {run.chip r_nope k1 err} \
        {snapshot k_nope /x/t.png /x/p.png 10 10 "" 1 TachyonInternal}]
    list [expr {[::vmdai::transcript::dump] eq $before}] $::vmdai::transcript::S(errors)
} -result {1 0}

test header-footer {run header summary, counts past 12 steps, and the footer links} -body {
    fresh
    five_steps
    set hdr [string map {"\t" "⇥"} [$t get {*}[$t tag ranges hdr:r1]]]
    click_link "Copy Tcl"
    click_link "Save .tcl…"
    feed [started req_2]
    for {set i 1} {$i <= 13} {incr i} { feed [tstart req_2 m$i "mol list"] [tfin req_2 m$i] }
    feed [finished req_2 complete {tool_calls 13 duration_ms 3000}]
    set hdr2 [$t get {*}[$t tag ranges hdr:r2]]
    list $hdr $::actions [string match "*✓13*" $hdr2] [string match "*13 steps · 3 s*" $hdr2]
} -result {{ChatVMD  qwen3.8:27b⇥✓ ✗ ✓ ✓ ✓  1 failed, recovered · 16 s
} {{copy_run_tcl req_1} {save_run_tcl req_1}} 1 1}

test expand-all {expand all opens every run and detail; off re-collapses older runs and closes details} -body {
    fresh
    five_steps
    feed [started req_2] [tstart req_2 k7 "mol list"] [tfin req_2 k7]
    ::vmdai::transcript::set_expand_all 1
    set r [list [$t tag cget wl:r1 -elide] [llength [$t tag ranges detail:k1]] [llength [$t tag ranges detail:k7]]]
    ::vmdai::transcript::set_expand_all 0
    lappend r [$t tag cget wl:r1 -elide] [llength [$t tag ranges detail:k1]] [$t tag cget wl:r2 -elide]
} -result {0 2 2 1 0 0}

test menus {right-click menus for a row and a run header} -body {
    fresh
    five_steps
    set row [::vmdai::transcript::menu_items [lindex [$t tag ranges row:k2] 0]]
    set hdr [::vmdai::transcript::menu_items [lindex [$t tag ranges hdr:r1] 0]]
    set labels {}
    foreach {label cmd} [concat $row $hdr] { lappend labels $label }
    set labels
} -result {{Copy command} {Copy error} Collapse {Copy run Tcl} {Save run .tcl…} Collapse}

test row-labels {snapshot, docs and wiki rows name their tool; a rescued call says (from text); a detail shows 10 command lines, then Show all} -body {
    fresh
    feed [started req_1] [tstart req_1 s1 "" "check the cartoon" capture_vmd_snapshot] \
        [st tool.started [dict create request_id req_1 turn 1 call_key d1 tool_name search_docs \
            executor runtime origin model input [dict create query "mol modcolor methods"]]] \
        [st tool.started [dict create request_id req_1 turn 1 call_key w1 tool_name wiki_read \
            executor runtime origin model input [dict create page coloring]]] \
        [st tool.started [dict create request_id req_1 turn 1 call_key r1 tool_name run_vmd_command \
            executor tcl origin rescued input [dict create command "mol list"]]]
    set long {}
    for {set i 1} {$i <= 14} {incr i} { lappend long "mol list $i" }
    feed [tstart req_1 k1 [join $long "\n"]] [tfin req_1 k1]
    ::vmdai::transcript::toggle_detail k1
    set before [llength [lsearch -all [split [$t get {*}[$t tag ranges detail:k1]] "\n"] "  mol list *"]]
    click_link "Show all 14 lines"
    ::vmdai::transcript::_do_show_all k1
    set after [llength [lsearch -all [split [$t get {*}[$t tag ranges detail:k1]] "\n"] "  mol list *"]]
    list [string match "*Snapshot  check the cartoon*" [rowtext s1]] \
        [string match "*Docs: mol modcolor methods*" [rowtext d1]] \
        [string match "*Wiki: coloring*" [rowtext w1]] \
        [string match "*mol list  (from text)*" [rowtext r1]] $before $after $::actions
} -result {1 1 1 1 10 14 {{show_all k1}}}

test row-click {a click on a row toggles its detail; a drag of more than 3 px or a new selection does not} -body {
    fresh
    five_steps
    set r {}
    ::vmdai::transcript::_row_press 10 10
    ::vmdai::transcript::_row_release k1 12 11
    lappend r [llength [$t tag ranges detail:k1]]
    ::vmdai::transcript::_row_press 10 10
    ::vmdai::transcript::_row_release k1 30 10
    lappend r [llength [$t tag ranges detail:k1]]
    ::vmdai::transcript::_row_press 10 10
    $t tag add sel "rowend:k3 -1l linestart" "rowend:k3 -1c"
    ::vmdai::transcript::_row_release k1 10 10
    $t tag remove sel 1.0 end
    lappend r [llength [$t tag ranges detail:k1]]
    ::vmdai::transcript::_row_press 10 10
    ::vmdai::transcript::_row_release k1 10 10
    lappend r [llength [$t tag ranges detail:k1]]
} -result {2 2 2 0}

test refit-order {V6 row refit: drop the rationale, then +N lines, then ellipsize the command (never below 12 characters), then drop the duration} -body {
    fresh
    feed [started req_1] \
        [tstart req_1 k1 "mol representation NewCartoon 0.3 30 4.1\nmol addrep top" "Draw it as a thick cartoon."] \
        [tfin req_1 k1 {duration_ms 412}]
    set seen {}
    for {set cw 900} {$cw >= 60} {incr cw -4} {
        lassign [::vmdai::transcript::_row_fit k1 $cw] text style suffix right
        set state [list [expr {[string first "Draw it" $suffix] >= 0}] \
            [expr {[string first "+1 lines" $suffix] >= 0}] \
            [expr {[string index $text end] eq "…"}] [expr {[string first "0.4 s" $right] >= 0}]]
        if {$state ne [lindex $seen end]} { lappend seen $state }
    }
    list $seen [string length [lindex [::vmdai::transcript::_row_fit k1 60] 0]]
} -result {{{1 1 0 1} {0 1 0 1} {0 0 0 1} {0 0 1 1} {0 0 1 0}} 13}

cleanupTests
exit
