# scripts/install_plugin.tcl - load ChatVMD when VMD starts, by adding one
# marked block to your own VMD startup file, ~/.vmdrc (spec 2h).
#
#   tclsh scripts/install_plugin.tcl               show the block, ask, add it
#   tclsh scripts/install_plugin.tcl --yes         add it without asking
#   tclsh scripts/install_plugin.tcl --dry-run     only show what would change
#   tclsh scripts/install_plugin.tcl --uninstall   remove the block again
#   options: --vmdrc PATH (another startup file), --plugin-dir DIR
#
# The block sits between "# >>> vmdai >>>" and "# <<< vmdai <<<". Running the
# installer again replaces it in place, so repeating it is safe. The rest of
# the file is kept byte for byte, and the first change saves a copy next to
# it as .vmdrc.vmdai-backup. VMD reads only the first .vmdrc it finds (./,
# then ~, then $VMDDIR), so when ~/.vmdrc does not exist yet the block also
# plays VMD's own default startup file, keeping VMD's usual menus and lights.
# Works with Tcl 8.5 and later.

namespace eval ::installer {
    variable begin "# >>> vmdai >>>"
    variable end "# <<< vmdai <<<"
    variable defaults_line {if {[info exists env(VMDDIR)] && [file readable [file join $env(VMDDIR) .vmdrc]]} { play [file join $env(VMDDIR) .vmdrc] }}
}

proc ::installer::usage {} {
    puts stderr "usage: tclsh install_plugin.tcl ?--yes? ?--dry-run? ?--uninstall? ?--vmdrc PATH? ?--plugin-dir DIR?"
    exit 2
}

# The file's bytes (the empty string when it does not exist).
proc ::installer::read_bytes {path} {
    if {![file exists $path]} {
        return ""
    }
    set fh [open $path r]
    fconfigure $fh -translation binary
    set data [read $fh]
    close $fh
    return $data
}

# Write bytes through a temporary file and a rename, keeping permissions.
proc ::installer::write_bytes {path data} {
    set tmp "$path.vmdai-tmp"
    set fh [open $tmp w]
    fconfigure $fh -translation binary
    puts -nonewline $fh $data
    close $fh
    if {[file exists $path] && $::tcl_platform(platform) eq "unix"} {
        catch {file attributes $tmp -permissions [file attributes $path -permissions]}
    }
    file rename -force $tmp $path
}

# The block, as UTF-8 bytes. The plugin path is quoted as one Tcl word.
proc ::installer::block {plugin_dir with_defaults} {
    variable begin
    variable end
    variable defaults_line
    set lines [list $begin \
        "# ChatVMD (Extensions > VMD AI). Added by scripts/install_plugin.tcl;" \
        "# remove it with: tclsh scripts/install_plugin.tcl --uninstall"]
    if {$with_defaults} {
        lappend lines $defaults_line
    }
    lappend lines "if \{\[catch \{lappend auto_path [list $plugin_dir]; package require vmd_ai 2.0\} vmdai_err\]\} \{ puts \"ChatVMD did not load: \$vmdai_err\" \}; unset vmdai_err"
    lappend lines $end
    return [encoding convertto utf-8 "[join $lines \n]\n"]
}

# {first last}: byte range of the block including its final newline, or
# {-1 -1} when the file has none.
proc ::installer::find_block {data} {
    variable begin
    variable end
    set first [string first $begin $data]
    if {$first < 0} {
        return {-1 -1}
    }
    set stop [string first $end $data $first]
    if {$stop < 0} {
        error "found \"$begin\" without \"$end\"; fix the file by hand"
    }
    set last [expr {$stop + [string length $end] - 1}]
    if {[string index $data [expr {$last + 1}]] eq "\n"} {
        incr last
    }
    return [list $first $last]
}

proc ::installer::confirm {question} {
    puts -nonewline "$question \[y/N\] "
    flush stdout
    if {[gets stdin answer] < 0} {
        return 0
    }
    return [expr {[string tolower [string trim $answer]] in {y yes}}]
}

proc ::installer::main {argv} {
    variable defaults_line
    set yes 0
    set dry 0
    set uninstall 0
    set vmdrc [file join $::env(HOME) .vmdrc]
    set here [file dirname [file normalize [info script]]]
    set plugin_dir [file normalize [file join $here .. plugin]]
    while {[llength $argv]} {
        set argv [lassign $argv arg]
        switch -- $arg {
            --yes { set yes 1 }
            --dry-run { set dry 1 }
            --uninstall { set uninstall 1 }
            --vmdrc {
                if {![llength $argv]} { usage }
                set argv [lassign $argv vmdrc]
            }
            --plugin-dir {
                if {![llength $argv]} { usage }
                set argv [lassign $argv plugin_dir]
                set plugin_dir [file normalize $plugin_dir]
            }
            default { usage }
        }
    }
    set vmdrc [file normalize $vmdrc]
    set old [read_bytes $vmdrc]
    lassign [find_block $old] first last
    if {$uninstall} {
        if {$first < 0} {
            puts "ChatVMD is not installed in $vmdrc; nothing changed."
            return 0
        }
        set before [string range $old 0 [expr {$first - 1}]]
        # Drop the blank line the installer put in front of the block.
        if {[string range $before end-1 end] eq "\n\n"} {
            set before [string range $before 0 end-1]
        }
        set new "$before[string range $old [expr {$last + 1}] end]"
        puts "ChatVMD will remove its block from $vmdrc."
        if {$dry} {
            return 0
        }
        if {!$yes && ![confirm "Remove it?"]} {
            puts "Nothing changed."
            return 1
        }
        if {[string trim $new] eq ""} {
            file delete $vmdrc
            puts "Removed ChatVMD from $vmdrc (the file only held ChatVMD, so it was deleted)."
        } else {
            write_bytes $vmdrc $new
            puts "Removed ChatVMD from $vmdrc."
        }
        return 0
    }
    if {![file exists [file join $plugin_dir pkgIndex.tcl]]} {
        puts stderr "No pkgIndex.tcl in $plugin_dir; pass --plugin-dir with the ChatVMD plugin folder."
        return 1
    }
    set exists [file exists $vmdrc]
    if {$first >= 0} {
        set current [string range $old $first $last]
        set with_defaults [expr {[string first $defaults_line $current] >= 0}]
        set block [block $plugin_dir $with_defaults]
        if {$current eq $block} {
            puts "ChatVMD is already installed in $vmdrc; nothing changed."
            return 0
        }
        set new "[string range $old 0 [expr {$first - 1}]]$block[string range $old [expr {$last + 1}] end]"
    } else {
        set block [block $plugin_dir [expr {!$exists}]]
        if {$old eq ""} {
            set sep ""
        } elseif {[string index $old end] eq "\n"} {
            set sep "\n"
        } else {
            set sep "\n\n"
        }
        set new "$old$sep$block"
    }
    puts "ChatVMD will add these lines to $vmdrc:\n"
    puts [encoding convertfrom utf-8 $block]
    if {$dry} {
        return 0
    }
    if {!$yes && ![confirm "Add them?"]} {
        puts "Nothing changed."
        return 1
    }
    if {$exists && ![file exists "$vmdrc.vmdai-backup"]} {
        file copy $vmdrc "$vmdrc.vmdai-backup"
    }
    write_bytes $vmdrc $new
    puts "Installed ChatVMD in $vmdrc. Start VMD and open Extensions > VMD AI."
    return 0
}

if {[info exists ::argv0] && [file normalize $::argv0] eq [file normalize [info script]]} {
    if {[catch {::installer::main $::argv} code]} {
        puts stderr "install_plugin: $code"
        exit 1
    }
    exit $code
}
