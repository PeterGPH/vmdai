# transcript.tcl core (P08-T05): proxy, blocks, reasoning, notes, error
# cards, sticky autoscroll, dump. Run by tests/test_tk_transcript.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched theme viewmodel transcript
::vmdai::theme::init light
set ::vmdai::transcript::opt(animate) 0
wm geometry . 560x420
set t [::vmdai::transcript::create .tx]
pack .tx -fill both -expand 1
update

set ::actions {}
set ::vmdai::transcript::on_action [list apply {{args} {lappend ::actions $args}}]

proc fresh {} {
    set ::actions {}
    ::vmdai::transcript::clear
    update
}
proc ops {args} { ::vmdai::transcript::apply_ops $args }
proc shown {} { return [$::t get -displaychars 1.0 end] }
proc dumped {} { return [lrange [split [::vmdai::transcript::dump] "\n"] 1 end-1] }
# Run the <ButtonRelease-1> script of the link whose text starts at the last match.
proc click_link {label} {
    set at [$::t search -backwards -exact $label end 1.0]
    foreach tag [$::t tag names $at] {
        if {[string match act:* $tag]} { uplevel #0 [tk_bound [$::t tag bind $tag <ButtonRelease-1>]] }
    }
}

test ro-1 {the proxy drops insert/delete/replace, passes tag, mark, peer and get, and takes focus} -body {
    fresh
    ops {block.open b1 user 0 1790208000} {block.append b1 "Load 1HCK"}
    set before [$t get 1.0 end]
    $t insert end INJECTED
    $t delete 1.0 end
    $t replace 1.0 2.0 X
    $t tag add probe 1.0
    $t mark set probe_mark 1.0
    $t peer create $t.__probe
    set r [list [string match .tx.t $t] [winfo class $t] [expr {[$t get 1.0 end] eq $before}] \
        [expr {"probe" in [$t tag names]}] [$t index probe_mark] [winfo class $t.__probe] \
        [$t cget -takefocus] [$t cget -state]]
    destroy $t.__probe
    set r
} -result {1 Text 1 1 1.0 Text 1 normal}

test blocks-seal {a user block shows You and the time; streamed text is sealed in place} -body {
    fresh
    ops {block.open b1 user 0 1790208000} {block.append b1 "load 1hck and show it as a cartoon"} \
        {block.open b2 assistant 1} {block.append b2 "I'll lo"} {block.append b2 "ad it."} \
        {notice info "a note after the block"} \
        {block.seal b2 "I'll load 1hck.\n"}
    dumped
} -result {{001 role rolemeta | You⇥12:00 AM} {002 user | load 1hck and show it as a cartoon} {003 md_p prose | I'll load 1hck.} {004 md_sp prose | } {005 note | a note after the block}}

test blocks-discard {a discarded block leaves nothing; a later seal of it is ignored} -body {
    fresh
    ops {block.open b1 assistant 1} [list block.append b1 "\{\"name\": \"run_vmd_command\""] \
        {block.discard b1} {block.seal b1 "late"} {rule r1} {block.open b2 assistant 2} {block.seal b2 Done.}
    dumped
} -result {{001 rule | <rule>} {002 md_p prose | Done.} {003 md_sp prose | }}

test unknown-op {an unknown op, or a bad argument list, is ignored and counted} -body {
    fresh
    ops {frobnicate 1 2} {block.open b1 assistant} {block.open b2 assistant 1} {block.append b2 ok}
    list [dumped] $::vmdai::transcript::S(errors)
} -result {{{001 prose | ok}} 1}

test reasoning-1 {Thinking… while streaming, then "Thought for N s ▸", which expands and collapses} -body {
    fresh
    ops {reasoning.open b1 1} {reasoning.append b1 "The user wants "} {reasoning.append b1 "the atom count."}
    set r [list [dumped]]
    ops {reasoning.seal b1 2.6} {block.open b2 assistant 1} {block.append b2 Answer}
    lappend r [dumped]
    ::vmdai::transcript::toggle_think b1
    lappend r [lrange [dumped] 0 1]
    ::vmdai::transcript::toggle_think b1
    lappend r [lindex [dumped] 0]
} -result {{{001 think | Thinking…}} {{001 think | Thought for 3 s ▸} {003 prose | Answer}} {{001 think | Thought for 3 s ▾} {002 thinkbody | The user wants the atom count.}} {001 think | Thought for 3 s ▸}}

test notice-1 {notes are centred lines; a notice action is a link that runs the action} -body {
    fresh
    ops {notice warn "Reconnected: request lost" retry} {notice info Stopped}
    click_link Retry
    list [dumped] $::actions
} -result {{{001 link note notewarn | Reconnected: request lost · Retry} {002 note | Stopped}} retry}

test error-card-1 {an error card: ✗ title, a copyable hint for model_not_found, the action link} -body {
    fresh
    ops {error.card model_not_found {Model not found: qwen3.8:27b} {ollama pull qwen3.8:27b} choose_model} \
        {error.card NO_MODEL {No model configured} {Set up a model in Settings.} open_settings}
    click_link Copy
    click_link "Choose model"
    click_link "Set up a model"
    list [dumped] $::actions
} -result {{{001 ecard ecard_t ecard_x | ✗ Model not found: qwen3.8:27b} {002 ecard ecard_c link | ollama pull qwen3.8:27b   Copy} {003 ecard ecard_a link | Choose model} {004 ecard ecard_t ecard_x | ✗ No model configured} {005 ecard ecard_h | Set up a model in Settings.} {006 ecard ecard_a link | Set up a model}} {{copy_text {ollama pull qwen3.8:27b}} choose_model open_settings}}

test sticky-autoscroll {scrolled up: no jump and the pill shows; at the bottom: follows, pill hides} -body {
    fresh
    for {set i 1} {$i <= 60} {incr i} {
        ops [list block.open u$i assistant 1] [list block.append u$i "line $i"]
    }
    update
    set r [list [expr {[lindex [$t yview] 1] >= 0.999}] [::vmdai::transcript::pill_shown]]
    $t yview moveto 0
    update
    ops {block.open x1 assistant 1} {block.append x1 "new output"}
    update
    lappend r [lindex [$t yview] 0] [::vmdai::transcript::pill_shown]
    $t yview moveto 1.0
    update
    lappend r [::vmdai::transcript::pill_shown]
    ops {block.open x2 assistant 1} {block.append x2 "more output"}
    update
    lappend r [expr {[lindex [$t yview] 1] >= 0.999}] [::vmdai::transcript::pill_shown]
} -result {1 0 0.0 1 0 1 0}

test non-bmp {emoji and a lone surrogate degrade without error in blocks, seals, notes and the dump} -body {
    fresh
    set emoji "DNA \U0001F9EC ok"
    set lone "x \uD800 y"
    ops [list block.open b1 user 0 1790208000] [list block.append b1 $emoji] \
        [list block.open b2 assistant 1] [list block.append b2 $lone] [list block.seal b2 "$emoji $lone"] \
        [list notice info $emoji] [list error.card other $emoji $lone open_log]
    set d [::vmdai::transcript::dump]
    list $::vmdai::transcript::S(errors) [regexp -all {DNA} $d] [string match "*x * y*" $d]
} -result {0 4 1}

test clear-1 {clear empties the text, drops per-item tags and state, and ids can be reused} -body {
    fresh
    ops {block.open b1 assistant 1} {block.append b1 one} {notice warn w retry}
    ::vmdai::transcript::clear
    set r [list [$t get 1.0 end-1c] [llength [lsearch -all [$t tag names] *:*]]]
    ops {block.open b1 assistant 1} {block.append b1 two}
    lappend r [dumped]
} -result {{} 0 {{001 prose | two}}}

test menu-prose {right-click on prose offers Copy and Select all} -body {
    fresh
    ops {block.open b1 assistant 1} {block.append b1 "some prose"}
    set items [::vmdai::transcript::menu_items 1.2]
    list [lindex $items 0] [lindex $items 2]
} -result {Copy {Select all}}

test wheel-embeds {embedded windows carry the ChatVMDScroll bindtag, so the wheel over them scrolls the transcript (V5)} -body {
    fresh
    for {set i 1} {$i <= 60} {incr i} {
        ops [list block.open u$i assistant 1] [list block.append u$i "line $i"]
    }
    ops {rule r1} {block.open b1 assistant 2} {block.seal b1 Done.}
    update
    set f [lindex $::vmdai::transcript::S(rules) 0]
    set before [lindex [$t yview] 0]
    ::vmdai::transcript::_wheel 120
    update
    list [lindex [bindtags $f] 0] [expr {[bind ChatVMDScroll <MouseWheel>] ne ""}] \
        [expr {[lindex [$t yview] 0] < $before}]
} -result {ChatVMDScroll 1 1}

test relayout-widths {-padx 14 below 440 px, else 20; prose stops at 680 px on a wide window (V2, V6)} -body {
    fresh
    ops {block.open b1 assistant 1} {block.append b1 "some prose"}
    set r {}
    foreach g {380x420 560x420 1000x420} {
        wm geometry . $g
        update
        ::vmdai::transcript::relayout
        set cw [::vmdai::transcript::_content_width]
        set rm [$t tag cget prose -rmargin]
        lappend r [$t cget -padx] [expr {$rm > 0}] [expr {$cw - $rm <= 680}]
    }
    wm geometry . 560x420
    update
    ::vmdai::transcript::relayout
    set r
} -result {14 0 1 20 0 1 20 1 1}

cleanupTests
exit
