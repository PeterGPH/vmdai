# load_docking.tcl
# Receptor + ligand-pose loader for the vmd-docking-viz skill.
#
# Public procs:
#   vmdai::detect_format <path>             -> pdbqt | pdb | sdf | mol2 | unknown
#   vmdai::load_format <path>               -> format VMD should be told to use
#                                              (handles pdbqt -> pdb fallback when
#                                              the pdbqt molfile plugin is missing,
#                                              which is common on macOS ARM64)
#   vmdai::load_receptor <path>             -> molid
#   vmdai::load_poses <path_or_glob>        -> molid (each pose becomes one frame)
#   vmdai::load_docking <rec> <poses>       -> dict with rec_id, lig_id, npose
#
# All procs print one progress line per major action.

namespace eval vmdai {}

proc vmdai::detect_format {path} {
    set ext [string tolower [file extension $path]]
    switch -- $ext {
        ".pdbqt" { return "pdbqt" }
        ".pdb"   { return "pdb"   }
        ".sdf"   { return "sdf"   }
        ".mol2"  { return "mol2"  }
        default  { return "unknown" }
    }
}

# Whether the requested molfile plugin is registered with this VMD build.
# `vmdinfo plugins` is not universally available, so we fall back to a
# best-effort probe via `mol pluginread`.
proc vmdai::has_plugin {fmt} {
    if {[catch {mol pluginread} plugs] == 0} {
        if {[lsearch -exact $plugs $fmt] >= 0} { return 1 }
    }
    # Heuristic: VMD on macOS ARM64 ships pdb but often not pdbqt.
    if {$fmt eq "pdb" || $fmt eq "sdf" || $fmt eq "mol2"} { return 1 }
    if {$fmt eq "pdbqt"} { return 0 }
    return 1
}

# Returns the file-type string to hand to `mol new ... type <type>`.
# Drops to a graceful fallback if the native plugin is missing — PDBQT is a
# PDB superset and VMD's pdb plugin reads it correctly enough for viz.
proc vmdai::load_format {path} {
    set fmt [vmdai::detect_format $path]
    if {$fmt eq "pdbqt" && ![vmdai::has_plugin pdbqt]} {
        puts "vmdai: pdbqt plugin missing, loading $path as plain pdb"
        return "pdb"
    }
    return $fmt
}

proc vmdai::load_receptor {path} {
    if {![file exists $path]} {
        error "vmdai::load_receptor: file not found: $path"
    }
    set fmt [vmdai::detect_format $path]
    if {$fmt eq "unknown"} {
        error "vmdai::load_receptor: unsupported format for $path"
    }
    set load_fmt [vmdai::load_format $path]
    set molid [mol new $path type $load_fmt waitfor all]
    mol rename $molid "receptor"
    set sel [atomselect $molid "all"]
    set n [$sel num]
    $sel delete
    puts "vmdai: receptor loaded ($n atoms, molid=$molid, fmt=$fmt, loaded_as=$load_fmt)"
    return $molid
}

# Accepts either a single multi-pose file (PDBQT/SDF/multi-MODEL PDB)
# or a glob pattern matching one file per pose (e.g. pose_*.pdb).
proc vmdai::load_poses {pattern} {
    set files [glob -nocomplain $pattern]
    if {[llength $files] == 0} {
        if {[file exists $pattern]} {
            set files [list $pattern]
        } else {
            error "vmdai::load_poses: no files matched $pattern"
        }
    }
    set first [lindex [lsort $files] 0]
    set fmt [vmdai::detect_format $first]
    if {$fmt eq "unknown"} {
        error "vmdai::load_poses: unsupported format for $first"
    }
    set load_fmt [vmdai::load_format $first]
    set molid [mol new $first type $load_fmt waitfor all]
    mol rename $molid "poses"

    foreach f [lsort $files] {
        if {$f eq $first} { continue }
        set f_load_fmt [vmdai::load_format $f]
        mol addfile $f type $f_load_fmt molid $molid waitfor all
    }
    set npose [molinfo $molid get numframes]
    puts "vmdai: loaded $npose pose(s) from [llength $files] file(s) into molid=$molid (fmt=$fmt, loaded_as=$load_fmt)"
    return $molid
}

proc vmdai::load_docking {receptor_path poses_pattern} {
    set rec_id [vmdai::load_receptor $receptor_path]
    set lig_id [vmdai::load_poses $poses_pattern]
    set npose [molinfo $lig_id get numframes]
    return [dict create rec_id $rec_id lig_id $lig_id npose $npose]
}
