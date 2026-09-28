# settings.tcl - the ChatVMD Settings dialog (Part B V4 "Settings"; section 2f; C7).
#
# A titled, transient toplevel (at least 460 px wide) with three ttk::notebook
# tabs: Model, Keys, Panel. Its data comes from the runtime (profiles.list,
# models.list, provider.test, keys.test, settings.set) and from
# ~/.vmdai/plugin.json; nothing is written until Save. Return saves, Esc
# cancels. "Changes apply to the next message": Save never cancels or
# restarts a running request.

namespace eval ::vmdai::settings {
    variable win .vmd_ai_settings
    variable PROVIDERS {ollama Ollama openai-compatible OpenAI-compatible anthropic-direct Anthropic openrouter OpenRouter}
    variable DEFAULT_URLS {ollama http://127.0.0.1:11434 openai-compatible http://localhost:8000/v1 openrouter https://openrouter.ai/api/v1}
    variable CTX_VALUES {8192 16384 32768 65536}
    variable SNAPSHOT_VALUES [list Auto Send "Don't send"]
    variable SERVER_HINTS [dict create \
        ollama "This Mac's Ollama is :11434; for a remote server use your SSH tunnel's local port." \
        openai-compatible "The server's OpenAI-compatible base URL, for example http://localhost:8000/v1."]
    variable CTX_NOTE "changing it reloads the model on the server"
    variable THINK_HINT "More reliable multi-step tool use; roughly 2\u00d7 slower per turn."
    variable FOOTER_TEXT "Changes apply to the next message."
    variable LOW_CTX_WARNING "Context below 16k: long tool output is compacted early and the model forgets earlier steps."
    variable NO_TOOLS_WARNING "No tool support: ChatVMD cannot run VMD commands with this model."
    variable SAVED_TEXT "Settings saved \u00b7 they apply to your next message"
    variable ACTIVE_DELETE "This is the active profile. Activate another profile before deleting it."
    if {![array exists ::vmdai::settings::v]} {
        variable v
        array set v {}
    }
    if {![info exists ::vmdai::settings::profiles]} { variable profiles {} }
    if {![info exists ::vmdai::settings::local_new]} { variable local_new {} }
    if {![info exists ::vmdai::settings::active]} { variable active "" }
    if {![info exists ::vmdai::settings::models]} { variable models {} }
    if {![info exists ::vmdai::settings::models_gen]} { variable models_gen 0 }
    if {![info exists ::vmdai::settings::profiles_gen]} { variable profiles_gen 0 }
    if {![info exists ::vmdai::settings::test_gen]} { variable test_gen 0 }
    if {![info exists ::vmdai::settings::saving]} { variable saving 0 }
    if {![info exists ::vmdai::settings::prefill]} { variable prefill {} }
}

# ---- small helpers ------------------------------------------------------------

# dict get with a default; JSON null counts as missing.
proc ::vmdai::settings::_dget {d key default} {
    if {[catch {dict exists $d $key} has] || !$has} { return $default }
    set value [dict get $d $key]
    if {$value eq "null"} { return $default }
    return $value
}

proc ::vmdai::settings::tab {name} {
    variable win
    return $win.bg.nb.$name
}

proc ::vmdai::settings::footer {} {
    variable win
    return $win.bg.foot
}

proc ::vmdai::settings::default_url {provider} {
    variable DEFAULT_URLS
    return [_dget $DEFAULT_URLS $provider ""]
}

proc ::vmdai::settings::_label_to_id {label} {
    variable PROVIDERS
    dict for {id name} $PROVIDERS {
        if {$name eq $label} { return $id }
    }
    return $label
}

proc ::vmdai::settings::_uses_server {{provider ""}} {
    variable v
    if {$provider eq ""} { set provider $v(provider) }
    return [expr {$provider in {ollama openai-compatible}}]
}

proc ::vmdai::settings::_k {n} {
    return "[expr {int(round($n / 1024.0))}]k"
}

proc ::vmdai::settings::_failure {prefix form rest} {
    if {$form eq "rpc_error"} { return "$prefix: [lindex $rest 1]" }
    if {$form eq "transport"} { return "$prefix: the runtime did not answer ([lindex $rest 0])." }
    return "$prefix."
}

proc ::vmdai::settings::_footer_msg {text {kind muted}} {
    set msg [footer].msg
    if {![winfo exists $msg]} { return }
    $msg configure -text $text -foreground [::vmdai::theme::c [expr {$kind eq "err" ? "err" : "muted"}]]
}

# ---- pure text builders (tested directly) ------------------------------------

# "qwen3.8:27b: tools ok vision ok thinking ok - ctx 32k (max 128k)" (C7).
proc ::vmdai::settings::model_hint {model_info num_ctx} {
    set id [_dget $model_info id ""]
    set head $id
    set caps [_dget $model_info capabilities {}]
    set flags {}
    foreach c {tools vision thinking} {
        if {[dict exists $caps $c]} {
            lappend flags "$c [expr {[string is true -strict [dict get $caps $c]] ? "\u2713" : "\u2717"}]"
        }
    }
    if {[llength $flags]} { set head "$id: [join $flags { }]" }
    set parts {}
    if {$head ne ""} { lappend parts $head }
    if {[string is integer -strict $num_ctx]} {
        set ctx "ctx [_k $num_ctx]"
        set max [_dget $model_info context_length ""]
        if {[string is integer -strict $max]} { append ctx " (max [_k $max])" }
        lappend parts $ctx
    }
    return [join $parts " \u00b7 "]
}

proc ::vmdai::settings::model_warnings {model_info num_ctx} {
    variable LOW_CTX_WARNING
    variable NO_TOOLS_WARNING
    set out {}
    set caps [_dget $model_info capabilities {}]
    if {[dict exists $caps tools] && ![string is true -strict [dict get $caps tools]]} {
        lappend out $NO_TOOLS_WARNING
    }
    if {[string is integer -strict $num_ctx] && $num_ctx < 16384} {
        lappend out $LOW_CTX_WARNING
    }
    return $out
}

# {icon line1 line2} for a provider.test result. The probes never call
# /api/chat, so nothing here claims the model "answered".
proc ::vmdai::settings::connection_lines {r model} {
    set ok [string is true -strict [_dget $r ok false]]
    set reachable [_dget $r reachable ""]
    set hint [_dget $r hint ""]
    set error [_dget $r error ""]
    set detail [expr {$hint ne "" ? $hint : $error}]
    if {$reachable eq ""} {
        # anthropic-direct: nothing to probe; the key decides.
        if {$ok} { return [list "\u2713" "API key found" "The model is reached on your next message."] }
        return [list "\u2717" [expr {$error ne "" ? $error : "Not ready"}] $hint]
    }
    if {![string is true -strict $reachable]} {
        return [list "\u2717" "Not connected" $detail]
    }
    set line1 "Connected"
    set latency [_dget $r latency_ms ""]
    if {$latency ne ""} { append line1 " \u00b7 $latency ms" }
    set version [_dget $r version ""]
    if {$version ne ""} { append line1 " \u00b7 Ollama $version" }
    set present [_dget $r model_present ""]
    if {$model eq "" || $present eq ""} {
        return [list [expr {$ok ? "\u2713" : "\u2717"}] $line1 $detail]
    }
    if {![string is true -strict $present]} {
        return [list "\u2717" $line1 [expr {$detail ne "" ? $detail : "$model is not on this server"}]]
    }
    set loaded [_dget $r loaded ""]
    if {$loaded eq ""} {
        set line2 "$model is served"
    } elseif {[string is true -strict $loaded]} {
        set line2 "$model loaded"
    } else {
        set line2 "$model available (not loaded yet)"
    }
    set caps [_dget $r capabilities {}]
    set flags {}
    foreach c {tools vision} {
        if {[dict exists $caps $c]} {
            lappend flags "$c [expr {[string is true -strict [dict get $caps $c]] ? "\u2713" : "\u2717"}]"
        }
    }
    if {[llength $flags]} { append line2 " \u00b7 [join $flags { }]" }
    set icon "\u2713"
    if {!$ok || ([dict exists $caps tools] && ![string is true -strict [dict get $caps tools]])} {
        set icon "!"
    }
    return [list $icon $line1 $line2]
}

# ---- the dialog ---------------------------------------------------------------

proc ::vmdai::settings::open {{which model} {prefill_dict {}}} {
    variable win
    variable prefill
    variable saving
    if {![winfo exists $win]} {
        set saving 0
        _defaults
        _build
    }
    select $which
    set prefill $prefill_dict
    reload
    ::vmdai::panel::present $win
    return $win
}

proc ::vmdai::settings::close {} {
    variable win
    variable saving
    variable v
    set saving 0
    # Typed API keys never outlive the dialog.
    array unset v key,*
    if {[winfo exists $win]} { ::destroy $win }
}

proc ::vmdai::settings::select {which} {
    if {$which in {model keys panel}} {
        [winfo parent [tab model]] select [tab $which]
    }
}

proc ::vmdai::settings::reload {} {
    variable win
    variable saving
    if {![winfo exists $win]} { return }
    # A resume/recover mid-Save drops the pending reply (net's epoch bump),
    # so saving would otherwise stick at 1 forever (M1).
    if {$saving} { set saving 0; _footer_msg "" }
    foreach step [reload_steps] { ::vmdai::settings::$step }
}

proc ::vmdai::settings::reload_steps {} {
    return {_load_profiles _load_keys _load_persisted _load_panel_prefs}
}

# A fresh form: every field (typed keys included) is rebuilt from the
# runtime and plugin.json by reload.
proc ::vmdai::settings::_defaults {} {
    variable v
    array unset v
    array set v [list profile "" provider ollama provider_label Ollama \
        server [default_url ollama] model "" ctx 32768 think 1 think_supported 0 \
        snapshots Auto new_name ""]
}

proc ::vmdai::settings::_build {} {
    variable win
    variable FOOTER_TEXT
    set C ::vmdai::theme::c
    toplevel $win
    wm withdraw $win
    wm title $win "ChatVMD Settings"
    if {[winfo exists $::vmdai::panel::win]} { wm transient $win $::vmdai::panel::win }
    wm minsize $win 460 1
    wm protocol $win WM_DELETE_WINDOW ::vmdai::settings::close
    ttk::frame $win.bg -padding {16 14 16 12}
    pack $win.bg -fill both -expand 1
    ttk::notebook $win.bg.nb
    foreach {name label} {model Model keys Keys panel Panel} {
        ttk::frame $win.bg.nb.$name -padding {14 12 14 10}
        $win.bg.nb add $win.bg.nb.$name -text $label
    }
    pack $win.bg.nb -fill both -expand 1
    _build_model [tab model]
    _build_keys [tab keys]
    _build_panel [tab panel]
    set f [footer]
    ttk::frame $f
    ttk::label $f.note -text $FOOTER_TEXT -font ChatMeta -foreground [$C muted]
    ttk::label $f.msg -text "" -font ChatMeta -foreground [$C muted] -wraplength 420 -justify left
    ttk::button $f.cancel -text Cancel -command ::vmdai::settings::close
    ttk::button $f.save -text Save -default active -command ::vmdai::settings::save
    grid $f.note -row 0 -column 0 -sticky w
    grid $f.cancel -row 0 -column 1 -padx {8 0}
    grid $f.save -row 0 -column 2 -padx {8 0}
    grid $f.msg -row 1 -column 0 -columnspan 3 -sticky w -pady {4 0}
    grid columnconfigure $f 0 -weight 1
    pack $f -fill x -pady {12 0}
    bind $win <Return> {::vmdai::settings::save; break}
    bind $win <KP_Enter> {::vmdai::settings::save; break}
    bind $win <Escape> {::vmdai::settings::close; break}
}

proc ::vmdai::settings::_build_model {m} {
    variable PROVIDERS
    variable CTX_VALUES
    variable SNAPSHOT_VALUES
    variable CTX_NOTE
    variable THINK_HINT
    set C ::vmdai::theme::c
    set muted [$C muted]
    set labels {}
    dict for {id label} $PROVIDERS { lappend labels $label }
    ttk::label $m.profile_l -text Profile
    ttk::combobox $m.profile -state readonly -width 24 -textvariable ::vmdai::settings::v(profile)
    ttk::frame $m.profile_b
    ttk::button $m.profile_b.new -text "New\u2026" -command ::vmdai::settings::_show_new_row
    ttk::button $m.profile_b.del -text "Delete\u2026" -command ::vmdai::settings::delete_profile
    pack $m.profile_b.new $m.profile_b.del -side left -padx {6 0}
    ttk::frame $m.newf
    ttk::entry $m.newf.e -width 20 -textvariable ::vmdai::settings::v(new_name)
    ttk::button $m.newf.ok -text Create -command {::vmdai::settings::new_profile $::vmdai::settings::v(new_name)}
    ttk::button $m.newf.cancel -text Cancel -command {grid remove [::vmdai::settings::tab model].newf}
    pack $m.newf.e -side left
    pack $m.newf.ok $m.newf.cancel -side left -padx {6 0}
    bind $m.newf.e <Return> {::vmdai::settings::new_profile $::vmdai::settings::v(new_name); break}
    bind $m.newf.e <Escape> {grid remove [::vmdai::settings::tab model].newf; break}
    ttk::label $m.provider_l -text Provider
    ttk::combobox $m.provider -state readonly -width 24 -values $labels \
        -textvariable ::vmdai::settings::v(provider_label)
    ttk::label $m.server_l -text Server
    ttk::entry $m.server -font ChatCode -width 32 -textvariable ::vmdai::settings::v(server)
    ttk::label $m.server_hint -text "" -font ChatMeta -foreground $muted -wraplength 340 -justify left
    ttk::label $m.model_l -text Model
    ttk::combobox $m.model -width 30 -textvariable ::vmdai::settings::v(model)
    ttk::button $m.refresh -text Refresh -command ::vmdai::settings::refresh_models
    ttk::label $m.model_hint -text "" -font ChatMeta -foreground $muted -wraplength 340 -justify left
    ttk::label $m.model_warn -text "" -font ChatMeta -foreground [$C warn] -wraplength 340 -justify left
    ttk::label $m.ctx_l -text Context
    ttk::frame $m.ctxf
    ttk::combobox $m.ctxf.cb -width 8 -values $CTX_VALUES -textvariable ::vmdai::settings::v(ctx)
    ttk::label $m.ctxf.unit -text tokens -foreground $muted
    pack $m.ctxf.cb -side left
    pack $m.ctxf.unit -side left -padx {6 0}
    ttk::label $m.ctx_note -text $CTX_NOTE -font ChatMeta -foreground $muted
    ttk::checkbutton $m.think -text Thinking -variable ::vmdai::settings::v(think)
    ttk::label $m.think_hint -text $THINK_HINT -font ChatMeta -foreground $muted
    ttk::label $m.snap_l -text Snapshots
    ttk::combobox $m.snap -state readonly -width 12 -values $SNAPSHOT_VALUES \
        -textvariable ::vmdai::settings::v(snapshots)
    ttk::separator $m.sep
    ttk::frame $m.test
    ttk::button $m.test.b -text "Test connection" -command ::vmdai::settings::test_connection
    ttk::label $m.test.icon -text "" -font ChatBodyBold
    ttk::label $m.test.l1 -text "" -font ChatMeta
    ttk::label $m.test.l2 -text "" -font ChatMeta -foreground $muted -wraplength 300 -justify left
    grid $m.test.b    -row 0 -column 0 -rowspan 2 -sticky nw
    grid $m.test.icon -row 0 -column 1 -rowspan 2 -sticky nw -padx {10 4}
    grid $m.test.l1   -row 0 -column 2 -sticky w
    grid $m.test.l2   -row 1 -column 2 -sticky w
    # Right-aligned labels, one field column, hints under the fields.
    grid $m.profile_l   -row 0  -column 0 -sticky e -padx {0 10} -pady 3
    grid $m.profile     -row 0  -column 1 -sticky ew -pady 3
    grid $m.profile_b   -row 0  -column 2 -sticky w
    grid $m.newf        -row 1  -column 1 -columnspan 2 -sticky w -pady {0 4}
    grid $m.provider_l  -row 2  -column 0 -sticky e -padx {0 10} -pady 3
    grid $m.provider    -row 2  -column 1 -sticky ew -pady 3
    grid $m.server_l    -row 3  -column 0 -sticky e -padx {0 10} -pady {8 0}
    grid $m.server      -row 3  -column 1 -columnspan 2 -sticky ew -pady {8 0}
    grid $m.server_hint -row 4  -column 1 -columnspan 2 -sticky w
    grid $m.model_l     -row 5  -column 0 -sticky e -padx {0 10} -pady {8 0}
    grid $m.model       -row 5  -column 1 -sticky ew -pady {8 0}
    grid $m.refresh     -row 5  -column 2 -sticky w -padx {6 0} -pady {8 0}
    grid $m.model_hint  -row 6  -column 1 -columnspan 2 -sticky w
    grid $m.model_warn  -row 7  -column 1 -columnspan 2 -sticky w
    grid $m.ctx_l       -row 8  -column 0 -sticky e -padx {0 10} -pady {8 0}
    grid $m.ctxf        -row 8  -column 1 -columnspan 2 -sticky w -pady {8 0}
    grid $m.ctx_note    -row 9  -column 1 -columnspan 2 -sticky w
    grid $m.think       -row 10 -column 1 -columnspan 2 -sticky w -pady {8 0}
    grid $m.think_hint  -row 11 -column 1 -columnspan 2 -sticky w -padx {22 0}
    grid $m.snap_l      -row 12 -column 0 -sticky e -padx {0 10} -pady {8 0}
    grid $m.snap        -row 12 -column 1 -sticky w -pady {8 0}
    grid $m.sep         -row 13 -column 0 -columnspan 3 -sticky ew -pady 10
    grid $m.test        -row 14 -column 0 -columnspan 3 -sticky w
    grid columnconfigure $m 1 -weight 1
    grid remove $m.newf
    bind $m.profile <<ComboboxSelected>> {::vmdai::settings::_load_profile $::vmdai::settings::v(profile)}
    bind $m.provider <<ComboboxSelected>> \
        {::vmdai::settings::set_provider [::vmdai::settings::_label_to_id $::vmdai::settings::v(provider_label)]}
    bind $m.model <<ComboboxSelected>> ::vmdai::settings::_refresh_model_hint
    bind $m.model <FocusOut> ::vmdai::settings::_refresh_model_hint
    bind $m.ctxf.cb <<ComboboxSelected>> ::vmdai::settings::_refresh_model_hint
    bind $m.ctxf.cb <FocusOut> ::vmdai::settings::_refresh_model_hint
    bind $m.server <FocusOut> ::vmdai::settings::refresh_models
}

# ---- rows that follow the provider --------------------------------------------

proc ::vmdai::settings::_rows {name} {
    set m [tab model]
    switch -- $name {
        server  { return [list $m.server_l $m.server $m.server_hint] }
        context { return [list $m.ctx_l $m.ctxf $m.ctx_note] }
        think   { return [list $m.think $m.think_hint] }
    }
    return {}
}

proc ::vmdai::settings::_show_rows {name on} {
    foreach w [_rows $name] {
        if {$on} { grid $w } else { grid remove $w }
    }
}

proc ::vmdai::settings::_layout_provider {} {
    variable v
    variable SERVER_HINTS
    variable win
    if {![winfo exists $win]} { return }
    set provider $v(provider)
    _show_rows server [_uses_server $provider]
    _show_rows context [_uses_server $provider]
    _show_rows think [expr {$provider eq "ollama" && $v(think_supported)}]
    [tab model].server_hint configure -text [_dget $SERVER_HINTS $provider ""]
}

proc ::vmdai::settings::_saved_profile {name} {
    variable profiles
    variable local_new
    if {[dict exists $profiles $name]} { return [dict get $profiles $name] }
    if {[dict exists $local_new $name]} { return [dict get $local_new $name] }
    return {}
}

# Switching provider restores the profile's saved server when it goes back
# to the saved provider, and uses the new provider's default otherwise.
proc ::vmdai::settings::set_provider {id} {
    variable v
    set saved [_saved_profile $v(profile)]
    set old $v(provider)
    set v(provider) $id
    set v(provider_label) [::vmdai::panel::provider_label $id]
    if {$id ne $old} {
        if {[_dget $saved provider ""] eq $id} {
            set v(server) [_dget $saved base_url [default_url $id]]
            set v(model) [_dget $saved model ""]
        } else {
            set v(server) [default_url $id]
            set v(model) ""
        }
        set v(snapshots) [expr {$id eq "openai-compatible" ? "Don't send" : "Auto"}]
        set v(think_supported) 0
    }
    _layout_provider
    refresh_models
}

# ---- profiles -----------------------------------------------------------------

proc ::vmdai::settings::_profile_names {} {
    variable profiles
    variable local_new
    return [lsort -dictionary [concat [dict keys $profiles] [dict keys $local_new]]]
}

proc ::vmdai::settings::_update_profile_values {} {
    variable win
    if {![winfo exists $win]} { return }
    [tab model].profile configure -values [_profile_names]
}

# Each load gets a generation: an answer to an older load (for example from
# a runtime that has since restarted) is dropped.
proc ::vmdai::settings::_load_profiles {} {
    variable profiles_gen
    incr profiles_gen
    ::vmdai::net::call profiles.list {} [list ::vmdai::settings::_on_profiles $profiles_gen]
}

proc ::vmdai::settings::_on_profiles {gen form args} {
    variable win
    variable profiles
    variable active
    variable local_new
    variable v
    variable prefill
    variable profiles_gen
    if {$gen != $profiles_gen || ![winfo exists $win]} { return }
    if {$form ne "ok"} {
        _footer_msg [_failure "Could not load the profiles" $form $args] err
        return
    }
    set r [lindex $args 0]
    set profiles [_dget $r profiles {}]
    set active [_dget $r active ""]
    _update_profile_values
    if {[dict size $prefill]} {
        set wanted $prefill
        set prefill {}
        _apply_prefill $wanted
        _footer_msg ""
        return
    }
    set name $v(profile)
    if {$name eq "" || !([dict exists $profiles $name] || [dict exists $local_new $name])} {
        set name $active
    }
    if {$name eq "" && [dict size $profiles]} { set name [lindex [_profile_names] 0] }
    if {$name ne ""} { _load_profile $name } else { _layout_provider }
    _footer_msg ""
}

# The empty state's "Use..." link: reuse a profile that points at the same
# server, else start an unsaved profile named <provider>-<port>.
proc ::vmdai::settings::_apply_prefill {pf} {
    variable profiles
    variable local_new
    variable v
    set url [_dget $pf base_url ""]
    set provider [_dget $pf provider ollama]
    set model [_dget $pf model ""]
    dict for {name p} $profiles {
        if {[_dget $p base_url ""] eq $url && [_dget $p provider ""] eq $provider} {
            _load_profile $name
            if {$v(model) eq ""} { set v(model) $model }
            return $name
        }
    }
    set base "$provider-[lindex [split [::vmdai::panel::hostport $url] :] end]"
    set name $base
    set n 2
    while {[dict exists $profiles $name] || [dict exists $local_new $name]} {
        set name "$base-$n"
        incr n
    }
    dict set local_new $name [dict create provider $provider base_url $url model $model options {}]
    _update_profile_values
    _load_profile $name
    return $name
}

proc ::vmdai::settings::_load_profile {name} {
    variable v
    set p [_saved_profile $name]
    set provider [_dget $p provider ollama]
    set opts [_dget $p options {}]
    set v(profile) $name
    set v(provider) $provider
    set v(provider_label) [::vmdai::panel::provider_label $provider]
    set v(server) [_dget $p base_url [default_url $provider]]
    set v(model) [_dget $p model ""]
    set ctx_key [expr {$provider eq "openai-compatible" ? "context_length" : "num_ctx"}]
    set v(ctx) [_dget $opts $ctx_key 32768]
    set v(think) [expr {[string is false -strict [_dget $opts think true]] ? 0 : 1}]
    set vision [_dget $opts supports_vision ""]
    if {[string is true -strict $vision]} {
        set v(snapshots) Send
    } elseif {[string is false -strict $vision]} {
        set v(snapshots) "Don't send"
    } elseif {$vision eq "" && $provider eq "openai-compatible"} {
        set v(snapshots) "Don't send"
    } else {
        set v(snapshots) Auto
    }
    set v(think_supported) 0
    _layout_provider
    refresh_models
}

proc ::vmdai::settings::_show_new_row {} {
    variable v
    set v(new_name) ""
    grid [tab model].newf
    focus [tab model].newf.e
}

proc ::vmdai::settings::new_profile {{name ""}} {
    variable profiles
    variable local_new
    set name [string trim $name]
    if {$name eq ""} {
        _show_new_row
        return ""
    }
    if {![regexp {^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$} $name]} {
        _footer_msg "Profile names use letters, digits, '.', '_' and '-' (at most 40)." err
        return ""
    }
    if {[dict exists $profiles $name] || [dict exists $local_new $name]} {
        _footer_msg "A profile named $name already exists." err
        return ""
    }
    dict set local_new $name [dict create provider ollama base_url [default_url ollama] model "" options {}]
    grid remove [tab model].newf
    _update_profile_values
    _load_profile $name
    _footer_msg ""
    return $name
}

proc ::vmdai::settings::_confirm {message} {
    variable win
    return [tk_messageBox -parent $win -type yesno -icon warning -title "ChatVMD Settings" -message $message]
}

proc ::vmdai::settings::delete_profile {} {
    variable v
    variable local_new
    variable active
    variable ACTIVE_DELETE
    set name $v(profile)
    if {$name eq ""} { return }
    if {[dict exists $local_new $name]} {
        dict unset local_new $name
        _update_profile_values
        _load_profile $active
        return
    }
    if {$name eq $active} {
        _footer_msg $ACTIVE_DELETE err
        return
    }
    if {[_confirm "Delete the profile \"$name\"?"] ne "yes"} { return }
    ::vmdai::net::call profiles.delete [list name s $name] [list ::vmdai::settings::_on_deleted $name]
}

proc ::vmdai::settings::_on_deleted {name form args} {
    variable profiles
    variable active
    variable win
    variable ACTIVE_DELETE
    if {![winfo exists $win]} { return }
    if {$form eq "rpc_error" && [lindex $args 0] eq "IN_USE"} {
        _footer_msg $ACTIVE_DELETE err
        return
    }
    if {$form ne "ok"} {
        _footer_msg [_failure "Could not delete the profile" $form $args] err
        return
    }
    dict unset profiles $name
    _update_profile_values
    _load_profile $active
    _footer_msg "Deleted $name."
}

# ---- models and the hint ------------------------------------------------------

proc ::vmdai::settings::refresh_models {} {
    variable v
    variable win
    variable models_gen
    if {![winfo exists $win]} { return }
    incr models_gen
    _set_model_hint "Loading models\u2026" {}
    set params [list provider s $v(provider)]
    if {[_uses_server] && [string trim $v(server)] ne ""} {
        lappend params base_url s [string trim $v(server)]
    }
    ::vmdai::net::call models.list $params [list ::vmdai::settings::_on_models $models_gen] -timeout 10000
}

proc ::vmdai::settings::_on_models {gen form args} {
    variable models_gen
    variable win
    variable models
    if {$gen != $models_gen || ![winfo exists $win]} { return }
    if {$form ne "ok"} {
        set models {}
        _update_model_values
        if {$form eq "transport"} {
            _set_model_hint "Could not list models ([lindex $args 0]). Type a model name, or use Test connection." {}
        } else {
            _set_model_hint "Could not list models: [lindex $args 1]" {}
        }
        return
    }
    set r [lindex $args 0]
    set models [_dget $r models {}]
    _update_model_values
    if {![llength $models]} {
        set message [_dget $r hint [_dget $r error ""]]
        if {$message eq ""} { set message "No models found on this server. Type a model name." }
        _set_model_hint $message {}
        return
    }
    _refresh_model_hint
}

proc ::vmdai::settings::_update_model_values {} {
    variable models
    set ids {}
    foreach model $models { lappend ids [_dget $model id ""] }
    [tab model].model configure -values $ids
}

proc ::vmdai::settings::_model_info {} {
    variable models
    variable v
    foreach model $models {
        if {[_dget $model id ""] eq [string trim $v(model)]} { return $model }
    }
    return [dict create id [string trim $v(model)]]
}

proc ::vmdai::settings::_refresh_model_hint {} {
    variable v
    variable win
    if {![winfo exists $win]} { return }
    set info [_model_info]
    set caps [_dget $info capabilities {}]
    set v(think_supported) [expr {[dict exists $caps thinking] && [string is true -strict [dict get $caps thinking]]}]
    set ctx [expr {[_uses_server] ? $v(ctx) : ""}]
    _set_model_hint [model_hint $info $ctx] [model_warnings $info $ctx]
    _layout_provider
}

proc ::vmdai::settings::_set_model_hint {hint warnings} {
    set m [tab model]
    $m.model_hint configure -text $hint
    $m.model_warn configure -text [join $warnings "\n"]
}

# ---- Test connection ------------------------------------------------------------

proc ::vmdai::settings::test_connection {} {
    variable v
    variable test_gen
    variable win
    if {![winfo exists $win]} { return }
    incr test_gen
    set m [tab model]
    $m.test.icon configure -text ""
    $m.test.l1 configure -text "Testing\u2026"
    $m.test.l2 configure -text ""
    set model [string trim $v(model)]
    set params [list provider s $v(provider)]
    if {[_uses_server] && [string trim $v(server)] ne ""} {
        lappend params base_url s [string trim $v(server)]
    }
    if {$model ne ""} { lappend params model s $model }
    ::vmdai::net::call provider.test $params [list ::vmdai::settings::_on_test $test_gen $model] -timeout 10000
}

proc ::vmdai::settings::_on_test {gen model form args} {
    variable test_gen
    variable win
    if {$gen != $test_gen || ![winfo exists $win]} { return }
    if {$form eq "ok"} {
        lassign [connection_lines [lindex $args 0] $model] icon line1 line2
    } else {
        set icon "\u2717"
        set line1 "Test failed"
        set line2 [_failure "The runtime could not run the test" $form $args]
    }
    set C ::vmdai::theme::c
    set colour [$C [expr {$icon eq "\u2713" ? "ok" : ($icon eq "!" ? "warn" : "err")}]]
    set m [tab model]
    $m.test.icon configure -text $icon -foreground $colour
    $m.test.l1 configure -text $line1
    $m.test.l2 configure -text $line2
}

# ---- Save -------------------------------------------------------------------

proc ::vmdai::settings::save {} {
    variable saving
    variable win
    if {$saving || ![winfo exists $win]} { return }
    set problem [_validate]
    if {$problem ne ""} {
        _footer_msg $problem err
        return
    }
    set saving 1
    _footer_msg "Saving\u2026"
    _next_step [save_steps]
}

proc ::vmdai::settings::save_steps {} {
    return {_save_profile _save_keys _save_persisted _save_plugin_prefs _finish_save}
}

# Each step is called with a continuation; it calls {*}$k when done, or
# _fail to stop the chain and keep the dialog open. An error in a step
# also stops the chain, so the dialog never stays at "Saving...".
proc ::vmdai::settings::_next_step {steps} {
    variable win
    if {![winfo exists $win] || ![llength $steps]} { return }
    set k [list ::vmdai::settings::_next_step [lrange $steps 1 end]]
    if {[catch {::vmdai::settings::[lindex $steps 0] $k} err]} {
        ::vmdai::config::log "settings: save step [lindex $steps 0] failed: $err"
        _fail "Could not save: $err"
    }
}

proc ::vmdai::settings::_fail {message} {
    variable saving
    set saving 0
    _footer_msg $message err
}

proc ::vmdai::settings::_validate {} {
    variable v
    if {$v(profile) eq ""} { return "Choose or create a profile first." }
    if {[_uses_server]} {
        if {![regexp {^https?://[^/\s]+} [string trim $v(server)]]} {
            return "The server must start with http:// or https://."
        }
        if {![string is integer -strict $v(ctx)] || $v(ctx) < 2048 || $v(ctx) > 1048576} {
            return "Context must be a whole number of tokens between 2048 and 1048576."
        }
    }
    return ""
}

proc ::vmdai::settings::_option_pairs {} {
    variable v
    set pairs {}
    switch -- $v(provider) {
        ollama {
            lappend pairs num_ctx i $v(ctx)
            if {$v(think_supported)} { lappend pairs think b [expr {$v(think) ? 1 : 0}] }
        }
        openai-compatible {
            lappend pairs context_length i $v(ctx)
        }
    }
    switch -- $v(snapshots) {
        Send          { lappend pairs supports_vision b 1 }
        "Don't send"  { lappend pairs supports_vision b 0 }
        default       { lappend pairs supports_vision s auto }
    }
    return $pairs
}

# An existing profile goes through provider.set {profile, ...}, which merges
# options key by key, so option keys this dialog does not show survive (section 2f).
# A profile made with New... is created with profiles.save.
proc ::vmdai::settings::_save_profile {k} {
    variable v
    variable profiles
    set name $v(profile)
    set options [::vmdai::net::encode_params [_option_pairs]]
    set model [string trim $v(model)]
    if {![dict exists $profiles $name]} {
        set pairs [list provider s $v(provider) model s $model]
        if {[_uses_server]} {
            lappend pairs base_url s [string trim $v(server)]
        } elseif {[default_url $v(provider)] ne ""} {
            lappend pairs base_url s [default_url $v(provider)]
        }
        lappend pairs options j $options
        set profile [::vmdai::net::encode_params $pairs]
        ::vmdai::net::call profiles.save [list name s $name profile j $profile activate b 1] \
            [list ::vmdai::settings::_after_profile $k $name 1]
        return
    }
    set params [list profile s $name provider s $v(provider) model s $model]
    if {[_uses_server]} { lappend params base_url s [string trim $v(server)] }
    lappend params options j $options
    ::vmdai::net::call provider.set $params [list ::vmdai::settings::_after_profile $k $name 0]
}

proc ::vmdai::settings::_after_profile {k name activated form args} {
    variable active
    variable local_new
    if {$form ne "ok"} {
        _fail [_failure "Could not save the profile" $form $args]
        return
    }
    if {[dict exists $local_new $name]} { dict unset local_new $name }
    if {$activated || $name eq $active} {
        set active $name
        {*}$k
        return
    }
    ::vmdai::net::call profiles.activate [list name s $name] [list ::vmdai::settings::_after_activate $k $name]
}

proc ::vmdai::settings::_after_activate {k name form args} {
    variable active
    if {$form ne "ok"} {
        _fail [_failure "Could not activate the profile" $form $args]
        return
    }
    set active $name
    {*}$k
}

proc ::vmdai::settings::_finish_save {k} {
    variable saving
    variable SAVED_TEXT
    set saving 0
    close
    set panel $::vmdai::panel::win
    if {[winfo exists $panel]} {
        ::vmdai::statusbar::flash $SAVED_TEXT 4000
        # The status bar follows the saved profile (P09-T07 makes
        # refresh_info re-read runtime.info and profiles.list).
        ::vmdai::panel::refresh_info
    }
    {*}$k
}

# ---- Keys tab (section 2f Providers and keys) ----------------------------------------

namespace eval ::vmdai::settings {
    variable KEY_PROVIDERS {anthropic Anthropic ANTHROPIC_API_KEY openrouter OpenRouter OPENROUTER_API_KEY}
    variable NO_KEYCHAIN_MESSAGE "No keychain backend available"
    variable NO_KEYCHAIN "No keychain backend: set ANTHROPIC_API_KEY/OPENROUTER_API_KEY in the environment, or install `keyring`"
    if {![info exists ::vmdai::settings::nokeychain]} { variable nokeychain 0 }
}

proc ::vmdai::settings::_build_keys {k} {
    variable KEY_PROVIDERS
    variable NO_KEYCHAIN
    variable nokeychain
    set C ::vmdai::theme::c
    set nokeychain 0
    set r 0
    foreach {id label env} $KEY_PROVIDERS {
        ttk::label $k.l_$id -text $label
        ttk::entry $k.e_$id -width 30 -show "\u2022" -textvariable ::vmdai::settings::v(key,$id)
        ttk::button $k.s_$id -text Show -width 6 -command [list ::vmdai::settings::_toggle_show $id]
        ttk::label $k.src_$id -text "" -font ChatMeta -foreground [$C muted]
        grid $k.l_$id -row $r -column 0 -sticky e -padx {0 10} -pady {6 0}
        grid $k.e_$id -row $r -column 1 -sticky ew -pady {6 0}
        grid $k.s_$id -row $r -column 2 -sticky w -padx {6 0} -pady {6 0}
        incr r
        grid $k.src_$id -row $r -column 1 -columnspan 2 -sticky w
        incr r
    }
    ttk::button $k.save -text "Save keys" -command ::vmdai::settings::save_keys
    ttk::label $k.nokey -text $NO_KEYCHAIN -font ChatMeta -foreground [$C warn] -wraplength 360 -justify left
    grid $k.save -row $r -column 1 -sticky w -pady {12 0}
    grid $k.nokey -row [expr {$r + 1}] -column 0 -columnspan 3 -sticky w -pady {12 0}
    grid remove $k.nokey
    grid columnconfigure $k 1 -weight 1
}

proc ::vmdai::settings::_toggle_show {id} {
    set k [tab keys]
    if {[$k.e_$id cget -show] eq ""} {
        $k.e_$id configure -show "\u2022"
        $k.s_$id configure -text Show
    } else {
        $k.e_$id configure -show ""
        $k.s_$id configure -text Hide
    }
}

proc ::vmdai::settings::key_source_text {id r} {
    variable KEY_PROVIDERS
    set env ""
    foreach {pid label var} $KEY_PROVIDERS {
        if {$pid eq $id} { set env $var }
    }
    switch -- [_dget $r source none] {
        env     { return "From the environment ($env)" }
        keyring { return "Saved in the Keychain" }
    }
    return "Not set"
}

proc ::vmdai::settings::_set_nokeychain {on} {
    variable nokeychain
    variable win
    set nokeychain [expr {$on ? 1 : 0}]
    if {![winfo exists $win]} { return }
    set k [tab keys]
    if {$nokeychain} {
        grid remove $k.save
        grid $k.nokey
    } else {
        grid $k.save
        grid remove $k.nokey
    }
}

proc ::vmdai::settings::_load_keys {} {
    variable KEY_PROVIDERS
    foreach {id label env} $KEY_PROVIDERS {
        ::vmdai::net::call keys.test [list provider s $id] [list ::vmdai::settings::_on_key_test $id]
    }
}

proc ::vmdai::settings::_on_key_test {id form args} {
    variable win
    variable NO_KEYCHAIN_MESSAGE
    if {![winfo exists $win]} { return }
    set src [tab keys].src_$id
    if {$form ne "ok"} {
        $src configure -text "Unknown: the runtime did not answer"
        return
    }
    set r [lindex $args 0]
    if {[_dget $r message ""] eq $NO_KEYCHAIN_MESSAGE} { _set_nokeychain 1 }
    $src configure -text [key_source_text $id $r]
}

# The Keys tab's own button: save the typed keys now.
proc ::vmdai::settings::save_keys {} {
    _save_keys [list ::vmdai::settings::_footer_msg "Keys saved."]
}

proc ::vmdai::settings::_save_keys {k} {
    variable nokeychain
    variable v
    variable KEY_PROVIDERS
    if {$nokeychain} {
        {*}$k
        return
    }
    set todo {}
    foreach {id label env} $KEY_PROVIDERS {
        if {[info exists v(key,$id)] && [string trim $v(key,$id)] ne ""} { lappend todo $id }
    }
    _save_next_key $todo $k
}

proc ::vmdai::settings::_save_next_key {todo k} {
    variable v
    if {![llength $todo]} {
        {*}$k
        return
    }
    set id [lindex $todo 0]
    ::vmdai::net::call keys.save [list provider s $id key s [string trim $v(key,$id)]] \
        [list ::vmdai::settings::_after_key $id [lrange $todo 1 end] $k]
}

proc ::vmdai::settings::_after_key {id rest k form args} {
    variable v
    variable win
    variable NO_KEYCHAIN_MESSAGE
    if {$form ne "ok"} {
        _fail [_failure "Could not save the $id key" $form $args]
        return
    }
    set r [lindex $args 0]
    if {![string is true -strict [_dget $r ok false]]} {
        if {[_dget $r message ""] eq $NO_KEYCHAIN_MESSAGE} {
            _set_nokeychain 1
            {*}$k
            return
        }
        _fail "Could not save the $id key: [_dget $r message {}]"
        return
    }
    set v(key,$id) ""
    if {[winfo exists $win]} { [tab keys].src_$id configure -text "Saved in the Keychain" }
    _save_next_key $rest $k
}

# ---- Panel tab ----------------------------------------------------------------

namespace eval ::vmdai::settings {
    # settings.json key -> form field, for the persisted toggles.
    variable PERSISTED_FIELDS {wiki_enabled wiki reasoning_visible reasoning}
    if {![info exists ::vmdai::settings::persisted]} { variable persisted {} }
}

# System needs MacWindowStyle (Tk 8.6 on aqua); elsewhere only Light and Dark (V7).
proc ::vmdai::settings::appearance_values {} {
    if {[tk windowingsystem] eq "aqua" && ![catch {::tk::unsupported::MacWindowStyle isdark .}]} {
        return {System Light Dark}
    }
    return {Light Dark}
}

proc ::vmdai::settings::_build_panel {p} {
    set C ::vmdai::theme::c
    set muted [$C muted]
    ttk::label $p.appearance_l -text Appearance
    ttk::combobox $p.appearance -state readonly -width 10 -values [appearance_values] \
        -textvariable ::vmdai::settings::v(appearance_label)
    ttk::checkbutton $p.expand -text "Expand steps by default" -variable ::vmdai::settings::v(expand)
    ttk::label $p.folder_l -text "Project folder"
    ttk::entry $p.folder -state readonly -width 30 -textvariable ::vmdai::settings::v(folder)
    ttk::button $p.folder_b -text "Choose\u2026" -command ::vmdai::settings::choose_folder
    ttk::label $p.python_l -text "Python for the runtime"
    ttk::entry $p.python -font ChatCode -width 30 -textvariable ::vmdai::settings::v(python)
    ttk::button $p.python_b -text "Choose\u2026" -command ::vmdai::settings::choose_python
    ttk::label $p.python_hint -font ChatMeta -foreground $muted -wraplength 340 -justify left \
        -text "Empty: VMD_AI_PYTHON, then python3 on PATH. Used the next time the runtime starts."
    ttk::checkbutton $p.wiki -text "Use project wiki (slower)" -variable ::vmdai::settings::v(wiki)
    ttk::label $p.wiki_hint -text "Adds about 17 s to every request." -font ChatMeta -foreground $muted
    ttk::label $p.tcl_l -text "Tcl execution"
    ttk::label $p.tcl -text "Auto-run (model-written Tcl runs without asking)" -foreground $muted
    ttk::button $p.log -text "Open log" -command ::vmdai::panel::open_log
    ttk::checkbutton $p.reasoning -text "Show model reasoning" -variable ::vmdai::settings::v(reasoning)
    grid $p.reasoning -row 1 -column 1 -columnspan 2 -sticky w -pady 4
    grid $p.appearance_l -row 0 -column 0 -sticky e -padx {0 10} -pady 4
    grid $p.appearance   -row 0 -column 1 -sticky w -pady 4
    grid $p.expand       -row 2 -column 1 -columnspan 2 -sticky w -pady 4
    grid $p.folder_l     -row 3 -column 0 -sticky e -padx {0 10} -pady 4
    grid $p.folder       -row 3 -column 1 -sticky ew -pady 4
    grid $p.folder_b     -row 3 -column 2 -sticky w -padx {6 0} -pady 4
    grid $p.python_l     -row 4 -column 0 -sticky e -padx {0 10} -pady {4 0}
    grid $p.python       -row 4 -column 1 -sticky ew -pady {4 0}
    grid $p.python_b     -row 4 -column 2 -sticky w -padx {6 0} -pady {4 0}
    grid $p.python_hint  -row 5 -column 1 -columnspan 2 -sticky w
    grid $p.wiki         -row 6 -column 1 -columnspan 2 -sticky w -pady {8 0}
    grid $p.wiki_hint    -row 7 -column 1 -columnspan 2 -sticky w -padx {22 0}
    grid $p.tcl_l        -row 8 -column 0 -sticky e -padx {0 10} -pady {8 0}
    grid $p.tcl          -row 8 -column 1 -columnspan 2 -sticky w -pady {8 0}
    grid $p.log          -row 9 -column 1 -sticky w -pady {10 0}
    grid columnconfigure $p 1 -weight 1
    bind $p.appearance <<ComboboxSelected>> \
        {set ::vmdai::settings::v(appearance) [string tolower $::vmdai::settings::v(appearance_label)]}
}

proc ::vmdai::settings::choose_folder {} {
    variable v
    variable win
    set dir [tk_chooseDirectory -parent $win -title "Project folder" -initialdir $v(folder) -mustexist 1]
    if {$dir ne ""} { set v(folder) $dir }
    return $dir
}

proc ::vmdai::settings::choose_python {} {
    variable v
    variable win
    set path [tk_getOpenFile -parent $win -title "Python for the runtime"]
    if {$path ne ""} { set v(python) $path }
    return $path
}

proc ::vmdai::settings::_load_panel_prefs {} {
    variable v
    set d {}
    catch {set d [::vmdai::config::load_plugin_settings]}
    set v(appearance) [_dget $d appearance system]
    if {$v(appearance) ni {system light dark}} { set v(appearance) system }
    set v(appearance_label) [string totitle $v(appearance)]
    set v(expand) [string is true -strict [_dget $d expand_steps false]]
    set v(expand_loaded) $v(expand)
    set v(python) [_dget $d python ""]
    set v(folder) [pwd]
}

# An empty patch reads the persisted top-level settings without writing them.
proc ::vmdai::settings::_load_persisted {} {
    ::vmdai::net::call settings.set [list patch j "{}"] [list ::vmdai::settings::_on_persisted]
}

proc ::vmdai::settings::_on_persisted {form args} {
    variable persisted
    variable v
    variable win
    variable PERSISTED_FIELDS
    if {$form ne "ok" || ![winfo exists $win]} { return }
    set persisted {}
    catch {set persisted [dict get [lindex $args 0] persisted]}
    foreach {key field} $PERSISTED_FIELDS {
        if {[dict exists $persisted $key]} {
            set v($field) [string is true -strict [dict get $persisted $key]]
        }
    }
}

# Only keys the runtime reported and the user changed; nothing when the
# settings could not be read (a tokenless session, or a failed read).
proc ::vmdai::settings::_persisted_pairs {} {
    variable persisted
    variable v
    variable PERSISTED_FIELDS
    set pairs {}
    foreach {key field} $PERSISTED_FIELDS {
        if {![dict exists $persisted $key] || ![info exists v($field)]} { continue }
        set old [string is true -strict [dict get $persisted $key]]
        set new [expr {$v($field) ? 1 : 0}]
        if {$old != $new} { lappend pairs $key b $new }
    }
    return $pairs
}

proc ::vmdai::settings::_save_persisted {k} {
    set pairs [_persisted_pairs]
    if {![llength $pairs]} {
        {*}$k
        return
    }
    ::vmdai::net::call settings.set [list patch j [::vmdai::net::encode_params $pairs]] \
        [list ::vmdai::settings::_after_persisted $k]
}

proc ::vmdai::settings::_after_persisted {k form args} {
    variable persisted
    if {$form ne "ok"} {
        _fail [_failure "Could not save the panel settings" $form $args]
        return
    }
    catch {set persisted [dict get [lindex $args 0] persisted]}
    variable v
    if {[info exists v(reasoning)]} { ::vmdai::panel::set_reasoning_visible $v(reasoning) }
    {*}$k
}

proc ::vmdai::settings::_save_plugin_prefs {k} {
    variable v
    set d {}
    catch {set d [::vmdai::config::load_plugin_settings]}
    dict set d version 1
    dict set d appearance $v(appearance)
    dict set d expand_steps [expr {$v(expand) ? 1 : 0}]
    dict set d python [string trim $v(python)]
    if {[catch {::vmdai::config::save_plugin_settings $d} err]} {
        _fail "Could not write plugin.json: $err"
        return
    }
    if {$v(expand) != $v(expand_loaded)} { ::vmdai::panel::set_expand_all $v(expand) }
    if {$v(folder) ne "" && $v(folder) ne [pwd]} { ::vmdai::bridge::apply_workdir $v(folder) }
    {*}$k
}
