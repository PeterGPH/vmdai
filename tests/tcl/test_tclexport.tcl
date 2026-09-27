# tclexport.tcl (P08-T11): the Copy/Save .tcl ledger. No Tk.
# Run by tests/test_tcl_tclexport.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched config net executor tclexport

# Evaluate exported Tcl in a fresh interpreter whose VMD commands only
# record their arguments; return the recorded calls.
proc replay {script} {
    set i [interp create]
    interp eval $i {
        set ::CALLS {}
        foreach c {mol color display render measure} {
            proc $c {args} "lappend ::CALLS \[list $c {*}\$args\]"
        }
    }
    set rc [catch {interp eval $i $script} err]
    set calls [interp eval $i {set ::CALLS}]
    interp delete $i
    if {$rc} { return [list error $err] }
    return $calls
}

set CMD "mol new 1hck.pdb\nmol modstyle 0 top NewCartoon\ncolor Display Background white\ndisplay backgroundcolor white\nrender TachyonInternal a.tga"

test test_applied_kept_rest_commented {applied statements are kept byte for byte, the failed one and the rest are commented out, and a call that applied nothing is left out} -body {
    ::vmdai::tclexport::reset
    ::vmdai::tclexport::record req_1 k1 $CMD 3 4
    ::vmdai::tclexport::record req_1 k2 "bogus 1" 0 1
    ::vmdai::tclexport::record req_1 k3 "mol new a.pdb; set p C:\\dir\\" 1 2
    ::vmdai::tclexport::record req_1 k4 "measure rgyr top" 1 ""
    ::vmdai::tclexport::record req_1 k5 "mol delrep 0 top\nmol addrep top\nmol off 0" 1 ""
    set text [::vmdai::tclexport::run_tcl req_1]
    list $text [replay $text]
} -result [list "mol new 1hck.pdb\nmol modstyle 0 top NewCartoon\ncolor Display Background white\n# statement 4 of 5 failed; statements 4–5 were not applied:\n# display backgroundcolor white\n# render TachyonInternal a.tga\nmol new a.pdb\n# statement 2 of 2 failed; statement 2 was not applied:\n# set p C:\\dir\\ \nmeasure rgyr top\nmol delrep 0 top\n# statements 2–3 were not applied:\n# mol addrep top\n# mol off 0\n" \
    {{mol new 1hck.pdb} {mol modstyle 0 top NewCartoon} {color Display Background white} {mol new a.pdb} {measure rgyr top} {mol delrep 0 top}}]

test test_run_and_chat_tcl {runs keep their order, a late result replaces its entry in place, chat_tcl numbers the runs, save writes UTF-8, reset forgets} -body {
    ::vmdai::tclexport::reset
    ::vmdai::tclexport::record req_1 k1 "mol new 1hck.pdb" 1 ""
    ::vmdai::tclexport::record req_2 k3 "measure rgyr \[atomselect top protein\]" 1 ""
    ::vmdai::tclexport::record req_1 k2 "mol modstyle 0 top NewCartoon" 0 ""
    ::vmdai::tclexport::record req_3 k4 "bogus" 0 1
    ::vmdai::tclexport::record req_1 k2 "mol modstyle 0 top NewCartoon" 1 ""
    set chat [::vmdai::tclexport::chat_tcl]
    set dir [file join $env(HOME) "exports é"]
    file mkdir $dir
    set path [::vmdai::tclexport::save [file join $dir chat.tcl] "# résumé\n$chat"]
    set fh [open $path rb]
    set bytes [read $fh]
    close $fh
    set r [list [::vmdai::tclexport::run_tcl req_1] [::vmdai::tclexport::run_tcl req_3] \
        [::vmdai::tclexport::run_tcl nope] $chat \
        [expr {$bytes eq [encoding convertto utf-8 "# résumé\n$chat"]}] \
        [catch {::vmdai::tclexport::save [file join $env(HOME) missing dir x.tcl] x}]]
    ::vmdai::tclexport::reset
    lappend r [::vmdai::tclexport::chat_tcl] [::vmdai::tclexport::run_tcl req_1]
} -result [list "mol new 1hck.pdb\nmol modstyle 0 top NewCartoon\n" {} {} \
    "# ChatVMD: the Tcl that ran in VMD, in order. Statements that did not run are commented out.\n\n# --- run 1 ---\nmol new 1hck.pdb\nmol modstyle 0 top NewCartoon\n\n# --- run 2 ---\nmeasure rgyr \[atomselect top protein\]\n" \
    1 1 {} {}]

cleanupTests
