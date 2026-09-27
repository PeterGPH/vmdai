# Snapshot cards, the 30-photo cap and the viewer (P08-T07).
# Run by tests/test_tk_snapshot_cards.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched config net executor theme viewmodel transcript viewer
::vmdai::theme::init light
set ::vmdai::transcript::opt(animate) 0
set ::vmdai::viewer::opt(map) 0
wm geometry . 560x780
set t [::vmdai::transcript::create .tx]
pack .tx -fill both -expand 1
update

set ::actions {}
set ::vmdai::transcript::on_action [list apply {{args} {lappend ::actions $args}}]
set SNAP [file join $env(VMDAI_REPO) docs design round1 assets snap_1hck.png]
set TMP [file join $env(HOME) cards]
file mkdir $TMP

proc fresh {{geometry 560x780}} {
    set ::actions {}
    ::vmdai::transcript::clear
    wm geometry . $geometry
    update
    ::vmdai::transcript::relayout
}
proc ops {args} { ::vmdai::transcript::apply_ops $args }
# A snapshot row plus its card, as the view-model emits them.
proc snap_row {run k thumb path {sent 1} {saved ""}} {
    ops [list tool.open $k capture_vmd_snapshot "check the cartoon" tcl model ""] \
        [list run.chip $run $k running] \
        [list tool.close $k ok "0.9 s" [dict create label "" error "" inline "" preview {} output "" \
            output_path "" total "" applied "" failed_index "" failed_text "" late 0] $thumb] \
        [list run.chip $run $k ok] \
        [list snapshot $k $thumb $path 1280 1547 $saved $sent TachyonInternal]
}
proc card {k} { return $::vmdai::transcript::SNAP($k,card) }
proc texts {k} { return [::vmdai::transcript::card_texts $k] }
# Write a photo made by script to a PNG under TMP.
proc png {name w h script} {
    set img [image create photo -width $w -height $h]
    $img put black -to 0 0 $w $h
    uplevel 1 [list set img $img]
    uplevel 1 $script
    set path [file join $::TMP $name]
    $img write $path -format png
    image delete $img
    return $path
}
proc mode {k} { return $::vmdai::transcript::SNAP($k,mode) }

test tk85-1 {an undecodable PNG gives a text card (name, W × H from the IHDR, Open, Reveal) and loads no photo} -body {
    fresh
    set bad [file join $TMP broken.png]
    set fh [open $bad wb]
    puts -nonewline $fh "\x89PNG\r\n\x1a\n[binary format I 13]IHDR[binary format II 1280 1547]\x08\x02\x00\x00\x00JUNKJUNK"
    close $fh
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    snap_row r1 k1 $bad $bad
    set tx [texts k1]
    list [mode k1] [::vmdai::transcript::loaded_image_count] [lindex $tx 0] \
        [expr {"Open" in $tx}] [expr {"Reveal" in $tx}] [expr {"Save PNG…" in $tx}] \
        [llength [[card k1] find withtag img]]
} -result {text 0 {broken.png · 1280 × 1547} 1 1 0 0}

test thumb_fallback {a missing thumbnail falls back to subsampling the full image} -body {
    fresh
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    snap_row r1 k1 [file join $TMP missing_thumb.png] $SNAP
    set p $::vmdai::transcript::SNAP(k1,photo)
    list [mode k1] [::vmdai::transcript::loaded_image_count] \
        [expr {[image width $p] <= 256 && [image height $p] <= 192}] [expr {[image width $p] > 64}]
} -result {image 1 1 1}

test autocrop-1 {the uniform border is cropped (grid 12, tolerance 36, pad 26) before scaling} -body {
    set path [png framed.png 400 300 {$img put white -to 150 120 250 180}]
    set src [image create photo -file $path]
    set box [::vmdai::transcript::autocrop $src]
    set th [::vmdai::transcript::thumb_photo $src 256 192]
    set r [list $box [image width $th] [image height $th]]
    image delete $src $th
    set r
} -result {{130 94 266 194} 136 100}

test scale-fit {a wide image is scaled by one integer factor to fit 256×192, never cropped to fill} -body {
    set path [png wide.png 1100 300 {$img put white -to 10 10 1090 290}]
    set src [image create photo -file $path]
    set th [::vmdai::transcript::thumb_photo $src 256 192]
    set r [list [image width $th] [image height $th]]
    image delete $src $th
    set r
} -result {220 60}

test not-sent {the card says whether the model saw the snapshot} -body {
    fresh
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    snap_row r1 k1 $SNAP $SNAP 1 /w/fig1.png
    snap_row r1 k2 $SNAP $SNAP 0
    set a [texts k1]
    set b [texts k2]
    list [expr {"✓ Sent to the model" in $a}] [expr {"Saved to fig1.png" in $a}] \
        [expr {"1280 × 1547 · TachyonInternal" in $a}] [expr {"check the cartoon" in $a}] \
        [expr {"✗ Not sent — qwen3.8:27b is text-only" in $b}] [expr {"✓ Sent to the model" in $b}]
} -result {1 1 1 1 1 0}

test max-30 {at most 30 photos stay loaded; older cards show "Show image", which reloads} -body {
    fresh
    set small [png small.png 64 48 {$img put white -to 8 8 56 40}]
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    for {set i 1} {$i <= 32} {incr i} { snap_row r1 s$i $small $small }
    set r [list [::vmdai::transcript::loaded_image_count] [mode s1] [mode s2] [mode s3] \
        [expr {"Show image" in [texts s1]}]]
    uplevel #0 [[card s1] bind lk_show <ButtonRelease-1>]
    lappend r [mode s1] [mode s3] [::vmdai::transcript::loaded_image_count]
    set before [llength [image names]]
    ::vmdai::transcript::clear
    lappend r [::vmdai::transcript::loaded_image_count] [expr {$before - [llength [image names]]}]
} -result {30 unloaded unloaded image 1 image unloaded 30 0 30}

test card-actions {image click opens the viewer; Open, Reveal, Save PNG… and the menu name the file} -body {
    fresh
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    snap_row r1 k1 $SNAP $SNAP
    set c [card k1]
    foreach tag {img lk_open lk_reveal lk_save} { uplevel #0 [$c bind $tag <ButtonRelease-1>] }
    set labels {}
    foreach {label cmd} [::vmdai::transcript::menu_items [lindex [$t tag ranges snap:k1] 0]] {
        lappend labels $label
    }
    list [lsort -unique [lmap a $::actions {lindex $a 1}]] [lmap a $::actions {lindex $a 0}] $labels
} -result [list [list $SNAP] {view_image open_file reveal_file save_png} {Open Reveal {Save PNG…} {Copy path}}]

test last-card-visible {a collapsed run keeps its newest snapshot card visible} -body {
    fresh
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    snap_row r1 k1 $SNAP $SNAP
    snap_row r1 k2 $SNAP $SNAP
    ops {run.close r1 complete 2 0 0 3 0 28} {run.open r2 req_2 qwen3.8:27b 1790208010}
    set d [::vmdai::transcript::dump]
    list [$t tag cget wl:r1 -elide] [regexp -all {thumb \| <card>} $d] [lindex [split $d "\n"] 0]
} -result {1 1 {images 2}}

test stack-narrow {below 440 px the caption stacks under the image} -body {
    fresh 380x700
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    snap_row r1 k1 $SNAP $SNAP
    set c [card k1]
    lassign [$c bbox img] ix0 iy0 ix1 iy1
    set first [lindex [$c find withtag lk_open] 0]
    lassign [$c bbox $first] lx0 ly0
    list [expr {$ly0 > $iy1}] [expr {[winfo reqwidth $c] <= [winfo width $t]}]
} -result {1 1}

test viewer-1 {the viewer shows the whole image, closes on Esc, and frees its photo} -body {
    set w [::vmdai::viewer::open $SNAP]
    set p $::vmdai::viewer::photo
    set r [list $w [wm state $w] [expr {[image width $p] <= [winfo screenwidth .]}] \
        [bind $w <Escape>] [::vmdai::viewer::open /nonexistent/x.png]]
    set w [::vmdai::viewer::open $SNAP]
    set p $::vmdai::viewer::photo
    uplevel #0 [bind $w <Escape>]
    lappend r [winfo exists $w] [expr {$p in [image names]}]
} -result {.vmd_ai_viewer withdrawn 1 ::vmdai::viewer::close {} 0 0}

cleanupTests
exit
