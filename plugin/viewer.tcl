# viewer.tcl -- ChatVMD full-size snapshot viewer (Part B V4 "Snapshot card").
#
#   ::vmdai::viewer::open path    -> the viewer window, or "" if the image
#                                    cannot be decoded
#   ::vmdai::viewer::close        destroy it and free its photo
#   ::vmdai::viewer::open_external path, reveal path, save_copy path
#
# One viewer at a time: opening another image replaces the first. The image
# is shown whole, subsampled by an integer factor to fit 90% of the screen.
# Esc or the window's close button closes it. Tests set opt(map) 0 so the
# window is created but never mapped, and opt(external) to a command prefix
# that receives {open|reveal} path instead of the desktop.

namespace eval ::vmdai::viewer {
    variable opt
    if {![info exists opt]} { array set opt {map 1 external ""} }
    variable win
    if {![info exists win]} { set win .vmd_ai_viewer }
    variable photo
    if {![info exists photo]} { set photo "" }
}

proc ::vmdai::viewer::open {path} {
    variable opt
    variable win
    variable photo
    close
    if {[catch {image create photo -file $path} src]} { return "" }
    set w [image width $src]
    set h [image height $src]
    set maxw [expr {int([winfo screenwidth .] * 0.9)}]
    set maxh [expr {int([winfo screenheight .] * 0.9)}]
    set f [expr {max(1, int(ceil(max(double($w) / $maxw, double($h) / $maxh))))}]
    if {$f > 1} {
        set photo [image create photo]
        $photo copy $src -subsample $f $f
        image delete $src
    } else {
        set photo $src
    }
    toplevel $win
    wm withdraw $win
    wm title $win "ChatVMD — [file tail $path]"
    canvas $win.c -width [image width $photo] -height [image height $photo] \
        -highlightthickness 0 -borderwidth 0 -background [::vmdai::theme::c surface]
    $win.c create image 0 0 -anchor nw -image $photo
    pack $win.c -fill both -expand 1
    bind $win <Escape> ::vmdai::viewer::close
    wm protocol $win WM_DELETE_WINDOW ::vmdai::viewer::close
    if {$opt(map)} {
        wm deiconify $win
        raise $win
        focus $win.c
    }
    return $win
}

proc ::vmdai::viewer::close {} {
    variable win
    variable photo
    if {[winfo exists $win]} { destroy $win }
    if {$photo ne ""} {
        catch {image delete $photo}
        set photo ""
    }
}

proc ::vmdai::viewer::_desktop {how path} {
    variable opt
    if {$opt(external) ne ""} {
        return [uplevel #0 [list {*}$opt(external) $how $path]]
    }
    if {[tk windowingsystem] eq "aqua"} {
        set cmd [expr {$how eq "reveal" ? [list open -R $path] : [list open $path]}]
    } else {
        set target [expr {$how eq "reveal" ? [file dirname $path] : $path}]
        set cmd [list xdg-open $target]
    }
    if {[catch {exec {*}$cmd &} err]} {
        catch {::vmdai::config::log "viewer: $how $path failed: $err"}
    }
}

proc ::vmdai::viewer::open_external {path} { _desktop open $path }

proc ::vmdai::viewer::reveal {path} { _desktop reveal $path }

# "Save PNG…": copy the snapshot to a file the user picks.
proc ::vmdai::viewer::save_copy {path} {
    set dest [tk_getSaveFile -title "Save PNG" -defaultextension .png \
        -initialfile [file tail $path]]
    if {$dest eq ""} { return "" }
    file copy -force -- $path $dest
    return $dest
}
