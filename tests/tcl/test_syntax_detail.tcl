# P10-T02: Tcl syntax colours in the step detail (Part B V4 "Step detail").
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
source [file join $env(VMDAI_REPO) tests tcl m3_helpers.tcl]
::harness::stub_bridge
::harness::stub_desktop

# 03_conversation's first call runs "mol new 1hck.pdb\nmol delrep 0 top\n..."
test syntax-detail-colours {an open step detail colours its command} -setup {
    ::m3::use_mws
    set t [::m3::replay 03_conversation]
    set k [::m3::call_key_of 03_conversation 1]
    ::vmdai::transcript::toggle_detail $k
    ::harness::settle
} -body {
    list [lrange [::m3::ranges_text $t syn_cmd] 0 1] [expr {[llength [$t tag ranges dcmd:$k]] > 0}] \
        [$t tag cget syn_cmd -foreground]
} -result {{mol mol} 1 #0550ae}

# The failed call 2 has its detail open too (a multi-statement failure opens
# by itself), so a syn_* range may sit in any step's dcmd:<call_key>.
test syntax-detail-only-command {syntax tags stay inside the command bytes} -body {
    set outside {}
    foreach cls {cmd var str num brace opt cmt} {
        foreach {a b} [$t tag ranges syn_$cls] {
            if {[lsearch -glob [$t tag names $a] dcmd:*] < 0} { lappend outside $cls@$a }
        }
    }
    set outside
} -result {}

test syntax-dim-wins {text dimmed with muted keeps its colour over the syntax colours} -body {
    set w [::m3::root_text]
    $w tag configure m3dim -foreground [::vmdai::theme::c muted]
    $w insert end "mol new x.pdb" m3dim
    ::vmdai::syntax::highlight $w 1.0 "mol new x.pdb"
    ::vmdai::theme::syntax_tags $w
    set names [$w tag names 1.0]
    list [expr {[lsearch $names m3dim] > [lsearch $names syn_cmd]}] [$w tag cget syn_cmd -foreground]
} -result {1 #0550ae}

cleanupTests
