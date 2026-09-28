# P09-T01: panel.tcl grid assembly (Part B V3, V6).
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop

test panel-grid_rows {one column: toolbar, hairline, banner slot, transcript, hairline, composer, status bar} -body {
    set w [::harness::fresh_panel]
    set rows {}
    foreach child {tb tbline tx cbline cb sb} {
        lappend rows $child [dict get [grid info $w.$child] -row]
    }
    set banner_hidden [expr {[winfo manager $w.banner] eq ""}]
    grid $w.banner
    set banner_row [dict get [grid info $w.banner] -row]
    grid remove $w.banner
    list $rows [grid rowconfigure $w 3 -weight] $banner_hidden $banner_row \
        [winfo class $::vmdai::panel::text] [string match $w.tx* $::vmdai::panel::text]
} -result {{tb 0 tbline 1 tx 3 cbline 4 cb 5 sb 6} 1 1 2 Text 1}

test panel-minsize_default_geometry {380x420 minimum; 560x780 unless plugin.json holds a sane geometry} -body {
    file delete -force [::vmdai::config::plugin_json_path]
    set w [::harness::fresh_panel]
    set r [list [wm minsize $w] [::vmdai::panel::initial_geometry] [wm title $w] [wm state $w] \
        [wm protocol $w WM_DELETE_WINDOW]]
    ::vmdai::config::save_plugin_settings [dict create version 1 python "" appearance system \
        expand_steps 0 geometry 700x900+10+20]
    lappend r [::vmdai::panel::initial_geometry]
    ::vmdai::config::save_plugin_settings [dict create version 1 python "" appearance system \
        expand_steps 0 geometry 200x100+0+0]
    lappend r [::vmdai::panel::initial_geometry]
} -result [list {380 420} 560x780 "ChatVMD \u2014 New chat" withdrawn ::vmdai::panel::withdraw \
    700x900+10+20 560x780]

test panel-withdraw_keeps_request {closing withdraws; the request, its timers and the runtime keep running} -body {
    set w [::harness::fresh_panel]
    set ::harness::busy 1
    ::vmdai::panel::set_busy 1
    set timer [::vmdai::sched::after 60000 {set ::harness::fired 1}]
    ::vmdai::config::save_plugin_settings [dict create version 1 python "" appearance system \
        expand_steps 0 geometry 640x800+5+5]
    uplevel #0 [wm protocol $w WM_DELETE_WINDOW]
    set r [list [wm state $w] [winfo exists $w] [::harness::count_calls cancel] \
        [::harness::count_calls runtime_stop] [expr {$timer in [::vmdai::sched::pending]}] \
        [dict get [::vmdai::bridge::state] busy] \
        [dict get [::vmdai::config::load_plugin_settings] geometry]]
    ::vmdai::sched::cancel $timer
    set ::harness::busy 0
    set r
} -result {withdrawn 1 0 0 1 1 640x800+5+5}

test panel-width_classes {narrow < 440 <= regular <= 720 < wide} -body {
    set out {}
    foreach width {300 439 440 560 720 721 900} {
        lappend out [::vmdai::panel::width_class $width]
    }
    set out
} -result {narrow narrow regular regular regular wide wide}

test panel-menu_actions {toolbar and menu actions reach the right modules} -body {
    ::harness::fresh_panel
    proc ::vmdai::tclexport::chat_tcl {} { return "mol new 1hck.pdb\n" }
    set ::harness::clipboard ""
    set ::harness::opened {}
    set ::vmdai::panel::expand_all 0
    ::vmdai::panel::copy_chat_tcl
    ::vmdai::panel::toggle_expand
    set expanded $::vmdai::panel::expand_all
    ::vmdai::panel::collapse_older
    ::vmdai::panel::open_runs_folder
    ::vmdai::panel::quit_runtime
    list $::harness::clipboard $expanded $::vmdai::panel::expand_all \
        [file tail [lindex $::harness::opened end]] [::harness::count_calls runtime_stop] \
        [::vmdai::panel::provider_label openai-compatible] \
        [::vmdai::panel::hostport http://127.0.0.1:11435/v1]
} -result [list "mol new 1hck.pdb\n" 1 0 .vmdai_runs 1 OpenAI-compatible 127.0.0.1:11435]

# Last: sourcing init.tcl re-sources every module, which replaces the fakes.
# Regression guard (plan-08 ruling I-3): init.tcl's M2 module loop must use
# `source -encoding utf-8`, not a plain `source`. A plain source would decode
# the plan-08 component files (which carry literal UTF-8 glyphs) using the
# process's system encoding instead, so forcing the system encoding to
# iso8859-1 around the source and then checking that statusbar.tcl's own
# " \u00b7 " separator survived intact proves the fix is really in place -
# with a plain source the mangled text fails this check (the last element
# comes out 0).
test panel-start_opens_panel {::vmdai::start opens the panel and returns its path} -body {
    ::harness::fresh_panel
    ::vmdai::panel::dispose
    set enc [encoding system]
    encoding system iso8859-1
    set rc [catch {source [file join $env(VMDAI_PLUGIN_DIR) init.tcl]} err]
    encoding system $enc
    if {$rc} { return -code error $err }
    ::harness::stub_bridge
    proc ::vmdai::runtime::ensure {args} { lappend ::harness::bridge_calls [list ensure] }
    proc ::vmdai::bridge::start_session {args} { lappend ::harness::bridge_calls [list start_session] }
    set ::vmdai::panel::headless 1
    set w [::vmdai::start]
    list $w [winfo class $w] [expr {[::harness::count_calls ensure] >= 1}] [wm state $w] \
        [expr {[string first " \u00b7 " [info body ::vmdai::statusbar::_connection_text]] >= 0}]
} -result {.vmd_ai Toplevel 1 withdrawn 1}

cleanupTests
