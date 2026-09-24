namespace eval ::vmdai {}

set _vmdai_here [file dirname [info script]]
source [file join $_vmdai_here config.tcl]
source [file join $_vmdai_here ui.tcl]
source [file join $_vmdai_here bridge.tcl]

proc ::vmdai::start {} {
    ::vmdai::ui::show_panel
}

proc ::vmdai::stop {} {
    # Close the panel and shut down the runtime. Idempotent — safe to
    # call when the panel was never opened or the runtime never started.
    catch {::vmdai::ui::_thinking_stop}
    catch {destroy $::vmdai::ui::win}
    catch {::vmdai::bridge::shutdown_runtime}
}

proc ::vmdai::reload {} {
    # Convenience helper: stop the current session, then re-source the
    # plugin so edits to .tcl files take effect, then start fresh.
    # Useful during plugin development.
    ::vmdai::stop
    set here [file dirname [info script]]
    source [file join $here init.tcl]
    ::vmdai::start
}

proc ::vmdai::cleanup {} {
    catch {::vmdai::bridge::shutdown_runtime}
}

proc ::vmdai::register_extension {} {
    if {[llength [info commands vmd_install_extension]] == 0} {
        puts {[VMD AI] vmd_install_extension not found. Run ::vmdai::start manually.}
        return
    }

    # If this script is sourced repeatedly, remove old registration first.
    if {[llength [info commands vmd_remove_extension]] > 0} {
        catch {vmd_remove_extension vmd_ai}
    }

    if {[catch {vmd_install_extension vmd_ai ::vmdai::start "Extensions/VMD AI"} err]} {
        puts [format {[VMD AI] Extension registration failed: %s} $err]
        puts {[VMD AI] You can still launch manually with ::vmdai::start}
    }
}

::vmdai::register_extension
