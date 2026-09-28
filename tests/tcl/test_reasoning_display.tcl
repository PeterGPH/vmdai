# P09-T08: reasoning display (Part B V4 "Reasoning") and its Settings toggle.
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop

namespace eval ::test {}
proc ::test::fresh {} {
    ::harness::fresh_panel
    ::vmdai::transcript::reasoning_reset $::vmdai::panel::text
    ::vmdai::panel::set_reasoning_visible 1
    return $::vmdai::panel::text
}
proc ::test::head {t b} {
    return [string trimright [$t get {*}[$t tag ranges rhead:$b]] "\n"]
}
proc ::test::shown {t} {
    return [$t get -displaychars 1.0 end]
}

test reasoning-thinking_timer {streaming reasoning is one line that counts seconds} -body {
    set t [::test::fresh]
    ::vmdai::transcript::reasoning_open $t b1 1
    set t0 $::vmdai::transcript::R(b1,t0)
    set r [list [::test::head $t b1] [expr {$::vmdai::transcript::R(b1,timer) in [::vmdai::sched::pending]}]]
    ::vmdai::transcript::reasoning_tick $t b1 [expr {$t0 + 3}]
    lappend r [::test::head $t b1]
    ::vmdai::transcript::reasoning_tick $t b1 [expr {$t0 + 75}]
    lappend r [::test::head $t b1] [string match "*Thinking*" [::test::shown $t]]
} -result [list "Thinking… 00:00" 1 "Thinking… 00:03" "Thinking… 01:15" 1]

test reasoning-thought_for_expand {sealed: "Thought for N s" expands to the text and collapses again} -body {
    set t [::test::fresh]
    ::vmdai::transcript::reasoning_open $t b1 1
    ::vmdai::transcript::reasoning_append $t b1 "Check the selection first."
    set timer $::vmdai::transcript::R(b1,timer)
    ::vmdai::transcript::reasoning_seal $t b1 3.4
    set r [list [::test::head $t b1] [$t tag cget rbody:b1 -elide] \
        [string match "*Check the selection*" [::test::shown $t]] \
        [expr {$timer in [::vmdai::sched::pending]}]]
    uplevel #0 [$t tag bind rhead:b1 <ButtonRelease-1>]
    lappend r [::test::head $t b1] [string match "*Check the selection*" [::test::shown $t]]
    uplevel #0 [$t tag bind rhead:b1 <ButtonRelease-1>]
    lappend r [::test::head $t b1]
} -result [list "Thought for 3 s ▸" 1 0 0 "Thought for 3 s ▾" 1 "Thought for 3 s ▸"]

test reasoning-hidden_when_off {reasoning_visible off hides every reasoning line, old and new; lines join their run's work log} -body {
    set t [::test::fresh]
    ::vmdai::panel::render [list {run.open r1 req_1 qwen3.8:27b 0} {reasoning.open b1 1} \
        {reasoning.append b1 "hidden thoughts"} {reasoning.seal b1 2}]
    set r [list [string match "*Thought for 2 s*" [::test::shown $t]]]
    ::vmdai::panel::set_reasoning_visible 0
    lappend r [string match "*Thought for*" [::test::shown $t]]
    ::vmdai::panel::render [list {reasoning.open b2 2}]
    lappend r [string match "*Thinking*" [::test::shown $t]]
    ::vmdai::panel::set_reasoning_visible 1
    lappend r [string match "*Thought for 2 s*" [::test::shown $t]] \
        [string match "*hidden thoughts*" [::test::shown $t]] [string match "*Thinking*" [::test::shown $t]] \
        [expr {"wl:r1" in [$t tag names [lindex [$t tag ranges rhead:b1] 0]]}] \
        [expr {"wl:r1" in [$t tag names [lindex [$t tag ranges rbody:b1] 0]]}]
} -result {1 0 0 1 0 1 1 1}

test reasoning-setting_saved {"Show model reasoning" is persisted and applied at once} -body {
    ::harness::fresh_panel
    ::fake::reply profiles.list ok [dict create active qwen settings_source file profiles [dict create \
        qwen [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b options {}]]]
    ::fake::reply models.list ok {models {} source server}
    ::fake::reply keys.test ok {ok false message {key missing} source none}
    ::fake::reply settings.set ok {ok true settings {} persisted {reasoning_visible true wiki_enabled false}}
    ::fake::reply provider.set ok {ok true}
    ::vmdai::panel::set_reasoning_visible 1
    ::vmdai::settings::open panel
    ::harness::wait_until {expr {[dict size $::vmdai::settings::persisted] > 0
        && $::vmdai::settings::v(profile) eq "qwen"}}
    set r [list $::vmdai::settings::v(reasoning) [winfo manager [::vmdai::settings::tab panel].reasoning]]
    set ::vmdai::settings::v(reasoning) 0
    ::vmdai::settings::save
    ::harness::wait_until {expr {![winfo exists .vmd_ai_settings]}}
    lappend r [::fake::param [::fake::last settings.set] patch] $::vmdai::panel::reasoning_visible
} -result {1 grid {{"reasoning_visible":false}} 0}

cleanupTests
