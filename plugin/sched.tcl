# sched.tcl - registry of every timer, fileevent and http token the plugin
# creates, so teardown can cancel all of them (spec 2d, S4). No Tk.

namespace eval ::vmdai::sched {
    variable seq
    if {![info exists seq]} { set seq 0 }
    # timers(<id>) = {<Tcl after id> <script>}
    variable timers
    if {![info exists timers]} { array set timers {} }
    # fevents(<chan>,<event>) = {<chan> <event>}
    variable fevents
    if {![info exists fevents]} { array set fevents {} }
    # tokens(<http token>) = 1
    variable tokens
    if {![info exists tokens]} { array set tokens {} }
    # Set while teardown runs: new timers are refused.
    variable closing
    if {![info exists closing]} { set closing 0 }
}

proc ::vmdai::sched::_log {msg} {
    catch {::vmdai::config::log "sched: $msg"}
}

proc ::vmdai::sched::_add {when script} {
    variable seq
    variable timers
    variable closing
    if {$closing} {
        return ""
    }
    set id "vmdai_sched#[incr seq]"
    set tcl_id [::after {*}$when [list ::vmdai::sched::_fire $id]]
    set timers($id) [list $tcl_id $script]
    return $id
}

# Run $script at global level after $ms; returns an id for cancel/pending.
proc ::vmdai::sched::after {ms script} {
    return [_add [list $ms] $script]
}

proc ::vmdai::sched::after_idle {script} {
    return [_add [list idle] $script]
}

proc ::vmdai::sched::_fire {id} {
    variable timers
    if {![info exists timers($id)]} {
        return
    }
    set script [lindex $timers($id) 1]
    unset timers($id)
    if {[catch {uplevel #0 $script} err]} {
        _log "timer $id failed: $err\n$::errorInfo"
    }
}

proc ::vmdai::sched::cancel {id} {
    variable timers
    if {$id eq "" || ![info exists timers($id)]} {
        return
    }
    catch {::after cancel [lindex $timers($id) 0]}
    unset timers($id)
}

# Ids from after/after_idle that have neither fired nor been cancelled.
proc ::vmdai::sched::pending {} {
    variable timers
    return [lsort -dictionary [array names timers]]
}

# Register (or, with an empty script, remove) a fileevent handler.
proc ::vmdai::sched::fileevent {chan event script} {
    variable fevents
    ::fileevent $chan $event $script
    if {$script eq ""} {
        unset -nocomplain fevents($chan,$event)
    } else {
        set fevents($chan,$event) [list $chan $event]
    }
    return
}

proc ::vmdai::sched::track_http {token} {
    variable tokens
    set tokens($token) 1
    return
}

proc ::vmdai::sched::untrack_http {token} {
    variable tokens
    unset -nocomplain tokens($token)
    return
}

# Cancel every registered resource. `stop` and `reload` call this.
proc ::vmdai::sched::teardown {} {
    variable timers
    variable fevents
    variable tokens
    variable closing
    set closing 1
    foreach token [array names tokens] {
        unset -nocomplain tokens($token)
        # reset runs the token's -command callback, which may try to
        # schedule a delivery; `closing` makes that a no-op.
        catch {::http::reset $token}
        catch {::http::cleanup $token}
    }
    foreach key [array names fevents] {
        foreach {chan event} $fevents($key) break
        catch {::fileevent $chan $event {}}
        unset fevents($key)
    }
    foreach id [array names timers] {
        catch {::after cancel [lindex $timers($id) 0]}
        unset timers($id)
    }
    set closing 0
    return
}
