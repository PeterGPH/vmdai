# config.tcl - paths, Python resolution, attach target, plugin.json, logs
# (spec 2d, 2h). No Tk. Loaded first; the other modules call into it.

namespace eval ::vmdai::config {
    variable plugin_dir [file dirname [file normalize [info script]]]
    variable runtime_main [file normalize [file join $plugin_dir .. runtime main.py]]

    # Timeouts and intervals (ms).
    variable request_timeout_ms 3000
    variable poll_ms 250
    variable ready_timeout_ms 20000
    variable shutdown_kill_ms 1500
    variable respawn_reset_ms 60000

    # plugin.json defaults (spec 2f Files).
    variable plugin_defaults [dict create version 1 python "" appearance system \
        expand_steps 0 geometry ""]
}

proc ::vmdai::config::home {} {
    if {[info exists ::env(HOME)] && $::env(HOME) ne ""} {
        return [file normalize $::env(HOME)]
    }
    return [file normalize ~]
}

proc ::vmdai::config::plugin_json_path {} {
    return [file join [home] .vmdai plugin.json]
}

proc ::vmdai::config::log_path {} {
    return [file join [home] .vmdai logs runtime.log]
}

proc ::vmdai::config::plugin_log_path {} {
    return [file join [home] .vmdai logs plugin.log]
}

proc ::vmdai::config::token_file_path {port} {
    return [file join [home] .vmdai run runtime-$port.json]
}

# Append one timestamped line to ~/.vmdai/logs/plugin.log. Never throws.
proc ::vmdai::config::log {msg} {
    catch {
        set path [plugin_log_path]
        file mkdir [file dirname $path]
        if {[file exists $path] && [file size $path] > 1048576} {
            file rename -force $path $path.1
        }
        set fh [open $path a]
        fconfigure $fh -encoding utf-8 -translation lf
        puts $fh "[clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}] $msg"
        close $fh
    }
    return
}

# Load json 1.1.2 from plugin/lib/json unless some json is already loaded.
proc ::vmdai::config::require_json {} {
    variable plugin_dir
    if {![catch {package present json} version]} {
        return $version
    }
    set dir [file join $plugin_dir lib json]
    if {[lsearch -exact $::auto_path $dir] < 0} {
        lappend ::auto_path $dir
    }
    return [package require -exact json 1.1.2]
}

# One JSON string literal, ASCII only. Same escaping as net::json_string
# (P06-T03); kept here because config.tcl loads before net.tcl.
proc ::vmdai::config::_json_quote {s} {
    set map [list "\\" "\\\\" "\"" "\\\""]
    for {set i 0} {$i < 32} {incr i} {
        lappend map [format %c $i] [format "\\u%04x" $i]
    }
    set s [string map $map $s]
    if {[regexp {[^\u0000-\u007f]} $s]} {
        set wide {}
        foreach ch [lsort -unique [regexp -all -inline {[^\u0000-\u007f]} $s]] {
            lappend wide $ch [format "\\u%04x" [scan $ch %c]]
        }
        set s [string map $wide $s]
    }
    return "\"$s\""
}

proc ::vmdai::config::load_plugin_settings {} {
    variable plugin_defaults
    set settings $plugin_defaults
    set path [plugin_json_path]
    if {![file exists $path]} {
        return $settings
    }
    if {[catch {
        set fh [open $path r]
        fconfigure $fh -encoding utf-8
        set text [read $fh]
        close $fh
        require_json
        set decoded [::json::json2dict $text]
        dict size $decoded
    } err]} {
        log "plugin.json unreadable, using defaults: $err"
        return $settings
    }
    dict for {key value} $decoded {
        dict set settings $key $value
    }
    return $settings
}

proc ::vmdai::config::save_plugin_settings {settings} {
    set parts {}
    dict for {key value} $settings {
        switch -- $key {
            version {
                if {![string is integer -strict $value]} { set value 1 }
                set json $value
            }
            expand_steps {
                set json [expr {[string is true -strict $value] ? "true" : "false"}]
            }
            default {
                set json [_json_quote $value]
            }
        }
        lappend parts "[_json_quote $key]:$json"
    }
    set path [plugin_json_path]
    file mkdir [file dirname $path]
    set tmp "$path.[pid].tmp"
    set fh [open $tmp w]
    fconfigure $fh -encoding ascii -translation lf
    puts -nonewline $fh "\{[join $parts ,]\}"
    close $fh
    file rename -force $tmp $path
    return $path
}

# Python for the owned runtime: VMD_AI_PYTHON, then plugin.json python, then
# `auto_execok python3`; returned absolute, or "" when none is found.
proc ::vmdai::config::resolve_python {} {
    set candidates {}
    if {[info exists ::env(VMD_AI_PYTHON)] && [string trim $::env(VMD_AI_PYTHON)] ne ""} {
        lappend candidates [string trim $::env(VMD_AI_PYTHON)]
    } else {
        set configured ""
        catch {set configured [string trim [dict get [load_plugin_settings] python]]}
        if {$configured ne ""} {
            lappend candidates $configured
        }
    }
    lappend candidates python3
    foreach candidate $candidates {
        if {[file pathtype $candidate] eq "relative" && [llength [file split $candidate]] == 1} {
            set found [auto_execok $candidate]
            if {$found ne ""} {
                return [file normalize [lindex $found 0]]
            }
            continue
        }
        return [file normalize $candidate]
    }
    return ""
}

# VMD_AI_ATTACH=host:port (or host, with the port from VMD_AI_PORT, else 8765).
# Returns "" when unset, else {host port}; errors on a malformed value.
proc ::vmdai::config::attach_target {} {
    if {![info exists ::env(VMD_AI_ATTACH)] || [string trim $::env(VMD_AI_ATTACH)] eq ""} {
        return ""
    }
    set value [string trim $::env(VMD_AI_ATTACH)]
    if {[regexp {^([^:]+):([0-9]+)$} $value -> host port]} {
        # explicit port
    } elseif {[regexp {^[^:]+$} $value]} {
        set host $value
        set port 8765
        if {[info exists ::env(VMD_AI_PORT)] && [string is integer -strict $::env(VMD_AI_PORT)]} {
            set port $::env(VMD_AI_PORT)
        }
    } else {
        error "VMD_AI_ATTACH must be host:port (got \"$value\")"
    }
    set host [string tolower $host]
    if {$host ni {127.0.0.1 localhost}} {
        error "VMD_AI_ATTACH must name 127.0.0.1 or localhost (got \"$value\")"
    }
    scan $port %d port
    if {$port < 1 || $port > 65535} {
        error "VMD_AI_ATTACH port out of range (got \"$value\")"
    }
    return [list $host $port]
}
