# P09-T04/T05: the Settings dialog (Part B V4 "Settings"; C7 Visibility).
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop

set ::QWEN [dict create id qwen3.8:27b label qwen3.8:27b \
    capabilities [dict create tools true vision true thinking true] context_length 131072]
set ::LLAVA [dict create id llava:7b label llava:7b \
    capabilities [dict create tools false vision true thinking false] context_length 4096]
set ::MODELS [dict create models [list $::QWEN $::LLAVA] source server]
set ::PROFILES [dict create active qwen settings_source file profiles [dict create \
    qwen [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b \
        options [dict create num_ctx 32768 think true]] \
    vllm [dict create provider openai-compatible base_url http://localhost:8000/v1 model m1 \
        options [dict create supports_vision false]]]]

namespace eval ::test {}
proc ::test::open_loaded {{which model}} {
    ::harness::fresh_panel
    ::fake::reply profiles.list ok $::PROFILES
    ::fake::reply models.list ok $::MODELS
    ::fake::reply keys.test ok {ok false message {key missing} source none}
    ::fake::reply settings.set ok {ok true settings {} persisted {reasoning_visible true wiki_enabled false}}
    set w [::vmdai::settings::open $which]
    ::harness::wait_until {expr {$::vmdai::settings::v(profile) eq "qwen"
        && [llength $::vmdai::settings::models] == 2}}
    return $w
}

test settings-provider_fields_change {the fields follow the provider} -body {
    ::test::open_loaded
    set m [::vmdai::settings::tab model]
    set r [list [winfo manager $m.server] [winfo manager $m.ctxf] [winfo manager $m.think]]
    ::vmdai::settings::set_provider anthropic-direct
    lappend r [winfo manager $m.server] [winfo manager $m.ctxf] [winfo manager $m.think] \
        [winfo manager $m.snap] $::vmdai::settings::v(provider_label)
    ::vmdai::settings::set_provider openai-compatible
    lappend r [winfo manager $m.server] [winfo manager $m.think] $::vmdai::settings::v(snapshots) \
        $::vmdai::settings::v(server)
    ::vmdai::settings::set_provider ollama
    lappend r $::vmdai::settings::v(server)
} -result [list grid grid grid {} {} {} grid Anthropic grid {} "Don't send" http://localhost:8000/v1 \
    http://127.0.0.1:11435]

test settings-model_hint_caps_and_ctx {the hint names the capabilities and the context (C7)} -body {
    set a [::vmdai::settings::model_hint $::QWEN 32768]
    set b [::vmdai::settings::model_hint [dict create id m] 16384]
    ::test::open_loaded
    list $a $b [expr {[[::vmdai::settings::tab model].model_hint cget -text] eq $a}]
} -result [list "qwen3.8:27b: tools \u2713 vision \u2713 thinking \u2713 \u00b7 ctx 32k (max 128k)" \
    "m \u00b7 ctx 16k" 1]

test settings-low_ctx_warning {num_ctx below 16384 and a model without tools are flagged} -body {
    set a [::vmdai::settings::model_warnings $::QWEN 8192]
    set b [::vmdai::settings::model_warnings $::QWEN 16384]
    set c [::vmdai::settings::model_warnings $::LLAVA 32768]
    ::test::open_loaded
    set ::vmdai::settings::v(ctx) 8192
    ::vmdai::settings::_refresh_model_hint
    set d [[::vmdai::settings::tab model].model_warn cget -text]
    list $a $b $c [expr {$d eq $::vmdai::settings::LOW_CTX_WARNING}]
} -result [list [list $::vmdai::settings::LOW_CTX_WARNING] {} [list $::vmdai::settings::NO_TOOLS_WARNING] 1]

test settings-models_timeout_hint {a models.list timeout or an empty list leaves the dialog usable} -body {
    ::harness::fresh_panel
    ::fake::reply profiles.list ok $::PROFILES
    ::fake::reply models.list transport timeout
    ::fake::reply keys.test ok {ok false message {key missing} source none}
    ::fake::reply settings.set ok {ok true settings {} persisted {reasoning_visible true wiki_enabled false}}
    set w [::vmdai::settings::open]
    set m [::vmdai::settings::tab model]
    ::harness::wait_until {string match "Could not list models*" [[::vmdai::settings::tab model].model_hint cget -text]}
    set r [list [$m.model_hint cget -text] [$m.model instate disabled] \
        [[::vmdai::settings::footer].save instate disabled] [::fake::timeout_of models.list]]
    ::fake::reply models.list ok {models {} source server}
    ::vmdai::settings::refresh_models
    ::harness::wait_until {string match "No models*" [[::vmdai::settings::tab model].model_hint cget -text]}
    lappend r [$m.model_hint cget -text]
    set ::vmdai::settings::v(model) typed-model:1b
    ::fake::reply provider.set ok {ok true}
    ::vmdai::settings::save
    ::harness::wait_until {expr {![winfo exists .vmd_ai_settings]}}
    lappend r [::fake::param [::fake::last provider.set] model]
} -result [list "Could not list models (timeout). Type a model name, or use Test connection." 0 0 10000 \
    "No models found on this server. Type a model name." typed-model:1b]

test settings-test_connection_lines {Test connection shows an icon and two lines, never "tool call"} -body {
    set ok [dict create ok true reachable true latency_ms 212 model_present true loaded true \
        capabilities [dict create tools true vision true thinking true]]
    set down [dict create ok false reachable false latency_ms null model_present null loaded null \
        capabilities {} error refused hint "Nothing is listening on 127.0.0.1:11435. Is the SSH tunnel up?"]
    set missing [dict create ok false reachable true latency_ms 40 model_present false loaded false \
        capabilities {} error "Model nope:1b is not on this server" hint "ollama pull nope:1b"]
    set r [list [::vmdai::settings::connection_lines $ok qwen3.8:27b] \
        [::vmdai::settings::connection_lines $down qwen3.8:27b] \
        [::vmdai::settings::connection_lines $missing nope:1b]]
    ::test::open_loaded
    ::fake::reply provider.test ok $ok
    ::vmdai::settings::test_connection
    set m [::vmdai::settings::tab model]
    ::harness::wait_until {string match Connected* [[::vmdai::settings::tab model].test.l1 cget -text]}
    lappend r [list [$m.test.icon cget -text] [$m.test.l1 cget -text] [$m.test.l2 cget -text]] \
        [::fake::timeout_of provider.test] [::fake::param [::fake::last provider.test] base_url] \
        [string match "*tool call*" [join [concat {*}$r]]]
} -result [list \
    [list "\u2713" "Connected \u00b7 212 ms" "qwen3.8:27b loaded \u00b7 tools \u2713 vision \u2713"] \
    [list "\u2717" "Not connected" "Nothing is listening on 127.0.0.1:11435. Is the SSH tunnel up?"] \
    [list "\u2717" "Connected \u00b7 40 ms" "ollama pull nope:1b"] \
    [list "\u2713" "Connected \u00b7 212 ms" "qwen3.8:27b loaded \u00b7 tools \u2713 vision \u2713"] \
    10000 http://127.0.0.1:11435 0]

test settings-new_delete_profile {New... adds an unsaved profile; the active profile cannot be deleted} -body {
    ::test::open_loaded
    ::vmdai::settings::new_profile lab-box
    set m [::vmdai::settings::tab model]
    set r [list $::vmdai::settings::v(profile) $::vmdai::settings::v(provider) \
        [expr {"lab-box" in [$m.profile cget -values]}]]
    ::vmdai::settings::new_profile qwen
    lappend r [[::vmdai::settings::footer].msg cget -text]
    ::vmdai::settings::delete_profile
    lappend r [::fake::count profiles.delete] $::vmdai::settings::v(profile)
    ::vmdai::settings::delete_profile
    lappend r [::fake::count profiles.delete] [[::vmdai::settings::footer].msg cget -text]
    proc ::vmdai::settings::_confirm {message} { return yes }
    ::vmdai::settings::_load_profile vllm
    ::fake::reply profiles.delete ok {ok true}
    ::vmdai::settings::delete_profile
    ::harness::wait_until {expr {![dict exists $::vmdai::settings::profiles vllm]}}
    lappend r [::fake::param [::fake::last profiles.delete] name] $::vmdai::settings::v(profile)
} -result [list lab-box ollama 1 "A profile named qwen already exists." 0 qwen 0 \
    "This is the active profile. Activate another profile before deleting it." vllm qwen]

cleanupTests
