# P09-T02: the empty state (Part B V4 "Empty state").
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop
::harness::stub_settings_open

set ::INFO [dict create connected 1 endpoint 127.0.0.1:8765 provider ollama model qwen3.8:27b \
    agent_loop true vision true tools {run_vmd_command capture_vmd_snapshot} \
    folder /tmp/proj runs 12 first_run [dict create servers {}]]

test empty-cards_2x2_or_column {four cards: 2x2 from 520 px, one column below} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::transcript::show_empty_state $::INFO $t
    set cards $t.empty.col.cards
    set r [list [::vmdai::transcript::layout_empty_state 560 $t]]
    foreach i {0 1 2 3} {
        lappend r [dict get [grid info $cards.c$i] -row] [dict get [grid info $cards.c$i] -column]
    }
    lappend r [::vmdai::transcript::layout_empty_state 480 $t]
    foreach i {0 1 2 3} {
        lappend r [dict get [grid info $cards.c$i] -row] [dict get [grid info $cards.c$i] -column]
    }
    lappend r [$cards.c0.title cget -text] [$cards.c3.title cget -text]
    lappend r [$t.empty.col.ready.v0 cget -wraplength]
    ::vmdai::transcript::layout_empty_state 560 $t
    lappend r [$t.empty.col.ready.v0 cget -wraplength]
    # <Configure> reports the overlay's width (the text's inner area): 505 is
    # the overlay at the default 560 px window, 470 one below the threshold.
    lappend r [::vmdai::transcript::_empty_relayout $t 505] [::vmdai::transcript::_empty_relayout $t 470]
} -result {pair 0 0 0 1 1 0 1 1 column 0 0 1 0 2 0 3 0 {Load & style} {Trajectory RMSD} 246 300 pair column}

test empty-card_fills_composer_never_sends {a card fills the composer and never sends} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::transcript::show_empty_state $::INFO $t
    ::harness::fire $t.empty.col.cards.c1.desc <ButtonRelease-1>
    ::harness::settle
    list [::vmdai::composer::get_text] [::harness::count_calls send] [::fake::count chat.send] \
        [winfo exists $t.empty]
} -result [list "Show residues within 5 \u00c5 of the ligand as Licorice" 0 0 1]

test empty-ready_group_first_run_servers {no model yet: the probe's servers are listed with Use...} -body {
    set info [dict create connected 1 endpoint 127.0.0.1:8765 provider "" model "" agent_loop false \
        folder /tmp/proj runs 1 first_run [dict create servers [list [dict create \
            base_url http://127.0.0.1:11435 version 0.12.3 models {qwen3.8:27b llama3.2:3b}]]]]
    set rows [::vmdai::transcript::empty_rows $info]
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::transcript::show_empty_state $info $t
    set ::harness::settings_opened {}
    ::harness::fire [::harness::label_with_text $t.empty "Use\u2026"] <ButtonRelease-1>
    ::harness::settle
    list [lindex $rows 0 2] [lindex $rows 1 2] [lindex $rows 1 3] [lindex $rows 2 2] [lindex $rows 3 2] \
        [lindex $::harness::settings_opened end]
} -result [list "running \u00b7 127.0.0.1:8765" "No model configured" "Set up\u2026" \
    "Found Ollama 0.12.3 at 127.0.0.1:11435 \u00b7 2 models" "/tmp/proj \u00b7 1 run recorded" \
    [list model [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b]]]

test empty-trust_row {the trust notice, title and key hints are shown} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::transcript::show_empty_state $::INFO $t
    set texts [::harness::texts_under $t.empty]
    set rows [::vmdai::transcript::empty_rows $::INFO]
    list [expr {$::vmdai::transcript::TRUST_TEXT in $texts}] [lindex $rows end 0] \
        [expr {"What should VMD do?" in $texts}] [expr {[::vmdai::transcript::_key_hints] in $texts}] \
        [lindex $rows 1 2]
} -result [list 1 warn 1 1 "Ollama \u00b7 qwen3.8:27b \u00b7 tools, vision"]

test empty-hide {hide_empty_state removes the overlay} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::transcript::show_empty_state $::INFO $t
    set before [::vmdai::transcript::empty_state_shown $t]
    ::vmdai::transcript::hide_empty_state $t
    list $before [::vmdai::transcript::empty_state_shown $t] [winfo exists $t.empty]
} -result {1 0 0}

cleanupTests
