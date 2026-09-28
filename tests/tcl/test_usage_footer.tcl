# P10-T05: the run footer's usage line (Part B V4 "Run footer"; spec 2c Usage).
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
source [file join $env(VMDAI_REPO) tests tcl m3_helpers.tcl]
::harness::stub_bridge
::harness::stub_desktop

namespace eval ::usage_test {}
# One request with no tool calls that answers "Done." and reports `usage`.
proc ::usage_test::run {rid usage} {
    ::m3::use_mws
    ::harness::fresh_panel
    ::m3::render [::m3::ev system state "" [dict create kind request.started request_id $rid \
        chat_id chat_000000000092 provider ollama model qwen3.8:27b max_turns 28 vision true think false]]
    ::m3::render [::m3::ev assistant chunk "Done." [dict create request_id $rid turn 1]]
    ::m3::render [::m3::ev assistant message "Done." [dict create request_id $rid turn 1 final true]]
    ::m3::render [::m3::ev system state "" [dict create kind request.finished request_id $rid \
        status complete wrapped_up false turns 1 tool_calls 0 final_text_empty false duration_ms 1200 \
        usage $usage error null run_dir null]]
    ::harness::settle
    return $::vmdai::panel::text
}

test usage-line {the footer shows the usage line in muted text; no links without applied Tcl} -body {
    set t [::usage_test::run req_000000000092 [dict create input_tokens_evaluated 20100 output_tokens 640]]
    set idx [$t search -exact "20.1k evaluated · 640 out" 1.0 end]
    set muted 0
    foreach tag [$t tag names $idx] {
        if {![catch {$t tag cget $tag -foreground} fg] && $fg eq [::vmdai::theme::c muted]} { set muted 1 }
    }
    list [expr {$idx ne ""}] $muted [string first "Copy Tcl" [$t get 1.0 end]] \
        [string match -nocase "*context*" [$t get "$idx linestart" "$idx lineend"]]
} -result {1 1 -1 0}

test usage-null-no-line {a null usage prints no usage line and never "0 out"} -body {
    set t [::usage_test::run req_000000000093 [dict create input_tokens_evaluated null output_tokens null]]
    set all [$t get 1.0 end]
    list [string first "evaluated" $all] [string first " out" $all] [string first "0 out" $all]
} -result {-1 -1 -1}

cleanupTests
