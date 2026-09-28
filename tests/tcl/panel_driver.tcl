# tests/tcl/panel_driver.tcl - P09-T09 end-to-end driver (not a tcltest file).
#
# tests/test_panel_integration.py runs this under tclsh 8.6 with VMD's Tk
# (helpers.tk.tk_prelude), http 2.9.5 and json 1.1.2 already loaded. It
# sources the real plugin, attaches to the in-process scripted runtime named
# by VMD_AI_ATTACH (token file under $HOME/.vmdai/run), sends two prompts
# through the panel, then opens a new chat and resumes the first one into a
# fresh view. It writes
#   $PANEL_OUT/live.txt    the transcript dump after both requests
#   $PANEL_OUT/replay.txt  the transcript dump after New chat + resume
#   $PANEL_OUT/error.txt   only on failure
# Tk on macOS swallows stdout, so everything goes to files.
set ::out $env(PANEL_OUT)
file mkdir $::out

proc ::driver_fail {message} {
    set fh [open [file join $::out error.txt] w]
    puts $fh $message
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

proc ::driver_dump {name} {
    set fh [open [file join $::out $name] w]
    fconfigure $fh -encoding utf-8
    puts -nonewline $fh [::vmdai::transcript::dump]
    close $fh
}

# VMD commands the executor calls. This is tclsh, not VMD.
proc ::display {args} { return "" }
proc ::mol {args} { return 0 }
proc ::vmdinfo {what} { return driver }
# render TachyonInternal <path>: an 8x6 uncompressed 24-bit TGA gradient.
proc ::render {renderer path args} {
    set fh [open $path w]
    fconfigure $fh -translation binary
    puts -nonewline $fh [binary format cccsscsssscc 0 0 2 0 0 0 0 0 8 6 24 0]
    for {set y 0} {$y < 6} {incr y} {
        for {set x 0} {$x < 8} {incr x} {
            puts -nonewline $fh [binary format ccc [expr {$x * 30}] [expr {$y * 40}] 200]
        }
    }
    close $fh
    return ""
}

# Count request.finished events without replacing panel::on_event.
set ::driver_finished 0
proc ::driver_count {cmd op} {
    set ev [lindex $cmd 1]
    if {![catch {dict get $ev metadata kind} kind] && $kind eq "request.finished"} {
        incr ::driver_finished
    }
}

if {[catch {
    cd $env(PANEL_WORKDIR)
    source [file join $env(VMDAI_PLUGIN_DIR) init.tcl]
    set ::vmdai::panel::headless 1
    # M3 (plan 10): never read the real OS appearance (the build calls
    # set_appearance); theme.tcl keeps this value when init.tcl re-sources it.
    set ::vmdai::theme::macstyle ::driver_no_macwindowstyle
    trace add execution ::vmdai::panel::on_event enter ::driver_count
    ::vmdai::start
    ::driver_wait {expr {[dict get [::vmdai::bridge::state] session_id] ne ""}} 20000 "the session"
    ::driver_wait {expr {$::vmdai::panel::rt_info ne ""}} 5000 "runtime.info"
    # Startup may add connection notes; the goldens cover the conversation.
    ::vmdai::panel::reset_view
    # Named ::driver_req, not ::n: the scripted model's first tool call runs
    # `set n 42` through the executor, which evaluates at true global scope
    # (uplevel #0) -- the same scope this driver runs in -- so a loop counter
    # named `n` here would be clobbered by that tool run.
    set ::driver_req 0
    foreach prompt [list $env(PANEL_PROMPT_1) $env(PANEL_PROMPT_2)] {
        incr ::driver_req
        ::vmdai::composer::set_text $prompt
        ::vmdai::panel::on_send
        ::driver_wait [list expr "\$::driver_finished >= $::driver_req"] 30000 "request $::driver_req"
        ::driver_wait {expr {![::vmdai::panel::bridge_busy]}} 5000 "idle after request $::driver_req"
    }
    update idletasks
    ::driver_dump live.txt
    set ::chat [dict get [::vmdai::bridge::state] chat_id]
    ::vmdai::panel::new_chat
    ::driver_wait {expr {[dict get [::vmdai::bridge::state] session_id] ne ""
        && [dict get [::vmdai::bridge::state] chat_id] ne $::chat}} 10000 "the new chat"
    ::vmdai::bridge::resume $::chat
    ::driver_wait {expr {$::vmdai::panel::replayed eq $::chat}} 10000 "the replay"
    update idletasks
    ::driver_dump replay.txt
    ::vmdai::stop
} err]} {
    ::driver_fail "$err\n$::errorInfo"
}
exit 0
