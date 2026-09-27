# tests/tcl/test_result_queue.tcl - net::post_result retries (P06-T04). The
# pytest wrapper serves a FakeRpcServer at $env(VMDAI_FAKE_URL) whose reply
# depends on the call_key (see tests/test_tcl_result_queue.py).
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
source [file join $plugin config.tcl]
source [file join $plugin sched.tcl]
source [file join $plugin net.tcl]
::vmdai::net::configure -base_url $::env(VMDAI_FAKE_URL) -session_id sess_rq -session_token tok_rq

proc wait_for {script {ms 3000}} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { return 0 }
        set ::_tick 0
        after 10 {set ::_tick 1}
        vwait ::_tick
    }
    return 1
}

proc sleep_ms {ms} {
    set ::_slept 0
    after $ms {set ::_slept 1}
    vwait ::_slept
}

proc plugin_log {} {
    set path [::vmdai::config::plugin_log_path]
    if {![file exists $path]} { return "" }
    set fh [open $path r]
    set text [read $fh]
    close $fh
    return $text
}

proc queued {call_key} { info exists ::vmdai::net::queue($call_key) }

proc http_tokens {} { llength [info vars ::http::\[0-9\]*] }

# How many posts for $call_key the fake server has received (test-only RPC).
proc server_seen {call_key} {
    set seen [::vmdai::net::call_sync test.seen {}]
    expr {[dict exists $seen $call_key] ? [dict get $seen $call_key] : 0}
}

# Leave trace on _http_done: sets ::rq_captured once the reply to the post
# for $::rq_watch has been captured and its after-0 delivery scheduled.
proc rq_on_http_done {cmd code result op} {
    if {[string match "*_queue_reply $::rq_watch*" $cmd]} { set ::rq_captured 1 }
}

set result_pairs {ok b 1 output s done executed s yes statements_total i 1 statements_applied i 1}

test rq-retry-1 {transport failures are retried with backoff until accepted} -body {
    set t0 [clock milliseconds]
    ::vmdai::net::post_result k_retry $result_pairs
    set waited [wait_for {expr {![queued k_retry]}} 4000]
    set elapsed [expr {[clock milliseconds] - $t0}]
    list $waited [expr {$elapsed >= 700 && $elapsed < 3000}] [::vmdai::net::result_queue_size] \
        [::vmdai::sched::pending]
} -result {1 1 0 {}}

test rq-dup-1 {a duplicate reply counts as accepted} -body {
    ::vmdai::net::post_result k_dup $result_pairs
    wait_for {expr {![queued k_dup]}}
    list [queued k_dup] [::vmdai::sched::pending]
} -result {0 {}}

test rq-unknown-1 {a permanent RPC error drops the result and logs it} -body {
    ::vmdai::net::post_result k_unknown $result_pairs
    wait_for {expr {![queued k_unknown]}}
    list [queued k_unknown] [::vmdai::sched::pending] \
        [string match "*dropped the result for k_unknown: TOOL_CALL_UNKNOWN*" [plugin_log]]
} -result {0 {} 1}

test rq-once-1 {posting a queued call_key again is ignored} -body {
    ::vmdai::net::post_result k_never $result_pairs
    ::vmdai::net::post_result k_never $result_pairs
    set size [::vmdai::net::result_queue_size]
    wait_for {expr {[dict get $::vmdai::net::queue(k_never) timer] ne ""}}
    list $size [dict get $::vmdai::net::queue(k_never) attempts]
} -result {1 1}

test rq-epoch-1 {an epoch change drops queued results and their timers} -body {
    ::vmdai::net::post_result k_auth $result_pairs
    wait_for {expr {[dict get $::vmdai::net::queue(k_auth) attempts] >= 2}} 3000
    ::vmdai::net::bump_epoch
    set right_after [list [::vmdai::net::result_queue_size] [::vmdai::sched::pending]]
    sleep_ms 1200
    list $right_after [::vmdai::net::result_queue_size] [::vmdai::sched::pending]
} -result {{0 {}} 0 {}}

# rq-epoch-1's CI race, forced: the reply was captured (http token cleaned
# up, after-0 delivery scheduled) but not yet delivered when the epoch
# changes. vwait returns right after the event that ran _http_done, so the
# delivery is still pending, as it was in CI when _http_done ran from the
# channel's buffered-input timer in the same timer pass as wait_for's tick.
test rq-epoch-2 {an epoch change cancels a captured but undelivered result reply} -setup {
    set ::rq_watch k_race
    set ::rq_captured 0
    trace add execution ::vmdai::net::_http_done leave rq_on_http_done
} -body {
    ::vmdai::net::post_result k_race $result_pairs
    set guard [after 3000 {set ::rq_captured timeout}]
    vwait ::rq_captured
    after cancel $guard
    set before [list $::rq_captured [llength [::vmdai::sched::pending]] [http_tokens]]
    ::vmdai::net::bump_epoch
    set right_after [list [::vmdai::net::result_queue_size] [::vmdai::sched::pending]]
    sleep_ms 400
    list $before $right_after [::vmdai::net::result_queue_size] [::vmdai::sched::pending]
} -cleanup {
    trace remove execution ::vmdai::net::_http_done leave rq_on_http_done
} -result {{1 1 0} {0 {}} 0 {}}

# The server has the post and holds its reply 0.6 s when the epoch changes:
# the post is aborted (token reset, cleaned up and unregistered) at once.
test rq-epoch-3 {an epoch change aborts an in-flight result post} -body {
    ::vmdai::net::post_result k_slow $result_pairs
    set received [wait_for {expr {[server_seen k_slow] == 1}}]
    set before [list $received [array size ::vmdai::sched::tokens] [http_tokens]]
    ::vmdai::net::bump_epoch
    set right_after [list [::vmdai::net::result_queue_size] [::vmdai::sched::pending] \
        [array size ::vmdai::sched::tokens] [http_tokens]]
    sleep_ms 700
    list $before $right_after [::vmdai::net::result_queue_size] [::vmdai::sched::pending] \
        [array size ::vmdai::sched::tokens] [http_tokens] \
        [string match "*callback failed*" [plugin_log]]
} -result {{1 1 1} {0 {} 0 0} 0 {} 0 0 0}

cleanupTests
