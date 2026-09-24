namespace eval ::vmdai::bridge {
    variable runtime_pid ""
    variable session_id ""
    variable session_token ""
    variable chat_id ""
    variable after_seq 0
    variable active_request_id ""
    variable poll_after_id ""
    variable req_counter 0
    variable has_json 0
    variable initialized 0
    variable is_resumed_chat 0
}

proc ::vmdai::bridge::_current_conv_mode {} {
    variable is_resumed_chat
    if {$is_resumed_chat} {
        return "hybrid_resume"
    }
    return "local_first"
}

proc ::vmdai::bridge::init {} {
    variable initialized
    variable has_json
    if {$initialized} {
        return
    }
    package require http
    if {[catch {package require json}]} {
        set has_json 0
    } else {
        set has_json 1
    }
    set initialized 1
}

proc ::vmdai::bridge::_json_escape {value} {
    # Produce a pure-ASCII JSON string. Three reasons we don't just
    # string-map the common escapes and call it done:
    #   1. JSON forbids ALL control chars (U+0000-U+001F) inside a
    #      string. Python's strict json.loads rejects any that leak in.
    #   2. Tcl's http::geturl doesn't always send non-ASCII as UTF-8
    #      bytes — depending on channel encoding, a stray "▎" or other
    #      Unicode char from a pasted prompt can corrupt the body.
    #   3. \uXXXX escapes are ASCII-only and universally interpretable,
    #      so the wire format is the same regardless of platform.
    set out ""
    foreach ch [split $value ""] {
        scan $ch %c code
        switch -- $ch {
            "\\" { append out "\\\\" }
            "\"" { append out "\\\"" }
            "\b" { append out "\\b" }
            "\f" { append out "\\f" }
            "\n" { append out "\\n" }
            "\r" { append out "\\r" }
            "\t" { append out "\\t" }
            default {
                if {$code < 32 || $code > 126} {
                    append out [format "\\u%04x" $code]
                } else {
                    append out $ch
                }
            }
        }
    }
    return $out
}

proc ::vmdai::bridge::_json_quote {value} {
    return "\"[::vmdai::bridge::_json_escape $value]\""
}

proc ::vmdai::bridge::_json_kv {key value_json} {
    return "[::vmdai::bridge::_json_quote $key]:$value_json"
}

proc ::vmdai::bridge::_json_object {kvs} {
    return "\{[join $kvs ,]\}"
}

proc ::vmdai::bridge::_rpc {method params_json} {
    variable req_counter
    variable session_token
    ::vmdai::bridge::init

    set req_counter [expr {$req_counter + 1}]
    set request_id "tcl_[format %06d $req_counter]"
    set payload [::vmdai::bridge::_json_object [list \
        [::vmdai::bridge::_json_kv jsonrpc [::vmdai::bridge::_json_quote "2.0"]] \
        [::vmdai::bridge::_json_kv id [::vmdai::bridge::_json_quote $request_id]] \
        [::vmdai::bridge::_json_kv method [::vmdai::bridge::_json_quote $method]] \
        [::vmdai::bridge::_json_kv params $params_json] \
    ]]

    set headers [list Content-Type application/json]
    if {$session_token ne ""} {
        lappend headers X-Session-Token $session_token
    }

    set url "[::vmdai::config::runtime_url]/rpc"

    # Guard against socket-level failures (connection reset, channel closed).
    if {[catch {
        set token [http::geturl $url -method POST -headers $headers -query $payload -timeout $::vmdai::config::request_timeout_ms]
    } sock_err]} {
        error "RPC transport error ($method): $sock_err"
    }

    # Read + cleanup — also guarded so a partial response doesn't leak the token.
    set http_status [http::status $token]
    if {$http_status ne "ok"} {
        set http_error [http::error $token]
        http::cleanup $token
        error "RPC HTTP error ($method): status=$http_status $http_error"
    }

    set data [http::data $token]
    http::cleanup $token
    return $data
}

proc ::vmdai::bridge::_response_error {body} {
    ::vmdai::bridge::init
    variable has_json

    if {$has_json} {
        if {[catch {set parsed [::json::json2dict $body]}]} {
            return ""
        }
        if {![dict exists $parsed error]} {
            return ""
        }
        set err [dict get $parsed error]
        if {[catch {dict size $err}]} {
            if {[string trim $err] ne ""} {
                return [string trim $err]
            }
            return "Unknown RPC error"
        }
        if {[dict exists $err message]} {
            set msg [dict get $err message]
            if {[string trim $msg] ne ""} {
                return $msg
            }
        }
        return "Unknown RPC error"
    }

    # Regex fallback (no json package).
    # A successful JSON-RPC response has "result"; an error has "error" at top level.
    # We must NOT false-positive on event data like {"role":"error",...} inside "result".
    if {[regexp {"result"\s*:} $body]} {
        return ""
    }
    if {![regexp {"error"\s*:} $body]} {
        return ""
    }
    if {[regexp {"message"\s*:\s*"((?:\\.|[^"])*)"} $body -> msg]} {
        return [string map [list "\\n" "\n" "\\r" "\r" "\\t" "\t" "\\\"" "\"" "\\\\" "\\"] $msg]
    }
    return "Unknown RPC error"
}

proc ::vmdai::bridge::_extract_string {body key} {
    set pattern [format {"%s"\s*:\s*"((?:\\.|[^"])*)"} $key]
    if {[regexp $pattern $body -> out]} {
        set out [string map [list "\\n" "\n" "\\r" "\r" "\\t" "\t" "\\\"" "\"" "\\\\" "\\"] $out]
        return $out
    }
    return ""
}

proc ::vmdai::bridge::_extract_int {body key default} {
    set pattern [format {"%s"\s*:\s*(\d+)} $key]
    if {[regexp $pattern $body -> out]} {
        return $out
    }
    return $default
}

proc ::vmdai::bridge::_parse_events_fallback {body} {
    set events [list]
    set matches [regexp -inline -all {\{[^\{\}]*"seq"[^\{\}]*\}} $body]
    foreach item $matches {
        set role [::vmdai::bridge::_extract_string $item role]
        set etype [::vmdai::bridge::_extract_string $item type]
        set text [::vmdai::bridge::_extract_string $item text]
        set request_id [::vmdai::bridge::_extract_string $item request_id]
        set ev [dict create role $role type $etype text $text metadata [dict create request_id $request_id]]
        lappend events $ev
    }
    return $events
}

proc ::vmdai::bridge::_parse_events {body} {
    variable has_json
    if {$has_json} {
        if {[catch {set parsed [::json::json2dict $body]} parse_err]} {
            # Non-JSON body (e.g. "END", empty, or corrupted) — fall through to regex
            return [::vmdai::bridge::_parse_events_fallback $body]
        }
        if {![dict exists $parsed result events]} {
            return [list]
        }
        set out [list]
        foreach ev [dict get $parsed result events] {
            set metadata [dict create]
            if {[dict exists $ev metadata]} {
                set metadata [dict get $ev metadata]
            }
            lappend out [dict create \
                role [dict get $ev role] \
                type [dict get $ev type] \
                text [dict get $ev text] \
                metadata $metadata]
        }
        return $out
    }
    return [::vmdai::bridge::_parse_events_fallback $body]
}

proc ::vmdai::bridge::_health_ok {} {
    ::vmdai::bridge::init
    set token [http::geturl "[::vmdai::config::runtime_url]/health" -timeout 600]
    set data [http::data $token]
    set status [http::status $token]
    http::cleanup $token
    if {$status ne "ok"} {
        return 0
    }
    return [expr {[string first "\"ok\": true" $data] >= 0 || [string first "\"ok\":true" $data] >= 0}]
}

proc ::vmdai::bridge::ensure_runtime {} {
    variable session_id
    if {$session_id ne ""} {
        return
    }
    ::vmdai::bridge::start_runtime
    ::vmdai::bridge::start_session
    ::vmdai::bridge::schedule_poll
}

proc ::vmdai::bridge::start_runtime {} {
    variable runtime_pid
    if {[catch {::vmdai::bridge::_health_ok} ok] == 0 && $ok} {
        return
    }

    set cmd [list $::vmdai::config::python_exec $::vmdai::config::runtime_main --host $::vmdai::config::host --port $::vmdai::config::port]
    set runtime_pid [exec {*}$cmd >> $::vmdai::config::runtime_log 2>> $::vmdai::config::runtime_log &]

    set started 0
    for {set i 0} {$i < 40} {incr i} {
        after 100
        if {[catch {::vmdai::bridge::_health_ok} ok] == 0 && $ok} {
            set started 1
            break
        }
    }
    if {!$started} {
        ::vmdai::ui::append_message error "Runtime failed to become healthy."
    }
}

proc ::vmdai::bridge::start_session {} {
    variable session_id
    variable session_token
    variable chat_id
    variable after_seq

    set params [::vmdai::bridge::_json_object [list \
        [::vmdai::bridge::_json_kv cwd [::vmdai::bridge::_json_quote [pwd]]] \
        [::vmdai::bridge::_json_kv ui_mode [::vmdai::bridge::_json_quote "qt"]] \
        [::vmdai::bridge::_json_kv client_version [::vmdai::bridge::_json_quote "vmd-plugin-skeleton"]] \
        [::vmdai::bridge::_json_kv platform [::vmdai::bridge::_json_quote $::tcl_platform(os)]] \
    ]]
    if {[catch {set body [::vmdai::bridge::_rpc "session.start" $params]} rpc_err]} {
        ::vmdai::ui::append_message error "session.start transport failed: $rpc_err"
        return
    }
    set err [::vmdai::bridge::_response_error $body]
    if {$err ne ""} {
        ::vmdai::ui::append_message error "session.start failed: $err"
        return
    }
    set session_id [::vmdai::bridge::_extract_string $body session_id]
    set session_token [::vmdai::bridge::_extract_string $body session_token]
    set chat_id [::vmdai::bridge::_extract_string $body chat_id]
    set after_seq 0
}

proc ::vmdai::bridge::send_chat {text} {
    variable session_id
    variable chat_id
    variable active_request_id

    if {$session_id eq ""} {
        ::vmdai::bridge::ensure_runtime
    }

    # Pull the current model from the UI's provider picker so the
    # runtime sees whichever model the user selected. Falls back to the
    # historical default if the UI hasn't initialized yet (e.g. headless
    # smoke tests calling send_chat directly).
    set picked_model "anthropic/claude-sonnet-4.6"
    if {[info exists ::vmdai::ui::model_name] \
            && [string trim $::vmdai::ui::model_name] ne ""} {
        set picked_model $::vmdai::ui::model_name
    }

    set params [::vmdai::bridge::_json_object [list \
        [::vmdai::bridge::_json_kv session_id [::vmdai::bridge::_json_quote $session_id]] \
        [::vmdai::bridge::_json_kv chat_id [::vmdai::bridge::_json_quote $chat_id]] \
        [::vmdai::bridge::_json_kv text [::vmdai::bridge::_json_quote $text]] \
        [::vmdai::bridge::_json_kv model [::vmdai::bridge::_json_quote $picked_model]] \
        [::vmdai::bridge::_json_kv mode [::vmdai::bridge::_json_quote "work"]] \
        [::vmdai::bridge::_json_kv conversation_mode [::vmdai::bridge::_json_quote [::vmdai::bridge::_current_conv_mode]]] \
    ]]

    if {[catch {set body [::vmdai::bridge::_rpc "chat.send" $params]} err]} {
        ::vmdai::ui::append_message error "chat.send transport failed: $err"
        return
    }
    set rpcerr [::vmdai::bridge::_response_error $body]
    if {$rpcerr ne ""} {
        ::vmdai::ui::append_message error "chat.send failed: $rpcerr"
        return
    }
    set active_request_id [::vmdai::bridge::_extract_string $body request_id]
}

proc ::vmdai::bridge::cancel_active {} {
    variable session_id
    variable active_request_id
    if {$session_id eq "" || $active_request_id eq ""} {
        return
    }
    set params [::vmdai::bridge::_json_object [list \
        [::vmdai::bridge::_json_kv session_id [::vmdai::bridge::_json_quote $session_id]] \
        [::vmdai::bridge::_json_kv request_id [::vmdai::bridge::_json_quote $active_request_id]] \
    ]]
    catch {::vmdai::bridge::_rpc "chat.cancel" $params}
}

proc ::vmdai::bridge::poll_once {} {
    variable session_id
    variable after_seq
    variable active_request_id

    if {$session_id eq ""} {
        ::vmdai::bridge::schedule_poll
        return
    }

    set params [::vmdai::bridge::_json_object [list \
        [::vmdai::bridge::_json_kv session_id [::vmdai::bridge::_json_quote $session_id]] \
        [::vmdai::bridge::_json_kv after_seq $after_seq] \
        [::vmdai::bridge::_json_kv limit $::vmdai::config::poll_limit] \
    ]]

    if {[catch {set body [::vmdai::bridge::_rpc "chat.events.poll" $params]} err]} {
        ::vmdai::ui::append_message error "poll failed: $err"
        ::vmdai::bridge::schedule_poll
        return
    }

    set rpcerr [::vmdai::bridge::_response_error $body]
    if {$rpcerr ne ""} {
        ::vmdai::ui::append_message error "poll rpc error: $rpcerr"
        ::vmdai::bridge::schedule_poll
        return
    }

    set events [::vmdai::bridge::_parse_events $body]
    foreach ev $events {
        set role [::vmdai::ui::_dict_get_or $ev role system]
        # Dispatch tool_start events to the VMD executor; pass all others to the UI.
        if {$role eq "tool_start"} {
            ::vmdai::bridge::_handle_tool_start $ev
        } else {
            ::vmdai::ui::render_event $ev
        }
    }

    set last_seq [::vmdai::bridge::_extract_int $body last_seq $after_seq]
    set after_seq $last_seq

    if {[regexp {"cancelled"} $body]} {
        set active_request_id ""
    }

    ::vmdai::bridge::schedule_poll
}

# ---------------------------------------------------------------------------
# VMD tool execution
# ---------------------------------------------------------------------------

proc ::vmdai::bridge::_handle_tool_start {event} {
    # Extract metadata fields
    set tool_call_id [::vmdai::ui::_dict_get_or \
        [::vmdai::ui::_dict_get_or $event metadata [dict create]] \
        tool_call_id ""]
    set tool_name [::vmdai::ui::_dict_get_or \
        [::vmdai::ui::_dict_get_or $event metadata [dict create]] \
        tool_name ""]
    set tool_input [::vmdai::ui::_dict_get_or \
        [::vmdai::ui::_dict_get_or $event metadata [dict create]] \
        tool_input [dict create]]

    if {$tool_call_id eq ""} {
        ::vmdai::ui::append_message error "tool_start: missing tool_call_id"
        return
    }

    # Show what we're doing in the transcript
    set label [::vmdai::ui::_dict_get_or $event text ""]
    if {$label ne ""} {
        ::vmdai::ui::append_message system $label
    }

    if {$tool_name eq "run_vmd_command"} {
        ::vmdai::bridge::_exec_vmd_command $tool_call_id $tool_input
    } elseif {$tool_name eq "capture_vmd_snapshot"} {
        ::vmdai::bridge::_exec_capture_snapshot $tool_call_id $tool_input
    } else {
        ::vmdai::bridge::_post_command_result $tool_call_id 0 "" \
            "Unknown tool: $tool_name" ""
    }
}

proc ::vmdai::bridge::_exec_vmd_command {tool_call_id tool_input} {
    variable session_id

    # Extract command string from tool_input dict
    set command ""
    if {[dict exists $tool_input command]} {
        set command [dict get $tool_input command]
    }

    if {[string trim $command] eq ""} {
        ::vmdai::bridge::_post_command_result $tool_call_id 0 "" \
            "Empty command" ""
        return
    }

    # Execute the command, treating it as a sequence of complete Tcl
    # statements. Multi-line constructs (foreach, for, proc, while, etc.)
    # span newlines and have braces that close on later lines; we must NOT
    # evaluate line-by-line. Instead, accumulate lines in a buffer and use
    # `info complete` to detect when the buffer forms a balanced statement
    # — the same pattern an interactive Tcl REPL uses. This handles single
    # one-liners, multiple `;`-separated statements on a line, and arbitrary
    # multi-line blocks.
    set lines [split $command "\n"]
    set all_output ""
    set had_error 0
    set error_msg ""
    set buf ""

    foreach raw_line $lines {
        if {$buf eq ""} {
            set trimmed [string trim $raw_line]
            # Skip blank lines and full-line comments only between statements.
            if {$trimmed eq "" || [string index $trimmed 0] eq "#"} {
                continue
            }
        }
        append buf $raw_line "\n"
        if {![info complete $buf]} {
            # Brace/quote still unclosed — keep accumulating.
            continue
        }
        # Buffer is a complete Tcl statement (or sequence of statements).
        set stmt [string trim $buf]
        set buf ""
        if {$stmt eq ""} { continue }

        if {[catch {uplevel #0 $stmt} result]} {
            set had_error 1
            # Truncate huge statements in the error message so we don't
            # blow up the chat transcript.
            set preview $stmt
            if {[string length $preview] > 200} {
                set preview "[string range $preview 0 197]..."
            }
            set error_msg "Command '$preview' failed: $result"
            break
        } else {
            if {$result ne ""} {
                append all_output "$result\n"
            }
        }
    }

    # Leftover unbalanced buffer is a syntax error — surface it instead of
    # silently dropping the trailing block.
    if {!$had_error && [string trim $buf] ne ""} {
        set had_error 1
        set preview [string trim $buf]
        if {[string length $preview] > 200} {
            set preview "[string range $preview 0 197]..."
        }
        set error_msg "Incomplete Tcl statement (unclosed braces or quotes): '$preview'"
    }

    if {$had_error} {
        ::vmdai::bridge::_post_command_result $tool_call_id 0 $all_output \
            $error_msg ""
    } else {
        # Capture the successful Tcl into the session log so the user
        # can save it via "Save Tcl…". Only the success path records —
        # failed attempts never make it into the replayable artifact.
        catch {::vmdai::ui::record_tcl_turn command $command}
        ::vmdai::bridge::_post_command_result $tool_call_id 1 $all_output \
            "" ""
    }
}

proc ::vmdai::bridge::_exec_capture_snapshot {tool_call_id tool_input} {
    # Generate a unique temp file path
    set snap_file "/tmp/vmdai_snap_${tool_call_id}.tga"

    # Try TachyonInternal first (better quality); fall back to snapshot
    set ok 0
    set err_msg ""

    if {[catch {render TachyonInternal $snap_file} render_err]} {
        # TachyonInternal failed — try the basic snapshot renderer
        if {[catch {render snapshot $snap_file} snap_err]} {
            set err_msg "Snapshot failed: $render_err / $snap_err"
        } else {
            set ok 1
        }
    } else {
        set ok 1
    }

    # Update display to ensure framebuffer is current before capturing
    catch {display update}

    if {$ok} {
        # Record the successful render in the session log; the file
        # path makes the saved Tcl reproducible against the same
        # working directory.
        catch {::vmdai::ui::record_tcl_turn snapshot "render snapshot $snap_file"}
        ::vmdai::bridge::_post_command_result $tool_call_id 1 \
            "Snapshot written to $snap_file" "" $snap_file
    } else {
        ::vmdai::bridge::_post_command_result $tool_call_id 0 "" $err_msg ""
    }
}

proc ::vmdai::bridge::_post_command_result {tool_call_id ok output error_msg snapshot_file} {
    variable session_id

    # Build the JSON params for tool.command_result
    set ok_json [expr {$ok ? "true" : "false"}]
    set params [::vmdai::bridge::_json_object [list \
        [::vmdai::bridge::_json_kv session_id    [::vmdai::bridge::_json_quote $session_id]] \
        [::vmdai::bridge::_json_kv tool_call_id  [::vmdai::bridge::_json_quote $tool_call_id]] \
        [::vmdai::bridge::_json_kv ok            $ok_json] \
        [::vmdai::bridge::_json_kv output        [::vmdai::bridge::_json_quote $output]] \
        [::vmdai::bridge::_json_kv error         [::vmdai::bridge::_json_quote $error_msg]] \
        [::vmdai::bridge::_json_kv snapshot_file [::vmdai::bridge::_json_quote $snapshot_file]] \
    ]]

    if {[catch {::vmdai::bridge::_rpc "tool.command_result" $params} rpc_err]} {
        ::vmdai::ui::append_message error "tool.command_result failed: $rpc_err"
    }
}

proc ::vmdai::bridge::schedule_poll {} {
    variable poll_after_id
    if {$poll_after_id ne ""} {
        after cancel $poll_after_id
    }
    set poll_after_id [after $::vmdai::config::poll_ms ::vmdai::bridge::poll_once]
}

proc ::vmdai::bridge::set_provider {provider model} {
    # Tell the runtime to swap which provider/model powers the agent.
    # The runtime rebuilds its provider + Claude tool loop in-place.
    # Safe to call before send_chat — if there's no session yet, we
    # spin one up first so the RPC has somewhere to land.
    variable session_id
    if {$session_id eq ""} {
        ::vmdai::bridge::ensure_runtime
    }
    if {$session_id eq ""} {
        # Runtime never came up — nothing we can do. Caller (the UI)
        # already surfaced ensure_runtime errors, so stay quiet here.
        return
    }
    set params [::vmdai::bridge::_json_object [list \
        [::vmdai::bridge::_json_kv session_id [::vmdai::bridge::_json_quote $session_id]] \
        [::vmdai::bridge::_json_kv provider   [::vmdai::bridge::_json_quote $provider]] \
        [::vmdai::bridge::_json_kv model      [::vmdai::bridge::_json_quote $model]] \
    ]]
    if {[catch {set body [::vmdai::bridge::_rpc "provider.set" $params]} err]} {
        ::vmdai::ui::append_message error "provider.set transport failed: $err"
        return
    }
    set rpcerr [::vmdai::bridge::_response_error $body]
    if {$rpcerr ne ""} {
        ::vmdai::ui::append_message error "provider.set failed: $rpcerr"
        return
    }
}

proc ::vmdai::bridge::new_chat {} {
    variable session_id
    variable session_token
    variable chat_id
    variable after_seq
    variable active_request_id

    if {$session_id ne ""} {
        set params [::vmdai::bridge::_json_object [list \
            [::vmdai::bridge::_json_kv session_id [::vmdai::bridge::_json_quote $session_id]] \
        ]]
        catch {::vmdai::bridge::_rpc "session.stop" $params}
    }

    set session_id ""
    set session_token ""
    set chat_id ""
    set after_seq 0
    set active_request_id ""
    variable is_resumed_chat
    set is_resumed_chat 0

    ::vmdai::bridge::ensure_runtime
}

proc ::vmdai::bridge::show_history {} {
    variable session_id
    if {$session_id eq ""} {
        ::vmdai::bridge::ensure_runtime
    }

    set params [::vmdai::bridge::_json_object [list \
        [::vmdai::bridge::_json_kv session_id [::vmdai::bridge::_json_quote $session_id]] \
        [::vmdai::bridge::_json_kv offset 0] \
        [::vmdai::bridge::_json_kv limit 20] \
    ]]

    if {[catch {set body [::vmdai::bridge::_rpc "chat.history.list" $params]} err]} {
        ::vmdai::ui::append_message error "history failed: $err"
        return
    }
    if {[::vmdai::bridge::_response_error $body] ne ""} {
        ::vmdai::ui::append_message error "history rpc failed"
        return
    }

    # Parse the items array.  Each row has chat_id, title, updated_at, message_count.
    set items [::vmdai::bridge::_parse_history_items $body]
    ::vmdai::ui::show_history_picker $items
}

proc ::vmdai::bridge::_parse_history_items {body} {
    variable has_json
    if {$has_json} {
        if {[catch {set parsed [::json::json2dict $body]} parse_err]} {
            return [list]
        }
        if {![dict exists $parsed result items]} {
            return [list]
        }
        return [dict get $parsed result items]
    }
    # Regex fallback: extract chat_id + title + message_count objects
    set items [list]
    set matches [regexp -inline -all {\{[^\{\}]*"chat_id"[^\{\}]*\}} $body]
    foreach m $matches {
        set cid [::vmdai::bridge::_extract_string $m chat_id]
        set title [::vmdai::bridge::_extract_string $m title]
        set mc [::vmdai::bridge::_extract_int $m message_count 0]
        set updated [::vmdai::bridge::_extract_string $m updated_at]
        if {$cid ne ""} {
            lappend items [dict create chat_id $cid title $title message_count $mc updated_at $updated]
        }
    }
    return $items
}

proc ::vmdai::bridge::resume_chat {target_chat_id} {
    variable session_id
    variable chat_id
    variable after_seq

    if {$session_id eq ""} {
        ::vmdai::bridge::ensure_runtime
    }

    # Tell the backend to switch the session to the target chat
    set params [::vmdai::bridge::_json_object [list \
        [::vmdai::bridge::_json_kv session_id [::vmdai::bridge::_json_quote $session_id]] \
        [::vmdai::bridge::_json_kv chat_id [::vmdai::bridge::_json_quote $target_chat_id]] \
    ]]

    if {[catch {set body [::vmdai::bridge::_rpc "chat.resume" $params]} err]} {
        ::vmdai::ui::append_message error "resume failed: $err"
        return
    }
    set rpcerr [::vmdai::bridge::_response_error $body]
    if {$rpcerr ne ""} {
        ::vmdai::ui::append_message error "resume rpc failed: $rpcerr"
        return
    }

    set chat_id $target_chat_id
    set after_seq 0
    variable is_resumed_chat
    set is_resumed_chat 1

    # Now fetch and display the prior transcript
    ::vmdai::bridge::_load_chat_transcript $target_chat_id
}

proc ::vmdai::bridge::_load_chat_transcript {target_chat_id} {
    variable session_id

    set params [::vmdai::bridge::_json_object [list \
        [::vmdai::bridge::_json_kv session_id [::vmdai::bridge::_json_quote $session_id]] \
        [::vmdai::bridge::_json_kv chat_id [::vmdai::bridge::_json_quote $target_chat_id]] \
        [::vmdai::bridge::_json_kv limit 200] \
    ]]

    if {[catch {set body [::vmdai::bridge::_rpc "chat.history.get" $params]} err]} {
        ::vmdai::ui::append_message error "load transcript failed: $err"
        return
    }
    set rpcerr [::vmdai::bridge::_response_error $body]
    if {$rpcerr ne ""} {
        ::vmdai::ui::append_message error "load transcript rpc failed: $rpcerr"
        return
    }

    # Parse events and replay them in the UI
    variable has_json
    set events [list]
    if {$has_json} {
        if {![catch {set parsed [::json::json2dict $body]}]} {
            if {[dict exists $parsed result events]} {
                set events [dict get $parsed result events]
            }
        }
    }

    foreach ev $events {
        set role [::vmdai::ui::_dict_get_or $ev role ""]
        set etype [::vmdai::ui::_dict_get_or $ev type ""]
        set text [::vmdai::ui::_dict_get_or $ev text ""]
        # Only show user and assistant messages (skip chunks, lifecycle, tool events)
        if {($role eq "user" || $role eq "assistant") && $etype eq "message" && $text ne ""} {
            ::vmdai::ui::append_message $role $text
        }
    }
}

proc ::vmdai::bridge::shutdown_runtime {} {
    variable session_id
    variable runtime_pid
    variable poll_after_id

    if {$poll_after_id ne ""} {
        after cancel $poll_after_id
        set poll_after_id ""
    }

    if {$session_id ne ""} {
        set params [::vmdai::bridge::_json_object [list \
            [::vmdai::bridge::_json_kv session_id [::vmdai::bridge::_json_quote $session_id]] \
        ]]
        catch {::vmdai::bridge::_rpc "session.stop" $params}
        set session_id ""
    }

    if {$runtime_pid ne ""} {
        catch {exec kill $runtime_pid}
        set runtime_pid ""
    }
}
