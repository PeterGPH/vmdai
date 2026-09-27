# ui.tcl - the M1 panel (spec 2h "Stage M1 keeps the existing ui.tcl"). It
# talks only to ::vmdai::bridge, and the bridge, runtime and executor reach
# it only through notify, render_event, set_busy and status. Without Tk (a
# tclsh driver) or without an open window those four do nothing. Plan 09
# replaces this file with a shim over the M2 panel.

namespace eval ::vmdai::ui {
    variable win ".vmd_ai"
    # Widget paths and stream/indicator state; kept when reload re-sources.
    foreach {name value} {
        transcript "" input "" stream_request_id "" stream_role ""
        thinking_after_id "" thinking_tag "" thinking_dots 0
        workdir_label "" runs_label "" runs_count_after_id ""
    } {
        variable $name
        if {![info exists $name]} { set $name $value }
    }
    unset name value
    # Provider picker state. Apply sends provider.set {provider, model};
    # chat.send never carries the model (a token session runs its profile).
    variable provider
    if {![info exists provider]} { set provider "openrouter" }
    variable model_name
    if {![info exists model_name]} { set model_name "anthropic/claude-sonnet-4.6" }
}

# Sensible default model strings per provider, for the model entry only.
proc ::vmdai::ui::_default_model_for_provider {prov} {
    switch -- $prov {
        "openrouter"       { return "anthropic/claude-sonnet-4.6" }
        "anthropic-direct" { return "claude-sonnet-4-5" }
        "ollama"           { return "llama3.1:8b" }
        default            { return "anthropic/claude-sonnet-4.6" }
    }
}

proc ::vmdai::ui::_dict_get_or {d key default} {
    if {[dict exists $d $key]} {
        return [dict get $d $key]
    }
    return $default
}

# True when Tk is loaded and the panel window exists.
proc ::vmdai::ui::_have_panel {} {
    variable win
    return [expr {[llength [info commands ::winfo]] && [winfo exists $win]}]
}

# First available of SF Mono, Menlo and DejaVu Sans Mono (never a fixed Menlo).
proc ::vmdai::ui::_mono {} {
    set families [font families]
    foreach family {"SF Mono" Menlo "DejaVu Sans Mono"} {
        if {[lsearch -exact $families $family] >= 0} {
            return $family
        }
    }
    return [font actual TkFixedFont -family]
}

# Build the panel (or show it again) and return its window path.
proc ::vmdai::ui::show_panel {} {
    variable win
    variable transcript
    variable input
    variable workdir_label
    variable runs_label

    if {[winfo exists $win]} {
        wm deiconify $win
        raise $win
        focus $input
        return $win
    }
    set mono [_mono]

    toplevel $win
    wm title $win "VMD AI"
    wm geometry $win "540x640"

    frame $win.header
    pack $win.header -side top -fill x -padx 8 -pady 8

    button $win.header.history -text "History" -command {::vmdai::ui::on_history}
    button $win.header.new -text "New Chat" -command {::vmdai::ui::on_new_chat}
    button $win.header.clear -text "Clear" -command {::vmdai::ui::on_clear}
    button $win.header.stop -text "Stop" -command {::vmdai::ui::on_stop} -state disabled

    pack $win.header.history -side left -padx 4
    pack $win.header.new -side left -padx 4
    pack $win.header.stop -side right -padx 4
    pack $win.header.clear -side right -padx 4

    # ----- Workdir row -----
    frame $win.folder_row
    pack $win.folder_row -side top -fill x -padx 8 -pady {0 6}

    label $win.folder_row.fixed -text "Folder:" -font [list $mono 11 bold]
    label $win.folder_row.path -text "(none)" -font [list $mono 11] \
        -foreground "#0055aa" -anchor w
    label $win.folder_row.runs -text "" -font [list $mono 10] \
        -foreground "#777777"
    button $win.folder_row.choose -text "Choose..." \
        -command {::vmdai::ui::on_choose_folder}
    button $win.folder_row.runs_btn -text "Runs..." \
        -command {::vmdai::ui::on_reveal_runs}
    button $win.folder_row.save -text "Save Tcl..." \
        -command {::vmdai::ui::on_save_tcl}

    pack $win.folder_row.fixed -side left -padx {0 4}
    pack $win.folder_row.path -side left -fill x -expand 1
    pack $win.folder_row.runs -side left -padx {6 0}
    pack $win.folder_row.save -side right -padx 4
    pack $win.folder_row.runs_btn -side right -padx 4
    pack $win.folder_row.choose -side right -padx 4

    set workdir_label $win.folder_row.path
    set runs_label $win.folder_row.runs
    # The bridge applies the remembered folder when the session starts.
    if {$::vmdai::bridge::workdir eq ""} {
        ::vmdai::bridge::_load_workdir
    }
    _refresh_workdir_label
    _refresh_runs_count
    _schedule_runs_count_refresh

    # ----- Provider row -----
    _load_persisted_provider

    frame $win.provider_row
    pack $win.provider_row -side top -fill x -padx 8 -pady {0 6}

    label $win.provider_row.fixed -text "Provider:" -font [list $mono 11 bold]
    tk_optionMenu $win.provider_row.menu ::vmdai::ui::provider \
        openrouter anthropic-direct ollama
    label $win.provider_row.model_label -text "Model:" -font [list $mono 11 bold]
    entry $win.provider_row.model_entry -width 28 \
        -textvariable ::vmdai::ui::model_name
    button $win.provider_row.apply -text "Apply" \
        -command {::vmdai::ui::on_apply_provider}

    pack $win.provider_row.fixed -side left -padx {0 4}
    pack $win.provider_row.menu  -side left -padx {0 8}
    pack $win.provider_row.model_label -side left -padx {0 4}
    pack $win.provider_row.model_entry -side left -fill x -expand 1 -padx {0 4}
    pack $win.provider_row.apply -side right -padx 4

    # The dropdown only refills the model entry; nothing reaches chat.send
    # until Apply. Remove any prior trace first (reload re-sources this file).
    catch {trace remove variable ::vmdai::ui::provider write \
        ::vmdai::ui::_on_provider_changed}
    trace add variable ::vmdai::ui::provider write \
        ::vmdai::ui::_on_provider_changed

    text $win.transcript -height 28 -wrap word -state disabled \
        -font [list $mono 12 bold] -background "#ffffff"
    set transcript $win.transcript
    pack $win.transcript -side top -fill both -expand 1 -padx 8 -pady 8

    $win.transcript tag configure role_user -foreground "#0055aa"
    $win.transcript tag configure role_assistant -foreground "#1a1a1a"
    $win.transcript tag configure role_system -foreground "#555555"
    $win.transcript tag configure role_error -foreground "#cc2233"
    $win.transcript tag configure role_tool_result -foreground "#0077aa"
    $win.transcript tag configure role_reasoning -foreground "#666666"
    $win.transcript tag configure notice_info -foreground "#555555"
    $win.transcript tag configure notice_warn -foreground "#a05a00"
    $win.transcript tag configure notice_error -foreground "#cc2233"
    $win.transcript tag configure thinking -foreground "#888888" \
        -font [list $mono 11 italic]

    frame $win.input_row
    pack $win.input_row -side bottom -fill x -padx 8 -pady 8

    entry $win.input_row.input
    set input $win.input_row.input
    button $win.input_row.send -text "Send" -command {::vmdai::ui::on_send}

    pack $win.input_row.input -side left -fill x -expand 1 -padx 4
    pack $win.input_row.send -side right -padx 4

    bind $win.input_row.input <Return> {::vmdai::ui::on_send}
    wm protocol $win WM_DELETE_WINDOW {::vmdai::ui::on_close}

    append_message system "VMD AI panel ready."
    focus $input
    return $win
}

# ----------------------------------------------------------------------
# Provider picker - persistence + dropdown handlers
# ----------------------------------------------------------------------

proc ::vmdai::ui::_persisted_provider_path {} {
    return [file join [::vmdai::config::home] .vmdai last_provider.txt]
}

proc ::vmdai::ui::_load_persisted_provider {} {
    variable provider
    variable model_name
    set path [_persisted_provider_path]
    if {![file readable $path]} { return }
    if {[catch {set fh [open $path r]}]} { return }
    set line [string trim [read $fh]]
    catch {close $fh}
    if {$line eq ""} { return }
    set parts [split $line "\t"]
    set prov [lindex $parts 0]
    set mdl  [lindex $parts 1]
    if {$prov ne ""} { set provider $prov }
    if {$mdl  ne ""} { set model_name $mdl }
}

proc ::vmdai::ui::_save_persisted_provider {prov mdl} {
    set path [_persisted_provider_path]
    catch {file mkdir [file dirname $path]}
    if {[catch {
        set fh [open $path w]
        puts -nonewline $fh "$prov\t$mdl"
        close $fh
    } err]} {
        append_message error "could not persist provider: $err"
    }
}

# Trace on the dropdown: refill the model entry for the new provider.
proc ::vmdai::ui::_on_provider_changed {args} {
    variable provider
    variable model_name
    set model_name [_default_model_for_provider $provider]
}

proc ::vmdai::ui::on_apply_provider {} {
    variable provider
    variable model_name
    set mdl [string trim $model_name]
    if {$mdl eq ""} {
        set mdl [_default_model_for_provider $provider]
        set model_name $mdl
    }
    _save_persisted_provider $provider $mdl
    ::vmdai::bridge::set_provider $provider $mdl \
        [list ::vmdai::ui::_on_provider_set $provider $mdl]
}

proc ::vmdai::ui::_on_provider_set {provider mdl kind args} {
    if {$kind eq "ok"} {
        append_message system "Provider set: $provider (model: $mdl)"
    } elseif {$kind eq "rpc_error"} {
        notify error "Could not set the provider: [lindex $args 1]"
    } else {
        notify error "Could not set the provider: the AI runtime did not answer."
    }
}

# Closing the window only hides it; the runtime and any request keep going
# (spec 2d Shutdown). ::vmdai::stop ends them.
proc ::vmdai::ui::on_close {} {
    variable win
    catch {wm withdraw $win}
}

# ----------------------------------------------------------------------
# Transcript
# ----------------------------------------------------------------------

proc ::vmdai::ui::_insert {text tags} {
    variable transcript
    $transcript configure -state normal
    $transcript insert end $text $tags
    $transcript configure -state disabled
    $transcript see end
}

# End the open streamed block, so the next role starts on its own line.
proc ::vmdai::ui::_close_block {} {
    variable stream_request_id
    variable stream_role
    if {$stream_role eq ""} {
        return
    }
    _insert "\n" {}
    set stream_request_id ""
    set stream_role ""
}

proc ::vmdai::ui::append_message {role text} {
    variable transcript
    if {![_have_panel]} {
        return
    }
    set clean [string trim [string map [list "\r" ""] $text]]
    if {$clean eq ""} {
        return
    }
    _close_block
    set tag "role_${role}"
    if {[lsearch -exact [$transcript tag names] $tag] < 0} {
        set tag "role_system"
    }
    _insert "[string toupper $role]: $clean\n" $tag
}

proc ::vmdai::ui::append_stream_chunk {role request_id chunk} {
    variable transcript
    variable stream_request_id
    variable stream_role
    if {![_have_panel]} {
        return
    }
    set tag "role_${role}"
    if {[lsearch -exact [$transcript tag names] $tag] < 0} {
        set tag "role_assistant"
    }
    if {$stream_request_id ne $request_id || $stream_role ne $role} {
        _thinking_stop
        _close_block
        set stream_request_id $request_id
        set stream_role $role
        _insert "[string toupper $role]: " $tag
    }
    _insert $chunk $tag
}

proc ::vmdai::ui::close_stream {request_id} {
    variable stream_request_id
    if {$request_id ne "" && $stream_request_id eq $request_id} {
        _close_block
    }
}

# The connection state machine's sink (S3): one line per call.
proc ::vmdai::ui::notify {level text} {
    if {![_have_panel]} {
        return
    }
    _close_block
    set text [string trim [string map [list "\r" "" "\n" " "] $text]]
    if {$level ni {info warn error}} {
        set level info
    }
    _insert "$text\n" [list notice_$level]
}

# Busy is set by the bridge once chat.send succeeded, and cleared when the
# request ends: Stop is enabled and "Thinking" shows only in between.
proc ::vmdai::ui::set_busy {on} {
    variable win
    if {![_have_panel]} {
        return
    }
    if {$on} {
        $win.header.stop configure -state normal
        $win.input_row.send configure -state disabled
        _thinking_start
    } else {
        $win.header.stop configure -state disabled
        $win.input_row.send configure -state normal
        _thinking_stop
    }
}

# A short progress line (e.g. "Running: mol new ...").
proc ::vmdai::ui::status {text} {
    append_message system $text
}

# ----------------------------------------------------------------------
# Thinking indicator ("Thinking" plus animated dots while busy)
# ----------------------------------------------------------------------

proc ::vmdai::ui::_thinking_start {} {
    variable thinking_after_id
    variable thinking_tag
    variable thinking_dots
    if {![_have_panel]} {
        return
    }
    _thinking_stop
    _close_block
    set thinking_tag "thinking_[clock microseconds]"
    set thinking_dots 0
    _insert "Thinking\n" [list thinking $thinking_tag]
    set thinking_after_id [::vmdai::sched::after 400 ::vmdai::ui::_thinking_tick]
}

proc ::vmdai::ui::_thinking_tick {} {
    variable transcript
    variable thinking_after_id
    variable thinking_tag
    variable thinking_dots
    set thinking_after_id ""
    if {$thinking_tag eq "" || ![_have_panel]} {
        return
    }
    set thinking_dots [expr {($thinking_dots + 1) % 4}]
    set ranges [$transcript tag ranges $thinking_tag]
    if {[llength $ranges] >= 2} {
        $transcript configure -state normal
        $transcript delete [lindex $ranges 0] [lindex $ranges 1]
        $transcript insert [lindex $ranges 0] "Thinking[string repeat . $thinking_dots]\n" \
            [list thinking $thinking_tag]
        $transcript configure -state disabled
    }
    set thinking_after_id [::vmdai::sched::after 400 ::vmdai::ui::_thinking_tick]
}

proc ::vmdai::ui::_thinking_stop {} {
    variable transcript
    variable thinking_after_id
    variable thinking_tag
    ::vmdai::sched::cancel $thinking_after_id
    set thinking_after_id ""
    catch {
        if {$thinking_tag ne "" && [_have_panel]} {
            set ranges [$transcript tag ranges $thinking_tag]
            if {[llength $ranges] >= 2} {
                $transcript configure -state normal
                $transcript delete [lindex $ranges 0] [lindex $ranges 1]
                $transcript configure -state disabled
            }
        }
    }
    set thinking_tag ""
}

# ----------------------------------------------------------------------
# Workdir (project folder). ::vmdai::bridge::apply_workdir cds VMD there,
# remembers it in ~/.vmdai/last_workdir.txt and sends session.set_cwd.
# ----------------------------------------------------------------------

proc ::vmdai::ui::_workdir {} {
    if {$::vmdai::bridge::workdir ne ""} {
        return $::vmdai::bridge::workdir
    }
    return [pwd]
}

proc ::vmdai::ui::_truncate_path {path max_len} {
    if {[string length $path] <= $max_len} { return $path }
    set tail [string range $path [expr {[string length $path] - $max_len + 4}] end]
    return "...$tail"
}

proc ::vmdai::ui::_refresh_workdir_label {} {
    variable workdir_label
    if {$workdir_label eq "" || ![winfo exists $workdir_label]} {
        return
    }
    $workdir_label configure -text [_truncate_path [_workdir] 60]
}

proc ::vmdai::ui::on_choose_folder {} {
    set initial [_workdir]
    if {![file isdirectory $initial]} {
        set initial [pwd]
    }
    set chosen [tk_chooseDirectory -title "VMD AI - pick project folder" \
        -initialdir $initial -mustexist 1]
    if {$chosen eq ""} { return }
    if {![::vmdai::bridge::apply_workdir $chosen]} {
        return
    }
    _refresh_workdir_label
    _refresh_runs_count
    append_message system "Project folder set: $::vmdai::bridge::workdir"
}

# ----------------------------------------------------------------------
# Recorder dir surface - show run count + open in Finder
# ----------------------------------------------------------------------

proc ::vmdai::ui::_runs_dir {} {
    return [file join [_workdir] ".vmdai_runs"]
}

proc ::vmdai::ui::_refresh_runs_count {} {
    variable runs_label
    if {$runs_label eq "" || ![winfo exists $runs_label]} { return }
    set dir [_runs_dir]
    set count 0
    if {[file isdirectory $dir]} {
        catch {set count [llength [glob -nocomplain -directory $dir -type d *]]}
    }
    if {$count == 0} {
        $runs_label configure -text ""
    } elseif {$count == 1} {
        $runs_label configure -text "(1 run)"
    } else {
        $runs_label configure -text "($count runs)"
    }
}

proc ::vmdai::ui::_schedule_runs_count_refresh {} {
    variable runs_count_after_id
    ::vmdai::sched::cancel $runs_count_after_id
    set runs_count_after_id [::vmdai::sched::after 3000 ::vmdai::ui::_runs_count_tick]
}

proc ::vmdai::ui::_runs_count_tick {} {
    variable runs_count_after_id
    set runs_count_after_id ""
    if {![_have_panel]} {
        return
    }
    _refresh_runs_count
    _schedule_runs_count_refresh
}

proc ::vmdai::ui::on_reveal_runs {} {
    set dir [_runs_dir]
    if {![file isdirectory $dir]} {
        append_message system "No runs yet - $dir will be created on the first request."
        return
    }
    set platform [tk windowingsystem]
    if {$platform eq "aqua"} {
        catch {exec open $dir &}
    } elseif {$platform eq "x11"} {
        catch {exec xdg-open $dir &}
    } else {
        append_message system "Runs directory: $dir"
    }
}

# ----------------------------------------------------------------------
# Save Tcl: the commands the executor ran in this chat (its ledger).
# ----------------------------------------------------------------------

proc ::vmdai::ui::on_save_tcl {} {
    set entries [::vmdai::executor::ledger]
    if {[llength $entries] == 0} {
        append_message system "Nothing to save yet - no VMD commands have run in this chat."
        return
    }
    set initial [_workdir]
    set default_name "vmd_ai_session_[clock format [clock seconds] -format %Y%m%dT%H%M%S].tcl"
    set chosen [tk_getSaveFile -title "Save VMD AI session as Tcl script" \
        -initialdir $initial -initialfile $default_name \
        -defaultextension .tcl -filetypes {{Tcl {.tcl}} {All *}}]
    if {$chosen eq ""} { return }
    if {[catch {
        set fh [open $chosen w]
        fconfigure $fh -encoding utf-8
        puts -nonewline $fh [_render_session_tcl $entries]
        close $fh
    } err]} {
        append_message error "save failed: $err"
        return
    }
    append_message system "Saved [llength $entries] commands to $chosen"
}

proc ::vmdai::ui::_render_session_tcl {entries} {
    set saved_at [clock format [clock seconds] -format "%Y-%m-%dT%H:%M:%SZ" -gmt 1]
    set out ""
    append out "# VMD AI session transcript\n"
    append out "# saved_at : $saved_at\n"
    append out "# workdir  : [_workdir]\n"
    append out "# turns    : [llength $entries]\n\n"
    set turn 0
    foreach entry $entries {
        incr turn
        set ts [clock format [dict get $entry ts] -format "%Y-%m-%dT%H:%M:%SZ" -gmt 1]
        append out "# --- turn [format %02d $turn] | $ts | [dict get $entry kind] ---\n"
        append out [string trimright [dict get $entry command]] "\n\n"
    }
    return $out
}

# ----------------------------------------------------------------------
# Events from the bridge (v1, spec 2c)
# ----------------------------------------------------------------------

proc ::vmdai::ui::render_event {event} {
    if {![_have_panel]} {
        return
    }
    if {[catch {_render_event_impl $event} err]} {
        catch {_thinking_stop}
        catch {append_message error "render_event: $err"}
    }
}

proc ::vmdai::ui::_render_event_impl {event} {
    set role [_dict_get_or $event role system]
    set etype [_dict_get_or $event type message]
    set text [_dict_get_or $event text ""]
    set metadata [_dict_get_or $event metadata [dict create]]
    set request_id [_dict_get_or $metadata request_id ""]
    if {$role eq "user"} {
        # Already shown by on_send.
        return
    }
    if {$etype eq "chunk"} {
        append_stream_chunk $role $request_id $text
        return
    }
    _thinking_stop
    if {$role eq "assistant" && $etype eq "message" && $request_id ne ""} {
        # The final message repeats the streamed text; just end the block.
        close_stream $request_id
        return
    }
    if {$etype eq "lifecycle"} {
        close_stream $request_id
        if {$text eq "cancelled"} {
            append_message system "Stopped."
        }
        return
    }
    append_message $role $text
}

# ----------------------------------------------------------------------
# Buttons
# ----------------------------------------------------------------------

proc ::vmdai::ui::on_send {} {
    variable input
    if {$input eq "" || ![winfo exists $input]} {
        return
    }
    set text [string trim [$input get]]
    if {$text eq ""} {
        return
    }
    if {[::vmdai::bridge::send $text]} {
        $input delete 0 end
        append_message user $text
    }
}

proc ::vmdai::ui::on_stop {} {
    ::vmdai::bridge::cancel
}

proc ::vmdai::ui::_clear_transcript {} {
    variable transcript
    if {![_have_panel]} {
        return
    }
    _thinking_stop
    set ::vmdai::ui::stream_request_id ""
    set ::vmdai::ui::stream_role ""
    $transcript configure -state normal
    $transcript delete 1.0 end
    $transcript configure -state disabled
}

proc ::vmdai::ui::on_clear {} {
    _clear_transcript
    ::vmdai::executor::clear_ledger
    ::vmdai::bridge::new_chat
}

proc ::vmdai::ui::on_new_chat {} {
    ::vmdai::executor::clear_ledger
    ::vmdai::bridge::new_chat
    append_message system "Started a new chat."
}

# ----------------------------------------------------------------------
# History
# ----------------------------------------------------------------------

proc ::vmdai::ui::on_history {} {
    ::vmdai::bridge::history_list ::vmdai::ui::_on_history_list
}

proc ::vmdai::ui::_on_history_list {kind args} {
    if {$kind ne "ok"} {
        notify error "Could not load the chat history."
        return
    }
    set items {}
    catch {set items [dict get [lindex $args 0] items]}
    show_history_picker $items
}

proc ::vmdai::ui::show_history_picker {items} {
    variable win
    set dlg "${win}.history_dlg"
    catch {destroy $dlg}

    toplevel $dlg
    wm title $dlg "Chat History"
    wm geometry $dlg "420x360"
    wm transient $dlg $win

    label $dlg.label -text "Select a conversation to resume:" -anchor w
    pack $dlg.label -side top -fill x -padx 10 -pady {10 4}

    frame $dlg.list_frame
    pack $dlg.list_frame -side top -fill both -expand 1 -padx 10 -pady 4

    listbox $dlg.list_frame.lb -font [list [_mono] 11] -selectmode single \
        -activestyle dotbox -height 12 -width 50 \
        -yscrollcommand [list $dlg.list_frame.sb set]
    scrollbar $dlg.list_frame.sb -command [list $dlg.list_frame.lb yview]
    pack $dlg.list_frame.sb -side right -fill y
    pack $dlg.list_frame.lb -side left -fill both -expand 1

    set chat_ids [list]
    if {[llength $items] == 0} {
        $dlg.list_frame.lb insert end "(no previous chats)"
    } else {
        foreach item $items {
            set cid [_dict_get_or $item chat_id ""]
            set title [_dict_get_or $item title "Untitled"]
            set mc [_dict_get_or $item message_count 0]
            set updated [_dict_get_or $item updated_at ""]
            $dlg.list_frame.lb insert end "$title  ($mc msgs)  [string range $updated 0 9]"
            lappend chat_ids $cid
        }
    }

    frame $dlg.buttons
    pack $dlg.buttons -side bottom -fill x -padx 10 -pady 10
    button $dlg.buttons.resume -text "Resume" \
        -command [list ::vmdai::ui::_on_history_resume $dlg $chat_ids]
    button $dlg.buttons.cancel -text "Cancel" -command [list destroy $dlg]
    pack $dlg.buttons.cancel -side right -padx 4
    pack $dlg.buttons.resume -side right -padx 4
    bind $dlg.list_frame.lb <Double-1> [list ::vmdai::ui::_on_history_resume $dlg $chat_ids]
}

proc ::vmdai::ui::_on_history_resume {dlg chat_ids} {
    set sel [$dlg.list_frame.lb curselection]
    if {[llength $sel] == 0} {
        return
    }
    set target [lindex $chat_ids [lindex $sel 0]]
    if {$target eq ""} {
        return
    }
    destroy $dlg
    ::vmdai::bridge::resume $target [list ::vmdai::ui::_on_resumed $target]
}

# chat.resume answered; the bridge already reported a failure.
proc ::vmdai::ui::_on_resumed {target kind args} {
    if {$kind ne "ok"} {
        return
    }
    _clear_transcript
    ::vmdai::executor::clear_ledger
    append_message system "Resumed chat."
    ::vmdai::bridge::history_get $target ::vmdai::ui::_on_history_get
}

proc ::vmdai::ui::_on_history_get {kind args} {
    if {$kind ne "ok"} {
        notify error "Could not load this chat's messages."
        return
    }
    set events {}
    catch {set events [dict get [lindex $args 0] events]}
    foreach ev $events {
        set role [_dict_get_or $ev role ""]
        set etype [_dict_get_or $ev type ""]
        set text [_dict_get_or $ev text ""]
        if {($role eq "user" || $role eq "assistant") && $etype eq "message" && $text ne ""} {
            append_message $role $text
        }
    }
}
