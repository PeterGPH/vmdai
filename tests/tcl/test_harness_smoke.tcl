# Smoke test for tests/helpers/tcl.py run_tcltest (P01-T03).
package require tcltest 2
namespace import ::tcltest::*

test harness-1 {the interpreter is Tcl 8.6} -body {
    string match 8.6.* [info patchlevel]
} -result 1

test harness-2 {HOME is a temp dir and VMDAI_REPO is the checkout} -body {
    list [expr {$env(HOME) ne ""}] \
         [file isdirectory $env(HOME)] \
         [file exists [file join $env(VMDAI_REPO) pytest.ini]] \
         [file isdirectory $env(VMDAI_PLUGIN_DIR)]
} -result {1 1 1 1}

cleanupTests
