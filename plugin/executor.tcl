# executor.tcl - runs the model's Tcl in this VMD session (spec 2d Executor,
# Part C C2, C3, C5). No Tk needed; VMD's mol/render/display are called at
# global level. For each tool_start: skip checks, approve, tool.ack, the
# whole-command pre-check, the run with stdout captured, then the result is
# queued with net::post_result.

namespace eval ::vmdai::executor {
    # 1 while model Tcl runs; the bridge holds tool_start events back.
    variable executing
    if {![info exists executing]} { set executing 0 }
    # Output posted to the runtime is cut here (C5); the runtime saves it.
    variable output_ceiling 1048576
    # tool_start events waiting their turn: each item is {epoch event}.
    variable queue
    if {![info exists queue]} { set queue {} }
    variable current
    if {![info exists current]} { set current "" }
    # The net epoch the current call's tool.ack was sent under.
    variable current_epoch
    if {![info exists current_epoch]} { set current_epoch "" }
    # call_keys that already ran (or were refused) and cancelled requests.
    variable ran
    if {![info exists ran]} { array set ran {} }
    variable ran_order
    if {![info exists ran_order]} { set ran_order {} }
    variable cancelled
    if {![info exists cancelled]} { array set cancelled {} }
    # Commands that ran, for the M1 panel's "Save Tcl...".
    variable ledger
    if {![info exists ledger]} { set ledger {} }
    # stdout/stderr captured while model Tcl runs.
    variable capture
    if {![info exists capture]} { set capture "" }
    variable capture_full
    if {![info exists capture_full]} { set capture_full 0 }
}

proc ::vmdai::executor::_log {msg} {
    catch {::vmdai::config::log "executor: $msg"}
}

proc ::vmdai::executor::_dget {d key default} {
    if {[catch {dict get $d $key} value] || $value eq "null"} {
        return $default
    }
    return $value
}

# --- statements (C3) ------------------------------------------------------------

# Scan a script into complete statements. Returns {spans tail_start}: each
# span is {first last next}, the index of the statement's first and last
# character and of the first character after its separator; tail_start is
# the index where an incomplete statement begins, or -1. Comment lines are
# skipped, as Tcl does.
proc ::vmdai::executor::_scan {script} {
    set spans {}
    set n [string length $script]
    set i 0
    while {$i < $n} {
        # Skip separators and blank space between statements.
        while {$i < $n && [string is space [string index $script $i]] || \
                ($i < $n && [string index $script $i] eq ";")} {
            incr i
        }
        if {$i >= $n} {
            break
        }
        set start $i
        if {[string index $script $i] eq "#"} {
            # A comment runs to the next newline not escaped by a backslash.
            while {$i < $n} {
                set ch [string index $script $i]
                if {$ch eq "\\"} {
                    incr i 2
                    continue
                }
                incr i
                if {$ch eq "\n"} {
                    break
                }
            }
            continue
        }
        set end -1
        set j $i
        while {$j < $n} {
            set ch [string index $script $j]
            if {$ch eq "\\"} {
                incr j 2
                continue
            }
            if {($ch eq "\n" || $ch eq ";")
                    && [info complete [string range $script $start [expr {$j - 1}]]]} {
                set end $j
                break
            }
            incr j
        }
        if {$end < 0} {
            if {![info complete [string range $script $start end]]} {
                return [list $spans $start]
            }
            set end $n
        }
        set text [string range $script $start [expr {$end - 1}]]
        set last [expr {$start + [string length [string trimright $text]] - 1}]
        lappend spans [list $start $last [expr {min($end + 1, $n)}]]
        set i [expr {$end + 1}]
    }
    return [list $spans -1]
}

# split_statements script -> dict {statements tail}: the complete statements
# (trimmed) and the incomplete remainder ("" when there is none).
proc ::vmdai::executor::split_statements {script} {
    lassign [_scan $script] spans tail_start
    set statements {}
    foreach span $spans {
        lappend statements [string range $script [lindex $span 0] [lindex $span 1]]
    }
    set tail ""
    if {$tail_start >= 0} {
        set tail [string trim [string range $script $tail_start end]]
    }
    return [dict create statements $statements tail $tail]
}

proc ::vmdai::executor::_clip {text limit} {
    if {[string length $text] <= $limit} {
        return $text
    }
    return "[string range $text 0 [expr {$limit - 4}]]..."
}

# --- stdout capture -------------------------------------------------------------

proc ::vmdai::executor::_capture_append {text} {
    variable capture
    variable capture_full
    variable output_ceiling
    if {$capture_full} {
        return
    }
    append capture $text
    if {[string length $capture] > $output_ceiling} {
        set capture_full 1
    }
}

# Stands in for ::puts while model Tcl runs: stdout and stderr are captured,
# any other channel (a file the model opened) is written as usual.
proc ::vmdai::executor::_puts {args} {
    set words $args
    set newline 1
    if {[lindex $words 0] eq "-nonewline"} {
        set newline 0
        set words [lrange $words 1 end]
    }
    switch -- [llength $words] {
        1 {
            set chan stdout
            set text [lindex $words 0]
        }
        2 {
            lassign $words chan text
        }
        default {
            return [uplevel 1 [list ::vmdai::executor::_real_puts {*}$args]]
        }
    }
    if {$chan ne "stdout" && $chan ne "stderr"} {
        return [uplevel 1 [list ::vmdai::executor::_real_puts {*}$args]]
    }
    _capture_append [expr {$newline ? "$text\n" : $text}]
    return
}

proc ::vmdai::executor::_install_puts {} {
    variable capture
    variable capture_full
    set capture ""
    set capture_full 0
    if {[llength [info commands ::vmdai::executor::_real_puts]]} {
        return
    }
    rename ::puts ::vmdai::executor::_real_puts
    interp alias {} ::puts {} ::vmdai::executor::_puts
}

# Puts back the real ::puts, whatever the model's Tcl did to the name.
proc ::vmdai::executor::_restore_puts {} {
    if {![llength [info commands ::vmdai::executor::_real_puts]]} {
        return
    }
    catch {rename ::puts {}}
    rename ::vmdai::executor::_real_puts ::puts
}

# --- running one command ----------------------------------------------------------

# Paint "Running..." before the model's Tcl blocks the event loop. With Tk
# loaded this is one `update idletasks` (redraws only).
proc ::vmdai::executor::_paint {text} {
    catch {::vmdai::ui::status $text}
    if {[llength [info commands ::winfo]]} {
        catch {update idletasks}
    }
}

# exec_command command -> dict {ok executed output error truncated
# duration_ms statements_total statements_applied failed_index
# failed_statement error_info applied_text}. The whole command is split
# first (C3): an incomplete tail runs nothing.
proc ::vmdai::executor::exec_command {command} {
    variable executing
    variable capture
    variable output_ceiling
    lassign [_scan $command] spans tail_start
    set total [llength $spans]
    set result [dict create ok 0 executed no output "" error "" truncated 0 duration_ms 0 \
        statements_total $total statements_applied 0 failed_index "" failed_statement "" \
        error_info "" applied_text ""]
    if {$tail_start >= 0} {
        incr total
        dict set result statements_total $total
        dict set result failed_index $total
        dict set result failed_statement [_clip [string trim [string range $command $tail_start end]] 200]
        dict set result error "Nothing was run: statement $total of $total is incomplete (unbalanced braces, brackets or quotes)"
        return $result
    }
    if {$total == 0} {
        dict set result error "Empty command"
        return $result
    }
    set t0 [clock milliseconds]
    set applied 0
    set failed ""
    set executing 1
    _install_puts
    set rc [catch {
        foreach span $spans {
            set statement [string range $command [lindex $span 0] [lindex $span 1]]
            set code [catch {uplevel #0 $statement} value]
            if {$code == 0 || $code == 2} {
                incr applied
                if {$value ne ""} {
                    _capture_append "$value\n"
                }
                continue
            }
            set einfo ""
            if {$code == 1} {
                set einfo [join [lrange [split $::errorInfo "\n"] 0 2] "\n"]
            } elseif {$code == 3} {
                set value "invoked \"break\" outside of a loop"
            } elseif {$code == 4} {
                set value "invoked \"continue\" outside of a loop"
            }
            set failed [list $statement $value $einfo]
            break
        }
    } err]
    _restore_puts
    set executing 0
    if {$rc} {
        set failed [list "" $err ""]
    }
    set output $capture
    set capture ""
    if {[string length $output] > $output_ceiling} {
        set output "[string range $output 0 [expr {$output_ceiling - 1}]]\n\[executor limit: output cut at 1 MB\]"
        dict set result truncated 1
    }
    dict set result output $output
    dict set result executed yes
    dict set result statements_applied $applied
    dict set result duration_ms [expr {[clock milliseconds] - $t0}]
    if {$failed eq ""} {
        dict set result ok 1
        return $result
    }
    lassign $failed statement message einfo
    dict set result error $message
    dict set result failed_index [expr {$applied + 1}]
    dict set result failed_statement [_clip $statement 200]
    dict set result error_info [_clip $einfo 500]
    if {$applied > 0} {
        set next [lindex [lindex $spans [expr {$applied - 1}]] 2]
        dict set result applied_text [string range $command 0 [expr {$next - 1}]]
    }
    return $result
}

# capture_snapshot input snapshot_path -> dict: `display update`, then
# `render TachyonInternal` to the path the runtime chose (spec 2d Snapshot).
proc ::vmdai::executor::capture_snapshot {input snapshot_path} {
    variable executing
    set result [dict create ok 0 executed yes output "" error "" duration_ms 0 \
        snapshot_file $snapshot_path]
    if {$snapshot_path eq ""} {
        dict set result executed no
        dict set result error "The runtime did not choose a snapshot path."
        return $result
    }
    set t0 [clock milliseconds]
    set executing 1
    catch {file delete $snapshot_path}
    catch {uplevel #0 [list display update]}
    set rc [catch {uplevel #0 [list render TachyonInternal $snapshot_path]} err]
    set executing 0
    dict set result duration_ms [expr {[clock milliseconds] - $t0}]
    if {$rc} {
        dict set result error "Snapshot failed: $err"
    } elseif {![file exists $snapshot_path]} {
        dict set result error "Snapshot failed: the renderer wrote no file."
    } else {
        dict set result ok 1
        dict set result output "Snapshot written to $snapshot_path"
    }
    return $result
}

# --- the tool_start pipeline ------------------------------------------------------

# approve meta -> run|refuse. Round 1 runs only `approval: auto` (C2); a
# runtime without the field predates approval and means auto.
proc ::vmdai::executor::approve {meta} {
    set approval [_dget $meta approval auto]
    if {$approval eq "auto"} {
        return run
    }
    return refuse
}

proc ::vmdai::executor::note_cancelled {request_id} {
    variable cancelled
    if {$request_id ne ""} {
        set cancelled($request_id) 1
    }
}

# Queue one tool_start event (the bridge calls this); they run in order.
proc ::vmdai::executor::run {event} {
    variable queue
    lappend queue [list [::vmdai::net::epoch] $event]
    _pump
}

proc ::vmdai::executor::_pump {} {
    variable queue
    variable current
    variable current_epoch
    variable executing
    if {$current ne "" && !$executing && $current_epoch != [::vmdai::net::epoch]} {
        # The session changed while this call waited for its ack: net drops
        # replies of an older epoch, so _on_ack never runs for it.
        _log "call $current abandoned after a session change"
        set current ""
    }
    if {$current ne "" || ![llength $queue]} {
        return
    }
    set item [lindex $queue 0]
    set queue [lrange $queue 1 end]
    lassign $item epoch event
    set current_epoch [::vmdai::net::epoch]
    set meta [_dget $event metadata {}]
    set current [_dget $meta call_key ""]
    if {$current eq ""} {
        _log "tool_start without a call_key ignored"
        _finish
        return
    }
    if {[catch {_start $epoch $meta} err]} {
        _log "tool_start $current failed: $::errorInfo"
        _finish
    }
}

proc ::vmdai::executor::_finish {} {
    variable current
    variable queue
    set current ""
    if {[llength $queue]} {
        ::vmdai::sched::after 0 ::vmdai::executor::_pump
    }
}

proc ::vmdai::executor::_start {epoch meta} {
    variable ran
    variable ran_order
    variable cancelled
    set key [dict get $meta call_key]
    set rid [_dget $meta request_id ""]
    if {[info exists ran($key)]} {
        _log "call $key already ran; skipped"
        _finish
        return
    }
    set ran($key) 1
    lappend ran_order $key
    if {[llength $ran_order] > 1000} {
        unset -nocomplain ran([lindex $ran_order 0])
        set ran_order [lrange $ran_order 1 end]
    }
    if {$rid ne "" && [info exists cancelled($rid)]} {
        _log "call $key belongs to cancelled request $rid; skipped"
        _finish
        return
    }
    if {[approve $meta] ne "run"} {
        # C2: not acked; the runtime treats this result as pickup.
        _post $epoch $meta [dict create ok 0 executed no \
            error "This panel cannot ask for approval"]
        _finish
        return
    }
    ::vmdai::net::call tool.ack [list call_key s $key state s running] \
        [list ::vmdai::executor::_on_ack $epoch $meta]
}

proc ::vmdai::executor::_on_ack {epoch meta kind args} {
    if {[llength [info commands ::vmdai::bridge::note_outcome]]} {
        catch {::vmdai::bridge::note_outcome tool.ack $kind {*}$args}
    }
    set key [dict get $meta call_key]
    set proceed 0
    if {$kind eq "ok"} {
        catch {set proceed [string is true -strict [dict get [lindex $args 0] proceed]]}
    }
    if {!$proceed || $epoch != [::vmdai::net::epoch]} {
        _log "call $key not run: ack $kind $args"
        _finish
        return
    }
    if {[catch {_execute $epoch $meta} err]} {
        _log "call $key failed in the executor: $::errorInfo"
        _post $epoch $meta [dict create ok 0 executed yes error "Executor error: $err"]
    }
    _finish
}

proc ::vmdai::executor::_execute {epoch meta} {
    variable ledger
    set name [_dget $meta tool_name ""]
    set input [_dget $meta tool_input {}]
    switch -- $name {
        run_vmd_command {
            set command [_dget $input command ""]
            # C3: paint "Running" only for a command the pre-check passes.
            if {[string trim $command] ne "" && [dict get [split_statements $command] tail] eq ""} {
                set lines [split [string trim $command] "\n"]
                set label [_clip [lindex $lines 0] 80]
                if {[llength $lines] > 1} {
                    append label " ..."
                }
                _paint "Running: $label"
            }
            set result [exec_command $command]
            if {[dict get $result ok]} {
                lappend ledger [dict create ts [clock seconds] kind command command $command]
            } elseif {[dict get $result applied_text] ne ""} {
                lappend ledger [dict create ts [clock seconds] kind command \
                    command [dict get $result applied_text]]
            }
        }
        capture_vmd_snapshot {
            set path [_dget $meta snapshot_path ""]
            _paint "Rendering a snapshot..."
            set result [capture_snapshot $input $path]
            if {[dict get $result ok]} {
                lappend ledger [dict create ts [clock seconds] kind snapshot \
                    command "render TachyonInternal $path"]
            }
        }
        default {
            set result [dict create ok 0 executed no error "Unknown tool: $name"]
        }
    }
    _post $epoch $meta $result
}

# Queue the result (net::post_result retries it). A result from before a
# session change is dropped: that session is gone.
proc ::vmdai::executor::_post {epoch meta result} {
    set key [dict get $meta call_key]
    if {$epoch != [::vmdai::net::epoch]} {
        _log "call $key finished after the session changed; result dropped"
        return
    }
    set pairs [list tool_call_id s [_dget $meta tool_call_id ""] \
        ok b [dict get $result ok] executed s [_dget $result executed yes] \
        output s [_dget $result output ""] error s [_dget $result error ""]]
    foreach {name type} {statements_total i statements_applied i failed_index i
            failed_statement s error_info s applied_text s duration_ms i
            snapshot_file s} {
        set value [_dget $result $name ""]
        if {$value ne ""} {
            lappend pairs $name $type $value
        }
    }
    if {[_dget $result truncated 0]} {
        lappend pairs truncated b 1
    }
    ::vmdai::net::post_result $key $pairs
}

# Forget queued events and past call_keys (new session, stop, tests). A
# command that is running finishes; the real ::puts is back afterwards.
proc ::vmdai::executor::reset {} {
    variable queue
    variable current
    variable current_epoch
    variable ran
    variable ran_order
    variable cancelled
    variable executing
    set queue {}
    set current ""
    set current_epoch ""
    array unset ran
    set ran_order {}
    array unset cancelled
    if {!$executing} {
        _restore_puts
    }
}

proc ::vmdai::executor::ledger {} {
    variable ledger
    return $ledger
}

proc ::vmdai::executor::clear_ledger {} {
    variable ledger
    set ledger {}
}
