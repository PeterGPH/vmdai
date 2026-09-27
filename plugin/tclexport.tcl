# tclexport.tcl -- ChatVMD Tcl export ledger: Copy/Save run and chat .tcl
# (spec §2h, Part B V1 console graft, C3). No Tk.
#
#   ::vmdai::tclexport::record request_id call_key command applied failed_index
#   ::vmdai::tclexport::run_tcl request_id  -> the Tcl one run applied
#   ::vmdai::tclexport::chat_tcl            -> every run, in order ("" if none)
#   ::vmdai::tclexport::save path text      write text as UTF-8 with LF endings
#   ::vmdai::tclexport::reset               forget everything (New chat, resume)
#
# The same rule as the runtime's recorder (C3): a command whose statements
# all ran is kept whole; one that failed after `applied` statements keeps
# that exact source prefix, then a comment naming the failed statement, then
# the rest commented out line by line; a call that applied nothing is left
# out. Statement boundaries come from the executor's own splitter
# (executor::split_statements), so they match what actually ran. Recording
# a call_key again (a late result) replaces its entry in place.

namespace eval ::vmdai::tclexport {
    variable runs
    if {![info exists runs]} { set runs {} }
    variable calls
    if {![info exists calls]} { array set calls {} }
    variable entry
    if {![info exists entry]} { array set entry {} }
}

proc ::vmdai::tclexport::reset {} {
    variable runs
    variable calls
    variable entry
    set runs {}
    array unset calls
    array set calls {}
    array unset entry
    array set entry {}
}

proc ::vmdai::tclexport::record {request_id call_key command applied failed_index} {
    variable runs
    variable calls
    variable entry
    if {[info exists entry($call_key)]} {
        set request_id [lindex $entry($call_key) 0]
    } else {
        if {$request_id ni $runs} { lappend runs $request_id }
        lappend calls($request_id) $call_key
    }
    set entry($call_key) [list $request_id $command $applied $failed_index]
    return
}

# {start end} character ranges of the statements in cmd, end exclusive,
# found where the executor's splitter says they are. An incomplete tail
# counts as the last statement. Without the splitter: one statement.
proc ::vmdai::tclexport::_ranges {cmd} {
    if {[catch {::vmdai::executor::split_statements $cmd} d]} {
        return [list [list 0 [string length $cmd]]]
    }
    set stmts [dict get $d statements]
    if {[string trim [dict get $d tail]] ne ""} { lappend stmts [dict get $d tail] }
    set out {}
    set pos 0
    foreach stmt $stmts {
        set s [string first $stmt $cmd $pos]
        if {$s < 0} { continue }
        set pos [expr {$s + [string length $stmt]}]
        lappend out [list $s $pos]
    }
    if {$out eq ""} { return [list [list 0 [string length $cmd]]] }
    return $out
}

# "# text" for each line; a line ending in an odd number of backslashes gets
# a trailing space, so the comment cannot swallow the next line.
proc ::vmdai::tclexport::_commented {text} {
    set out ""
    foreach line [split [string trimright $text "\n"] "\n"] {
        set tail [expr {[string length $line] - [string length [string trimright $line "\\"]]}]
        if {$tail % 2 == 1} { append line " " }
        append out "# $line\n"
    }
    return $out
}

# The kept text of one recorded call ("" when nothing of it ran).
proc ::vmdai::tclexport::_call_tcl {call_key} {
    variable entry
    lassign $entry($call_key) request_id cmd applied failed_index
    if {![string is integer -strict $applied] || $applied < 1} { return "" }
    set ranges [_ranges $cmd]
    set total [llength $ranges]
    if {$applied >= $total} {
        return "[string trimright $cmd "\n"]\n"
    }
    set end [lindex $ranges [expr {$applied - 1}] 1]
    set kept [string trimright [string range $cmd 0 [expr {$end - 1}]] "\n"]
    set rest [string trimleft [string range $cmd $end end] " \t;\n"]
    set first [expr {$applied + 1}]
    if {[string is integer -strict $failed_index] && $failed_index > $applied} {
        set first $failed_index
        set head "# statement $failed_index of $total failed; "
    } else {
        set head "# "
    }
    if {$first < $total} {
        append head "statements $first–$total were not applied:"
    } else {
        append head "statement $first was not applied:"
    }
    return "$kept\n$head\n[_commented $rest]"
}

proc ::vmdai::tclexport::run_tcl {request_id} {
    variable calls
    if {![info exists calls($request_id)]} { return "" }
    set out ""
    foreach key $calls($request_id) { append out [_call_tcl $key] }
    return $out
}

proc ::vmdai::tclexport::chat_tcl {} {
    variable runs
    set out ""
    set n 0
    foreach request_id $runs {
        set body [run_tcl $request_id]
        if {$body eq ""} { continue }
        incr n
        append out "\n# --- run $n ---\n" $body
    }
    if {$n == 0} { return "" }
    return "# ChatVMD: the Tcl that ran in VMD, in order. Statements that did not run are commented out.\n$out"
}

proc ::vmdai::tclexport::save {path text} {
    set fh [open $path w]
    set rc [catch {
        fconfigure $fh -encoding utf-8 -translation lf
        puts -nonewline $fh $text
    } err]
    close $fh
    if {$rc} { return -code error $err }
    return $path
}
