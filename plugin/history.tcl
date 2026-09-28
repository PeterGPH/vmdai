# history.tcl - the History picker (Part B V4 "History"), ported to ttk.
#
# A titled transient dialog, 560x400, with a ttk::treeview of the newest 50
# chats (Title, Updated, Messages; the first row selected). Return or a
# double-click resumes, Esc cancels. A chat that another VMD window holds
# (CHAT_LOCKED) is reported inline and the dialog stays open. History is
# unavailable while a request runs.

namespace eval ::vmdai::history {
    variable win .vmd_ai_history
    variable LIMIT 50
    variable LOCKED_TEXT "Open in another VMD window"
    variable BUSY_TEXT "History is unavailable while a request is running"
    if {![info exists ::vmdai::history::rows]} { variable rows {} }
    if {![info exists ::vmdai::history::gen]} { variable gen 0 }
}

proc ::vmdai::history::_dget {d key default} {
    if {[catch {dict exists $d $key} has] || !$has} { return $default }
    set value [dict get $d $key]
    if {$value eq "null"} { return $default }
    return $value
}

proc ::vmdai::history::tree {} {
    variable win
    return $win.bg.tv
}

proc ::vmdai::history::message {} {
    variable win
    if {![winfo exists $win.bg.msg]} { return "" }
    return [$win.bg.msg cget -text]
}

proc ::vmdai::history::_message {text} {
    variable win
    if {[winfo exists $win.bg.msg]} { $win.bg.msg configure -text $text }
}

proc ::vmdai::history::open {} {
    variable win
    variable BUSY_TEXT
    if {[::vmdai::panel::bridge_busy]} {
        if {[winfo exists $::vmdai::panel::win]} { ::vmdai::statusbar::flash $BUSY_TEXT 3000 }
        return ""
    }
    if {![winfo exists $win]} { _build }
    _message ""
    fetch
    ::vmdai::panel::present $win
    return $win
}

proc ::vmdai::history::close {} {
    variable win
    if {[winfo exists $win]} { ::destroy $win }
}

proc ::vmdai::history::_build {} {
    variable win
    set C ::vmdai::theme::c
    toplevel $win
    wm withdraw $win
    wm title $win "ChatVMD History"
    if {[winfo exists $::vmdai::panel::win]} { wm transient $win $::vmdai::panel::win }
    wm geometry $win 560x400
    wm minsize $win 380 240
    wm protocol $win WM_DELETE_WINDOW ::vmdai::history::close
    set f $win.bg
    ttk::frame $f -padding {12 12 12 10}
    pack $f -fill both -expand 1
    ttk::treeview $f.tv -columns {title updated messages} -show headings -selectmode browse
    $f.tv heading title -text Title -anchor w
    $f.tv heading updated -text Updated -anchor w
    $f.tv heading messages -text Messages -anchor e
    $f.tv column title -width 300 -stretch 1 -anchor w
    $f.tv column updated -width 120 -stretch 0 -anchor w
    $f.tv column messages -width 80 -stretch 0 -anchor e
    ttk::scrollbar $f.sb -orient vertical -command [list $f.tv yview]
    $f.tv configure -yscrollcommand [list $f.sb set]
    ttk::label $f.msg -text "" -font ChatMeta -foreground [$C warn]
    ttk::frame $f.foot
    ttk::button $f.foot.cancel -text Cancel -command ::vmdai::history::close
    ttk::button $f.foot.open -text Open -default active -command ::vmdai::history::resume_selected
    pack $f.foot.open $f.foot.cancel -side right -padx {8 0}
    grid $f.tv   -row 0 -column 0 -sticky nsew
    grid $f.sb   -row 0 -column 1 -sticky ns
    grid $f.msg  -row 1 -column 0 -columnspan 2 -sticky w -pady {6 0}
    grid $f.foot -row 2 -column 0 -columnspan 2 -sticky ew -pady {8 0}
    grid rowconfigure $f 0 -weight 1
    grid columnconfigure $f 0 -weight 1
    bind $f.tv <Double-1> {::vmdai::history::resume_selected; break}
    bind $win <Return> {::vmdai::history::resume_selected; break}
    bind $win <KP_Enter> {::vmdai::history::resume_selected; break}
    bind $win <Escape> {::vmdai::history::close; break}
}

proc ::vmdai::history::fetch {} {
    variable LIMIT
    variable gen
    incr gen
    ::vmdai::net::call chat.history.list [list offset i 0 limit i $LIMIT] \
        [list ::vmdai::history::_on_list $gen]
}

proc ::vmdai::history::_newer {a b} {
    return [string compare [_dget $b updated_at ""] [_dget $a updated_at ""]]
}

proc ::vmdai::history::_on_list {g form args} {
    variable gen
    variable win
    variable rows
    variable LIMIT
    if {$g != $gen || ![winfo exists $win]} { return }
    if {$form ne "ok"} {
        if {$form eq "rpc_error"} {
            _message "Could not list chats: [lindex $args 1]"
        } else {
            _message "Could not list chats: the runtime did not answer ([lindex $args 0])."
        }
        return
    }
    set items {}
    catch {set items [dict get [lindex $args 0] items]}
    set items [lsort -command ::vmdai::history::_newer $items]
    set rows [lrange $items 0 [expr {$LIMIT - 1}]]
    set tv [tree]
    $tv delete [$tv children {}]
    set now [clock seconds]
    set i 0
    foreach item $rows {
        set title [_dget $item title "New Chat"]
        $tv insert {} end -id row$i -values [list [ellipsize_middle $title TkDefaultFont 290] \
            [format_updated [_dget $item updated_at ""] $now] [_dget $item message_count 0]]
        incr i
    }
    if {[llength $rows]} {
        $tv selection set row0
        $tv focus row0
    } else {
        _message "No chats yet."
    }
}

# "Today 14:32", "Yesterday 09:10", "Mon 08:00" (within 6 days), "Sep 3"
# (this year) or "2025-12-31"; anything unparseable is shown as-is.
proc ::vmdai::history::format_updated {iso now} {
    if {[catch {clock scan $iso -format {%Y-%m-%dT%H:%M:%SZ} -timezone :UTC} t]} { return $iso }
    set day [clock format $t -format %Y-%m-%d]
    set hm [clock format $t -format %H:%M]
    if {$day eq [clock format $now -format %Y-%m-%d]} { return "Today $hm" }
    if {$day eq [clock format [clock add $now -1 day] -format %Y-%m-%d]} { return "Yesterday $hm" }
    if {$t <= $now && $now - $t < 6 * 86400} { return "[clock format $t -format %a] $hm" }
    if {[clock format $t -format %Y] eq [clock format $now -format %Y]} {
        set md [clock format $t -format "%b %d"]
        regsub { 0([0-9])$} $md { \1} md
        return $md
    }
    return $day
}

# Middle ellipsis by binary search, so both ends of a long title stay visible.
proc ::vmdai::history::ellipsize_middle {s font px} {
    if {[font measure $font $s] <= $px} { return $s }
    set lo 1
    set hi [expr {[string length $s] - 1}]
    set best "\u2026"
    while {$lo <= $hi} {
        set keep [expr {($lo + $hi) / 2}]
        set head [expr {($keep + 1) / 2}]
        set tail [expr {$keep - $head}]
        set candidate "[string range $s 0 [expr {$head - 1}]]\u2026"
        if {$tail > 0} { append candidate [string range $s end-[expr {$tail - 1}] end] }
        if {[font measure $font $candidate] <= $px} {
            set best $candidate
            set lo [expr {$keep + 1}]
        } else {
            set hi [expr {$keep - 1}]
        }
    }
    return $best
}

proc ::vmdai::history::resume_selected {} {
    variable rows
    variable win
    if {![winfo exists $win]} { return }
    set selected [lindex [[tree] selection] 0]
    if {$selected eq ""} { return }
    set chat_id [_dget [lindex $rows [string range $selected 3 end]] chat_id ""]
    if {$chat_id eq ""} { return }
    _message ""
    ::vmdai::bridge::resume $chat_id [list ::vmdai::history::_on_resume $chat_id]
}

proc ::vmdai::history::_on_resume {chat_id form args} {
    variable win
    variable LOCKED_TEXT
    if {![winfo exists $win]} { return }
    if {$form eq "ok"} {
        close
        return
    }
    if {$form eq "rpc_error"} {
        switch -- [lindex $args 0] {
            CHAT_LOCKED      { _message $LOCKED_TEXT }
            REQUEST_CONFLICT { _message "A request is running; stop it before opening another chat." }
            NOT_FOUND        { _message "This chat no longer exists." }
            default          { _message "Could not open this chat: [lindex $args 1]" }
        }
        return
    }
    _message "Could not open this chat: the runtime did not answer ([lindex $args 0])."
}
