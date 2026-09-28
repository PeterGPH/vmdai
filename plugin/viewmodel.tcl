# viewmodel.tcl -- ChatVMD view-model: v2 display events -> render ops.
#
# Pure Tcl, no Tk (spec §2h). The state lives in a dict held by the caller:
#
#   ::vmdai::vm::init  stateVar ?options?
#   ::vmdai::vm::apply stateVar event      -> list of ops
#
# An event is a decoded §2c envelope, {seq ts role type text metadata}, as
# json::json2dict returns it: JSON null is the string "null" and booleans
# are "true"/"false"; _get and _bool normalise both. The op vocabulary and
# argument lists are fixed by spec §2h and Part B V4 so that op goldens can
# be written before any widget exists. Optional trailing arguments added by
# this plan: block.open ?time?, tool.open ?rationale?, run.close ?max_turns?,
# snapshot ?renderer?.

namespace eval ::vmdai::vm {}

proc ::vmdai::vm::init {stateVar {options {}}} {
    upvar 1 $stateVar S
    set S [dict create \
        opts [dict merge {reasoning_visible 1} $options] \
        bseq 0 rseq 0 \
        open {} \
        texts {} \
        reasons {} \
        rsealed {} \
        runs {} \
        tools {} \
        warned {} \
        request "" \
        busy 0 phase "" phase_t0 "" stopping 0 \
        conn "" \
        trust_notice 0]
    return
}

# ---- small helpers ----------------------------------------------------------

proc ::vmdai::vm::_get {d key {default ""}} {
    if {[catch {dict exists $d $key} has] || !$has} { return $default }
    set v [dict get $d $key]
    if {$v eq "null"} { return $default }
    return $v
}

proc ::vmdai::vm::_bool {v} {
    if {[string is boolean -strict $v]} { return [expr {$v ? 1 : 0}] }
    return 0
}

proc ::vmdai::vm::_secs {ts} {
    if {![string is double -strict $ts]} { return 0 }
    return [expr {wide(floor($ts))}]
}

proc ::vmdai::vm::_first_line {s} {
    foreach line [split $s "\n"] {
        if {[string trim $line] ne ""} { return [string trim $line] }
    }
    return ""
}

proc ::vmdai::vm::_dur_text {ms} {
    if {![string is double -strict $ms]} { return "" }
    if {$ms < 10000} { return [format "%.1f s" [expr {$ms / 1000.0}]] }
    return [format "%d s" [expr {int(round($ms / 1000.0))}]]
}

proc ::vmdai::vm::_new_block {sv} {
    upvar 1 $sv S
    dict incr S bseq
    return b[dict get $S bseq]
}

# Encode one op as a single line that `lindex` parses back exactly
# (tests/fixtures/ops/<name>.ops holds one op per line).
proc ::vmdai::vm::format_op {op} {
    set words {}
    foreach w $op {
        if {$w ne "" && [regexp {^[A-Za-z0-9_.:/+@%,=-]+$} $w]} {
            lappend words $w
        } else {
            lappend words "\"[string map {\\ \\\\ \" \\\" \n \\n \r \\r \t \\t} $w]\""
        }
    }
    return [join $words " "]
}

# ---- runs, phases -----------------------------------------------------------

proc ::vmdai::vm::_ensure_run {sv req ts} {
    upvar 1 $sv S
    if {$req eq "" || [dict exists $S runs $req]} { return {} }
    return [_open_run S $req "" 28 1 $ts]
}

proc ::vmdai::vm::_open_run {sv req model max_turns vision ts} {
    upvar 1 $sv S
    dict incr S rseq
    set run r[dict get $S rseq]
    dict set S runs $req [dict create id $run model $model t0 [_secs $ts] \
        max_turns $max_turns vision $vision steps 0 failed 0 last_tcl "" \
        applied 0 status running]
    dict set S request $req
    return [list [list run.open $run $req $model [_secs $ts]]]
}

proc ::vmdai::vm::_run_id {sv req} {
    upvar 1 $sv S
    if {$req ne "" && [dict exists $S runs $req]} { return [dict get $S runs $req id] }
    return ""
}

# Set the busy phase; returns a status op only when the text changes.
proc ::vmdai::vm::_phase {sv text ts {timed 1}} {
    upvar 1 $sv S
    if {[dict get $S busy] && [dict get $S phase] eq $text} { return {} }
    dict set S busy 1
    dict set S phase $text
    dict set S phase_t0 [expr {$timed ? [_secs $ts] : ""}]
    return [list [list status busy $text [dict get $S phase_t0]]]
}

proc ::vmdai::vm::_tool_phase {name n} {
    switch -glob -- $name {
        run_vmd_command      { return "Step $n · running VMD command" }
        capture_vmd_snapshot { return "Step $n · rendering snapshot" }
        search_docs          { return "Step $n · searching docs" }
        wiki_*               { return "Step $n · reading the wiki" }
        default              { return "Step $n · running $name" }
    }
}

# ---- blocks -----------------------------------------------------------------

# Close the open block. A reasoning block is sealed here (the thinking is
# over once anything else arrives); a text block stays unsealed until its
# assistant/message.
proc ::vmdai::vm::_close_open {sv ts} {
    upvar 1 $sv S
    set open [dict get $S open]
    dict set S open {}
    if {$open eq "" || [dict get $open kind] ne "reasoning"} { return {} }
    return [_seal_reason S [dict get $open id] [expr {[_secs $ts] - [dict get $open t0]}]]
}

proc ::vmdai::vm::_seal_reason {sv b secs} {
    upvar 1 $sv S
    if {[lsearch -exact [dict get $S rsealed] $b] >= 0} { return {} }
    dict lappend S rsealed $b
    if {$secs < 0} { set secs 0 }
    return [list [list reasoning.seal $b $secs]]
}

proc ::vmdai::vm::_on_text_chunk {sv md text ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    set turn [_get $md turn 0]
    set open [dict get $S open]
    if {$open ne "" && [dict get $open kind] eq "text"
            && [dict get $open request_id] eq $req && [dict get $open turn] eq $turn} {
        return [list [list block.append [dict get $open id] $text]]
    }
    set ops [_close_open S $ts]
    lappend ops {*}[_ensure_run S $req $ts]
    set b [_new_block S]
    dict set S open [dict create kind text id $b request_id $req turn $turn t0 [_secs $ts]]
    dict lappend S texts "$req|$turn" $b
    lappend ops [list block.open $b assistant $turn] [list block.append $b $text]
    if {$req ne ""} { lappend ops {*}[_phase S "Writing" $ts] }
    return $ops
}

proc ::vmdai::vm::_on_reason_chunk {sv md text ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    set turn [_get $md turn 0]
    set open [dict get $S open]
    if {$open ne "" && [dict get $open kind] eq "reasoning"
            && [dict get $open request_id] eq $req && [dict get $open turn] eq $turn} {
        return [list [list reasoning.append [dict get $open id] $text]]
    }
    set ops [_close_open S $ts]
    lappend ops {*}[_ensure_run S $req $ts]
    set b [_new_block S]
    dict set S open [dict create kind reasoning id $b request_id $req turn $turn t0 [_secs $ts]]
    dict lappend S reasons "$req|$turn" $b
    lappend ops [list reasoning.open $b $turn] [list reasoning.append $b $text]
    if {$req ne ""} { lappend ops {*}[_phase S "Thinking" $ts] }
    return $ops
}

# The per-turn assistant/message replaces the streamed text (§2c Sealing).
# A final answer is re-opened under a rule so that live and replayed chats
# render the same (the rule separates the work log from the answer).
proc ::vmdai::vm::_on_assistant_message {sv md text ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    set turn [_get $md turn 0]
    set final [_bool [_get $md final false]]
    set key "$req|$turn"
    set pending [_get [dict get $S texts] $key]
    dict unset S texts $key
    set ops [_ensure_run S $req $ts]
    if {[string trim $text] eq ""} {
        foreach b $pending { lappend ops [list block.discard $b] }
        return $ops
    }
    if {$final && $req ne ""} {
        foreach b $pending { lappend ops [list block.discard $b] }
        set b [_new_block S]
        lappend ops [list rule [_run_id S $req]] [list block.open $b assistant $turn] \
            [list block.seal $b $text]
        return $ops
    }
    if {[llength $pending]} {
        set b [lindex $pending 0]
        lappend ops [list block.seal $b $text]
        foreach extra [lrange $pending 1 end] { lappend ops [list block.discard $extra] }
        return $ops
    }
    set b [_new_block S]
    lappend ops [list block.open $b assistant $turn] [list block.seal $b $text]
    return $ops
}

# A sealed reasoning/message: seals the live block, or renders the whole
# block when replaying a stored chat (no chunks were seen).
proc ::vmdai::vm::_on_reasoning_message {sv md text ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    set turn [_get $md turn 0]
    set secs [_get $md duration_s ""]
    if {![string is double -strict $secs]} {
        set ms [_get $md duration_ms ""]
        set secs [expr {[string is double -strict $ms] ? $ms / 1000.0 : 0}]
    }
    set secs [expr {int(round($secs))}]
    set blocks [_get [dict get $S reasons] "$req|$turn"]
    if {[llength $blocks]} {
        return [_seal_reason S [lindex $blocks end] $secs]
    }
    if {[string trim $text] eq ""} { return {} }
    set ops [_ensure_run S $req $ts]
    set b [_new_block S]
    dict lappend S reasons "$req|$turn" $b
    lappend ops [list reasoning.open $b $turn] [list reasoning.append $b $text]
    lappend ops {*}[_seal_reason S $b $secs]
    return $ops
}

proc ::vmdai::vm::_on_user_message {sv text ts} {
    upvar 1 $sv S
    set b [_new_block S]
    return [list [list block.open $b user 0 [_secs $ts]] [list block.append $b $text]]
}

# turn.retry discards everything the dropped attempt of that turn showed.
proc ::vmdai::vm::_on_turn_retry {sv md} {
    upvar 1 $sv S
    set key "[_get $md request_id]|[_get $md turn 0]"
    set ops {}
    foreach b [_get [dict get $S texts] $key] { lappend ops [list block.discard $b] }
    foreach b [_get [dict get $S reasons] $key] { lappend ops [list block.discard $b] }
    dict unset S texts $key
    dict unset S reasons $key
    return $ops
}

# ---- tools ------------------------------------------------------------------

proc ::vmdai::vm::_tool_text {name input} {
    switch -glob -- $name {
        run_vmd_command      { return [_get $input command] }
        capture_vmd_snapshot { return [_get $input purpose] }
        search_docs          { return [_get $input query] }
        wiki_*               { return [_get $input page] }
        default              { return [_get $input command] }
    }
}

proc ::vmdai::vm::_on_tool_started {sv md ts} {
    upvar 1 $sv S
    set k [_get $md call_key]
    if {$k eq "" || [dict exists $S tools $k]} { return {} }
    set req [_get $md request_id]
    set ops [_ensure_run S $req $ts]
    set run [_run_id S $req]
    set n 1
    if {[dict exists $S runs $req]} {
        set n [expr {[dict get $S runs $req steps] + 1}]
        dict set S runs $req steps $n
    }
    set name [_get $md tool_name]
    set input [_get $md input]
    dict set S tools $k [dict create run $run request_id $req tool_name $name \
        executor [_get $md executor tcl] state running index $n finished 0]
    lappend ops [list tool.open $k $name [_tool_text $name $input] \
        [_get $md executor tcl] [_get $md origin model] [_get $input rationale]]
    if {$run ne ""} { lappend ops [list run.chip $run $k running] }
    lappend ops {*}[_phase S [_tool_phase $name $n] $ts]
    return $ops
}

proc ::vmdai::vm::tool_state {md} {
    switch -- [_get $md executed yes] {
        no      { return notrun }
        unknown { return unknown }
    }
    if {[_bool [_get $md ok false]]} { return ok }
    return err
}

# Inline result and preview lines for a tool's output (Part B V4 Results).
proc ::vmdai::vm::_result_view {output} {
    set o [string trim $output]
    if {$o eq "" || [regexp {^(0|1|atomselect[0-9]+)$} $o]} { return [list "" {}] }
    if {[string first "\n" $o] < 0 && [string length $o] <= 24} {
        if {[string is double -strict $o] && [regexp {[.eE]} $o]} {
            set o [format %.6g $o]
        }
        return [list $o {}]
    }
    set lines [split [string trimright $output "\n"] "\n"]
    if {[llength $lines] <= 4} { return [list "" $lines] }
    set more [expr {[llength $lines] - 3}]
    return [list "" [concat [lrange $lines 0 2] [list "… $more more lines"]]]
}

proc ::vmdai::vm::_tool_detail {md state late} {
    set output [_get $md output]
    lassign [_result_view $output] inline preview
    set label ""
    set error ""
    switch -- $state {
        notrun  { set label [notrun_label $md]; set inline ""; set preview {} }
        unknown { set label "stopped while running · outcome unknown" }
        err     { set error [_first_line [_get $md error]]; set inline "" }
    }
    if {$late} { set label [string trim "$label (finished late)"] }
    set stmts [_get $md statements]
    set failed [_get $stmts failed]
    return [dict create label $label error $error inline $inline preview $preview \
        output $output output_path [_get $md output_path] \
        total [_get $stmts total] applied [_get $stmts applied] \
        failed_index [_get $failed index] failed_text [_get $failed text] \
        late $late]
}

proc ::vmdai::vm::_chip_state {state k warned} {
    if {$state eq "unknown"} { return warn }
    if {$state eq "ok" && [lsearch -exact $warned $k] >= 0} { return warn }
    return $state
}

proc ::vmdai::vm::_on_tool_finished {sv md ts} {
    upvar 1 $sv S
    set k [_get $md call_key]
    if {$k eq "" || ![dict exists $S tools $k]} { return {} }
    set late [_bool [_get $md late false]]
    set tool [dict get $S tools $k]
    if {[dict get $tool finished] && !$late} { return {} }
    set state [tool_state $md]
    if {$late && $state ni {ok err}} { return {} }
    set was [dict get $tool state]
    dict set S tools $k state $state
    dict set S tools $k finished 1
    set run [dict get $tool run]
    set req [dict get $tool request_id]
    set image [_get $md image]
    set thumb [expr {$image eq "" ? "" : [_get $image thumb_path]}]
    set ops [list [list tool.close $k $state [_dur_text [_get $md duration_ms ""]] \
        [_tool_detail $md $state $late] $thumb]]
    if {$run ne ""} {
        lappend ops [list run.chip $run $k [_chip_state $state $k [dict get $S warned]]]
    }
    if {$image ne ""} {
        set vision 1
        if {[dict exists $S runs $req]} { set vision [dict get $S runs $req vision] }
        set w [_get $image src_width [_get $image width]]
        set h [_get $image src_height [_get $image height]]
        lappend ops [list snapshot $k $thumb [_get $image path] $w $h \
            [_get $md saved_path] $vision [_get $image renderer TachyonInternal]]
    }
    if {[dict exists $S runs $req] && [dict get $tool executor] eq "tcl"
            && [dict get $tool tool_name] eq "run_vmd_command"} {
        if {$state eq "err" && $was ne "err"} {
            dict set S runs $req failed [expr {[dict get $S runs $req failed] + 1}]
        }
        if {$state in {ok err}} { dict set S runs $req last_tcl $state }
        set stmts [_get $md statements]
        set applied [_get $stmts applied ""]
        if {![string is integer -strict $applied]} {
            set applied [expr {$state eq "ok" ? 1 : 0}]
        }
        if {!$late || $was ni {ok err}} {
            dict set S runs $req applied [expr {[dict get $S runs $req applied] + $applied}]
        }
    }
    if {!$late && [dict get $S request] eq $req && [dict get $S busy]} {
        lappend ops {*}[_phase S "Thinking" $ts]
    }
    return $ops
}

# ---- status, errors, request lifecycle ------------------------------------

proc ::vmdai::vm::_on_status {sv md ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    switch -- [_get $md phase] {
        retrying {
            set text "Retrying [_get $md attempt ?]/[_get $md max_attempts ?] in [_get $md wait_s ?] s"
            return [_phase S $text $ts 0]
        }
        loading_model {
            set model ""
            if {[dict exists $S runs $req]} { set model [dict get $S runs $req model] }
            return [_phase S [string trim "Loading $model"] $ts]
        }
        wrapping_up   { return [_phase S "Writing a summary" $ts] }
        loop_detected {
            set k [_get $md call_key]
            if {$k eq ""} { return {} }
            dict lappend S warned $k
            if {![dict exists $S tools $k]} { return {} }
            set run [dict get $S tools $k run]
            set state [dict get $S tools $k state]
            if {$run eq "" || $state eq "running"} { return {} }
            return [list [list run.chip $run $k [_chip_state $state $k [dict get $S warned]]]]
        }
        context_near_full {
            return [list [list notice info "Context is nearly full; older tool output is shortened"]]
        }
        turn_truncated {
            return [list [list notice info "The reply was cut off, so its tool calls were not run"]]
        }
        think_unsupported {
            return [list [list notice info "This model does not support thinking; continuing without it"]]
        }
    }
    return {}
}

proc ::vmdai::vm::_on_request_started {sv md ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    if {$req eq "" || [dict exists $S runs $req]} { return {} }
    set max_turns [_get $md max_turns 28]
    set ops [_open_run S $req [_get $md model] $max_turns [_bool [_get $md vision true]] $ts]
    dict set S stopping 0
    lappend ops {*}[_phase S "Thinking" $ts]
    return $ops
}

proc ::vmdai::vm::_on_turn_started {sv md ts} {
    upvar 1 $sv S
    if {[dict get $S request] ne [_get $md request_id]} { return {} }
    return [_phase S "Thinking" $ts]
}

proc ::vmdai::vm::_close_run {sv req status final_text_empty duration_s} {
    upvar 1 $sv S
    set run [dict get $S runs $req]
    dict set S runs $req status $status
    set failed [dict get $run failed]
    set recovered [expr {$failed > 0 && [dict get $run last_tcl] eq "ok" && $status ne "error"}]
    set ops {}
    if {[dict get $run applied] > 0} {
        lappend ops [list footer [dict get $run id] [dict get $run applied] ""]
    }
    lappend ops [list run.close [dict get $run id] $status [dict get $run steps] $failed \
        $recovered $duration_s $final_text_empty [dict get $run max_turns]]
    if {[dict get $S request] eq $req} {
        dict set S request ""
        dict set S busy 0
        dict set S phase ""
        dict set S phase_t0 ""
        dict set S stopping 0
        lappend ops [list status idle]
    }
    return $ops
}

proc ::vmdai::vm::_on_request_finished {sv md ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    if {$req eq "" || ![dict exists $S runs $req]} { return {} }
    if {[dict get $S runs $req status] ne "running"} { return {} }
    set status [_get $md status complete]
    set ms [_get $md duration_ms ""]
    if {[string is double -strict $ms]} {
        set secs [expr {int(round($ms / 1000.0))}]
    } else {
        set secs [expr {[_secs $ts] - [dict get $S runs $req t0]}]
    }
    set empty [_bool [_get $md final_text_empty false]]
    set calls [_get $md tool_calls [dict get $S runs $req steps]]
    set ops [_finish_notes [dict get $S runs $req] $status $calls $empty \
        [_bool [_get $md wrapped_up false]] [_get $md error]]
    lappend ops {*}[_close_run S $req $status $empty $secs]
    return $ops
}

# ---- entry point ------------------------------------------------------------

proc ::vmdai::vm::apply {stateVar event} {
    upvar 1 $stateVar S
    set role [_get $event role]
    set type [_get $event type]
    set text [_get $event text]
    set md [_get $event metadata]
    set ts [_get $event ts 0]
    if {$type eq "chunk"} {
        switch -- $role {
            assistant { return [_on_text_chunk S $md $text $ts] }
            reasoning { return [_on_reason_chunk S $md $text $ts] }
        }
        return {}
    }
    # A reasoning/message seals its block with the runtime's duration_ms
    # before the generic close could seal it from chunk timestamps, so a
    # live chat and its replay say the same "Thought for N s" (spec 2c).
    if {$role eq "reasoning" && $type eq "message"} {
        set ops [_on_reasoning_message S $md $text $ts]
        return [concat $ops [_close_open S $ts]]
    }
    set ops [_close_open S $ts]
    set kind [_get $md kind]
    switch -- $role/$type {
        user/message      { lappend ops {*}[_on_user_message S $text $ts] }
        assistant/message { lappend ops {*}[_on_assistant_message S $md $text $ts] }
        error/message     { lappend ops {*}[_on_error $md $text] }
        system/message {
            if {[_get $md notice] eq "tcl_trust_boundary"} {
                dict set S trust_notice 1
            } elseif {[string trim $text] ne ""} {
                lappend ops [list notice info $text]
            }
        }
        system/state {
            switch -glob -- $kind {
                request.started  { lappend ops {*}[_on_request_started S $md $ts] }
                request.finished { lappend ops {*}[_on_request_finished S $md $ts] }
                turn.started     { lappend ops {*}[_on_turn_started S $md $ts] }
                turn.retry       { lappend ops {*}[_on_turn_retry S $md] }
                tool.started     { lappend ops {*}[_on_tool_started S $md $ts] }
                tool.finished    { lappend ops {*}[_on_tool_finished S $md $ts] }
                status           { lappend ops {*}[_on_status S $md $ts] }
                usage            { }
                local.*          { lappend ops {*}[_on_local S $kind $md $ts] }
            }
        }
    }
    return $ops
}

# First line wins, in C1-C4 order (Part B V4 "not run").
proc ::vmdai::vm::notrun_label {md} {
    set blocked [_get $md blocked]
    if {[llength $blocked]} {
        return "not run · blocked: [_get [lindex $blocked 0] word exec]"
    }
    set stmts [_get $md statements]
    if {$stmts ne "" && [_get $stmts failed] ne ""} { return "not run · incomplete Tcl" }
    set err [string trim [_get $md error]]
    if {$err eq "not executed: loop guard"} { return "not run · loop guard" }
    if {$err eq "cancelled"} { return "not run · stopped" }
    if {[string match "VMD did not pick up the command*" $err]} {
        return "VMD did not pick up the command"
    }
    set first [_first_line $err]
    if {$first eq ""} { return "not run" }
    return "not run · $first"
}

proc ::vmdai::vm::_default_action {code} {
    switch -- $code {
        auth            { return open_settings }
        billing         { return switch_profile }
        model_not_found { return choose_model }
        unreachable     { return test_connection }
        NO_MODEL        { return open_settings }
        default         { return open_log }
    }
}

proc ::vmdai::vm::_on_error {md text} {
    set code [_get $md code other]
    set action [_get $md action [_default_action $code]]
    return [list [list error.card $code $text [_get $md hint] $action]]
}

# ---- plugin-local events (P07-T08 kinds) -----------------------------------

proc ::vmdai::vm::local_event {kind fields} {
    set ts [clock seconds]
    if {[dict exists $fields ts]} {
        set ts [dict get $fields ts]
        dict unset fields ts
    }
    return [dict create seq 0 ts $ts role system type state text "" \
        metadata [dict merge [dict create kind $kind] $fields]]
}

proc ::vmdai::vm::_clock_text {secs} {
    return [string trimleft [clock format $secs -format "%I:%M %p"] 0]
}

# The request was lost (restart) or ended while we were away: settle every
# running row and close the run, so the panel never stays busy.
proc ::vmdai::vm::_lose_request {sv status ts} {
    upvar 1 $sv S
    set req [dict get $S request]
    if {$req eq "" || ![dict exists $S runs $req]} { return {} }
    set ops {}
    dict for {k tool} [dict get $S tools] {
        if {[dict get $tool request_id] ne $req || [dict get $tool state] ne "running"} continue
        dict set S tools $k state unknown
        dict set S tools $k finished 1
        set label [expr {$status eq "lost" ? "connection lost · outcome unknown" : "outcome unknown"}]
        lappend ops [list tool.close $k unknown "" [dict create label $label error "" \
            inline "" preview {} output "" output_path "" total "" applied "" \
            failed_index "" failed_text "" late 0] ""]
        lappend ops [list run.chip [dict get $tool run] $k warn]
    }
    lappend ops {*}[_close_run S $req $status 0 [expr {[_secs $ts] - [dict get $S runs $req t0]}]]
    return $ops
}

proc ::vmdai::vm::_on_local {sv kind md ts} {
    upvar 1 $sv S
    switch -- $kind {
        local.connection {
            set new [_get $md state]
            # launching and connecting (a restart in progress) keep the last
            # state, so the ready that ends a restart still closes the loss.
            if {$new ni {reconnecting down ready}} { return {} }
            set old [dict get $S conn]
            # Never connected in this panel: not a lost connection, and conn
            # stays "" so a later real loss is still noted.
            if {$old eq "" && $new eq "down"} {
                return [list [list notice warn \
                    "Runtime unavailable at [_clock_text [_secs $ts]] \u00b7 your draft is kept"]]
            }
            dict set S conn $new
            if {$new eq $old} { return {} }
            switch -- $new {
                reconnecting - down {
                    if {$old in {reconnecting down}} { return {} }
                    return [list [list notice warn \
                        "Connection lost at [_clock_text [_secs $ts]] · your draft is kept"]]
                }
                ready {
                    if {$old ni {reconnecting down}} { return {} }
                    if {[_bool [_get $md request_lost false]]} {
                        set ops [list [list notice warn "Reconnected: request lost" retry]]
                        lappend ops {*}[_lose_request S lost $ts]
                        return $ops
                    }
                    return [list [list notice info "Reconnected"]]
                }
            }
            return {}
        }
        local.request_ended {
            set req [_get $md request_id]
            if {$req eq "" || $req ne [dict get $S request]} { return {} }
            set ops [list [list notice info "Request ended (details may be missing)"]]
            lappend ops {*}[_lose_request S ended $ts]
            return $ops
        }
        local.send_failed {
            set code [_get $md code other]
            if {$code eq "NO_MODEL"} {
                set ops [list [list error.card NO_MODEL "No model configured" \
                    [_get $md message] open_settings]]
            } else {
                set ops [list [list error.card $code "Message not sent" \
                    [_get $md message] [_default_action $code]]]
            }
            if {[dict get $S busy] && [dict get $S request] eq ""} {
                dict set S busy 0
                dict set S phase ""
                dict set S phase_t0 ""
                lappend ops [list status idle]
            }
            return $ops
        }
    }
    return {}
}

proc ::vmdai::vm::_plural {n word} {
    if {$n == 1} { return "1 $word" }
    return "$n ${word}s"
}

proc ::vmdai::vm::_finish_notes {run status tool_calls final_text_empty wrapped_up error} {
    set ops {}
    if {$status in {stuck max_turns} && !$wrapped_up && [_first_line $error] ne ""} {
        lappend ops [list notice info "The summary could not be written: [_first_line $error]"]
    }
    switch -- $status {
        cancelled { lappend ops [list notice info "Stopped"] }
        stuck     { lappend ops [list notice warn "Stopped: the model kept repeating the same step"] }
        max_turns {
            lappend ops [list notice warn "Stopped after [dict get $run max_turns] turns — reply 'continue'"]
        }
        complete {
            if {$final_text_empty} {
                lappend ops [list notice info "Finished after [_plural $tool_calls step]"]
            }
        }
    }
    return $ops
}

# ---- texts for the status bar and run header (P08-T03) ---------------------

proc ::vmdai::vm::_mmss {secs} {
    if {$secs < 0} { set secs 0 }
    return [format "%02d:%02d" [expr {$secs / 60}] [expr {$secs % 60}]]
}

proc ::vmdai::vm::status_text {stateVar now} {
    upvar 1 $stateVar S
    if {![dict get $S busy]} { return "" }
    set t0 [dict get $S phase_t0]
    if {$t0 eq ""} { return [dict get $S phase] }
    return "[dict get $S phase] · [_mmss [expr {[_secs $now] - $t0}]]"
}

proc ::vmdai::vm::_duration_text {secs} {
    if {$secs < 60} { return "$secs s" }
    return [format "%d min %d s" [expr {$secs / 60}] [expr {$secs % 60}]]
}

proc ::vmdai::vm::run_summary {status steps failed recovered duration_s max_turns} {
    set dur [_duration_text $duration_s]
    switch -- $status {
        cancelled { return "Stopped · [_plural $steps step]" }
        stuck     { return "Stopped (stuck) · [_plural $steps step]" }
        max_turns { return "Stopped at $max_turns turns" }
        lost      { return "Connection lost · [_plural $steps step]" }
        ended     { return "Ended · [_plural $steps step]" }
        running   { return "" }
        error {
            if {$failed > 0} { return "$failed failed · $dur" }
            return "Error · $dur"
        }
    }
    if {$failed > 0 && $recovered} { return "$failed failed, recovered · $dur" }
    if {$failed > 0} { return "$failed failed · $dur" }
    return "[_plural $steps step] · $dur"
}

proc ::vmdai::vm::stop_requested {stateVar} {
    upvar 1 $stateVar S
    if {![dict get $S busy] || [dict get $S stopping]} { return {} }
    dict set S stopping 1
    dict set S phase "Stopping…"
    dict set S phase_t0 ""
    return [list [list status busy "Stopping…" ""]]
}
