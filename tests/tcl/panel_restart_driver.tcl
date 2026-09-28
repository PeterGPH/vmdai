# tests/tcl/panel_restart_driver.tcl - final-fix I2 real-runtime driver
# (not a tcltest file; plan-09 final-review.md I2).
#
# tests/test_panel_restart_integration.py runs this under tclsh 8.6 with
# VMD's Tk (helpers.tk.tk_prelude), http 2.9.5 and json 1.1.2 already
# loaded. It sources the real plugin, attaches to the in-process scripted
# runtime named by VMD_AI_ATTACH (token file under $HOME/.vmdai/run), sends
# one prompt through the panel and opens Settings, then waits at a marker
# file while pytest kills the runtime, sleeps past the outage and restarts
# it on the same port with the same SettingsStore (so the active profile
# survives the crash, like a real ~/.vmdai/settings.json would). It checks
# that Settings reloads cleanly from the new session afterwards, instead of
# showing the old session's AUTH_FAILED.
set ::out $env(PANEL_RESTART_OUT)
set ::sync $env(PANEL_RESTART_SYNC)

proc ::driver_fail {message} {
    set fh [open $::out w]
    fconfigure $fh -encoding utf-8
    puts -nonewline $fh [::vmdai::net::encode_params [list error s $message]]
    close $fh
    exit 3
}
proc bgerror {message} { ::driver_fail "background error: $message\n$::errorInfo" }

proc ::driver_wait {script ms what} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { ::driver_fail "timed out waiting for $what" }
        after 20 {set ::driver_tick 1}
        vwait ::driver_tick
    }
}
proc ::marker {name} { file join $::sync $name }
proc ::touch {name} { close [open [marker $name] w] }
proc ::write_out {pairs} {
    set fh [open $::out w]
    fconfigure $fh -encoding utf-8
    puts -nonewline $fh [::vmdai::net::encode_params $pairs]
    close $fh
}

# VMD commands the executor calls. This is tclsh, not VMD.
proc ::display {args} { return "" }
proc ::mol {args} { return 0 }
proc ::vmdinfo {what} { return driver }

# Count request.finished events without replacing panel::on_event (P09-T09's
# panel_driver.tcl does the same).
set ::driver_finished 0
proc ::driver_count {cmd op} {
    set ev [lindex $cmd 1]
    if {![catch {dict get $ev metadata kind} kind] && $kind eq "request.finished"} {
        incr ::driver_finished
    }
}

if {[catch {
    cd $env(PANEL_RESTART_WORKDIR)
    source [file join $env(VMDAI_PLUGIN_DIR) init.tcl]
    set ::vmdai::panel::headless 1
    trace add execution ::vmdai::panel::on_event enter ::driver_count
    ::vmdai::start
    ::driver_wait {expr {[dict get [::vmdai::bridge::state] session_id] ne ""}} 20000 "the session"
    ::driver_wait {expr {$::vmdai::panel::rt_info ne ""}} 5000 "runtime.info"

    ::vmdai::panel::on_send "Hello"
    ::driver_wait {expr {$::driver_finished >= 1}} 30000 "the first request"
    ::driver_wait {expr {![::vmdai::panel::bridge_busy]}} 5000 "idle after the first request"

    ::vmdai::panel::open_settings
    ::driver_wait {expr {[info exists ::vmdai::settings::v(profile)]
        && $::vmdai::settings::v(profile) eq "qwen"}} 10000 "the profile before the restart"

    set ::old_session [dict get [::vmdai::bridge::state] session_id]
    # Prove the post-restart value really comes from a reload, not leftovers.
    set ::vmdai::settings::v(profile) ""
    ::touch ready_for_restart
    ::driver_wait {file exists [marker restarted]} 20000 "pytest to restart the runtime"

    ::driver_wait {expr {[dict get [::vmdai::bridge::state] session_id] ne $::old_session
        && [dict get [::vmdai::bridge::state] session_id] ne ""
        && !$::vmdai::bridge::op_busy && !$::vmdai::bridge::recovering}} 15000 "the recovered session"
    ::driver_wait {expr {[info exists ::vmdai::settings::v(profile)]
        && $::vmdai::settings::v(profile) eq "qwen"}} 5000 "the profile after the restart"

    ::write_out [list \
        profile        s [set ::vmdai::settings::v(profile)] \
        footer_msg     s [[::vmdai::settings::footer].msg cget -text] \
        src_anthropic  s [[::vmdai::settings::tab keys].src_anthropic cget -text] \
        src_openrouter s [[::vmdai::settings::tab keys].src_openrouter cget -text] \
        saving         b [expr {$::vmdai::settings::saving ? 1 : 0}]]
    ::vmdai::stop
} err]} {
    ::driver_fail "$err\n$::errorInfo"
}
exit 0
