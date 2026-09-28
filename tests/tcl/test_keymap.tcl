# P09-T03: keyboard and interaction map (Part B V5).
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop

test keys-esc_stops {Esc stops a running request and does nothing when idle} -body {
    ::harness::fresh_panel
    set ct [::vmdai::panel::composer_text]
    ::harness::fire $ct <Escape>
    set idle [::harness::count_calls cancel]
    set ::harness::busy 1
    ::vmdai::panel::set_busy 1
    ::harness::fire $ct <Escape>
    set busy [::harness::count_calls cancel]
    set stopping $::vmdai::panel::stopping
    set ::harness::busy 0
    ::vmdai::panel::set_busy 0
    list $idle $busy $stopping
} -result {0 1 1}

test keys-mod_e_toggles {Mod-E toggles the global expand flag from anywhere in the panel} -body {
    ::harness::fresh_panel
    ::vmdai::panel::set_expand_all 0
    set mod [::vmdai::panel::mod_key]
    ::harness::fire [::vmdai::panel::composer_text] <$mod-e>
    set first $::vmdai::panel::expand_all
    ::harness::fire $::vmdai::panel::text <$mod-e>
    list $first $::vmdai::panel::expand_all
} -result {1 0}

test keys-copy_displaychars {<<Copy>> copies display chars: elided text skipped, tabs as two spaces} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::vm::init ::harness::vmstate
    set ev [dict create role user type message text "alpha\tbeta gamma" \
        metadata [dict create request_id req_1]]
    ::vmdai::transcript::apply_ops [::vmdai::vm::apply ::harness::vmstate $ev]
    set at [$t search -exact beta 1.0]
    $t tag configure hidden_for_test -elide 1
    $t tag add hidden_for_test $at "$at + 5 chars"
    $t tag add sel 1.0 end
    set ::harness::clipboard ""
    ::harness::fire $t <<Copy>>
    ::harness::settle
    list [string match "*alpha  gamma*" $::harness::clipboard] \
         [string match "*beta*" $::harness::clipboard] \
         [string match "*\t*" $::harness::clipboard]
} -result {1 0 0}

test keys-up_down_history {Up/Down on the first/last line walk this chat's prompts; Down past the newest restores the draft} -body {
    ::harness::fresh_panel
    ::vmdai::composer::clear_history
    ::vmdai::composer::push_history "one"
    ::vmdai::composer::push_history "two"
    ::vmdai::composer::set_text "draft"
    set ct [::vmdai::panel::composer_text]
    set seen {}
    foreach key {Up Up Up Down Down} {
        $ct mark set insert [expr {$key eq "Up" ? "1.0" : "end -1c"}]
        ::harness::fire $ct <$key>
        lappend seen [::vmdai::composer::get_text]
    }
    for {set i 0} {$i < 60} {incr i} { ::vmdai::composer::push_history "p$i" }
    lappend seen [llength $::vmdai::composer::recall] [lindex $::vmdai::composer::recall 0]
} -result {two one one two draft 50 p10}

test keys-tab_order {Tab: composer -> Send -> toolbar -> transcript, then back to the composer} -body {
    set w [::harness::fresh_panel]
    ::vmdai::panel::set_busy 0
    ::vmdai::composer::set_text "x"
    set ring [::vmdai::panel::focus_ring]
    set first [lindex $ring 0]
    list [winfo class $first] [string match $w.cb* $first] \
        [winfo class [lindex $ring 1]] [string match $w.cb* [lindex $ring 1]] \
        [expr {[llength [lsearch -all -glob $ring $w.tb*]] >= 1}] \
        [expr {[lindex $ring end] eq $::vmdai::panel::text}] \
        [expr {[::vmdai::panel::focus_next [lindex $ring end]] eq $first}] \
        [expr {[::vmdai::panel::focus_prev $first] eq [lindex $ring end]}] \
        [expr {[bind $first <Tab>] ne ""}]
} -result {Text 1 TButton 1 1 1 1 1 1}

cleanupTests
