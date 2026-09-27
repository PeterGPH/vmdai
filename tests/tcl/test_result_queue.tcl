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

cleanupTests
