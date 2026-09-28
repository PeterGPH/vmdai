# capture_panel.tcl - screenshot the real ChatVMD panel in the review states
# A-G of screenshots/native/ (spec Part A section 8, M3 exit; Part B V1).
#
#   docs/design/round1/tools/capture_locked.sh \
#       docs/design/round1/tools/capture_panel.tcl <A..G> </abs/out.png | -> [WxH]
#
# capture_locked.sh loads VMD.app's Tk 8.6 into tclsh (vmdtk_run.tcl) and
# holds the global screen lock.  The panel is the real plugin on the Tk test
# harness's fake transport (tests/tcl/panel_harness.tcl): no runtime, no
# network, and a temporary HOME, so ~/.vmdai is never read or written.  The
# conversation is tests/fixtures/events/03_conversation.jsonl, replayed
# through ::vmdai::panel::on_event with its times moved to "now".
#
#   A  Light: the conversation and a follow-up draft in the composer
#   B  A with Appearance Dark (MacWindowStyle sets this window to darkaqua)
#   C  mid-run: request 1 up to its third tool.started, step 1 expanded
#   D  the empty state (New chat)
#   E  A with Settings open on the Model tab
#   F  A at 466x780, the size of screenshots/native/F_narrow.png
#   G  A after the runtime went away: banner, timeline note, reconnecting
#
# out "-" builds the state withdrawn, logs one line and exits 0 without a
# screenshot, so it needs no screen lock.  Exit codes: 0 done, 2 usage,
# 3 error, 4 timeout.  Tk swallows stdout on macOS, so every run appends one
# line to $CAPTURE_LOG (default $TMPDIR/chatvmd_capture.log).

namespace eval ::cap {
    variable here [file dirname [file normalize [info script]]]
    variable repo [file normalize [file join $here .. .. .. ..]]
    variable follow "Now zoom on the binding pocket\nand make the protein transparent"
    variable title "CDK2 with ATP (1HCK)"
    variable tmp /tmp
    if {[info exists ::env(TMPDIR)] && $::env(TMPDIR) ne ""} {
        set tmp $::env(TMPDIR)
    }
    variable logfile [file join $tmp chatvmd_capture.log]
    if {[info exists ::env(CAPTURE_LOG)] && $::env(CAPTURE_LOG) ne ""} {
        set logfile $::env(CAPTURE_LOG)
    }
    variable home [file join $tmp chatvmd_capture_[pid]]
    variable state [lindex $::argv 0]
    variable out [lindex $::argv 1]
    variable geom [lindex $::argv 2]
}

proc ::cap::log {msg} {
    variable logfile
    variable state
    if {![catch {open $logfile a} fh]} {
        puts $fh "[clock format [clock seconds] -format %H:%M:%S] $state $msg"
        close $fh
    }
}

proc ::cap::finish {code} {
    variable home
    catch {file delete -force $home}
    exit $code
}

proc ::bgerror {msg} {
    ::cap::log "error: $msg | $::errorInfo"
    ::cap::finish 3
}

# vmdtk_run.tcl maps "." when it loads Tk; the panel is its own toplevel.
wm withdraw .
if {[lsearch -exact {A B C D E F G} $::cap::state] < 0 || $::cap::out eq ""} {
    ::cap::log "usage: capture_panel.tcl A..G /abs/out.png|- ?WxH?"
    ::cap::finish 2
}
if {$::cap::geom eq ""} {
    set ::cap::geom [expr {$::cap::state eq "F" ? "466x780" : "560x780"}]
}
after 14000 {::cap::log timeout; ::cap::finish 4}

# The harness expects the test environment; point it at this checkout.
set ::env(VMDAI_REPO) $::cap::repo
set ::env(VMDAI_PLUGIN_DIR) [file join $::cap::repo plugin]
if {![info exists ::env(VMDAI_TCL_TM)]} {
    set ::env(VMDAI_TCL_TM) /Applications/VMD.app/Contents/Frameworks/Tcl.framework/Versions/8.6/Resources/tcl8/8.6
}
file mkdir [file join $::cap::home proj cdk2]
set ::env(HOME) $::cap::home
cd [file join $::cap::home proj cdk2]
source [file join $::cap::repo tests tcl panel_harness.tcl]
source [file join $::cap::repo tests tcl m3_helpers.tcl]
::harness::stub_bridge
::harness::stub_desktop
# Tests never touch the real MacWindowStyle; captures want it, so a forced
# Light or Dark also sets this window's title bar and native controls.
set ::vmdai::theme::macstyle ::tk::unsupported::MacWindowStyle
set ::vmdai::panel::headless [expr {$::cap::out eq "-"}]

# events upto -> 03_conversation's events 0..upto, moved so the last one
# happened 12 s ago (C's status timer then reads 00:12, as in C_midrun.png).
proc ::cap::events {upto} {
    set evs [lrange [::m3::events 03_conversation] 0 $upto]
    set shift [expr {[clock seconds] - 12 - [dict get [lindex $evs end] ts]}]
    set out {}
    foreach ev $evs {
        dict set ev ts [expr {[dict get $ev ts] + $shift}]
        lappend out $ev
    }
    return $out
}

# open_panel appearance: a fresh panel at the capture size (mapped unless
# dry), with the runtime.info and profile the status bar and empty state show.
proc ::cap::open_panel {appearance} {
    variable geom
    ::m3::save_appearance $appearance $geom
    ::harness::fresh_panel
    # The empty state's Ready > Runtime row (panel::empty_info) reads the
    # launched-process endpoint from ::vmdai::runtime::info directly, not
    # from the runtime.info RPC stubbed below (that is the model provider's
    # own endpoint); the harness never launches a runtime, so it defaults to
    # host/port "". Match G's own "127.0.0.1:8765" so D shows a real value.
    set ::vmdai::runtime::info [dict create host 127.0.0.1 port 8765 pid 4242 \
        version 1 protocol 2 launch_token cap owned 1]
    ::fake::reply runtime.info ok [dict create provider ollama model qwen3.8:27b agent_loop true \
        protocol 2 settings_source file]
    ::fake::reply profiles.list ok [dict create active qwen settings_source file profiles [dict create \
        qwen [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b \
            options [dict create num_ctx 32768]]]]
    ::fake::reply models.list ok [dict create models {} source server]
    ::fake::reply keys.test ok {ok false message {key missing} source none}
    ::vmdai::panel::show
    wm geometry $::vmdai::panel::win +80+70
    ::harness::settle
    ::vmdai::panel::refresh_info
    ::harness::wait_until {expr {$::vmdai::panel::rt_info ne ""}} 3000
    ::harness::settle
}

proc ::cap::conversation {upto} {
    variable title
    foreach ev [events $upto] {
        ::vmdai::panel::on_event $ev
    }
    ::vmdai::panel::set_title $title
    ::harness::settle
}

# draft text: text in the composer (focused), transcript scrolled to the end.
proc ::cap::draft {text} {
    ::vmdai::composer::set_text $text
    catch {::vmdai::composer::focus}
    ::vmdai::transcript::relayout
    ::harness::settle
    $::vmdai::panel::text yview moveto 1.0
}

proc ::cap::build {st} {
    variable follow
    set evs [::m3::events 03_conversation]
    set last [expr {[llength $evs] - 1}]
    switch -- $st {
        A - F {
            open_panel light
            conversation $last
            draft $follow
        }
        B {
            open_panel dark
            conversation $last
            draft $follow
        }
        C {
            open_panel light
            set ::harness::busy 1
            conversation [::m3::index_of $evs tool.started 3]
            ::vmdai::transcript::toggle_detail [::m3::call_key_of 03_conversation 1]
            # The replayed events are a finished request's history, not a live
            # one: they update the statusbar's activity/t0 text (panel::render
            # -> _apply_status) but only a real bridge round trip normally
            # flips busy itself (bridge::_on_send -> ui::set_busy).  Drive it
            # directly, exactly as the Tk tests do (e.g. test_panel.tcl,
            # test_keymap.tcl), so the composer, toolbar and status bar show
            # the same mid-run state a live run would.
            ::vmdai::panel::set_busy 1
            draft ""
        }
        D {
            open_panel light
        }
        E {
            open_panel light
            conversation $last
            draft $follow
            ::vmdai::panel::open_settings model
            ::harness::wait_until {expr {[info exists ::vmdai::settings::v(profile)]
                && $::vmdai::settings::v(profile) eq "qwen"}} 3000
            set win $::vmdai::panel::win
            if {[winfo exists .vmd_ai_settings]} {
                wm geometry .vmd_ai_settings \
                    +[expr {[winfo rootx $win] + 30}]+[expr {[winfo rooty $win] + 40}]
            }
        }
        G {
            open_panel light
            conversation $last
            draft $follow
            set ::harness::runtime_state reconnecting
            ::vmdai::panel::on_runtime_state ready reconnecting \
                "Nothing answered on 127.0.0.1:8765. Retrying in 8 s."
            ::vmdai::panel::on_event [::vmdai::vm::local_event local.connection \
                [dict create state reconnecting detail "Runtime not reachable" request_lost 0]]
            ::harness::settle
            $::vmdai::panel::text yview moveto 1.0
        }
    }
    ::harness::settle
}

# shoot_rect: screencapture the region (x, y-28..h+28) of window top, resample
# to its point width (screencapture/Retina is 2x; the native renders are 1x,
# "half size"), and return it as a fresh Tk photo image (caller disposes it).
proc ::cap::shoot_rect {top tmp} {
    set x [winfo rootx $top]
    set y [winfo rooty $top]
    set w [winfo width $top]
    set h [winfo height $top]
    exec /usr/sbin/screencapture -x -o -R$x,[expr {$y - 28}],$w,[expr {$h + 28}] $tmp
    exec /usr/bin/sips --resampleWidth $w $tmp >/dev/null 2>/dev/null
    set img [image create photo -file $tmp]
    return [list $img $x [expr {$y - 28}] $w [expr {$h + 28}]]
}

# shoot: the panel's region plus its 28 pt title bar, like screenshots/native;
# a dialog over the panel (E) is on screen there, so it is in the picture.
# The real Settings window (E) is a titled ttk toplevel whose natural width
# (~686 px, driven by the Model tab's Profile row: combobox + New.../
# Delete... buttons) is wider than the 560 px panel, unlike the native
# prototype's narrow sheet (spec V1 "Not carried over"), and it is offset
# down and right of the panel's own top-left corner -- so neither a plain
# panel-sized region (clips Cancel/Save) nor a single screencapture of their
# union rectangle (the corner outside both windows would show whatever real
# window sits behind them on the capturing machine's desktop) is right.
# Shoot each window separately and compose them into the union canvas with
# Tk's own photo image, so any uncovered corner is blank, never leaked
# desktop content; every state but E has just the one window and one shot.
proc ::cap::shoot {} {
    variable out
    variable home
    set top $::vmdai::panel::win
    raise $top
    set dlg ""
    if {[winfo exists .vmd_ai_settings] && [winfo ismapped .vmd_ai_settings]} {
        set dlg .vmd_ai_settings
        raise $dlg
    }
    update
    after 250
    update
    lassign [shoot_rect $top [file join $home panel_shot.png]] pimg px py pw ph
    if {$dlg eq ""} {
        $pimg write $out -format png
        image delete $pimg
        log "captured $out ${pw}x${ph} mode=[::vmdai::theme::mode]"
        finish 0
    }
    lassign [shoot_rect $dlg [file join $home dlg_shot.png]] dimg dx dy dw dh
    set minx [expr {min($px, $dx)}]
    set miny [expr {min($py, $dy)}]
    set unionw [expr {max($px + $pw, $dx + $dw) - $minx}]
    set unionh [expr {max($py + $ph, $dy + $dh) - $miny}]
    set canvas [image create photo -width $unionw -height $unionh]
    $canvas copy $pimg -to [expr {$px - $minx}] [expr {$py - $miny}]
    $canvas copy $dimg -to [expr {$dx - $minx}] [expr {$dy - $miny}]
    $canvas write $out -format png
    foreach i [list $pimg $dimg $canvas] { image delete $i }
    log "captured $out ${unionw}x${unionh} mode=[::vmdai::theme::mode]"
    finish 0
}

proc ::cap::dry {} {
    set t $::vmdai::panel::text
    set banner [expr {[winfo manager $::vmdai::panel::win.banner] ne ""}]
    log "dry ok mode=[::vmdai::theme::mode] lines=[lindex [split [$t index end] .] 0]\
        settings=[winfo exists .vmd_ai_settings] banner=$banner busy=$::harness::busy"
    finish 0
}

if {[catch {::cap::build $::cap::state} err]} {
    ::cap::log "error: $err | $::errorInfo"
    ::cap::finish 3
}
if {$::cap::out eq "-"} {
    after 300 ::cap::dry
} else {
    after 1500 ::cap::shoot
}
