# tests/tcl/test_net.tcl - net.tcl transport (P06-T03). The pytest wrapper
# serves tests/helpers/fake_rpc_server.py at $env(VMDAI_FAKE_URL) (ASCII JSON)
# and $env(VMDAI_FAKE_UTF8_URL) (raw UTF-8 JSON).
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
source [file join $plugin config.tcl]
source [file join $plugin sched.tcl]
source [file join $plugin net.tcl]
testConstraint http295 [expr {[package present http] eq "2.9.5"}]

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

proc plugin_log {} {
    set path [::vmdai::config::plugin_log_path]
    if {![file exists $path]} { return "" }
    set fh [open $path r]
    set text [read $fh]
    close $fh
    return $text
}

# Collects callback outcomes: ::got(<tag>) = the appended words.
proc collect {tag args} { set ::got($tag) $args }

proc reset_net {{url ""}} {
    if {$url eq ""} { set url $::env(VMDAI_FAKE_URL) }
    array unset ::got
    ::vmdai::net::configure -base_url $url -session_id "" -session_token ""
}

proc http_tokens {} { llength [info vars ::http::\[0-9\]*] }

test net-escape-1 {json_string escapes quotes, backslashes, controls and non-ASCII} -body {
    set r {}
    set arrow [format %c%c%c 0xc5 0x2192 0xb0]
    foreach s [list "" "plain" "a\"b\\c" "t\tn\nr\r" "\x01\x1f\x7f" $arrow "\[x\] \$y \{z\}"] {
        set out [::vmdai::net::json_string $s]
        lappend r $out [expr {$out eq [::vmdai::config::_json_quote $s]}]
    }
    set r
} -result [list {""} 1 {"plain"} 1 {"a\"b\\c"} 1 {"t\u0009n\u000ar\u000d"} 1 \
    "\"\\u0001\\u001f\x7f\"" 1 "\"\\u00c5\\u2192\\u00b0\"" 1 {"[x] $y {z}"} 1]

test net-escape-2 {1 MB of text encodes quickly} -body {
    set big [string repeat "abc\tdef\"ghi[format %c 0xe9] " 70000]
    set us [lindex [time {::vmdai::net::json_string $big}] 0]
    expr {$us < 1000000}
} -result 1

test net-typed-1 {typed params encode in order; s, i, b, j} -body {
    ::vmdai::net::encode_params [list a s x n i 3 f b 1 g b no o j {{"k":1}} neg i -42]
} -result {{"a":"x","n":3,"f":true,"g":false,"o":{"k":1},"neg":-42}}

test net-typed-2 {bad typed params are errors} -body {
    set r {}
    foreach pairs [list {n i 3.5} {n i 08} {n i x} {f b maybe} {o j {}} {x q 1} {a s}] {
        lappend r [catch {::vmdai::net::encode_params $pairs}]
    }
    set r
} -result {1 1 1 1 1 1 1}

test net-typed-3 {default timeouts per method} -body {
    list [::vmdai::net::_default_timeout chat.send {}] \
        [::vmdai::net::_default_timeout chat.events.poll {after_seq i 0 wait_ms i 2000}] \
        [::vmdai::net::_default_timeout chat.events.poll {after_seq i 0}] \
        [::vmdai::net::_default_timeout models.list {}] \
        [::vmdai::net::_default_timeout provider.test {}] \
        [::vmdai::net::_default_timeout runtime.shutdown {}]
} -result {3000 5000 3000 10000 10000 1500}

test net-call-1 {an ok reply is delivered later, never inside net::call} -body {
    reset_net
    ::vmdai::net::configure -session_id sess_typed -session_token tok_typed
    ::vmdai::net::call echo [list name s "a\"b\\c\n" n i 42 flag b yes obj j {{"k":[1,2]}}] {collect typed}
    set sync [info exists ::got(typed)]
    wait_for {info exists ::got(typed)}
    lassign $::got(typed) kind result
    list $sync $kind [dict get $result session_id] [expr {[dict get $result name] eq "a\"b\\c\n"}] \
        [dict get $result n] [dict get $result flag] [dict get $result obj]
} -result {0 ok sess_typed 1 42 true {k {1 2}}}

test net-call-2 {session.start and -session 0 carry no session} -body {
    reset_net
    ::vmdai::net::configure -session_id sess_x -session_token tok_x
    ::vmdai::net::call session.start {cwd s /tmp} {collect start}
    ::vmdai::net::call echo {tag s nosession} {collect plain} -session 0
    wait_for {expr {[info exists ::got(start)] && [info exists ::got(plain)]}}
    list [dict exists [lindex $::got(start) 1] session_id] [dict exists [lindex $::got(plain) 1] session_id]
} -result {0 0}

test net-call-3 {rpc errors: JSON-RPC error body and HTTP 403 FORBIDDEN} -body {
    reset_net
    ::vmdai::net::call fail.rpc {} {collect rpc}
    ::vmdai::net::call fail.403 {} {collect forbidden}
    wait_for {expr {[info exists ::got(rpc)] && [info exists ::got(forbidden)]}}
    list $::got(rpc) [lrange $::got(forbidden) 0 1]
} -result {{rpc_error NO_MODEL {No model configured} {action open_settings}} {rpc_error FORBIDDEN}}

test net-call-4 {transport errors: undecodable body, timeout, refused port, no address} -body {
    reset_net
    ::vmdai::net::call fail.garbage {} {collect garbage}
    ::vmdai::net::call slow {} {collect timeout} -timeout 200
    wait_for {expr {[info exists ::got(garbage)] && [info exists ::got(timeout)]}}
    set srv [socket -server {apply {{c a p} {close $c}}} -myaddr 127.0.0.1 0]
    set dead [lindex [fconfigure $srv -sockname] 2]
    close $srv
    ::vmdai::net::configure -base_url http://127.0.0.1:$dead
    ::vmdai::net::call echo {} {collect refused}
    ::vmdai::net::configure -base_url ""
    ::vmdai::net::call echo {} {collect noaddr}
    wait_for {expr {[info exists ::got(refused)] && [info exists ::got(noaddr)]}}
    list $::got(garbage) $::got(timeout) [lindex $::got(refused) 0] $::got(noaddr) \
        [::vmdai::sched::pending] [http_tokens]
} -result {{transport {undecodable response: not a JSON object}} {transport timeout} transport {transport {no runtime address}} {} 0}

test net-epoch-1 {a reply from an older epoch is dropped and its token cleaned up} -body {
    reset_net
    ::vmdai::net::call slow.short {} {collect stale}
    set before [::vmdai::net::epoch]
    ::vmdai::net::bump_epoch
    wait_for {expr {[http_tokens] == 0}} 3000
    set ::after_wait 0
    after 200 {set ::after_wait 1}
    vwait ::after_wait
    list [expr {[::vmdai::net::epoch] == $before + 1}] [info exists ::got(stale)] \
        [http_tokens] [array size ::vmdai::sched::tokens] [::vmdai::sched::pending] \
        [string match "*dropped a reply from epoch*" [plugin_log]]
} -result {1 0 0 0 {} 1}

test net-deliver-1 {a throwing handler is logged and later replies still arrive} -body {
    reset_net
    # Both calls are in flight together; the replies may come back in either
    # order, so wait until the handler has thrown and the second has arrived.
    ::vmdai::net::call echo {n i 1} {apply {{args} {error "boom-handler"}}}
    ::vmdai::net::call echo {n i 2} {collect second}
    set done [wait_for {expr {[info exists ::got(second)]
                              && [string match "*boom-handler*" [plugin_log]]}}]
    list [lindex $::got(second) 0] $done
} -result {ok 1}

test net-sync-1 {call_sync returns the result or raises with an errorcode} -body {
    reset_net
    set ok [::vmdai::net::call_sync echo {n i 7}]
    set code [catch {::vmdai::net::call_sync fail.rpc {}} msg opts]
    list [dict get $ok n] $code [dict get $opts -errorcode] $msg
} -result {7 1 {VMDAI RPC NO_MODEL} {NO_MODEL: No model configured}}

test net-get-1 {http_get delivers the decoded /health body} -body {
    reset_net
    ::vmdai::net::http_get /health {collect health}
    wait_for {info exists ::got(health)}
    lassign $::got(health) kind body
    list $kind [dict get $body ok] [dict get $body protocol]
} -result {ok true 2}

test net-get-2 {health probes are never dropped by an epoch change} -body {
    reset_net
    ::vmdai::net::http_get /health {collect health2}
    ::vmdai::net::bump_epoch
    wait_for {info exists ::got(health2)}
    lindex $::got(health2) 0
} -result ok

test net-s8-1 {S8: Unicode round-trips through ASCII and UTF-8 replies with http 2.9.5} -constraints http295 -body {
    set text [format %c%c%c 0xc5 0x2192 0xb0]
    set r {}
    foreach url [list $::env(VMDAI_FAKE_URL) $::env(VMDAI_FAKE_UTF8_URL)] {
        reset_net $url
        ::vmdai::net::call echo [list text s $text] {collect s8}
        wait_for {info exists ::got(s8)}
        lappend r [lindex $::got(s8) 0] [expr {[dict get [lindex $::got(s8) 1] text] eq $text}]
    }
    set r
} -result {ok 1 ok 1}

cleanupTests
