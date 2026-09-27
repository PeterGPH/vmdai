# net.tcl - JSON encoding and decoding, the async JSON-RPC transport, after-0
# delivery and the epoch (spec 2d, 3 Tcl interfaces). No Tk.
#
# Callback forms (the callback is a command prefix; these words are appended):
#   ok <result>
#   rpc_error <code> <message> <data>
#   transport <reason>
# Callbacks always run later, from the event loop, never inside net::call.

package require http 2
::vmdai::config::require_json

namespace eval ::vmdai::net {
    variable base_url
    if {![info exists base_url]} { set base_url "" }
    variable session_id
    if {![info exists session_id]} { set session_id "" }
    variable session_token
    if {![info exists session_token]} { set session_token "" }
    variable epoch
    if {![info exists epoch]} { set epoch 0 }
    variable seq
    if {![info exists seq]} { set seq 0 }
    # inflight(<rid>) = http token until the http callback for that request
    # ran (1 while http::geturl itself runs).
    variable inflight
    if {![info exists inflight]} { array set inflight {} }
    # delivery(<rid>) = sched id of the after-0 delivery that has not run yet.
    variable delivery
    if {![info exists delivery]} { array set delivery {} }

    # Control characters, backslash and quote -> JSON escapes.
    variable escape_map [list "\\" "\\\\" "\"" "\\\""]
    for {set i 0} {$i < 32} {incr i} {
        lappend escape_map [format %c $i] [format "\\u%04x" $i]
    }
    unset i
}

proc ::vmdai::net::_log {msg} {
    catch {::vmdai::config::log "net: $msg"}
}

# One JSON string literal, ASCII only (non-ASCII becomes \uXXXX).
proc ::vmdai::net::json_string {s} {
    variable escape_map
    set s [string map $escape_map $s]
    if {[regexp {[^\u0000-\u007f]} $s]} {
        set wide {}
        foreach ch [lsort -unique [regexp -all -inline {[^\u0000-\u007f]} $s]] {
            lappend wide $ch [format "\\u%04x" [scan $ch %c]]
        }
        set s [string map $wide $s]
    }
    return "\"$s\""
}

# Typed params: a flat list {name type value ...}; type is s (string),
# i (integer), b (boolean) or j (JSON text, inserted verbatim).
proc ::vmdai::net::encode_params {pairs} {
    if {[llength $pairs] % 3 != 0} {
        error "encode_params: expected name type value triples, got [llength $pairs] words"
    }
    set parts {}
    foreach {name type value} $pairs {
        switch -- $type {
            s { set json [json_string $value] }
            i {
                if {![regexp {^-?(0|[1-9][0-9]*)$} $value]} {
                    error "encode_params: $name is not an integer: \"$value\""
                }
                set json $value
            }
            b {
                if {![string is boolean -strict $value]} {
                    error "encode_params: $name is not a boolean: \"$value\""
                }
                set json [expr {[string is true -strict $value] ? "true" : "false"}]
            }
            j {
                if {[string trim $value] eq ""} {
                    error "encode_params: $name has empty JSON"
                }
                set json $value
            }
            default { error "encode_params: unknown type \"$type\" for $name" }
        }
        lappend parts "[json_string $name]:$json"
    }
    return "\{[join $parts ,]\}"
}

# Decode a JSON object into a dict; errors when the body is not one.
proc ::vmdai::net::decode {body} {
    set text [string trim $body]
    if {[string index $text 0] ne "\{" || [string index $text end] ne "\}"} {
        error "not a JSON object"
    }
    set value [::json::json2dict $text]
    if {[catch {dict size $value}]} {
        error "not a JSON object"
    }
    return $value
}

proc ::vmdai::net::configure {args} {
    variable base_url
    variable session_id
    variable session_token
    if {[llength $args] == 0} {
        return [list -base_url $base_url -session_id $session_id -session_token $session_token]
    }
    if {[llength $args] % 2 != 0} {
        error "net::configure: expected option value pairs"
    }
    foreach {option value} $args {
        switch -- $option {
            -base_url { set base_url [string trimright $value /] }
            -session_id { set session_id $value }
            -session_token { set session_token $value }
            default { error "net::configure: unknown option $option" }
        }
    }
    return
}

proc ::vmdai::net::epoch {} {
    variable epoch
    return $epoch
}

# New session, resume and shutdown bump the epoch: replies issued under an
# older epoch are dropped (their http tokens are still cleaned up). Queued
# results of an older epoch are given up at once: their retry timers and
# pending deliveries are cancelled and their in-flight posts aborted.
proc ::vmdai::net::bump_epoch {} {
    variable epoch
    incr epoch
    _queue_drop_stale
    return $epoch
}

proc ::vmdai::net::_default_timeout {method pairs} {
    switch -- $method {
        models.list - provider.test { return 10000 }
        runtime.shutdown { return 1500 }
        chat.events.poll {
            foreach {name type value} $pairs {
                if {$name eq "wait_ms" && [string is integer -strict $value]} {
                    return [expr {$value + 3000}]
                }
            }
        }
    }
    return $::vmdai::config::request_timeout_ms
}

# Build {url body headers timeout id} for one RPC.
proc ::vmdai::net::_prepare {method params options} {
    variable base_url
    variable session_id
    variable session_token
    variable seq
    set timeout ""
    set use_session [expr {$method ne "session.start"}]
    foreach {option value} $options {
        switch -- $option {
            -timeout { set timeout $value }
            -session { set use_session [string is true -strict $value] }
            default { error "net::call: unknown option $option" }
        }
    }
    if {$timeout eq ""} {
        set timeout [_default_timeout $method $params]
    }
    set headers {}
    if {$use_session && $session_id ne ""} {
        set params [linsert $params 0 session_id s $session_id]
        if {$session_token ne ""} {
            lappend headers X-Session-Token $session_token
        }
    }
    set id "tcl_[format %06d [incr seq]]"
    set body "\{\"jsonrpc\":\"2.0\",\"id\":[json_string $id],\"method\":[json_string $method],\"params\":[encode_params $params]\}"
    return [list "$base_url/rpc" $body $headers $timeout $id]
}

# One outcome list (ok ... | rpc_error ... | transport ...) from an http reply.
proc ::vmdai::net::_classify {status ncode body err} {
    if {$status ne "ok"} {
        if {$err ne ""} {
            return [list transport "$status: $err"]
        }
        return [list transport $status]
    }
    if {[catch {decode $body} decoded]} {
        if {$ncode ne "200"} {
            return [list transport "HTTP $ncode"]
        }
        return [list transport "undecodable response: $decoded"]
    }
    if {[dict exists $decoded error]} {
        set e [dict get $decoded error]
        if {[catch {dict exists $e code} has] || !$has} {
            return [list rpc_error ERROR $e {}]
        }
        set message ""
        set data {}
        catch {set message [dict get $e message]}
        catch {set data [dict get $e data]}
        return [list rpc_error [dict get $e code] $message $data]
    }
    if {$ncode ne "200"} {
        return [list transport "HTTP $ncode"]
    }
    if {[dict exists $decoded result]} {
        return [list ok [dict get $decoded result]]
    }
    return [list transport "response has neither result nor error"]
}

# Run a callback with its outcome words; failures go to the plugin log.
proc ::vmdai::net::deliver {callback args} {
    if {[catch {uplevel #0 [list {*}$callback {*}$args]} err]} {
        _log "callback failed ($callback [lindex $args 0]): $::errorInfo"
    }
    return
}

# call_epoch "" (health probes) is never stale.
proc ::vmdai::net::_deliver_if_current {call_epoch callback args} {
    variable epoch
    if {$call_epoch ne "" && $call_epoch != $epoch} {
        _log "dropped a reply from epoch $call_epoch (now $epoch)"
        return
    }
    deliver $callback {*}$args
}

proc ::vmdai::net::_later {rid call_epoch callback outcome} {
    variable delivery
    set id [::vmdai::sched::after 0 \
        [list ::vmdai::net::_deliver $rid $call_epoch $callback {*}$outcome]]
    if {$id ne ""} {
        set delivery($rid) $id
    }
}

proc ::vmdai::net::_deliver {rid call_epoch callback args} {
    variable delivery
    unset -nocomplain delivery($rid)
    _deliver_if_current $call_epoch $callback {*}$args
}

# Give up request $rid: cancel its pending delivery and, if it is still in
# flight, reset its http request. Its callback never runs.
proc ::vmdai::net::abort {rid} {
    variable inflight
    variable delivery
    if {[info exists delivery($rid)]} {
        ::vmdai::sched::cancel $delivery($rid)
        unset delivery($rid)
    }
    if {![info exists inflight($rid)]} {
        return
    }
    set token $inflight($rid)
    unset inflight($rid)
    ::vmdai::sched::untrack_http $token
    # reset runs the -command callback, which finds $rid no longer in flight
    # and only cleans up the token. A second http::cleanup would re-create
    # the token variable, so clean up here only if reset left it behind.
    catch {::http::reset $token}
    if {[info exists $token]} {
        catch {::http::cleanup $token}
    }
    return
}

# http -command callback: capture, clean up, then hand off with after 0.
# http runs this inside `catch`, so it must not rely on errors surfacing.
proc ::vmdai::net::_http_done {rid call_epoch callback kind token} {
    variable inflight
    variable epoch
    if {![info exists inflight($rid)]} {
        # net::abort gave this request up (it resets the token).
        catch {::http::cleanup $token}
        return
    }
    unset inflight($rid)
    ::vmdai::sched::untrack_http $token
    set status error
    set ncode ""
    set body ""
    set err ""
    catch {set status [::http::status $token]}
    catch {set ncode [::http::ncode $token]}
    catch {set body [::http::data $token]}
    catch {set err [::http::error $token]}
    catch {::http::cleanup $token}
    if {$call_epoch ne "" && $call_epoch != $epoch} {
        _log "dropped a reply from epoch $call_epoch (now $epoch)"
        return
    }
    if {$kind eq "get"} {
        set outcome [_classify_get $status $ncode $body $err]
    } else {
        set outcome [_classify $status $ncode $body $err]
    }
    _later $rid $call_epoch $callback $outcome
}

proc ::vmdai::net::_geturl {rid callback kind call_epoch url args} {
    variable inflight
    set inflight($rid) 1
    set cmd [list ::vmdai::net::_http_done $rid $call_epoch $callback $kind]
    if {[catch {::http::geturl $url {*}$args -command $cmd} token]} {
        unset -nocomplain inflight($rid)
        _later $rid $call_epoch $callback [list transport "connect failed: $token"]
        return $rid
    }
    if {[info exists inflight($rid)]} {
        set inflight($rid) $token
        ::vmdai::sched::track_http $token
    }
    return $rid
}

# Asynchronous JSON-RPC call. Returns a request id.
proc ::vmdai::net::call {method params callback args} {
    variable base_url
    variable epoch
    lassign [_prepare $method $params $args] url body headers timeout id
    set rid "rpc#$id"
    if {$base_url eq ""} {
        _later $rid $epoch $callback [list transport "no runtime address"]
        return $rid
    }
    return [_geturl $rid $callback rpc $epoch $url -query $body -type application/json \
        -headers $headers -timeout $timeout -keepalive 0]
}

# Synchronous call for the console and tests only (it nests the event loop).
# Returns the result; errors carry -errorcode {VMDAI RPC code} or {VMDAI TRANSPORT}.
proc ::vmdai::net::call_sync {method params args} {
    lassign [_prepare $method $params $args] url body headers timeout id
    if {[catch {::http::geturl $url -query $body -type application/json \
            -headers $headers -timeout $timeout -keepalive 0} token]} {
        return -code error -errorcode {VMDAI TRANSPORT} "connect failed: $token"
    }
    set outcome [_classify [::http::status $token] [::http::ncode $token] \
        [::http::data $token] [::http::error $token]]
    ::http::cleanup $token
    switch -- [lindex $outcome 0] {
        ok { return [lindex $outcome 1] }
        rpc_error {
            return -code error -errorcode [list VMDAI RPC [lindex $outcome 1]] \
                "[lindex $outcome 1]: [lindex $outcome 2]"
        }
        default {
            return -code error -errorcode {VMDAI TRANSPORT} [lindex $outcome 1]
        }
    }
}

proc ::vmdai::net::_classify_get {status ncode body err} {
    if {$status ne "ok"} {
        if {$err ne ""} {
            return [list transport "$status: $err"]
        }
        return [list transport $status]
    }
    if {[catch {decode $body} decoded]} {
        return [list transport "HTTP $ncode, undecodable body"]
    }
    if {$ncode ne "200"} {
        return [_classify $status $ncode $body $err]
    }
    return [list ok $decoded]
}

# GET <base_url><path> (e.g. /health); the callback gets `ok <dict>` with the
# whole decoded body, or `rpc_error ...` / `transport ...`. Health probes
# belong to the runtime, not to a session, so the epoch never drops them.
proc ::vmdai::net::http_get {path callback args} {
    variable base_url
    variable seq
    set timeout $::vmdai::config::request_timeout_ms
    foreach {option value} $args {
        switch -- $option {
            -timeout { set timeout $value }
            default { error "net::http_get: unknown option $option" }
        }
    }
    set rid "get#[incr seq]"
    if {$base_url eq ""} {
        _later $rid "" $callback [list transport "no runtime address"]
        return $rid
    }
    return [_geturl $rid $callback get "" "$base_url$path" -timeout $timeout -keepalive 0]
}

# --- Result queue (spec 2d Post, 5 "Result post fails") -------------------
# tool.command_result posts are retried (0.25 s doubling to 2 s) until the
# runtime accepts them or the epoch changes. The runtime dedupes by call_key
# and answers {accepted, late, duplicate}; a duplicate counts as accepted.

namespace eval ::vmdai::net {
    # queue(<call_key>) = dict {pairs epoch delay timer rid attempts}; rid is
    # the request id of the latest post.
    variable queue
    if {![info exists queue]} { array set queue {} }
    variable retry_min_ms 250
    variable retry_max_ms 2000
}

# result_pairs: typed pairs for tool.command_result, without call_key.
proc ::vmdai::net::post_result {call_key result_pairs} {
    variable queue
    variable epoch
    variable retry_min_ms
    if {[info exists queue($call_key)]} {
        _log "result for $call_key is already queued"
        return
    }
    set queue($call_key) [dict create pairs [linsert $result_pairs 0 call_key s $call_key] \
        epoch $epoch delay $retry_min_ms timer "" rid "" attempts 0]
    _queue_send $call_key
}

proc ::vmdai::net::result_queue_size {} {
    variable queue
    return [array size queue]
}

proc ::vmdai::net::_queue_send {call_key} {
    variable queue
    variable epoch
    if {![info exists queue($call_key)]} {
        return
    }
    set entry $queue($call_key)
    if {[dict get $entry epoch] != $epoch} {
        unset queue($call_key)
        return
    }
    dict set entry timer ""
    dict incr entry attempts
    set queue($call_key) $entry
    set rid [call tool.command_result [dict get $entry pairs] \
        [list ::vmdai::net::_queue_reply $call_key]]
    dict set queue($call_key) rid $rid
}

proc ::vmdai::net::_queue_reply {call_key kind args} {
    variable queue
    if {![info exists queue($call_key)]} {
        return
    }
    switch -- $kind {
        ok {
            set reply [lindex $args 0]
            set accepted 0
            set duplicate 0
            catch {set accepted [string is true -strict [dict get $reply accepted]]}
            catch {set duplicate [string is true -strict [dict get $reply duplicate]]}
            if {!$accepted && !$duplicate} {
                _log "runtime did not accept the result for $call_key: $reply"
            }
            unset queue($call_key)
        }
        rpc_error {
            lassign $args code message
            if {$code in {TOOL_CALL_UNKNOWN INVALID_PARAMS METHOD_NOT_FOUND}} {
                _log "dropped the result for $call_key: $code $message"
                unset queue($call_key)
                return
            }
            _queue_retry $call_key "$code: $message"
        }
        default {
            _queue_retry $call_key [lindex $args 0]
        }
    }
}

proc ::vmdai::net::_queue_retry {call_key reason} {
    variable queue
    variable retry_max_ms
    set entry $queue($call_key)
    set delay [dict get $entry delay]
    _log "result for $call_key not delivered ($reason); retrying in $delay ms"
    dict set entry delay [expr {min($delay * 2, $retry_max_ms)}]
    dict set entry timer [::vmdai::sched::after $delay [list ::vmdai::net::_queue_send $call_key]]
    set queue($call_key) $entry
}

# A post of an older epoch may be waiting for its retry timer, in flight, or
# answered with its delivery still pending; all three are cancelled here, so
# an epoch change leaves no timer, delivery or http token behind.
proc ::vmdai::net::_queue_drop_stale {} {
    variable queue
    variable epoch
    foreach call_key [array names queue] {
        set entry $queue($call_key)
        if {[dict get $entry epoch] != $epoch} {
            unset queue($call_key)
            ::vmdai::sched::cancel [dict get $entry timer]
            abort [dict get $entry rid]
        }
    }
}
