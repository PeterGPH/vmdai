# View-model unit tests (P08-T01..T03). No Tk. Run by tests/test_tcl_viewmodel.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}

source [file join $env(VMDAI_PLUGIN_DIR) viewmodel.tcl]

# Build decoded envelopes the way json::json2dict returns them.
proc ev {role type text md {ts 100}} {
    return [dict create seq 0 ts $ts role $role type $type text $text metadata $md]
}
proc st {kind md {ts 100}} {
    return [ev system state "" [dict merge [dict create kind $kind] $md] $ts]
}
proc started {req {extra {}}} {
    return [st request.started [dict merge [dict create request_id $req chat_id chat_0123456789ab \
        provider ollama model qwen3.8:27b max_turns 28 vision true think true] $extra]]
}
proc tstart {req k {cmd "mol new 1hck.pdb"} {name run_vmd_command}} {
    return [st tool.started [dict create request_id $req turn 1 call_key $k tool_call_id call_$k \
        tool_name $name executor tcl origin model input [dict create command $cmd rationale "load it"]]]
}
proc tfin {req k {extra {}}} {
    return [st tool.finished [dict merge [dict create request_id $req call_key $k \
        tool_name run_vmd_command executor tcl ok true executed yes output "" error "" \
        truncated false duration_ms 412 statements null blocked null output_path null \
        output_bytes 0 image null saved_path null late false] $extra]]
}
# Apply events in order; return the concatenated ops.
proc feed {sv args} {
    upvar 1 $sv S
    set ops {}
    foreach e $args { lappend ops {*}[::vmdai::vm::apply S $e] }
    return $ops
}
# Only the ops whose name is in $names.
proc only {ops names} {
    set out {}
    foreach op $ops { if {[lindex $op 0] in $names} { lappend out $op } }
    return $out
}

# ---- P08-T01 ---------------------------------------------------------------

test user_block_ops {a user message is one block: open (with its time), then its text} -body {
    ::vmdai::vm::init S
    ::vmdai::vm::apply S [ev user message "Load 1HCK" {request_id req_a} 1727180000.7]
} -result {{block.open b1 user 0 1727180000} {block.append b1 {Load 1HCK}}}

test block_closes_on_role_request_turn_change {role, request and turn changes each open a new block} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] \
        [ev assistant chunk "one " {request_id req_a turn 1}] \
        [ev assistant chunk "two" {request_id req_a turn 1}] \
        [ev reasoning chunk "hmm" {request_id req_a turn 1}] \
        [ev assistant chunk "three" {request_id req_a turn 1}] \
        [ev assistant chunk "four" {request_id req_a turn 2}] \
        [ev assistant chunk "five" {request_id req_b turn 2}]]
    only $ops {block.open block.append reasoning.open reasoning.append reasoning.seal run.open}
} -result {{run.open r1 req_a qwen3.8:27b 100} {block.open b1 assistant 1} {block.append b1 {one }} {block.append b1 two} {reasoning.open b2 1} {reasoning.append b2 hmm} {reasoning.seal b2 0} {block.open b3 assistant 1} {block.append b3 three} {block.open b4 assistant 2} {block.append b4 four} {run.open r2 req_b {} 100} {block.open b5 assistant 2} {block.append b5 five}}

test non_chunk_event_closes_block {any non-chunk event closes the open block} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] \
        [ev assistant chunk "a" {request_id req_a turn 1}] \
        [st usage {request_id req_a turn 1 input_tokens_evaluated 10 output_tokens 2}] \
        [ev assistant chunk "b" {request_id req_a turn 1}]]
    only $ops {block.open block.append}
} -result {{block.open b1 assistant 1} {block.append b1 a} {block.open b2 assistant 1} {block.append b2 b}}

test seal_replaces_streamed_text {assistant/message seals the streamed block in place, even after usage closed it} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] \
        [ev assistant chunk "I'll lo" {request_id req_a turn 1}] \
        [ev assistant chunk "ad it." {request_id req_a turn 1}] \
        [st usage {request_id req_a turn 1}] \
        [ev assistant message "I'll load it." {request_id req_a turn 1 final false}]]
    only $ops {block.open block.append block.seal block.discard rule}
} -result {{block.open b1 assistant 1} {block.append b1 {I'll lo}} {block.append b1 {ad it.}} {block.seal b1 {I'll load it.}}}

test seal_empty_discards {an empty canonical text discards the streamed block (rescued JSON)} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] \
        [ev assistant chunk "\{\"name\": \"run_vmd_command\"" {request_id req_a turn 1}] \
        [ev assistant message "" {request_id req_a turn 1 final false}]]
    only $ops {block.open block.seal block.discard}
} -result {{block.open b1 assistant 1} {block.discard b1}}

test final_answer_under_rule {a final answer is re-opened under the run's rule; replay renders the same} -body {
    ::vmdai::vm::init S
    set live [only [feed S [started req_a] \
        [ev assistant chunk "Done." {request_id req_a turn 2}] \
        [ev assistant message "Done." {request_id req_a turn 2 final true}]] \
        {block.open block.seal block.discard rule}]
    ::vmdai::vm::init R
    set replay [only [feed R [started req_a] \
        [ev assistant message "Done." {request_id req_a turn 2 final true}]] \
        {block.open block.seal block.discard rule}]
    list $live $replay
} -result {{{block.open b1 assistant 2} {block.discard b1} {rule r1} {block.open b2 assistant 2} {block.seal b2 Done.}} {{rule r1} {block.open b1 assistant 2} {block.seal b1 Done.}}}

test reasoning_seal_and_replay {reasoning seals once when the answer starts; a later reasoning/message is ignored; replay renders it} -body {
    ::vmdai::vm::init S
    set live [only [feed S [started req_a] \
        [ev reasoning chunk "think" {request_id req_a turn 1} 100] \
        [ev assistant chunk "Answer" {request_id req_a turn 1} 103] \
        [ev reasoning message "think" {request_id req_a turn 1} 104]] \
        {reasoning.open reasoning.append reasoning.seal}]
    ::vmdai::vm::init R
    set replay [only [feed R [started req_a] \
        [ev reasoning message "think" {request_id req_a turn 1 duration_ms 2600}]] \
        {reasoning.open reasoning.append reasoning.seal}]
    list $live $replay
} -result {{{reasoning.open b1 1} {reasoning.append b1 think} {reasoning.seal b1 3}} {{reasoning.open b1 1} {reasoning.append b1 think} {reasoning.seal b1 3}}}

test turn_retry_discards {turn.retry discards the dropped attempt's text and reasoning} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] \
        [ev reasoning chunk "r" {request_id req_a turn 1}] \
        [ev assistant chunk "Partial" {request_id req_a turn 1}] \
        [st turn.retry {request_id req_a turn 1 reason {stream dropped}}] \
        [ev assistant chunk "Again" {request_id req_a turn 1}]]
    only $ops {block.open block.discard reasoning.open}
} -result {{reasoning.open b1 1} {block.open b2 assistant 1} {block.discard b2} {block.discard b1} {block.open b3 assistant 1}}

test run_and_tool_ops {request.started opens a run; tools open, chip and close; request.finished closes the run} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] [tstart req_a k1] \
        [tfin req_a k1 {output 20.843129 statements {total 2 applied 2 failed null}}] \
        [st request.finished {request_id req_a status complete wrapped_up false turns 2 tool_calls 1 final_text_empty false duration_ms 1600}]]
    set close [lindex [only $ops tool.close] 0]
    list [only $ops {run.open run.chip run.close footer}] \
         [lrange $close 0 2] [dict get [lindex $close 4] inline] [lindex $close 5]
} -result {{{run.open r1 req_a qwen3.8:27b 100} {run.chip r1 k1 running} {run.chip r1 k1 ok} {footer r1 2 {}} {run.close r1 complete 1 0 0 2 0 28}} {tool.close k1 ok} 20.8431 {}}

test tool_open_args {tool.open carries the command, executor, origin and rationale} -body {
    ::vmdai::vm::init S
    only [feed S [started req_a] [tstart req_a k1 "mol new a.pdb\nmol delrep 0 top"]] tool.open
} -result {{tool.open k1 run_vmd_command {mol new a.pdb
mol delrep 0 top} tcl model {load it}}}

test status_ops_follow_phases {status ops change only with the phase} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] \
        [st turn.started {request_id req_a turn 1}] \
        [ev assistant chunk "x" {request_id req_a turn 1}] \
        [ev assistant chunk "y" {request_id req_a turn 1}] \
        [tstart req_a k1] \
        [st status {request_id req_a phase retrying attempt 2 max_attempts 5 wait_s 8 http_status 429}] \
        [st status {request_id req_a phase loading_model}]]
    only $ops status
} -result {{status busy Thinking 100} {status busy Writing 100} {status busy {Step 1 · running VMD command} 100} {status busy {Retrying 2/5 in 8 s} {}} {status busy {Loading qwen3.8:27b} 100}}

test snapshot_op {a snapshot result emits tool.close with its thumb and a snapshot op} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a {vision false}] \
        [tstart req_a k9 "" capture_vmd_snapshot] \
        [tfin req_a k9 {tool_name capture_vmd_snapshot saved_path /w/fig1.png image {path /c/k9.png thumb_path /c/k9_thumb.png width 1024 height 768 src_width 1280 src_height 1547 renderer TachyonInternal}}]]
    list [lindex [only $ops tool.close] 0 5] [only $ops snapshot]
} -result {/c/k9_thumb.png {{snapshot k9 /c/k9_thumb.png /c/k9.png 1280 1547 /w/fig1.png 0 TachyonInternal}}}

test format_op_round_trip {format_op writes one line that lindex parses back exactly} -body {
    set op [list block.seal b1 "a \"q\" \\ \$x \[y\] \{z\nnext\ttab"]
    set line [::vmdai::vm::format_op $op]
    list [string first "\n" $line] [expr {[lindex $line 2] eq [lindex $op 2]}] [llength $line]
} -result {-1 1 3}

test trust_notice_no_op {the runtime's security notice produces no op; it is routed to the empty state} -body {
    ::vmdai::vm::init S
    set ops [::vmdai::vm::apply S [ev system message "Security note: ..." {notice tcl_trust_boundary}]]
    list $ops [dict get $S trust_notice]
} -result {{} 1}

# ---- P08-T02 ---------------------------------------------------------------

test notrun_label_order {not-run labels: first match wins in C1-C4 order} -body {
    set all [dict create executed no ok false \
        blocked [list [dict create id cmd_exec word exec text {exec ls}]] \
        statements [dict create total 2 applied 0 failed [dict create index 2 text "x \{" error_info null]] \
        error cancelled]
    set r {}
    lappend r [::vmdai::vm::notrun_label $all]
    dict set all blocked null
    lappend r [::vmdai::vm::notrun_label $all]
    dict set all statements null
    dict set all error "not executed: loop guard"
    lappend r [::vmdai::vm::notrun_label $all]
    dict set all error cancelled
    lappend r [::vmdai::vm::notrun_label $all]
    dict set all error "VMD did not pick up the command (45 s)"
    lappend r [::vmdai::vm::notrun_label $all]
    dict set all error "This panel cannot ask for approval\nmore"
    lappend r [::vmdai::vm::notrun_label $all]
    dict set all error ""
    lappend r [::vmdai::vm::notrun_label $all]
} -result {{not run · blocked: exec} {not run · incomplete Tcl} {not run · loop guard} {not run · stopped} {VMD did not pick up the command} {not run · This panel cannot ask for approval} {not run}}

test tool_state_values {tool_state maps executed/ok to ok|err|notrun|unknown} -body {
    list [::vmdai::vm::tool_state {ok true executed yes}] \
         [::vmdai::vm::tool_state {ok false executed yes}] \
         [::vmdai::vm::tool_state {ok false executed no}] \
         [::vmdai::vm::tool_state {ok false executed unknown}] \
         [::vmdai::vm::tool_state {ok true}]
} -result {ok err notrun unknown ok}

test unknown_call_key_ignored {tool.finished before tool.started, or for an unknown call_key, does nothing} -body {
    ::vmdai::vm::init S
    feed S [started req_a] [tfin req_a k_nope] [tstart req_a k1] [tstart req_a k1]
    set before $S
    set ops [::vmdai::vm::apply S [tfin req_a k_other]]
    list $ops [expr {$S eq $before}] [llength [only [feed S [tstart req_a k1]] tool.open]]
} -result {{} 1 0}

test second_finished_ignored_unless_late {a repeated tool.finished is ignored unless late:true} -body {
    ::vmdai::vm::init S
    feed S [started req_a] [tstart req_a k1] [tfin req_a k1 {ok false executed unknown}]
    set again [::vmdai::vm::apply S [tfin req_a k1 {ok true}]]
    set late [::vmdai::vm::apply S [tfin req_a k1 {ok true late true output 7.5}]]
    list $again [lrange [lindex $late 0] 0 2] [dict get [lindex $late 0 4] label] [lindex $late 1]
} -result {{} {tool.close k1 ok} {(finished late)} {run.chip r1 k1 ok}}

test late_updates_row_after_finished {a late result updates its row after request.finished and after the next request started} -body {
    ::vmdai::vm::init S
    feed S [started req_a] [tstart req_a k1] [tfin req_a k1 {ok false executed unknown}] \
        [st request.finished {request_id req_a status cancelled tool_calls 1 final_text_empty false duration_ms 3000}] \
        [started req_b]
    set ops [::vmdai::vm::apply S [tfin req_a k1 {ok false late true error {boom}}]]
    list [lrange [lindex $ops 0] 0 1] [dict get [lindex $ops 0 4] error] [lindex $ops 1] [llength $ops]
} -result {{tool.close k1} boom {run.chip r1 k1 err} 2}

test error_card_actions_and_no_model {error events become cards with an action; NO_MODEL is a local card; truncation, context and thinking get a muted notice, never a card} -body {
    ::vmdai::vm::init S
    set r {}
    lappend r [::vmdai::vm::apply S [ev error message "Model not found: qwen3.8:27b" \
        {request_id req_a code model_not_found http_status 404 hint {ollama pull qwen3.8:27b} action choose_model}]]
    lappend r [::vmdai::vm::apply S [ev error message "Credit balance too low" {request_id req_a code billing}]]
    lappend r [::vmdai::vm::apply S [::vmdai::vm::local_event local.send_failed \
        {code NO_MODEL message {Set up a model in Settings.}}]]
    lappend r [only [feed S [st status {request_id req_a phase turn_truncated}] \
        [st status {request_id req_a phase context_near_full}] \
        [st status {request_id req_a phase think_unsupported}]] {notice error.card}]
} -result {{{error.card model_not_found {Model not found: qwen3.8:27b} {ollama pull qwen3.8:27b} choose_model}} {{error.card billing {Credit balance too low} {} switch_profile}} {{error.card NO_MODEL {No model configured} {Set up a model in Settings.} open_settings}} {{notice info {The reply was cut off, so its tool calls were not run}} {notice info {Context is nearly full; older tool output is shortened}} {notice info {This model does not support thinking; continuing without it}}}}

test local_connection_notices {one notice per connection state change; a lost request settles its rows} -body {
    ::vmdai::vm::init S
    feed S [started req_a] [tstart req_a k1]
    set ops [feed S \
        [::vmdai::vm::local_event local.connection {state reconnecting detail 127.0.0.1:8765 request_lost false ts 1727180000}] \
        [::vmdai::vm::local_event local.connection {state down detail 127.0.0.1:8765 request_lost false ts 1727180001}] \
        [::vmdai::vm::local_event local.connection {state ready detail 127.0.0.1:8765 request_lost true ts 1727180002}]]
    list [only $ops notice] [lrange [lindex [only $ops tool.close] 0] 0 2] \
         [lrange [lindex [only $ops run.close] 0] 0 1] [lindex $ops end]
} -result {{{notice warn {Connection lost at 12:13 PM · your draft is kept}} {notice warn {Reconnected: request lost} retry}} {tool.close k1 unknown} {run.close r1} {status idle}}

test request_ended_local {local.request_ended ends a busy request with a note} -body {
    ::vmdai::vm::init S
    feed S [started req_a]
    set ops [::vmdai::vm::apply S [::vmdai::vm::local_event local.request_ended {request_id req_a}]]
    list [lindex $ops 0] [lrange [lindex [only $ops run.close] 0] 0 2] [lindex $ops end] [dict get $S busy]
} -result {{notice info {Request ended (details may be missing)}} {run.close r1 ended} {status idle} 0}

cleanupTests
