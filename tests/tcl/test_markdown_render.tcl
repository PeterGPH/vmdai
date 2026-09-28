# P10-T04: Markdown rendered on seal (Part B V4 "Markdown"; V1 NBSP; V8 md-1/2).
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
source [file join $env(VMDAI_REPO) tests tcl m3_helpers.tcl]
::harness::stub_bridge
::harness::stub_desktop

set FINAL "- **Protein** — NewCartoon, colored by secondary structure\n- **ATP** — Licorice, colored by element\n\nThe radius of gyration is **20.84 Å**. To reproduce it, run `measure rgyr` on a protein selection:\n\n```tcl\nset sel \[atomselect top protein\]\nmeasure rgyr \$sel\n```"

test md-1 {markdown is rendered, not shown raw} -body {
    set w [::m3::root_text]
    ::vmdai::md::render_into $w end $FINAL
    set all [$w get 1.0 end]
    list [string first "**" $all] [string first "```" $all] [lindex [::m3::ranges_text $w md_b] end]
} -result [list -1 -1 "20.84 Å"]

test md-2 {fenced block lines are tagged code} -body {
    set w [::m3::root_text]
    ::vmdai::md::render_into $w end $FINAL
    llength [lsearch -all [split [join [::m3::ranges_text $w md_pre] \n] \n] *measure*]
} -result 1

test md-inline-nowrap {inline code never wraps, wherever it falls on a 380 px line} -body {
    set w [::m3::root_text 380x700]
    set wrapped {}
    for {set n 0} {$n <= 30} {incr n} {
        $w delete 1.0 end
        ::vmdai::md::render_into $w end "[string repeat {word } $n]`measure rgyr \$sel` tail"
        update idletasks
        foreach {a b} [$w tag ranges md_code] {
            if {[$w count -update -displaylines $a $b] != 0} { lappend wrapped $n }
        }
    }
    list [winfo width $w] $wrapped [string first " " [lindex [::m3::ranges_text $w md_code] 0]]
} -result {380 {} -1}

test md-codehdr {a fenced block gets a "tcl ... Copy" header whose Copy copies the exact code} -body {
    set w [::m3::root_text]
    ::vmdai::md::render_into $w end $FINAL
    set ::harness::clipboard ""
    ::vmdai::md::copy_at $w [lindex [$w tag ranges md_copy] 0]
    list [::m3::ranges_text $w md_codehdr] [::m3::ranges_text $w md_copy] $::harness::clipboard \
        [::m3::ranges_text $w syn_cmd] [lindex [$w tag cget md_codehdr -tabs] 1]
} -result [list [list "tcl\tCopy\n"] Copy "set sel \[atomselect top protein\]\nmeasure rgyr \$sel" \
    {set atomselect measure} right]

test md-basetags {every inserted character carries basetags; no trailing newline} -body {
    set w [::m3::root_text]
    $w insert end "before\n"
    set end [::vmdai::md::render_into $w end "A **b**\n\n- c" {prose wl:r1}]
    $w insert end "|after"
    list [$w get 2.0 "end - 1c"] [$w tag ranges wl:r1] $end
} -result [list "A b\n•\tc|after" {2.0 3.3} 3.3]

test md-proxy {a renamed widget behind a read-only proxy renders and right-aligns Copy} -body {
    set w [::m3::root_text 600x700]
    rename $w ::m3::real_md
    proc ::$w {args} {
        if {[lindex $args 0] in {insert delete replace}} { return }
        uplevel 1 [list ::m3::real_md {*}$args]
    }
    ::vmdai::md::render_into ::m3::real_md end "```tcl\nputs hi\n```"
    set r [list [::vmdai::md::_window_of ::m3::real_md] [lindex [$w tag cget md_codehdr -tabs] 0]]
    rename ::$w {}
    rename ::m3::real_md {}
    destroy $w
    set r
} -result {.m3md 546}

test md-seal {streamed text stays raw; the sealed block is rendered} -setup {
    ::m3::use_mws
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    set rid req_000000000088
    ::m3::render [::m3::ev system state "" [dict create kind request.started request_id $rid \
        chat_id chat_000000000088 provider ollama model qwen3.8:27b max_turns 28 vision true think false]]
    ::m3::render [::m3::ev assistant chunk "Loaded **1hck** with `mol new`" [dict create request_id $rid turn 1]]
    ::harness::settle
} -body {
    set streaming [expr {[string first "**1hck**" [$t get 1.0 end]] >= 0}]
    ::m3::render [::m3::ev assistant message "Loaded **1hck** with `mol new`." \
        [dict create request_id $rid turn 1 final true]]
    ::harness::settle
    set all [$t get 1.0 end]
    list $streaming [string first "**" $all] [::m3::ranges_text $t md_b] [::m3::ranges_text $t md_code]
} -result [list 1 -1 1hck "mol new"]

test md-copy-plain {copying rendered inline code gives plain spaces} -body {
    $t tag remove sel 1.0 end
    $t tag add sel {*}[$t tag ranges md_code]
    set ::harness::clipboard ""
    ::vmdai::panel::copy_selection
    set ::harness::clipboard
} -result {mol new}

test md-pre-spacing {fenced code lines are not spaced by the base prose tag; the block ends 8 px below} -body {
    set w [::m3::root_text]
    $w tag configure prose -font ChatBody -spacing3 8
    ::vmdai::md::render_into $w end "Para one.\n\n```tcl\nset a 1\nset b 2\nset c 3\n```\nAfter." prose
    set h3 [$w count -update -ypixels 3.0 4.0]
    set h4 [$w count -update -ypixels 4.0 5.0]
    set h5 [$w count -update -ypixels 5.0 6.0]
    list [expr {$h3 == [font metrics ChatCode -linespace] && $h4 == $h3}] [expr {$h5 - $h4 >= 8}]
} -result {1 1}

cleanupTests
