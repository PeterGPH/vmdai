# P10-T02: Tcl syntax tokens.  Pure Tcl: runs under tclsh 8.6 (and in CI).
package require tcltest 2
namespace import ::tcltest::*
source [file join $env(VMDAI_PLUGIN_DIR) syntax.tcl]

test syntax-1 {commands, brackets, variables and numbers} -body {
    list [::vmdai::syntax::tokens {set sel [atomselect top protein]}] \
         [::vmdai::syntax::tokens {mol delrep 0 $molid}]
} -result {{{0 3 cmd} {8 9 brace} {9 19 cmd} {31 32 brace}} {{0 3 cmd} {11 12 num} {13 19 var}}}

test syntax-2 {comments, strings, options} -body {
    list [::vmdai::syntax::tokens {# load it}] \
         [::vmdai::syntax::tokens {puts "rgyr: $r"}] \
         [::vmdai::syntax::tokens {mol representation Licorice -radius 0.3 12}]
} -result {{{0 9 cmt}} {{0 4 cmd} {5 15 str}} {{0 3 cmd} {28 35 opt} {36 39 num} {40 42 num}}}

test syntax-3 {offsets run across lines; every line starts a command} -body {
    ::vmdai::syntax::tokens "mol new 1hck.pdb\nmol delrep 0 top"
} -result {{0 3 cmd} {17 20 cmd} {28 29 num}}

test syntax-4 {semicolons and brackets start commands; offsets count characters} -body {
    list [::vmdai::syntax::tokens {set s [measure rgyr $sel]; puts $s}] \
         [::vmdai::syntax::tokens "puts Å; set a(1) 2"]
} -result {{{0 3 cmd} {6 7 brace} {7 14 cmd} {20 24 var} {24 25 brace} {27 31 cmd} {32 34 var}} {{0 4 cmd} {8 11 cmd} {17 18 num}}}

test syntax-5 {braced bodies and namespaced variables} -body {
    ::vmdai::syntax::tokens {if {$x > 2} { puts $::env(HOME) }}
} -result {{0 2 cmd} {3 4 brace} {4 6 var} {9 10 num} {10 11 brace} {12 13 brace} {19 31 var} {32 33 brace}}

test syntax-6 {every class is one of the seven syn tokens; empty input has none} -body {
    set classes {}
    foreach tok [::vmdai::syntax::tokens "# c\nset x \"s\" -o 1 \$v \[y\]"] {
        lappend classes [lindex $tok 2]
    }
    list [lsort -unique $classes] [::vmdai::syntax::tokens ""]
} -result {{brace cmd cmt num opt str var} {}}

cleanupTests
