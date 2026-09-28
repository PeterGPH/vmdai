# markdown.tcl - the minimal Markdown subset of Part B V4, rendered only when
# a block is sealed.  ChatVMD round 1, M3 (plan 10, P10-T03 and P10-T04).
#
#   ::vmdai::md::spans text                            block spans (no Tk)
#   ::vmdai::md::render_into t index text ?basetags?   Tk rendering (P10-T04)
#
# Supported: **bold**, `code`, "- " / "* " / "1. " list items, "# " / "## "
# headings and ``` fenced code blocks.  Everything else, including an
# unclosed ``` or **, stays literal text.  Sourcing this file needs no Tk.

namespace eval ::vmdai::md {
    if {![info exists ::vmdai::md::seq]} { set ::vmdai::md::seq 0 }
}

# inline s -> list of {kind text {}} with kind text|bold|code.
proc ::vmdai::md::inline {s} {
    set out {}
    while {[regexp -indices {\*\*([^*]+)\*\*|`([^`]+)`} $s all b c]} {
        foreach {a0 a1} $all break
        if {$a0 > 0} {
            lappend out [list text [string range $s 0 [expr {$a0 - 1}]] {}]
        }
        if {[lindex $b 0] >= 0} {
            lappend out [list bold [string range $s [lindex $b 0] [lindex $b 1]] {}]
        } else {
            lappend out [list code [string range $s [lindex $c 0] [lindex $c 1]] {}]
        }
        set s [string range $s [expr {$a1 + 1}] end]
    }
    if {$s ne ""} {
        lappend out [list text $s {}]
    }
    return $out
}

# spans text -> list of block spans {kind text attrs}, in document order:
#   {para    <raw> {inline <inl>}}               lines joined with one space
#   {item    <raw> {marker <m> inline <inl>}}    <m> is \u2022 or "<n>."
#   {heading <raw> {level 1|2 inline <inl>}}
#   {code    <body> {lang <lang>}}               body is byte-exact
# where <inl> is the list [inline <raw>] returns.
proc ::vmdai::md::spans {text} {
    set lines [split [string map [list "\r\n" "\n"] $text] "\n"]
    set n [llength $lines]
    set out {}
    set para {}
    for {set i 0} {$i < $n} {incr i} {
        set line [lindex $lines $i]
        if {[regexp {^\s*```\s*([A-Za-z0-9_+-]*)\s*$} $line -> lang]} {
            set close -1
            for {set j [expr {$i + 1}]} {$j < $n} {incr j} {
                if {[regexp {^\s*```\s*$} [lindex $lines $j]]} {
                    set close $j
                    break
                }
            }
            if {$close >= 0} {
                _flush out para
                set body [join [lrange $lines [expr {$i + 1}] [expr {$close - 1}]] "\n"]
                lappend out [list code $body [list lang $lang]]
                set i $close
                continue
            }
            # An unclosed fence is not a code block: the line stays literal.
        }
        if {[regexp {^(#{1,2})\s+(.*)$} $line -> hashes head]} {
            _flush out para
            lappend out [list heading $head \
                [list level [string length $hashes] inline [inline $head]]]
            continue
        }
        if {[regexp {^\s*[-*]\s+(.*)$} $line -> item]} {
            _flush out para
            lappend out [list item $item [list marker "\u2022" inline [inline $item]]]
            continue
        }
        if {[regexp {^\s*([0-9]+)[.)]\s+(.*)$} $line -> num item]} {
            _flush out para
            lappend out [list item $item [list marker "$num." inline [inline $item]]]
            continue
        }
        if {[string trim $line] eq ""} {
            _flush out para
            continue
        }
        lappend para [string trim $line]
    }
    _flush out para
    return $out
}

proc ::vmdai::md::_flush {outVar paraVar} {
    upvar 1 $outVar out $paraVar para
    if {[llength $para] == 0} {
        return
    }
    set raw [join $para " "]
    lappend out [list para $raw [list inline [inline $raw]]]
    set para {}
}
