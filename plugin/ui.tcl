# ui.tcl - M2 compatibility shim (section 2h). The M1 panel is retired: panel.tcl
# and the plan-08 components draw everything. These names stay because
# bridge.tcl, runtime.tcl and executor.tcl call them; without Tk or without
# a panel window (the tclsh bridge driver) they do nothing.
namespace eval ::vmdai::ui {
    if {![info exists ::vmdai::ui::seen_ready]} { variable seen_ready 0 }
}

proc ::vmdai::ui::_panel_ready {} {
    return [expr {[info commands ::winfo] ne "" && [info commands ::vmdai::panel::on_event] ne ""
        && [winfo exists $::vmdai::panel::win]}]
}

proc ::vmdai::ui::show_panel {} {
    return [::vmdai::panel::show]
}

proc ::vmdai::ui::render_event {event} {
    if {[_panel_ready]} { ::vmdai::panel::on_event $event }
}

proc ::vmdai::ui::session_started {result} {
    if {[_panel_ready]} { ::vmdai::panel::on_session_started $result }
}

proc ::vmdai::ui::replay {chat_id events title} {
    if {[_panel_ready]} { ::vmdai::panel::replay $chat_id $events $title }
}

# A plugin-local event (local.send_failed, local.request_ended). The
# view-model builds it, so nothing happens without a panel.
proc ::vmdai::ui::local_event {kind fields} {
    if {[_panel_ready]} { ::vmdai::panel::on_event [::vmdai::vm::local_event $kind $fields] }
}

# The connection state machine's one-notice-per-transition sink (S3). It
# becomes a local.connection event for the view-model; the first connect
# after launch is not a notice.
proc ::vmdai::ui::notify {level text} {
    variable seen_ready
    if {![_panel_ready]} { return }
    set state [::vmdai::runtime::state]
    if {!$seen_ready} {
        if {$state eq "ready"} { set seen_ready 1 }
        if {$state ne "down"} { return }
    }
    set lost [expr {$state eq "ready" && [::vmdai::panel::bridge_busy]}]
    ::vmdai::panel::on_event [::vmdai::vm::local_event local.connection \
        [dict create state $state detail $text request_lost $lost]]
}

proc ::vmdai::ui::set_busy {on} {
    if {[_panel_ready]} { ::vmdai::panel::set_busy $on }
}

proc ::vmdai::ui::status {text} {
    if {[_panel_ready]} { ::vmdai::statusbar::flash $text 3000 }
}
