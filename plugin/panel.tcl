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
    # An open Settings dialog missed a reload while the runtime was not
    # ready (I2); the next session_started/on_recovered catches it up.
    if {![info exists ::vmdai::panel::settings_stale]} { variable settings_stale 0 }
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
    ::vmdai::theme::set_appearance [::vmdai::theme::saved_appearance]
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
    ::vmdai::runtime::subscribe ::vmdai::panel::on_runtime_state
    bind_keys
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
    # The toolbar tooltip toplevel must not outlive the panel (M4).
    catch {::destroy .vmd_ai_tip}
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
    variable replaying
    set batch {}
    foreach op $ops {
        switch -- [lindex $op 0] {
            status {
                if {!$replaying} { _apply_status $op }
            }
            error.card {
                lappend batch $op
                if {[lindex $op 1] eq "NO_MODEL"} {
                    set nomodel 1
                    _sync_composer
                }
            }
            reasoning.open - reasoning.append - reasoning.seal {
                if {[llength $batch]} {
                    _apply_transcript $batch
                    set batch {}
                }
                _apply_reasoning $op
            }
            default { lappend batch $op }
        }
    }
    if {[llength $batch]} { _apply_transcript $batch }
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
    if {$prompt eq ""} { return 0 }
    # A refused send (not connected, or a request already running) keeps the
    # draft and the chat title untouched, and never joins recall (I1).
    if {![::vmdai::bridge::send $prompt]} { return 0 }
    # Sending jumps to the end and follows the new run (V5 sticky autoscroll).
    ::vmdai::transcript::follow_end
    set last_sent $prompt
    ::vmdai::composer::push_history $prompt
    ::vmdai::composer::set_text ""
    if {$title eq "New chat"} { set_title [_title_from $prompt] }
    return 1
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

# A new chat is empty, so it shows the empty state again once the runtime
# has answered runtime.info.
proc ::vmdai::panel::new_chat {} {
    variable rt_info
    variable text
    if {[bridge_busy]} { return }
    reset_view
    ::vmdai::bridge::new_chat
    if {[dict size $rt_info]} { ::vmdai::transcript::show_empty_state [empty_info] $text }
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

# Called after Settings saves, and on session start: re-reads runtime.info
# and profiles.list before updating the status bar and empty state.
proc ::vmdai::panel::refresh_info {} {
    ::vmdai::net::call runtime.info {} [list ::vmdai::panel::_on_info]
    ::vmdai::net::call profiles.list {} [list ::vmdai::panel::_on_profiles]
}

# ---- keyboard map (Part B V5; P09-T03) ----------------------------------------

# Mod means Command on aqua and Control elsewhere.
proc ::vmdai::panel::mod_key {} {
    if {[tk windowingsystem] eq "aqua"} { return Command }
    return Control
}

proc ::vmdai::panel::_first_of_class {w cls} {
    set queue [list $w]
    while {[llength $queue]} {
        set queue [lassign $queue current]
        foreach child [winfo children $current] {
            if {[winfo class $child] eq $cls} { return $child }
            lappend queue $child
        }
    }
    return ""
}

# The composer's input (plan 08 builds it as the first Text under $win.cb).
proc ::vmdai::panel::composer_text {} {
    variable win
    return [_first_of_class $win.cb Text]
}

# Focusable, managed descendants of w in stacking order. A disabled ttk
# button (Send with an empty composer) is skipped, as Tk's traversal does.
proc ::vmdai::panel::_focusables {w} {
    set out {}
    foreach child [winfo children $w] {
        if {[winfo manager $child] eq ""} { continue }
        set takefocus ""
        catch {set takefocus [$child cget -takefocus]}
        set cls [winfo class $child]
        set candidate [expr {$takefocus eq "1" || ($takefocus in {"" ttk::takefocus}
            && $cls in {Text TButton TEntry TCombobox TCheckbutton Button Entry})}]
        if {$candidate && ![catch {$child instate disabled} disabled] && $disabled} {
            set candidate 0
        }
        if {$candidate} { lappend out $child }
        set out [concat $out [_focusables $child]]
    }
    return $out
}

# V5 Tab order: composer -> Send/Stop -> toolbar -> transcript.
proc ::vmdai::panel::focus_ring {} {
    variable win
    variable text
    set ring [concat [_focusables $win.cb] [_focusables $win.tb]]
    if {$text ne ""} { lappend ring $text }
    return $ring
}

proc ::vmdai::panel::focus_next {w {step 1}} {
    set ring [focus_ring]
    if {![llength $ring]} { return "" }
    set i [lsearch -exact $ring $w]
    set j [expr {$i < 0 ? 0 : ($i + $step) % [llength $ring]}]
    set target [lindex $ring $j]
    focus $target
    return $target
}

proc ::vmdai::panel::focus_prev {w} {
    return [focus_next $w -1]
}

# <<Copy>>: display chars only (collapsed text is skipped), tabs as two spaces.
proc ::vmdai::panel::copy_selection {} {
    variable text
    if {[catch {$text get -displaychars sel.first sel.last} s]} { return "" }
    set s [::vmdai::md::plain_text [string map [list "\t" "  "] $s]]
    _set_clipboard $s
    return $s
}

# Scroll keys are user scroll gestures (V5): paging or jumping to the top
# stops following unless the view ends at the bottom; the end follows again.
proc ::vmdai::panel::scroll_transcript {how {n 1}} {
    switch -- $how {
        page   { ::vmdai::transcript::user_scroll scroll $n pages }
        top    { ::vmdai::transcript::user_scroll moveto 0 }
        bottom { ::vmdai::transcript::follow_end }
    }
}

proc ::vmdai::panel::on_escape {} {
    if {![bridge_busy]} { return 0 }
    on_stop
    return 1
}

proc ::vmdai::panel::bind_keys {} {
    variable win
    variable text
    set mod [mod_key]
    bind $win <Escape> {if {[::vmdai::panel::on_escape]} break}
    foreach key {e E} { bind $win <$mod-$key> {::vmdai::panel::toggle_expand; break} }
    foreach key {n N} { bind $win <$mod-$key> {::vmdai::panel::new_chat; break} }
    foreach key {l L} { bind $win <$mod-$key> {::vmdai::composer::focus; break} }
    bind $win <$mod-comma> {::vmdai::panel::open_settings; break}
    set input [composer_text]
    if {$input ne ""} {
        bind $input <Up>         {if {[::vmdai::composer::on_up %W]} break}
        bind $input <Down>       {if {[::vmdai::composer::on_down %W]} break}
        bind $input <Prior>      {::vmdai::panel::scroll_transcript page -1; break}
        bind $input <Next>       {::vmdai::panel::scroll_transcript page 1; break}
        bind $input <$mod-Up>    {::vmdai::panel::scroll_transcript top; break}
        bind $input <$mod-Down>  {::vmdai::panel::scroll_transcript bottom; break}
    }
    bind $text <<Copy>> {::vmdai::panel::copy_selection; break}
    foreach key {a A} { bind $text <$mod-$key> {%W tag add sel 1.0 end; break} }
    # Tab on the toplevel covers Send/Stop and the toolbar in any state (it
    # runs before the `all` traversal binding). The two Text widgets need
    # their own binding: the Text class binding for Tab inserts a tab and breaks.
    foreach w [list $win $input $text] {
        if {$w eq ""} { continue }
        bind $w <Tab> {::vmdai::panel::focus_next %W; break}
        bind $w <<PrevWindow>> {::vmdai::panel::focus_prev %W; break}
    }
}

# ---- view-model wiring (P09-T07) -------------------------------------------------

namespace eval ::vmdai::panel {
    if {![info exists ::vmdai::panel::replaying]} { variable replaying 0 }
    if {![info exists ::vmdai::panel::replayed]} { variable replayed "" }
    if {![info exists ::vmdai::panel::replay_synthetic]} { variable replay_synthetic {} }
    if {![info exists ::vmdai::panel::has_content]} { variable has_content 0 }
    # call_key -> {request_id command} of the Tcl commands this view has seen.
    if {![array exists ::vmdai::panel::commands]} {
        variable commands
        array set commands {}
    }
}

# Every display event (live, local or replayed) enters here.
proc ::vmdai::panel::on_event {ev} {
    variable win
    variable last_sent
    if {![winfo exists $win]} { return }
    render [::vmdai::vm::apply ::vmdai::panel::vm $ev]
    _record_tcl $ev
    set kind ""
    catch {set kind [dict get $ev metadata kind]}
    if {$kind eq "local.send_failed" && $last_sent ne "" && [::vmdai::composer::get_text] eq ""} {
        ::vmdai::composer::set_text $last_sent
    }
}

# Feed the Copy/Save .tcl ledger (P08-T11) from the display events: the
# command comes from tool.started, the statement counts from tool.finished
# (a late tool.finished records again, so the ledger follows the late result).
# Replay goes through here too, so a resumed chat's ledger is rebuilt.
proc ::vmdai::panel::_record_tcl {ev} {
    variable commands
    set md {}
    set kind ""
    set key ""
    catch {set md [dict get $ev metadata]}
    catch {set kind [dict get $md kind]}
    catch {set key [dict get $md call_key]}
    if {$key eq "" || $kind ni {tool.started tool.finished}} { return }
    if {$kind eq "tool.started"} {
        set command ""
        set executor tcl
        catch {set command [dict get $md input command]}
        catch {set executor [dict get $md executor]}
        if {$command ne "" && $executor eq "tcl"} {
            set rid ""
            catch {set rid [dict get $md request_id]}
            set commands($key) [list $rid $command]
        }
        return
    }
    if {![info exists commands($key)]} { return }
    lassign $commands($key) rid command
    set applied 0
    set failed_index ""
    catch {set applied [dict get $md statements applied]}
    catch {set failed_index [dict get $md statements failed index]}
    if {![string is integer -strict $applied]} { set applied 0 }
    if {![string is integer -strict $failed_index]} { set failed_index "" }
    if {[catch {::vmdai::tclexport::record $rid $key $command $applied $failed_index} err]} {
        ::vmdai::config::log "panel: tclexport::record failed for $key: $err"
    }
}

proc ::vmdai::panel::_apply_transcript {ops} {
    variable has_content
    set has_content 1
    ::vmdai::transcript::hide_empty_state
    ::vmdai::transcript::apply_ops $ops
}

# A fresh view: New chat, and before a resumed chat is replayed.
proc ::vmdai::panel::reset_view {} {
    variable has_content
    variable nomodel
    variable stopping
    set has_content 0
    set nomodel 0
    set stopping 0
    ::vmdai::transcript::hide_empty_state
    ::vmdai::transcript::clear
    ::vmdai::transcript::reasoning_reset $::vmdai::panel::text
    ::vmdai::vm::init ::vmdai::panel::vm
    ::vmdai::tclexport::reset
    array unset ::vmdai::panel::commands
    ::vmdai::composer::clear_history
    set_title "New chat"
    _sync_composer
}

# Replay a chat's display log. A request with request.started but no
# request.finished (the runtime died) is closed with local.request_ended.
# The chat's own prompts go back into Up/Down recall (V5 "in this chat").
proc ::vmdai::panel::replay {chat_id events {title ""}} {
    variable replaying
    variable replayed
    variable replay_synthetic
    reset_view
    set replaying 1
    set replay_synthetic {}
    set open ""
    foreach ev $events {
        set kind ""
        set rid ""
        set role ""
        catch {set kind [dict get $ev metadata kind]}
        catch {set rid [dict get $ev metadata request_id]}
        catch {set role [dict get $ev role]}
        if {$role eq "user" && [dict exists $ev text]} {
            ::vmdai::composer::push_history [dict get $ev text]
        }
        if {$kind eq "request.started"} { set open $rid }
        if {$kind eq "request.finished" && $rid eq $open} { set open "" }
        if {[catch {on_event $ev} err]} {
            ::vmdai::config::log "panel: replay skipped an event: $err"
        }
    }
    if {$open ne ""} {
        lappend replay_synthetic local.request_ended
        on_event [::vmdai::vm::local_event local.request_ended [dict create request_id $open]]
    }
    set replaying 0
    if {$title ne ""} { set_title $title }
    set replayed $chat_id
}

proc ::vmdai::panel::on_session_started {result} {
    variable win
    variable settings_stale
    if {![winfo exists $win]} { return }
    # A recovering session_started is followed by chat.resume or a give-up;
    # on_recovered is the point that actually ends recovery (I2).
    if {[info exists ::vmdai::bridge::recovering] && $::vmdai::bridge::recovering} { return }
    refresh_info
    _load_persisted
    if {$settings_stale} { _reload_settings }
}

proc ::vmdai::panel::_on_info {form args} {
    variable win
    variable rt_info
    variable has_content
    variable nomodel
    variable text
    if {$form ne "ok" || ![winfo exists $win]} { return }
    set rt_info [lindex $args 0]
    set model ""
    set loop 0
    catch {set model [dict get $rt_info model]}
    catch {set loop [string is true -strict [dict get $rt_info agent_loop]]}
    set nomodel [expr {$model eq "" || $model eq "null" || !$loop}]
    _sync_composer
    _update_status
    if {!$has_content} { ::vmdai::transcript::show_empty_state [empty_info] $text }
}

proc ::vmdai::panel::_on_profiles {form args} {
    variable server_host
    if {$form ne "ok"} { return }
    set r [lindex $args 0]
    set active ""
    set url ""
    catch {set active [dict get $r active]}
    catch {set url [dict get $r profiles $active base_url]}
    set server_host [expr {$url eq "" || $url eq "null" ? "" : [hostport $url]}]
    _update_status
}

# runtime.info plus what the empty state's Ready group shows.
proc ::vmdai::panel::empty_info {} {
    variable rt_info
    set info $rt_info
    set endpoint ""
    catch {
        set rt [::vmdai::runtime::info]
        set endpoint "[dict get $rt host]:[dict get $rt port]"
    }
    dict set info connected [expr {[::vmdai::runtime::state] eq "ready"}]
    dict set info endpoint $endpoint
    dict set info folder [pwd]
    dict set info runs [run_count]
    return $info
}

# runtime::subscribe callback: banner, status bar and composer. Settings
# reloads only from on_session_started/on_recovered (I2): runtime::_became_ready
# runs subscribers before recover starts the new session, so a reload from
# here would still use the old session and token; mark it stale instead and
# catch it up once the new session is in place.
proc ::vmdai::panel::on_runtime_state {old new detail} {
    variable win
    variable settings_stale
    if {![winfo exists $win]} { return }
    ::vmdai::banner::on_runtime_state $old $new $detail
    _sync_composer
    _update_status
    if {$new ne "ready"} { set settings_stale 1 }
}

# bridge::_recover_finished (I2): recovery has ended, with a new session
# (and, for a resumed chat, a new chat.resume answer) in place.
proc ::vmdai::panel::on_recovered {} {
    variable win
    if {![winfo exists $win]} { return }
    refresh_info
    _load_persisted
    _reload_settings
}

# Reload an open Settings dialog from the runtime that is current right now.
proc ::vmdai::panel::_reload_settings {} {
    variable settings_stale
    set settings_stale 0
    if {[winfo exists $::vmdai::settings::win]} { ::vmdai::settings::reload }
}

# ---- reasoning (P09-T08) --------------------------------------------------------

namespace eval ::vmdai::panel {
    if {![info exists ::vmdai::panel::reasoning_visible]} { variable reasoning_visible 1 }
}

proc ::vmdai::panel::_apply_reasoning {op} {
    variable text
    variable has_content
    variable replaying
    set has_content 1
    ::vmdai::transcript::hide_empty_state
    lassign $op name b arg
    switch -- $name {
        reasoning.open   { ::vmdai::transcript::reasoning_open $text $b $arg [expr {!$replaying}] }
        reasoning.append { ::vmdai::transcript::reasoning_append $text $b $arg }
        reasoning.seal   { ::vmdai::transcript::reasoning_seal $text $b $arg }
    }
}

proc ::vmdai::panel::set_reasoning_visible {on} {
    variable reasoning_visible
    variable text
    set reasoning_visible [expr {$on ? 1 : 0}]
    if {$text ne "" && [winfo exists $text]} {
        ::vmdai::transcript::set_reasoning_visible $text $reasoning_visible
    }
}

# An empty settings.set patch returns the persisted settings without writing.
proc ::vmdai::panel::_load_persisted {} {
    ::vmdai::net::call settings.set [list patch j "{}"] [list ::vmdai::panel::_on_persisted]
}

proc ::vmdai::panel::_on_persisted {form args} {
    if {$form ne "ok"} { return }
    set persisted {}
    catch {set persisted [dict get [lindex $args 0] persisted]}
    if {[dict exists $persisted reasoning_visible]} {
        set_reasoning_visible [string is true -strict [dict get $persisted reasoning_visible]]
    }
}
