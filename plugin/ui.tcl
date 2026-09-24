namespace eval ::vmdai::ui {
    variable win ".vmd_ai"
    variable transcript ""
    variable input ""
    variable stream_request_id ""
    variable stream_role ""
    # Thinking indicator state
    variable thinking_after_id ""
    variable thinking_tag ""
    variable thinking_dots 0
    # Workdir state (the "project folder" the user picks)
    variable workdir ""
    variable workdir_label ""
    # Live count of recorded runs under <workdir>/.vmdai_runs/ — shown
    # in the header so users can see how many tasks have been saved.
    variable runs_label ""
    variable runs_count_after_id ""
    # Session Tcl capture — list of {timestamp, command, kind} dicts
    # Cleared when a new chat starts; offered to the user via "Save Tcl…".
    variable session_tcl [list]
    # Provider picker state. Three modes mirror runtime/provider.py's
    # build_provider(): "openrouter", "anthropic-direct", "ollama".
    # Defaults assume the user has an OpenRouter key; can be overridden
    # by ~/.vmdai/last_provider.txt on startup.
    variable provider "openrouter"
    variable model_name "anthropic/claude-sonnet-4.6"
}

# Sensible default model strings per provider. Used when the user
# switches the dropdown without manually editing the model entry.
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

proc ::vmdai::ui::show_panel {} {
    variable win
    variable transcript
    variable input

    if {[winfo exists $win]} {
        raise $win
        focus $input
        return
    }

    toplevel $win
    wm title $win "VMD AI"
    wm geometry $win "540x640"

    frame $win.header
    pack $win.header -side top -fill x -padx 8 -pady 8

    button $win.header.history -text "History" -command {::vmdai::ui::on_history}
    button $win.header.new -text "New Chat" -command {::vmdai::ui::on_new_chat}
    button $win.header.clear -text "Clear" -command {::vmdai::ui::on_clear}
    button $win.header.stop -text "Stop" -command {::vmdai::ui::on_stop}

    pack $win.header.history -side left -padx 4
    pack $win.header.new -side left -padx 4
    pack $win.header.stop -side right -padx 4
    pack $win.header.clear -side right -padx 4

    # ----- Workdir row -----
    # Project folder + Choose / Save Tcl actions, sandwiched between
    # the header bar and the transcript so it's always visible.
    frame $win.folder_row
    pack $win.folder_row -side top -fill x -padx 8 -pady {0 6}

    label $win.folder_row.fixed -text "Folder:" -font {{Menlo} 11 bold}
    label $win.folder_row.path -text "(none)" -font {{Menlo} 11} \
        -foreground "#0055aa" -anchor w
    label $win.folder_row.runs -text "" -font {{Menlo} 10} \
        -foreground "#777777"
    button $win.folder_row.choose -text "Choose…" \
        -command {::vmdai::ui::on_choose_folder}
    button $win.folder_row.runs_btn -text "Runs…" \
        -command {::vmdai::ui::on_reveal_runs}
    button $win.folder_row.save -text "Save Tcl…" \
        -command {::vmdai::ui::on_save_tcl}

    pack $win.folder_row.fixed -side left -padx {0 4}
    pack $win.folder_row.path -side left -fill x -expand 1
    pack $win.folder_row.runs -side left -padx {6 0}
    pack $win.folder_row.save -side right -padx 4
    pack $win.folder_row.runs_btn -side right -padx 4
    pack $win.folder_row.choose -side right -padx 4

    set workdir_label $win.folder_row.path
    set runs_label $win.folder_row.runs

    # Apply persisted workdir (if any). Falls back to current pwd.
    ::vmdai::ui::_load_persisted_workdir
    ::vmdai::ui::_refresh_workdir_label
    ::vmdai::ui::_refresh_runs_count
    # Re-check the runs count every 3s so the header reflects new
    # task directories as they get written.
    ::vmdai::ui::_schedule_runs_count_refresh

    # ----- Provider row -----
    # Lets the user pick which backend powers the assistant:
    #   openrouter        — OpenRouter API (default)
    #   anthropic-direct  — Anthropic's API directly
    #   ollama            — local Ollama instance (no key needed)
    # The choice is persisted to ~/.vmdai/last_provider.txt and applied
    # to the runtime via the provider.set RPC.
    ::vmdai::ui::_load_persisted_provider

    frame $win.provider_row
    pack $win.provider_row -side top -fill x -padx 8 -pady {0 6}

    label $win.provider_row.fixed -text "Provider:" -font {{Menlo} 11 bold}
    tk_optionMenu $win.provider_row.menu ::vmdai::ui::provider \
        openrouter anthropic-direct ollama
    label $win.provider_row.model_label -text "Model:" -font {{Menlo} 11 bold}
    entry $win.provider_row.model_entry -width 28 \
        -textvariable ::vmdai::ui::model_name
    button $win.provider_row.apply -text "Apply" \
        -command {::vmdai::ui::on_apply_provider}

    pack $win.provider_row.fixed -side left -padx {0 4}
    pack $win.provider_row.menu  -side left -padx {0 8}
    pack $win.provider_row.model_label -side left -padx {0 4}
    pack $win.provider_row.model_entry -side left -fill x -expand 1 -padx {0 4}
    pack $win.provider_row.apply -side right -padx 4

    # Auto-fill the model field when the provider dropdown changes, so
    # users don't have to remember model strings per backend. We trace
    # the namespace variable rather than wiring a -command on tk_optionMenu
    # because the latter doesn't expose a per-item callback in plain Tk.
    # Remove any prior trace first — ::vmdai::reload re-sources this
    # file, and stacked traces would fire _on_provider_changed twice.
    catch {trace remove variable ::vmdai::ui::provider write \
        ::vmdai::ui::_on_provider_changed}
    trace add variable ::vmdai::ui::provider write \
        ::vmdai::ui::_on_provider_changed

    text $win.transcript -height 28 -wrap word -state disabled -font {{Menlo} 12 bold} -background "#ffffff"
    set transcript $win.transcript
    pack $win.transcript -side top -fill both -expand 1 -padx 8 -pady 8

    $win.transcript tag configure role_user -foreground "#0055aa"
    $win.transcript tag configure role_assistant -foreground "#1a1a1a"
    $win.transcript tag configure role_system -foreground "#555555"
    $win.transcript tag configure role_error -foreground "#cc2233"
    $win.transcript tag configure role_tool_result -foreground "#0077aa"
    $win.transcript tag configure role_reasoning -foreground "#666666"
    # Thinking indicator: dim, italic, visually distinct from real content.
    $win.transcript tag configure thinking -foreground "#888888" \
        -font {{Menlo} 11 italic}

    frame $win.input_row
    pack $win.input_row -side bottom -fill x -padx 8 -pady 8

    entry $win.input_row.input
    set input $win.input_row.input
    button $win.input_row.send -text "Send" -command {::vmdai::ui::on_send}

    pack $win.input_row.input -side left -fill x -expand 1 -padx 4
    pack $win.input_row.send -side right -padx 4

    bind $win.input_row.input <Return> {::vmdai::ui::on_send}
    wm protocol $win WM_DELETE_WINDOW {::vmdai::ui::on_close}

    ::vmdai::bridge::ensure_runtime
    # Push the persisted provider selection to the runtime so the
    # backend matches what the UI is showing. Safe to call before the
    # first chat.send.
    catch {::vmdai::bridge::set_provider \
        $::vmdai::ui::provider $::vmdai::ui::model_name}
    ::vmdai::ui::append_message system "VMD AI panel ready."
    focus $input
}

# ----------------------------------------------------------------------
# Provider picker — persistence + dropdown handlers
# ----------------------------------------------------------------------

proc ::vmdai::ui::_persisted_provider_path {} {
    return [file join $::env(HOME) .vmdai last_provider.txt]
}

proc ::vmdai::ui::_load_persisted_provider {} {
    variable provider
    variable model_name
    set path [::vmdai::ui::_persisted_provider_path]
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
    set path [::vmdai::ui::_persisted_provider_path]
    catch {file mkdir [file dirname $path]}
    if {[catch {
        set fh [open $path w]
        puts -nonewline $fh "$prov\t$mdl"
        close $fh
    } err]} {
        ::vmdai::ui::append_message error "could not persist provider: $err"
    }
}

proc ::vmdai::ui::_on_provider_changed {args} {
    # Trace callback — fires whenever ::vmdai::ui::provider is rewritten,
    # including by tk_optionMenu. Reset the model entry to a sane default
    # for the newly chosen provider so the user doesn't accidentally send
    # an OpenRouter-formatted model string to a direct-Anthropic backend.
    variable provider
    variable model_name
    set model_name [::vmdai::ui::_default_model_for_provider $provider]
}

proc ::vmdai::ui::on_apply_provider {} {
    variable provider
    variable model_name
    set mdl [string trim $model_name]
    if {$mdl eq ""} {
        set mdl [::vmdai::ui::_default_model_for_provider $provider]
        set model_name $mdl
    }
    ::vmdai::ui::_save_persisted_provider $provider $mdl
    ::vmdai::bridge::set_provider $provider $mdl
    ::vmdai::ui::append_message system \
        "Provider set: $provider (model: $mdl)"
}

proc ::vmdai::ui::on_close {} {
    variable win
    variable runs_count_after_id
    if {$runs_count_after_id ne ""} {
        catch {after cancel $runs_count_after_id}
        set runs_count_after_id ""
    }
    catch {::vmdai::bridge::shutdown_runtime}
    catch {destroy $win}
}

proc ::vmdai::ui::append_message {role text} {
    variable transcript
    if {$transcript eq "" || ![winfo exists $transcript]} {
        return
    }
    set clean [string trim [string map [list "\r" ""] $text]]
    if {$clean eq ""} {
        return
    }
    $transcript configure -state normal
    set tag "role_${role}"
    if {[lsearch -exact [$transcript tag names] $tag] < 0} {
        set tag "role_system"
    }
    $transcript insert end "[string toupper $role]: $clean\n" $tag
    $transcript configure -state disabled
    $transcript see end
}

proc ::vmdai::ui::append_stream_chunk {role request_id chunk} {
    variable transcript
    variable stream_request_id
    variable stream_role
    if {$transcript eq "" || ![winfo exists $transcript]} {
        return
    }
    # First chunk of a new stream → kill the Thinking indicator.
    if {$stream_request_id ne $request_id || $stream_role ne $role} {
        ::vmdai::ui::_thinking_stop
        set stream_request_id $request_id
        set stream_role $role
        $transcript configure -state normal
        set tag "role_${role}"
        if {[lsearch -exact [$transcript tag names] $tag] < 0} {
            set tag "role_assistant"
        }
        $transcript insert end "[string toupper $role]: " $tag
    } else {
        $transcript configure -state normal
    }

    set tag "role_${role}"
    if {[lsearch -exact [$transcript tag names] $tag] < 0} {
        set tag "role_assistant"
    }
    $transcript insert end $chunk $tag
    $transcript configure -state disabled
    $transcript see end
}

proc ::vmdai::ui::close_stream {request_id} {
    variable transcript
    variable stream_request_id
    variable stream_role
    if {$request_id ne "" && $stream_request_id eq $request_id} {
        $transcript configure -state normal
        $transcript insert end "\n"
        $transcript configure -state disabled
        $transcript see end
        set stream_request_id ""
        set stream_role ""
    }
}

# ----------------------------------------------------------------------
# Thinking indicator
# ----------------------------------------------------------------------
# Shows "Thinking..." with animated dots while waiting for the model.
# Inserted on Send, removed the moment the first assistant chunk arrives
# (or on stop / error / lifecycle close). Animation cadence is calm:
# one frame every 400ms, dots cycle 0..3.

proc ::vmdai::ui::_thinking_start {} {
    variable transcript
    variable thinking_after_id
    variable thinking_tag
    variable thinking_dots
    if {$transcript eq "" || ![winfo exists $transcript]} {
        return
    }
    # If one is already running, refresh rather than stack two indicators.
    ::vmdai::ui::_thinking_stop
    set thinking_tag "thinking_[clock microseconds]"
    set thinking_dots 0
    $transcript configure -state normal
    $transcript insert end "Thinking\n" [list thinking $thinking_tag]
    $transcript configure -state disabled
    $transcript see end
    set thinking_after_id [after 400 ::vmdai::ui::_thinking_tick]
}

proc ::vmdai::ui::_thinking_tick {} {
    variable transcript
    variable thinking_after_id
    variable thinking_tag
    variable thinking_dots
    if {$thinking_tag eq "" || $transcript eq "" \
            || ![winfo exists $transcript]} {
        return
    }
    set thinking_dots [expr {($thinking_dots + 1) % 4}]
    set dots [string repeat "." $thinking_dots]
    $transcript configure -state normal
    set ranges [$transcript tag ranges $thinking_tag]
    if {[llength $ranges] >= 2} {
        $transcript delete [lindex $ranges 0] [lindex $ranges 1]
    }
    $transcript insert end "Thinking$dots\n" [list thinking $thinking_tag]
    $transcript configure -state disabled
    $transcript see end
    set thinking_after_id [after 400 ::vmdai::ui::_thinking_tick]
}

proc ::vmdai::ui::_thinking_stop {} {
    variable transcript
    variable thinking_after_id
    variable thinking_tag
    # Cancel any pending tick; never propagate errors.
    catch {
        if {$thinking_after_id ne ""} {
            after cancel $thinking_after_id
        }
    }
    set thinking_after_id ""
    # Delete the indicator row from the widget — guard every step so
    # this proc cannot throw and kill the event pump.
    catch {
        if {$thinking_tag ne "" && $transcript ne "" \
                && [winfo exists $transcript]} {
            $transcript configure -state normal
            set ranges [$transcript tag ranges $thinking_tag]
            if {[llength $ranges] >= 2} {
                $transcript delete [lindex $ranges 0] [lindex $ranges 1]
            }
            $transcript configure -state disabled
        }
    }
    set thinking_tag ""
}

# ----------------------------------------------------------------------
# Workdir (project folder)
# ----------------------------------------------------------------------
# The user picks a working directory via Tk's tk_chooseDirectory dialog.
# Effects: VMD `cd`'s into it (so `mol load receptor.pdb` resolves
# correctly), the path is shown in the header, and the choice is
# persisted to ~/.vmdai/last_workdir.txt so reloading the plugin keeps
# the same context.

proc ::vmdai::ui::_persisted_workdir_path {} {
    # Tucked under the chat-history root so it sits next to the other
    # plugin state files (chats/, keys, etc.).
    return [file join $::env(HOME) .vmdai last_workdir.txt]
}

proc ::vmdai::ui::_load_persisted_workdir {} {
    variable workdir
    set path [::vmdai::ui::_persisted_workdir_path]
    if {[file readable $path]} {
        set candidate [string trim [read [open $path r]]]
        if {$candidate ne "" && [file isdirectory $candidate]} {
            set workdir $candidate
            catch {cd $candidate}
            return
        }
    }
    # Fall back to whatever directory VMD was launched in.
    set workdir [pwd]
}

proc ::vmdai::ui::_save_persisted_workdir {dir} {
    set path [::vmdai::ui::_persisted_workdir_path]
    set parent [file dirname $path]
    catch {file mkdir $parent}
    if {[catch {
        set fh [open $path w]
        puts -nonewline $fh $dir
        close $fh
    } err]} {
        ::vmdai::ui::append_message error \
            "could not persist workdir: $err"
    }
}

proc ::vmdai::ui::_truncate_path {path max_len} {
    if {[string length $path] <= $max_len} { return $path }
    set tail [string range $path [expr {[string length $path] - $max_len + 4}] end]
    return "...$tail"
}

proc ::vmdai::ui::_refresh_workdir_label {} {
    variable workdir
    variable workdir_label
    if {$workdir_label eq "" || ![winfo exists $workdir_label]} {
        return
    }
    set shown [::vmdai::ui::_truncate_path $workdir 60]
    $workdir_label configure -text $shown
}

proc ::vmdai::ui::on_choose_folder {} {
    variable workdir
    set initial $workdir
    if {$initial eq "" || ![file isdirectory $initial]} {
        set initial [pwd]
    }
    set chosen [tk_chooseDirectory \
        -title "VMD AI — pick project folder" \
        -initialdir $initial \
        -mustexist 1]
    if {$chosen eq ""} { return }
    if {![file isdirectory $chosen]} {
        ::vmdai::ui::append_message error \
            "Not a directory: $chosen"
        return
    }
    if {[catch {cd $chosen} cd_err]} {
        ::vmdai::ui::append_message error \
            "cd failed: $cd_err"
        return
    }
    set workdir $chosen
    ::vmdai::ui::_refresh_workdir_label
    ::vmdai::ui::_save_persisted_workdir $chosen
    ::vmdai::ui::_refresh_runs_count
    ::vmdai::ui::append_message system "Project folder set: $chosen"
}

# ----------------------------------------------------------------------
# Recorder dir surface — show run count + open in Finder
# ----------------------------------------------------------------------
# The runtime auto-records every successful chat.send to
# <workdir>/.vmdai_runs/<task_id>/. This block makes those artifacts
# discoverable from inside the panel without breaking the chat flow.

proc ::vmdai::ui::_runs_dir {} {
    variable workdir
    if {$workdir eq ""} { return "" }
    return [file join $workdir ".vmdai_runs"]
}

proc ::vmdai::ui::_refresh_runs_count {} {
    variable runs_label
    if {$runs_label eq "" || ![winfo exists $runs_label]} { return }
    set dir [::vmdai::ui::_runs_dir]
    set count 0
    if {$dir ne "" && [file isdirectory $dir]} {
        # Count immediate subdirectories. catch in case of permissions.
        catch {
            foreach entry [glob -nocomplain -directory $dir -type d *] {
                incr count
            }
        }
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
    # Cancel any prior schedule (e.g. on plugin reload) to avoid stacked
    # callbacks ticking simultaneously.
    if {$runs_count_after_id ne ""} {
        catch {after cancel $runs_count_after_id}
    }
    set runs_count_after_id [after 3000 [list \
        ::vmdai::ui::_runs_count_tick]]
}

proc ::vmdai::ui::_runs_count_tick {} {
    variable runs_count_after_id
    set runs_count_after_id ""
    ::vmdai::ui::_refresh_runs_count
    # Reschedule only while the panel is still alive.
    variable win
    if {[winfo exists $win]} {
        ::vmdai::ui::_schedule_runs_count_refresh
    }
}

proc ::vmdai::ui::on_reveal_runs {} {
    set dir [::vmdai::ui::_runs_dir]
    if {$dir eq ""} {
        ::vmdai::ui::append_message system \
            "Pick a project folder first (Choose…), then I'll record runs there."
        return
    }
    if {![file isdirectory $dir]} {
        ::vmdai::ui::append_message system \
            "No runs yet — $dir will be created on the first chat.send."
        return
    }
    # Cross-platform best-effort: macOS / Linux / Windows.
    set platform [tk windowingsystem]
    if {$platform eq "aqua"} {
        catch {exec open $dir &}
    } elseif {$platform eq "x11"} {
        catch {exec xdg-open $dir &}
    } elseif {$platform eq "win32"} {
        catch {exec cmd /c start "" $dir &}
    } else {
        ::vmdai::ui::append_message system "Runs directory: $dir"
    }
}

# ----------------------------------------------------------------------
# Session Tcl capture + Save Tcl dialog
# ----------------------------------------------------------------------
# Every successful run_vmd_command and capture_vmd_snapshot is recorded
# (by the bridge) into ::vmdai::ui::session_tcl. The user can dump the
# accumulated Tcl to a runnable .tcl file at any time. New Chat / Clear
# resets the capture so each chat produces a clean script.

proc ::vmdai::ui::record_tcl_turn {kind command} {
    # kind: "command" (run_vmd_command) | "snapshot" (capture_vmd_snapshot)
    variable session_tcl
    set entry [dict create \
        ts [clock seconds] \
        kind $kind \
        command $command]
    lappend session_tcl $entry
}

proc ::vmdai::ui::clear_session_tcl {} {
    variable session_tcl
    set session_tcl [list]
}

proc ::vmdai::ui::on_save_tcl {} {
    variable session_tcl
    variable workdir
    if {[llength $session_tcl] == 0} {
        ::vmdai::ui::append_message system \
            "Nothing to save yet — no VMD commands have run in this chat."
        return
    }
    set initial $workdir
    if {$initial eq "" || ![file isdirectory $initial]} {
        set initial [pwd]
    }
    set default_name "vmd_ai_session_[clock format [clock seconds] -format %Y%m%dT%H%M%S].tcl"
    set chosen [tk_getSaveFile \
        -title "Save VMD AI session as Tcl script" \
        -initialdir $initial \
        -initialfile $default_name \
        -defaultextension .tcl \
        -filetypes {{Tcl {.tcl}} {All *}}]
    if {$chosen eq ""} { return }

    set content [::vmdai::ui::_render_session_tcl]
    if {[catch {
        set fh [open $chosen w]
        puts -nonewline $fh $content
        close $fh
    } err]} {
        ::vmdai::ui::append_message error "save failed: $err"
        return
    }
    ::vmdai::ui::append_message system \
        "Saved [llength $session_tcl] commands to $chosen"
}

proc ::vmdai::ui::_render_session_tcl {} {
    # Build the on-disk Tcl artifact: header comment + one block per
    # captured turn, in order. Only successful commands were ever
    # appended by the bridge, so the script is replayable as-is.
    variable session_tcl
    variable workdir
    set saved_at [clock format [clock seconds] -format "%Y-%m-%dT%H:%M:%SZ" -gmt 1]
    set out ""
    append out "# VMD AI session transcript\n"
    append out "# saved_at : $saved_at\n"
    append out "# workdir  : $workdir\n"
    append out "# turns    : [llength $session_tcl]\n"
    append out "#\n"
    append out "# This file is replayable in fresh VMD:\n"
    append out "#   vmd -e [file tail [info script]]\n"
    append out "# (or vmd -dispdev text -e ... for headless replay)\n"
    append out "\n"
    set turn 0
    foreach entry $session_tcl {
        incr turn
        set ts [clock format [dict get $entry ts] -format "%Y-%m-%dT%H:%M:%SZ" -gmt 1]
        set kind [dict get $entry kind]
        set cmd [dict get $entry command]
        append out "# --- turn [format %02d $turn] | $ts | $kind ---\n"
        append out [string trimright $cmd]
        append out "\n\n"
    }
    return $out
}

proc ::vmdai::ui::render_event {event} {
    # The bridge poll loop calls render_event without a catch — a Tcl
    # error in here halts the entire event pump. Wrap the whole body
    # so any bug surfaces as a visible error line instead of silence.
    if {[catch {::vmdai::ui::_render_event_impl $event} err]} {
        catch {::vmdai::ui::_thinking_stop}
        catch {::vmdai::ui::append_message error "render_event: $err"}
    }
}

proc ::vmdai::ui::_render_event_impl {event} {
    set role [::vmdai::ui::_dict_get_or $event role system]
    set etype [::vmdai::ui::_dict_get_or $event type message]
    set text [::vmdai::ui::_dict_get_or $event text ""]
    set metadata [::vmdai::ui::_dict_get_or $event metadata [dict create]]
    set request_id [::vmdai::ui::_dict_get_or $metadata request_id ""]

    # ANY response-side event means the model is no longer pending —
    # kill the Thinking indicator before we route the event further.
    # (User-side events are appended locally in on_send and skipped here.)
    if {$role ne "user"} {
        ::vmdai::ui::_thinking_stop
    }

    if {$etype eq "chunk" && $role eq "assistant"} {
        ::vmdai::ui::append_stream_chunk $role $request_id $text
        return
    }

    if {$role eq "assistant" && $etype eq "message"} {
        if {$request_id ne ""} {
            ::vmdai::ui::close_stream $request_id
            return
        }
    }

    if {$etype eq "lifecycle"} {
        ::vmdai::ui::close_stream $request_id
    }

    # Skip user-role events — already appended locally in on_send.
    if {$role eq "user"} {
        return
    }

    ::vmdai::ui::append_message $role $text
}

proc ::vmdai::ui::on_send {} {
    variable input
    if {$input eq "" || ![winfo exists $input]} {
        return
    }
    set text [string trim [$input get]]
    if {$text eq ""} {
        return
    }
    $input delete 0 end
    ::vmdai::ui::append_message user $text
    ::vmdai::bridge::send_chat $text
    # Show "Thinking..." until the first chunk lands (or stop / error).
    ::vmdai::ui::_thinking_start
}

proc ::vmdai::ui::on_stop {} {
    ::vmdai::bridge::cancel_active
    ::vmdai::ui::_thinking_stop
}

proc ::vmdai::ui::on_clear {} {
    variable transcript
    if {$transcript ne "" && [winfo exists $transcript]} {
        $transcript configure -state normal
        $transcript delete 1.0 end
        $transcript configure -state disabled
    }
    ::vmdai::ui::clear_session_tcl
    ::vmdai::bridge::new_chat
}

proc ::vmdai::ui::on_new_chat {} {
    ::vmdai::ui::clear_session_tcl
    ::vmdai::bridge::new_chat
    ::vmdai::ui::append_message system "Started a new chat session."
}

proc ::vmdai::ui::on_history {} {
    ::vmdai::bridge::show_history
}

proc ::vmdai::ui::show_history_picker {items} {
    variable win
    set dlg "${win}.history_dlg"

    # Destroy previous dialog if it exists
    catch {destroy $dlg}

    toplevel $dlg
    wm title $dlg "Chat History"
    wm geometry $dlg "420x360"
    wm transient $dlg $win

    label $dlg.label -text "Select a conversation to resume:" -font {{Menlo} 11 bold} -anchor w
    pack $dlg.label -side top -fill x -padx 10 -pady {10 4}

    # Scrollable listbox frame
    frame $dlg.list_frame
    pack $dlg.list_frame -side top -fill both -expand 1 -padx 10 -pady 4

    listbox $dlg.list_frame.lb -font {{Menlo} 11} -selectmode single \
        -activestyle dotbox -height 12 -width 50 \
        -yscrollcommand [list $dlg.list_frame.sb set]
    scrollbar $dlg.list_frame.sb -command [list $dlg.list_frame.lb yview]
    pack $dlg.list_frame.sb -side right -fill y
    pack $dlg.list_frame.lb -side left -fill both -expand 1

    # Populate the listbox and track chat_ids in parallel
    set chat_ids [list]
    if {[llength $items] == 0} {
        $dlg.list_frame.lb insert end "(no previous chats)"
    } else {
        foreach item $items {
            set cid [::vmdai::ui::_dict_get_or $item chat_id ""]
            set title [::vmdai::ui::_dict_get_or $item title "Untitled"]
            set mc [::vmdai::ui::_dict_get_or $item message_count 0]
            set updated [::vmdai::ui::_dict_get_or $item updated_at ""]
            # Show a compact date if available (first 10 chars = YYYY-MM-DD)
            set date_str ""
            if {[string length $updated] >= 10} {
                set date_str [string range $updated 0 9]
            }
            set display_line "$title  ($mc msgs)  $date_str"
            $dlg.list_frame.lb insert end $display_line
            lappend chat_ids $cid
        }
    }

    # Buttons
    frame $dlg.buttons
    pack $dlg.buttons -side bottom -fill x -padx 10 -pady 10

    button $dlg.buttons.resume -text "Resume" -command [list ::vmdai::ui::_on_history_resume $dlg $chat_ids]
    button $dlg.buttons.cancel -text "Cancel" -command [list destroy $dlg]
    pack $dlg.buttons.cancel -side right -padx 4
    pack $dlg.buttons.resume -side right -padx 4

    # Double-click to resume
    bind $dlg.list_frame.lb <Double-1> [list ::vmdai::ui::_on_history_resume $dlg $chat_ids]
}

proc ::vmdai::ui::_on_history_resume {dlg chat_ids} {
    variable transcript

    set sel [$dlg.list_frame.lb curselection]
    if {[llength $sel] == 0} {
        return
    }
    set idx [lindex $sel 0]
    set target_chat_id [lindex $chat_ids $idx]
    if {$target_chat_id eq ""} {
        return
    }

    # Close the dialog
    destroy $dlg

    # Clear the transcript and resume the chat
    if {$transcript ne "" && [winfo exists $transcript]} {
        $transcript configure -state normal
        $transcript delete 1.0 end
        $transcript configure -state disabled
    }
    ::vmdai::ui::append_message system "Resuming chat..."
    ::vmdai::bridge::resume_chat $target_chat_id
}
