# tests/tcl/test_executor.tcl - executor.tcl (P06-T08; spec 2d, C2, C3, C5,
# S10). VMD's mol, display and render are stubbed; net::call answers
# tool.ack from ::ack_reply and net::post_result records what is posted.
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
foreach m {config sched net executor} { source [file join $plugin $m.tcl] }

# --- fakes --------------------------------------------------------------------
proc ::mol {args} { lappend ::vmd_calls [concat mol $args]; return 0 }
proc ::display {args} { lappend ::vmd_calls [concat display $args]; return "" }
proc ::render {renderer path args} {
    lappend ::vmd_calls [list render $renderer $path]
    set fh [open $path w]
    puts -nonewline $fh [string repeat x 2048]
    close $fh
    return ""
}
proc ::vmdai::net::call {method params callback args} {
    lappend ::rpc [list $method $params]
    ::vmdai::sched::after 0 [list ::vmdai::net::_deliver_if_current \
        [::vmdai::net::epoch] $callback {*}$::ack_reply]
    return rpc#fake
}
namespace eval ::vmdai::ui {}
proc ::vmdai::ui::status {text} { lappend ::statuses $text }
# Posted params, decoded from the JSON the real encoder builds.
proc ::vmdai::net::post_result {call_key pairs} {
    lappend ::posts [list $call_key [::vmdai::net::decode [::vmdai::net::encode_params $pairs]]]
}
proc settle {{ms 30}} {
    set ::_settled 0
    after $ms {set ::_settled 1}
    vwait ::_settled
}
proc fresh {} {
    ::vmdai::executor::reset
    ::vmdai::executor::clear_ledger
    ::vmdai::sched::teardown
    set ::vmd_calls {}
    set ::rpc {}
    set ::posts {}
    set ::statuses {}
    set ::ack_reply {ok {proceed true}}
}
proc tool_start {key command args} {
    set md [dict create call_key $key request_id req_1 tool_call_id tc_$key \
        tool_name run_vmd_command tool_input [dict create command $command] \
        approval auto snapshot_path ""]
    foreach {k v} $args { dict set md $k $v }
    return [dict create seq 1 role tool_start type message text "\[VMD\] x" metadata $md]
}
# Run one command through the whole pipeline; returns the posted dict.
proc run_cmd {command} {
    ::vmdai::executor::run [tool_start k[incr ::key_seq] $command]
    settle
    return [lindex $::posts end 1]
}
proc pick {d args} {
    set out {}
    foreach k $args { lappend out [expr {[dict exists $d $k] ? [dict get $d $k] : "-"}] }
    return $out
}
set ::key_seq 0

# --- tests --------------------------------------------------------------------

test exec-split-1 {split_statements: complete statements and the incomplete tail} -body {
    set d [::vmdai::executor::split_statements "mol new a.pdb\nset x \{\n 1\n\}\nbad \["]
    set e [::vmdai::executor::split_statements "# note \{\nputs a; # b ; c\nputs \"x;y\"\nputs z\\\n w"]
    list [llength [dict get $d statements]] [dict get $d tail] [dict get $e statements] [dict get $e tail]
} -result [list 2 {bad [} [list {puts a} {puts "x;y"} "puts z\\\n w"] {}]

test exec-puts-1 {puts output and statement results reach the posted output (S10)} -setup fresh -body {
    set r [run_cmd "puts hello\nset n 42"]
    list [pick $r ok executed output statements_total statements_applied] \
        [lindex $::rpc 0] [lindex $::posts 0 0] $::statuses
} -result {{true yes {hello
42
} 2 2} {tool.ack {call_key s k1 state s running}} k1 {{Running: puts hello ...}}}

test exec-puts-2 {puts -nonewline, puts stdout/stderr are captured; puts $fh writes the file; puts is restored} -setup fresh -body {
    set path [file join $::env(HOME) out.txt]
    set ::fh [open $path w]
    set r [run_cmd "puts -nonewline a\nputs stdout b\nputs -nonewline stderr c\nputs \$::fh file-line"]
    close $::fh
    set fh [open $path]
    set file [read $fh]
    close $fh
    set bad [run_cmd "puts x\nerror boom"]
    list [dict get $r output] $file [dict get $bad output] \
        [info commands ::vmdai::executor::_real_puts] [expr {[info commands ::puts] eq "::puts"}]
} -result {{ab
c} {file-line
} {x
} {} 1}

test exec-puts-3 {puts is restored even when the model's Tcl renames it} -setup fresh -body {
    set r [run_cmd "rename puts gone"]
    list [dict get $r ok] [expr {[info commands ::puts] eq "::puts"}] \
        [info commands ::vmdai::executor::_real_puts]
} -cleanup { catch {rename ::gone {}} } -result {true 1 {}}

test exec-puts-4 {a puts that cannot be captured resets executing instead of sticking} -setup fresh -body {
    rename ::puts ::saved_puts
    set r [::vmdai::executor::exec_command "set x 1"]
    list [dict get $r executed] $::vmdai::executor::executing
} -cleanup {
    if {[llength [info commands ::saved_puts]]} { rename ::saved_puts ::puts }
    fresh
} -result {no 0}

test exec-code2-1 {catch codes 0 and 2 count as success} -setup fresh -body {
    set r [run_cmd "set a 1\nreturn 7\nset b 2"]
    set brk [run_cmd "break"]
    list [pick $r ok output statements_applied] [pick $brk ok error failed_index]
} -result {{true {1
7
2
} 3} {false {invoked "break" outside of a loop} 1}}

test exec-partial-1 {an error in statement 3 of 4: failed_index, applied_text, error_info (C3)} -setup fresh -body {
    proc ::fails_inside {} { error "no such molecule" }
    set cmd "mol new a.pdb\nmol delrep 0 top\nfails_inside\nmol addrep 0"
    set r [run_cmd $cmd]
    list [pick $r ok executed statements_total statements_applied failed_index failed_statement error] \
        [expr {[dict get $r applied_text] eq "mol new a.pdb\nmol delrep 0 top\n"}] \
        [llength [split [dict get $r error_info] "\n"]] [dict get $r output] [llength $::vmd_calls]
} -cleanup { rename ::fails_inside {} } -result {{false yes 4 2 3 fails_inside {no such molecule}} 1 3 {0
0
} 2}

test exec-precheck-1 {an incomplete tail runs nothing and posts executed no (C3)} -setup fresh -body {
    set r [run_cmd "mol new a.pdb\nmol modstyle 0 0 NewCartoon\nmol modcolor 0 0 \{Name"]
    list [pick $r ok executed statements_total statements_applied failed_index error] \
        [expr {[dict get $r failed_statement] eq "mol modcolor 0 0 \{Name"}] $::vmd_calls [llength $::rpc] \
        $::statuses
} -result {{false no 3 0 3 {Nothing was run: statement 3 of 3 is incomplete (unbalanced braces, brackets or quotes)}} 1 {} 1 {}}

test exec-ceiling-1 {output past 1 MB is cut with a note and truncated true (C5)} -setup fresh -body {
    set r [run_cmd "puts \[string repeat x 2000000\]"]
    set out [dict get $r output]
    set note "\n\[executor limit: output cut at 1 MB\]"
    list [expr {[string length $out] == 1048576 + [string length $note]}] \
        [expr {[string range $out 1048576 end] eq $note}] [string range $out 0 2] \
        [dict get $r truncated] $::vmdai::executor::output_ceiling
} -result {1 1 xxx true 1048576}

test exec-ack-1 {ack proceed false: nothing runs and nothing is posted} -setup fresh -body {
    set ::ack_reply {ok {proceed false reason cancelled}}
    ::vmdai::executor::run [tool_start k100 "mol new a.pdb"]
    settle
    list $::vmd_calls $::posts [llength $::rpc]
} -result {{} {} 1}

test exec-dup-1 {a call_key that already ran is skipped} -setup fresh -body {
    ::vmdai::executor::run [tool_start k200 "mol new a.pdb"]
    ::vmdai::executor::run [tool_start k200 "mol new a.pdb"]
    settle
    list [llength $::rpc] [llength $::posts] [llength $::vmd_calls]
} -result {1 1 1}

test exec-cancel-1 {a tool_start of a cancelled request is skipped} -setup fresh -body {
    ::vmdai::executor::note_cancelled req_1
    ::vmdai::executor::run [tool_start k300 "mol new a.pdb"]
    settle
    list [llength $::rpc] $::posts $::vmd_calls
} -result {0 {} {}}

test exec-approval-1 {approval ask: not acked, not run, posts executed no (C2)} -setup fresh -body {
    ::vmdai::executor::run [tool_start k400 "mol new a.pdb" approval ask]
    settle
    list [llength $::rpc] $::vmd_calls [pick [lindex $::posts 0 1] ok executed error]
} -result {0 {} {false no {This panel cannot ask for approval}}}

test exec-epoch-1 {a session change before the ack answer: nothing runs; the next call still runs} -setup fresh -body {
    ::vmdai::executor::run [tool_start k500 "mol new a.pdb"]
    ::vmdai::net::bump_epoch
    settle
    set stale [list $::vmd_calls $::posts]
    ::vmdai::executor::run [tool_start k501 "mol new b.pdb"]
    settle
    list $stale $::vmd_calls [lindex $::posts 0 0]
} -result {{{} {}} {{mol new b.pdb}} k501}

test exec-snap-1 {capture_vmd_snapshot: display update, render TachyonInternal to snapshot_path} -setup fresh -body {
    set path [file join $::env(HOME) vmdai_snap_k600.tga]
    ::vmdai::executor::run [tool_start k600 "" tool_name capture_vmd_snapshot \
        tool_input {purpose check} snapshot_path $path]
    settle
    set r [lindex $::posts 0 1]
    list $::vmd_calls [pick $r ok executed snapshot_file] [file size $path] \
        [dict get [lindex [::vmdai::executor::ledger] end] command]
} -result [list [list {display update} [list render TachyonInternal [file join $::env(HOME) vmdai_snap_k600.tga]]] \
    [list true yes [file join $::env(HOME) vmdai_snap_k600.tga]] 2048 \
    "render TachyonInternal [file join $::env(HOME) vmdai_snap_k600.tga]"]

test exec-snap-2 {a render error posts ok false with the message} -setup fresh -body {
    rename ::render ::render_ok
    proc ::render {args} { error "Tachyon failed" }
    ::vmdai::executor::run [tool_start k700 "" tool_name capture_vmd_snapshot \
        snapshot_path [file join $::env(HOME) snap2.tga]]
    settle
    pick [lindex $::posts 0 1] ok error
} -cleanup { rename ::render {}; rename ::render_ok ::render } -result {false {Snapshot failed: Tachyon failed}}

cleanupTests
