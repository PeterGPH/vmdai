# P10-T01: dark tokens and appearance events (Part B V2, V7).
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
source [file join $env(VMDAI_REPO) tests tcl m3_helpers.tcl]
::harness::stub_bridge
::harness::stub_desktop
testConstraint aquaWs [expr {[tk windowingsystem] eq "aqua"}]

proc ::m3::mws_old {args} {
    if {[lindex $args 0] in {isdark appearance}} {
        error "bad subcommand \"[lindex $args 0]\": must be style"
    }
    return ""
}

test theme-1 {dark palette swaps tokens; every item re-renders without error} -setup {
    ::m3::use_mws
    set t [::m3::replay 03_conversation]
} -body {
    ::vmdai::theme::set_appearance dark
    ::vmdai::transcript::relayout
    ::harness::settle
    set r [list [::vmdai::theme::mode] [::vmdai::theme::c surface] [$t cget -background]]
    ::vmdai::theme::set_appearance light
    ::vmdai::transcript::relayout
    ::harness::settle
    lappend r [::vmdai::theme::mode] [$t cget -background]
} -result {dark #1e1e1e #1e1e1e light #ffffff}

test dark-events_repaint_dialogs {an appearance event while Settings is open repaints the panel and the dialog} -constraints aquaWs -setup {
    ::m3::use_mws
    set t [::m3::replay 03_conversation]
    ::vmdai::theme::set_appearance system
    set dlg [::vmdai::settings::open model]
    ::harness::settle
    set roots [list $::vmdai::panel::win $dlg]
    set before [::m3::colours $roots]
} -body {
    set ::m3::os_dark 1
    event generate $dlg <<DarkAqua>> -when tail
    ::harness::settle
    set report [::m3::repaint_report $before [::m3::colours $roots]]
    list [::vmdai::theme::mode] [expr {[lindex $report 0] > 0}] [lindex $report 1] [lindex $report 2] \
        [expr {$dlg in [::vmdai::theme::owned_toplevels]}]
} -cleanup {
    ::vmdai::settings::close
    set ::m3::os_dark 0
    ::vmdai::theme::set_appearance light
} -result {dark 1 {} {} 1}

test dark-no_macwindowstyle {without MacWindowStyle only Light and Dark are offered, with no errors} -setup {
    set ::vmdai::theme::macstyle ::m3::no_such_command
    ::vmdai::config::save_plugin_settings [dict create version 1 python "" appearance system \
        expand_steps 0 geometry 560x780]
} -body {
    set r [list [::vmdai::theme::appearance_choices] [::vmdai::theme::set_appearance system] \
        [::vmdai::theme::set_appearance Dark] [::vmdai::theme::set_appearance light]]
    ::harness::fresh_panel
    ::vmdai::settings::open panel
    ::harness::settle
    set p [::vmdai::settings::tab panel]
    lappend r [$p.appearance cget -values] [$p.appearance get] \
        [catch {::vmdai::theme::set_appearance bogus}]
} -cleanup {
    ::vmdai::settings::close
    ::m3::use_mws
    ::vmdai::theme::set_appearance light
} -result {{Light Dark} light dark light {Light Dark} Light 1}

test dark-forced_sets_window_appearance {Light/Dark set the window's MacWindowStyle appearance; System gives it back} -constraints aquaWs -setup {
    ::m3::use_mws
    ::harness::fresh_panel
    ::harness::settle
} -body {
    set ::m3::mws_calls {}
    ::vmdai::theme::set_appearance dark
    set dark [lsearch -all -inline $::m3::mws_calls {appearance .vmd_ai *}]
    set ::m3::mws_calls {}
    ::vmdai::theme::set_appearance system
    set sys [lsearch -all -inline $::m3::mws_calls {appearance .vmd_ai *}]
    list $dark $sys
} -cleanup {
    ::vmdai::theme::set_appearance light
} -result {{{appearance .vmd_ai darkaqua}} {{appearance .vmd_ai auto}}}

test dark-dialog_opened_later {a dialog opened after the switch is drawn dark} -setup {
    ::m3::use_mws
    ::harness::fresh_panel
    ::vmdai::theme::set_appearance dark
} -body {
    set dlg [::vmdai::settings::open model]
    ::harness::settle
    set lo [::m3::light_only]
    set left {}
    foreach e [::m3::colours [list $dlg]] {
        if {[lsearch -exact $lo [lindex $e 1]] >= 0} { lappend left [lindex $e 0] }
    }
    set left
} -cleanup {
    ::vmdai::settings::close
    ::vmdai::theme::set_appearance light
} -result {}

test dark-save_applies {Save in Settings applies the chosen appearance at once} -setup {
    ::m3::use_mws
    ::harness::fresh_panel
    ::fake::reply profiles.list ok [dict create active qwen settings_source file profiles [dict create \
        qwen [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b \
            options [dict create num_ctx 32768]]]]
    ::fake::reply models.list ok [dict create models {} source server]
    ::fake::reply keys.test ok {ok false message {key missing} source none}
    ::fake::reply settings.set ok {ok true settings {} persisted {reasoning_visible true wiki_enabled false}}
    ::fake::reply provider.set ok {ok true}
    ::vmdai::settings::open panel
    ::harness::wait_until {expr {$::vmdai::settings::v(profile) eq "qwen"}}
} -body {
    set ::vmdai::settings::v(appearance) dark
    set ::vmdai::settings::v(appearance_label) Dark
    ::vmdai::settings::save
    ::harness::wait_until {expr {![winfo exists .vmd_ai_settings]}}
    list [::vmdai::theme::mode] [::vmdai::theme::appearance] \
        [dict get [::vmdai::config::load_plugin_settings] appearance]
} -cleanup {
    ::vmdai::theme::set_appearance light
} -result {dark dark dark}

test dark-every_m2_token {every token M2's theme defines has a light and a dark value} -body {
    set missing {}
    foreach tok $::m3::m2_tokens {
        foreach m {light dark} {
            if {![dict exists [dict get $::vmdai::theme::PALETTE $m] $tok]} { lappend missing $m:$tok }
        }
    }
    set missing
} -result {}

test dark-other_windows_untouched {windows that are not ChatVMD's keep their colours} -setup {
    ::m3::use_mws
    toplevel .m3other
    wm withdraw .m3other
    label .m3other.l -text other -foreground #636366 -background #ffffff
} -body {
    ::vmdai::theme::set_appearance dark
    list [.m3other.l cget -foreground] [.m3other.l cget -background] \
        [expr {".m3other" in [::vmdai::theme::owned_toplevels]}]
} -cleanup {
    destroy .m3other
    ::vmdai::theme::set_appearance light
} -result [list #636366 #ffffff 0]

test dark-empty_card_hover {an example card's hover border uses the colours in effect when the pointer moves} -setup {
    ::m3::use_mws
    ::vmdai::theme::set_appearance light
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::transcript::show_empty_state [dict create] $t
    ::harness::settle
} -body {
    ::vmdai::theme::set_appearance dark
    ::harness::settle
    set c [::vmdai::transcript::_empty_path $t].col.cards.c0
    uplevel #0 [bind $c.title <Enter>]
    set in [$c cget -highlightbackground]
    uplevel #0 [bind $c.title <Leave>]
    list [expr {$in eq [::vmdai::theme::c accent]}] \
        [expr {[$c cget -highlightbackground] eq [::vmdai::theme::c hairline]}] [::vmdai::theme::mode]
} -cleanup {
    ::vmdai::theme::set_appearance light
} -result {1 1 dark}

test dark-no_isdark {a MacWindowStyle without isdark (Tk before 8.6.10) offers only Light and Dark} -setup {
    set ::vmdai::theme::macstyle ::m3::mws_old
} -body {
    list [::vmdai::theme::appearance_choices] [::vmdai::theme::set_appearance system] \
        [::vmdai::theme::set_appearance dark] [::vmdai::theme::set_appearance light]
} -cleanup {
    ::m3::use_mws
    ::vmdai::theme::set_appearance light
} -result {{Light Dark} light dark light}

cleanupTests
