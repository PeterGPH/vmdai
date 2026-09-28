# init.tcl - ChatVMD entry points, module loading and the VMD menu (spec 2h).
# Loaded by `package require vmd_ai` (pkgIndex.tcl, which the installer's
# ~/.vmdrc line puts on auto_path) or sourced directly. Loading needs no Tk
# and starts nothing: the runtime starts when the panel is opened.

namespace eval ::vmdai {}
package provide vmd_ai 2.0

source [file join [file dirname [file normalize [info script]]] config.tcl]
source [file join $::vmdai::config::plugin_dir sched.tcl]
source [file join $::vmdai::config::plugin_dir net.tcl]
source [file join $::vmdai::config::plugin_dir runtime.tcl]
source [file join $::vmdai::config::plugin_dir bridge.tcl]
source [file join $::vmdai::config::plugin_dir executor.tcl]
source [file join $::vmdai::config::plugin_dir ui.tcl]

# The M2 panel and its components (plan 08/09). Sourced only when Tk is
# loaded, so the tclsh bridge driver (tests/tcl/driver.tcl, no Tk) keeps
# sourcing just the M1 modules above. These files carry literal UTF-8 glyphs
# (spinner frames, ellipsis, the status bar's middle dot), so each is sourced
# with an explicit -encoding utf-8: a plain `source` would decode them using
# the process's system encoding instead and mangle them.
if {[info commands ::winfo] ne ""} {
    foreach ::vmdai::_m {theme viewmodel transcript viewer composer statusbar banner toolbar tclexport panel settings} {
        source -encoding utf-8 [file join $::vmdai::config::plugin_dir $::vmdai::_m.tcl]
    }
    unset ::vmdai::_m
}

# Open the panel and make sure the runtime is up (launch, or attach with
# VMD_AI_ATTACH). Returns the panel's window path, as VMD's menu expects.
proc ::vmdai::start {} {
    set w [::vmdai::panel::show]
    ::vmdai::runtime::ensure
    return $w
}

# Close the panel and stop the runtime. An owned runtime is shut down; an
# attached one keeps running (spec 2d). With -sync, wait (without an event
# loop) until an owned runtime has exited, and give an attached runtime's
# session.stop the same synchronous treatment, so it releases its chat lock
# before a following cleanup resets the http tokens.
proc ::vmdai::stop {args} {
    if {[info commands ::vmdai::panel::dispose] ne ""} { ::vmdai::panel::dispose }
    if {[lsearch -exact $args -sync] >= 0} {
        ::vmdai::bridge::shutdown -sync
        ::vmdai::runtime::stop -sync
    } else {
        ::vmdai::bridge::shutdown
        ::vmdai::runtime::stop
    }
    ::vmdai::executor::reset
}

# Stop everything, then cancel every timer, fileevent and http token the
# plugin registered (S4). The runtime is stopped with -sync first, because
# teardown would cancel the timer that escalates to kill -9; -sync also
# makes an attached runtime's session.stop synchronous, since teardown's
# http::reset would otherwise close the socket before an async request was
# ever written.
proc ::vmdai::cleanup {} {
    catch {::vmdai::stop -sync}
    ::vmdai::sched::teardown
}

# Development helper: tear everything down, re-source the plugin from
# config::plugin_dir and, when Tk is loaded, open the panel again. Returns
# the window path, or "" without Tk.
proc ::vmdai::reload {} {
    ::vmdai::cleanup
    source [file join $::vmdai::config::plugin_dir init.tcl]
    if {[llength [info commands ::winfo]]} {
        return [::vmdai::start]
    }
    return ""
}

# Extensions > VMD AI. Outside VMD (tclsh tests) there is no menu.
proc ::vmdai::register_extension {} {
    if {![llength [info commands ::vmd_install_extension]]} {
        return 0
    }
    if {[llength [info commands ::vmd_remove_extension]]} {
        catch {::vmd_remove_extension vmd_ai}
    }
    if {[catch {::vmd_install_extension vmd_ai ::vmdai::start "VMD AI"} err]} {
        ::vmdai::config::log "menu registration failed: $err"
        return 0
    }
    return 1
}

::vmdai::register_extension
