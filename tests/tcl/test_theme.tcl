# theme.tcl (P08-T04): named fonts, tokens, paint registry, ChatVMD.* styles.
# Run by tests/test_tk_theme.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

set before_theme [ttk::style theme use]
set before_styles {}
foreach s {TFrame TLabel TButton TEntry Treeview} {
    lappend before_styles $s [ttk::style configure $s]
}
source [file join $env(VMDAI_PLUGIN_DIR) theme.tcl]
::vmdai::theme::init light

test test_fonts_defined {every named font exists and derives from TkDefaultFont} -body {
    set missing {}
    foreach f {ChatBody ChatBodyBold ChatBodyItal ChatRole ChatMeta ChatMetaBold ChatH1 ChatH2 ChatCode ChatCodeSmall ChatHair} {
        if {[lsearch -exact [font names] $f] < 0} { lappend missing $f }
    }
    set base [font actual TkDefaultFont -size]
    list $missing [expr {[font configure ChatRole -size] == $base - 1}] \
         [expr {[font configure ChatMeta -size] == $base - 2}] \
         [expr {[font configure ChatH1 -size] == $base + 7}] \
         [font configure ChatCode -family] [font configure ChatHair -size]
} -result [list {} 1 1 1 [::vmdai::theme::mono_family] 1]

test test_mono_family_fallback {SF Mono, then Menlo, then DejaVu Sans Mono, else TkFixedFont's family} -body {
    list [::vmdai::theme::mono_family {Foo "DejaVu Sans Mono" Menlo "SF Mono"}] \
         [::vmdai::theme::mono_family {Foo "DejaVu Sans Mono" Menlo}] \
         [::vmdai::theme::mono_family {Foo "DejaVu Sans Mono"}] \
         [expr {[::vmdai::theme::mono_family {Foo}] eq [font actual TkFixedFont -family]}]
} -result {{SF Mono} Menlo {DejaVu Sans Mono} 1}

test test_tokens {light tokens match Part B V2; chrome is the system colour on aqua} -body {
    list [::vmdai::theme::c surface] [::vmdai::theme::c text] [::vmdai::theme::c muted] \
         [::vmdai::theme::c accent] [::vmdai::theme::c err_bg] [::vmdai::theme::c stop_bg] \
         [expr {[tk windowingsystem] eq "aqua" ? [::vmdai::theme::c chrome] eq "systemWindowBackgroundColor" : [::vmdai::theme::c chrome] eq "#ececec"}]
} -result [list #ffffff #1d1d1f #636366 #0a66d8 #fdecec #1d1d1f 1]

test test_repaint_registry {repaint re-applies registered colours, runs hooks and prunes destroyed widgets} -body {
    label .a
    label .b
    ::vmdai::theme::paint .a -foreground text -background surface
    ::vmdai::theme::paint .b -foreground muted
    set ::hooked 0
    ::vmdai::theme::on_repaint {incr ::hooked}
    set n [::vmdai::theme::painted_count]
    set ::vmdai::theme::T(text) #123456
    destroy .b
    ::vmdai::theme::repaint
    set r [list [.a cget -foreground] [.a cget -background] [expr {$n - [::vmdai::theme::painted_count]}] $::hooked]
    destroy .a
    ::vmdai::theme::init light
    set r
} -result [list #123456 #ffffff 1 1]

test test_only_chatvmd_styles {only ChatVMD.* styles are configured; the ttk theme is never switched} -body {
    set after {}
    foreach s {TFrame TLabel TButton TEntry Treeview} { lappend after $s [ttk::style configure $s] }
    list [expr {[ttk::style theme use] eq $before_theme}] [expr {$after eq $before_styles}] \
         [expr {[ttk::style configure ChatVMD.TFrame -background] ne ""}]
} -result {1 1 1}

test fit_helpers {fit keeps at least min characters; fit_middle keeps both ends} -body {
    set long [string repeat x 200]
    set a [::vmdai::theme::fit ChatCodeSmall 30 $long 12]
    set b [::vmdai::theme::fit_middle ChatCodeSmall 120 "a_very_long_snapshot_file_name_for_testing.png"]
    list [string length $a] [string match "*…" $a] [string match "a_*…*.png" $b]
} -result {13 1 1}

test fit_middle_binary {fit_middle's binary search keeps as much as the linear scan did} -body {
    proc linear {font px text} {
        if {[font measure $font $text] <= $px} { return $text }
        set n [string length $text]
        for {set keep [expr {$n - 1}]} {$keep > 2} {incr keep -1} {
            set head [expr {($keep + 1) / 2}]
            set tail [expr {$keep - $head}]
            set s "[string range $text 0 [expr {$head - 1}]]…[string range $text end-[expr {$tail - 1}] end]"
            if {[font measure $font $s] <= $px} { return $s }
        }
        return "…"
    }
    set bad {}
    foreach text {a ab abc abcd a_very_long_snapshot_file_name_for_testing.png WWWWWWiiiiiiiWWWWWW.png} {
        foreach px {0 5 10 20 40 80 120 160 240 400} {
            if {[::vmdai::theme::fit_middle ChatCodeSmall $px $text] ne [linear ChatCodeSmall $px $text]} {
                lappend bad [list $text $px]
            }
        }
    }
    set bad
} -result {}

cleanupTests
exit
