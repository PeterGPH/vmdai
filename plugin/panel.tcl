# panel.tcl - the ChatVMD window (Part B V3, V5, V6; plan 09).
#
# One grid column: toolbar, hairline, banner slot (hidden), transcript
# (weight 1), hairline, composer bar, status bar. Closing the window only
# withdraws it, so a request in progress keeps running. The panel owns the
# view-model state ::vmdai::panel::vm and is the one place that routes ops:
# `status` ops go to the status bar, everything else to the transcript.

namespace eval ::vmdai::panel {
    variable DEFAULT_GEOMETRY 560x780
    variable MIN_W 380
    variable MIN_H 420
    if {![info exists ::vmdai::panel::win]} { variable win .vmd_ai }
    if {![info exists ::vmdai::panel::text]} { variable text "" }
    if {![info exists ::vmdai::panel::title]} { variable title "New chat" }
    if {![info exists ::vmdai::panel::busy]} { variable busy 0 }
    if {![info exists ::vmdai::panel::stopping]} { variable stopping 0 }
    if {![info exists ::vmdai::panel::nomodel]} { variable nomodel 0 }
    if {![info exists ::vmdai::panel::expand_all]} { variable expand_all 0 }
    if {![info exists ::vmdai::panel::headless]} { variable headless 0 }
    if {![info exists ::vmdai::panel::last_sent]} { variable last_sent "" }
    if {![info exists ::vmdai::panel::rt_info]} { variable rt_info {} }
    if {![info exists ::vmdai::panel::server_host]} { variable server_host "" }
    # The view-model state; ::vmdai::vm::init fills it in build.
    if {![info exists ::vmdai::panel::vm]} { variable vm {} }
}

# ---- geometry ---------------------------------------------------------------

proc ::vmdai::panel::width_class {w} {
    if {$w < 440} { return narrow }
    if {$w > 720} { return wide }
    return regular
}

proc ::vmdai::panel::window_title {} {
    variable title
    return "ChatVMD \u2014 $title"
}

# plugin.json's geometry when it is at least the minimum size, else 560x780.
proc ::vmdai::panel::initial_geometry {} {
    variable DEFAULT_GEOMETRY
    variable MIN_W
    variable MIN_H
    set geom ""
    catch {set geom [dict get [::vmdai::config::load_plugin_settings] geometry]}
    if {[regexp {^(\d+)x(\d+)([+-]-?\d+[+-]-?\d+)?$} $geom -> w h] && $w >= $MIN_W && $h >= $MIN_H} {
        return $geom
    }
    return $DEFAULT_GEOMETRY
}

proc ::vmdai::panel::save_geometry {} {
    variable win
    variable MIN_W
    variable MIN_H
    if {![winfo exists $win]} { return }
    set geom [wm geometry $win]
    # A window that was never mapped reports 1x1; never save that.
    if {![regexp {^(\d+)x(\d+)} $geom -> w h] || $w < $MIN_W || $h < $MIN_H} { return }
    if {[catch {
        set settings [::vmdai::config::load_plugin_settings]
        dict set settings geometry $geom
        ::vmdai::config::save_plugin_settings $settings
    } err]} {
        ::vmdai::config::log "panel: could not save the window geometry: $err"
    }
}

# ---- window -----------------------------------------------------------------

proc ::vmdai::panel::_hairline {w} {
    frame $w -height 1 -borderwidth 0 -highlightthickness 0 \
        -background [::vmdai::theme::c hairline]
    ::vmdai::theme::paint $w -background hairline
    return $w
}

proc ::vmdai::panel::build {{w ""}} {
    variable win
    variable text
    variable expand_all
    variable MIN_W
    variable MIN_H
    if {$w ne ""} { set win $w }
    if {[winfo exists $win]} { return $win }
    ::vmdai::theme::init
    toplevel $win
    wm withdraw $win
    $win configure -background [::vmdai::theme::c chrome]
    wm title $win [window_title]
    wm minsize $win $MIN_W $MIN_H
    wm geometry $win [initial_geometry]
    wm protocol $win WM_DELETE_WINDOW ::vmdai::panel::withdraw
    grid columnconfigure $win 0 -weight 1
    # Created first, so default traversal also starts in the composer (V5 Tab).
    ::vmdai::composer::create $win.cb -onsend ::vmdai::panel::on_send -onstop ::vmdai::panel::on_stop
    ::vmdai::toolbar::create $win.tb
    set text [::vmdai::transcript::create $win.tx]
    ::vmdai::banner::create $win.banner
    ::vmdai::statusbar::create $win.sb
    _hairline $win.tbline
    _hairline $win.cbline
    grid $win.tb     -row 0 -column 0 -sticky ew
    grid $win.tbline -row 1 -column 0 -sticky ew
    grid $win.banner -row 2 -column 0 -sticky ew
    grid remove $win.banner
    grid $win.tx     -row 3 -column 0 -sticky nsew
    grid $win.cbline -row 4 -column 0 -sticky ew
    grid $win.cb     -row 5 -column 0 -sticky ew
    grid $win.sb     -row 6 -column 0 -sticky ew
    grid rowconfigure $win 3 -weight 1
    ::vmdai::vm::init ::vmdai::panel::vm
    catch {set expand_all [string is true -strict [dict get [::vmdai::config::load_plugin_settings] expand_steps]]}
    ::vmdai::transcript::set_expand_all $expand_all
    ::vmdai::toolbar::set_title [set ::vmdai::panel::title]
    _sync_composer
    _update_status
    return $win
}

# Map a window unless the panel runs headless (tests).
proc ::vmdai::panel::present {w} {
    variable headless
    if {$headless} { return }
    wm deiconify $w
    raise $w
}

proc ::vmdai::panel::show {} {
    variable win
    build
    present $win
    return $win
}

# Closing the window: withdraw only. Requests, timers and the runtime go on.
proc ::vmdai::panel::withdraw {} {
    variable win
    if {![winfo exists $win]} { return }
    save_geometry
    wm withdraw $win
}

proc ::vmdai::panel::dispose {} {
    variable win
    variable text
    foreach dialog {.vmd_ai_settings .vmd_ai_history} {
        if {[winfo exists $dialog]} { ::destroy $dialog }
    }
    if {![winfo exists $win]} { return }
    save_geometry
    ::destroy $win
    set text ""
}

proc ::vmdai::panel::set_title {s} {
    variable win
    variable title
    set title $s
    if {![winfo exists $win]} { return }
    wm title $win [window_title]
    ::vmdai::toolbar::set_title $s
}

proc ::vmdai::panel::_title_from {prompt} {
    set line [lindex [split [string trim $prompt] "\n"] 0]
    if {[string length $line] > 60} { set line "[string range $line 0 59]\u2026" }
    return $line
}

# ---- busy state -------------------------------------------------------------

# The bridge is the source of truth for "a request is running".
proc ::vmdai::panel::bridge_busy {} {
    set state [::vmdai::bridge::state]
    return [expr {[dict exists $state busy] && [string is true -strict [dict get $state busy]]}]
}

# Called by the bridge (through ui.tcl's shim) when a request starts or ends.
proc ::vmdai::panel::set_busy {on} {
    variable win
    variable busy
    variable stopping
    set busy [expr {$on ? 1 : 0}]
    if {!$busy} { set stopping 0 }
    if {![winfo exists $win]} { return }
    ::vmdai::toolbar::set_busy $busy
    ::vmdai::statusbar::update [dict create busy $busy]
    _sync_composer
}

proc ::vmdai::panel::_composer_mode {} {
    variable busy
    variable stopping
    variable nomodel
    if {$busy} { return [expr {$stopping ? "stopping" : "busy"}] }
    if {[::vmdai::runtime::state] ne "ready"} { return disabled }
    if {$nomodel} { return nomodel }
    return idle
}

proc ::vmdai::panel::_sync_composer {} {
    variable win
    if {![winfo exists $win]} { return }
    ::vmdai::composer::set_mode [_composer_mode]
}

# ---- ops --------------------------------------------------------------------

proc ::vmdai::panel::render {ops} {
    variable nomodel
    set batch {}
    foreach op $ops {
        switch -- [lindex $op 0] {
            status { _apply_status $op }
            error.card {
                lappend batch $op
                if {[lindex $op 1] eq "NO_MODEL"} {
                    set nomodel 1
                    _sync_composer
                }
            }
            default { lappend batch $op }
        }
    }
    if {[llength $batch]} { ::vmdai::transcript::apply_ops $batch }
}

# {status busy <text> <t0>} or {status idle}
proc ::vmdai::panel::_apply_status {op} {
    if {[lindex $op 1] eq "busy"} {
        ::vmdai::statusbar::update [dict create activity [lindex $op 2] t0 [lindex $op 3]]
    } else {
        ::vmdai::statusbar::update [dict create activity "" t0 ""]
    }
}

# ---- actions (composer, toolbar, ... menu, banner) -----------------------------

proc ::vmdai::panel::on_send {args} {
    variable title
    variable last_sent
    if {[llength $args]} { set prompt [lindex $args 0] } else { set prompt [::vmdai::composer::get_text] }
    set prompt [string trim $prompt]
    if {$prompt eq ""} { return }
    set last_sent $prompt
    ::vmdai::composer::push_history $prompt
    ::vmdai::composer::set_text ""
    if {$title eq "New chat"} { set_title [_title_from $prompt] }
    ::vmdai::bridge::send $prompt
}

# Idempotent: Esc on the composer can reach both the composer's own Stop
# binding and the panel's, and Stop shows "Stopping..." until the request ends.
proc ::vmdai::panel::on_stop {args} {
    variable stopping
    if {$stopping || ![bridge_busy]} { return }
    set stopping 1
    ::vmdai::bridge::cancel
    render [::vmdai::vm::stop_requested ::vmdai::panel::vm]
    _sync_composer
}

proc ::vmdai::panel::new_chat {} {
    if {[bridge_busy]} { return }
    ::vmdai::bridge::new_chat
}

proc ::vmdai::panel::open_settings {{tab model} {prefill {}}} {
    return [::vmdai::settings::open $tab $prefill]
}

proc ::vmdai::panel::open_history {} {
    return [::vmdai::history::open]
}

proc ::vmdai::panel::choose_folder {} {
    variable win
    set dir [tk_chooseDirectory -parent $win -title "Project folder" -initialdir [pwd] -mustexist 1]
    if {$dir eq ""} { return "" }
    ::vmdai::bridge::apply_workdir $dir
    _update_status
    return $dir
}

proc ::vmdai::panel::toggle_expand {} {
    variable expand_all
    set_expand_all [expr {!$expand_all}]
}

proc ::vmdai::panel::set_expand_all {on} {
    variable win
    variable expand_all
    set expand_all [expr {$on ? 1 : 0}]
    if {[winfo exists $win]} { ::vmdai::transcript::set_expand_all $expand_all }
}

proc ::vmdai::panel::collapse_older {} {
    set_expand_all 0
}

proc ::vmdai::panel::copy_chat_tcl {} {
    _set_clipboard [::vmdai::tclexport::chat_tcl]
}

proc ::vmdai::panel::save_chat_tcl {} {
    variable win
    set path [tk_getSaveFile -parent $win -title "Save chat .tcl" -defaultextension .tcl \
        -initialfile chat.tcl -initialdir [pwd]]
    if {$path eq ""} { return "" }
    ::vmdai::tclexport::save $path [::vmdai::tclexport::chat_tcl]
    return $path
}

proc ::vmdai::panel::open_runs_folder {} {
    open_path [file join [pwd] .vmdai_runs]
}

proc ::vmdai::panel::open_log {} {
    open_path [::vmdai::config::log_path]
}

proc ::vmdai::panel::quit_runtime {} {
    ::vmdai::runtime::stop
}

proc ::vmdai::panel::open_path {path} {
    if {[tk windowingsystem] eq "aqua"} { set opener open } else { set opener xdg-open }
    if {[catch {exec $opener $path &} err]} {
        ::vmdai::config::log "panel: could not open $path: $err"
    }
}

proc ::vmdai::panel::_set_clipboard {s} {
    variable win
    clipboard clear -displayof $win
    clipboard append -displayof $win -- $s
}

# ---- status bar data --------------------------------------------------------

proc ::vmdai::panel::provider_label {id} {
    switch -- $id {
        ollama { return Ollama }
        openai-compatible { return OpenAI-compatible }
        anthropic-direct { return Anthropic }
        openrouter { return OpenRouter }
        mock { return Mock }
    }
    return $id
}

# host:port of a URL (never the word "tunnel": Part B V1 required fixes).
proc ::vmdai::panel::hostport {url} {
    if {[regexp {^[A-Za-z][A-Za-z0-9+.-]*://([^/?#]+)} $url -> hp]} { return $hp }
    return $url
}

proc ::vmdai::panel::run_count {} {
    return [llength [glob -nocomplain -types d -directory [file join [pwd] .vmdai_runs] *]]
}

proc ::vmdai::panel::_update_status {} {
    variable win
    variable rt_info
    variable server_host
    if {![winfo exists $win]} { return }
    set provider ""
    set model ""
    catch {set provider [dict get $rt_info provider]}
    catch {set model [dict get $rt_info model]}
    if {$model eq "null"} { set model "" }
    ::vmdai::statusbar::update [dict create connection [::vmdai::runtime::state] \
        provider [provider_label $provider] model $model host $server_host \
        folder [pwd] runs [run_count]]
}

# Called after Settings saves. P09-T07 replaces it with the version that
# re-reads runtime.info and profiles.list before updating the status bar.
proc ::vmdai::panel::refresh_info {} {
    _update_status
}
