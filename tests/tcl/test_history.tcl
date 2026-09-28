# P09-T06: the History picker (Part B V4 "History").
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop
set ::env(TZ) :UTC

namespace eval ::test {}
# n chats, oldest first on the wire (the dialog sorts them).
proc ::test::items {n} {
    set items {}
    for {set i 0} {$i < $n} {incr i} {
        set ts [clock format [expr {1790000000 + $i * 60}] -format {%Y-%m-%dT%H:%M:%SZ} -timezone :UTC]
        lappend items [dict create chat_id [format chat_%012x $i] title "Chat $i" \
            updated_at $ts message_count $i]
    }
    return $items
}

test history-columns_newest_50 {Title, Updated, Messages; the newest 50; the first row selected} -body {
    ::harness::fresh_panel
    ::fake::reply chat.history.list ok [dict create items [::test::items 60]]
    set w [::vmdai::history::open]
    ::harness::wait_until {expr {[llength [[::vmdai::history::tree] children {}]] > 0}}
    set tv [::vmdai::history::tree]
    set first [lindex [$tv children {}] 0]
    list [llength [$tv children {}]] [lindex [$tv item $first -values] 0] \
        [lindex [$tv item $first -values] 2] [$tv selection] [$tv cget -columns] \
        [::fake::param [::fake::last chat.history.list] limit] [wm title $w]
} -result {50 {Chat 59} 59 row0 {title updated messages} 50 {ChatVMD History}}

test history-format_updated {Today / Yesterday / weekday / month day / full date} -body {
    set now [clock scan "2026-09-24 15:00:00" -format "%Y-%m-%d %H:%M:%S" -timezone :UTC]
    list [::vmdai::history::format_updated 2026-09-24T14:32:05Z $now] \
         [::vmdai::history::format_updated 2026-09-23T09:10:00Z $now] \
         [::vmdai::history::format_updated 2026-09-21T08:00:00Z $now] \
         [::vmdai::history::format_updated 2026-09-03T08:00:00Z $now] \
         [::vmdai::history::format_updated 2025-12-31T08:00:00Z $now] \
         [::vmdai::history::format_updated garbage $now]
} -result {{Today 14:32} {Yesterday 09:10} {Mon 08:00} {Sep 3} 2025-12-31 garbage}

test history-locked_inline {CHAT_LOCKED shows inline and the dialog stays open} -body {
    ::harness::fresh_panel
    ::fake::reply chat.history.list ok [dict create items [::test::items 3]]
    set ::harness::resume_reply [list rpc_error CHAT_LOCKED "chat is open in another runtime" {}]
    set w [::vmdai::history::open]
    ::harness::wait_until {expr {[llength [[::vmdai::history::tree] children {}]] == 3}}
    ::harness::fire [::vmdai::history::tree] <Return>
    ::harness::wait_until {expr {[::vmdai::history::message] ne ""}}
    set r [list [::vmdai::history::message] [winfo exists $w] [lindex $::harness::bridge_calls end]]
    ::harness::fire [::vmdai::history::tree] <Double-1>
    ::harness::settle
    set ::harness::resume_reply {ok {ok true chat_id chat_000000000002 title {Chat 2}}}
    lappend r [::harness::count_calls resume]
} -result [list "Open in another VMD window" 1 [list resume chat_000000000002] 2]

test history-disabled_while_busy {History is unavailable while a request is running} -body {
    ::harness::fresh_panel
    set ::harness::busy 1
    set ::harness::flashes {}
    set r [list [::vmdai::history::open] [winfo exists .vmd_ai_history] [lindex $::harness::flashes end] \
        [::fake::count chat.history.list]]
    set ::harness::busy 0
    set r
} -result [list "" 0 "History is unavailable while a request is running" 0]

cleanupTests
