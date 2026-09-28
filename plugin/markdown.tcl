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

# ---- Tk rendering (P10-T04) --------------------------------------------------
# t is a writable text widget command.  In the transcript that is the real
# widget behind the read-only proxy (a renamed command, not a window path);
# _window_of finds the window for the width and the <Configure> binding.

# configure_tags t: the md_* tags on text widget t (idempotent).  Colours are
# theme tokens, so a dark/light switch retints them with everything else.
proc ::vmdai::md::configure_tags {t} {
    set C ::vmdai::theme::c
    $t tag configure md_p -spacing3 8
    $t tag configure md_li -lmargin1 0 -lmargin2 18 -tabs {18 left} -spacing3 4
    $t tag configure md_marker -foreground [$C muted]
    $t tag configure md_h1 -font ChatH2 -spacing1 12 -spacing3 6
    $t tag configure md_h2 -font ChatH2 -spacing1 8 -spacing3 4
    $t tag configure md_b -font ChatBodyBold
    $t tag configure md_code -font ChatCode -background [$C icode_bg]
    $t tag configure md_codehdr -font ChatMeta -foreground [$C muted] \
        -background [$C code_bg] -lmargin1 12 -lmargin2 12 -spacing1 8 -spacing3 2
    $t tag configure md_copy -foreground [$C accent]
    # Code lines are tight; the block's last line carries md_pretail, i.e.
    # 8 px below the block (Part B V2 "Detail and code blocks. 8 vertical").
    $t tag configure md_pre -font ChatCode -background [$C code_bg] \
        -lmargin1 12 -lmargin2 12 -rmargin 12 -spacing1 0 -spacing2 0 -spacing3 0
    $t tag configure md_pretail -font ChatCode -background [$C code_bg] -spacing3 8
    catch {
        foreach tag {md_codehdr md_pre md_pretail} {
            $t tag configure $tag -lmargincolor [$C code_bg] -rmargincolor [$C code_bg]
        }
    }
    $t tag raise md_pretail md_pre
    foreach tag {md_code md_b md_h1 md_h2 md_marker md_copy} {
        $t tag raise $tag
    }
    catch {$t tag raise sel}
    $t tag bind md_copy <Enter> {%W configure -cursor hand2}
    $t tag bind md_copy <Leave> {%W configure -cursor {}}
    $t tag bind md_copy <1> {::vmdai::md::copy_at %W @%x,%y}
    set w [_window_of $t]
    if {$w ne ""} {
        if {[string first ::vmdai::md::retab [bind $w <Configure>]] < 0} {
            bind $w <Configure> {+::vmdai::md::retab %W}
        }
        retab $w
    }
}

# retab w: right-align each code header's "Copy" at the content edge of
# text window w (a window path; tag configure passes through the proxy).
proc ::vmdai::md::retab {w} {
    if {[catch {winfo width $w} px]} {
        return
    }
    set px [expr {$px - 2 * [$w cget -padx] - 2}]
    if {$px < 100} {
        set px 480
    }
    $w tag configure md_codehdr -tabs [list [expr {$px - 12}] right]
}

# _window_of t -> the window path of text widget command t, or "".  A
# renamed widget command is matched to its window by a probe mark, which the
# window path (the read-only proxy passes "mark names" through) also sees.
proc ::vmdai::md::_window_of {t} {
    variable win
    if {[winfo exists $t]} {
        return $t
    }
    if {[info exists win($t)] && [winfo exists $win($t)]} {
        return $win($t)
    }
    set probe md_probe[incr ::vmdai::md::seq]
    if {[catch {$t mark set $probe 1.0}]} {
        return ""
    }
    set found ""
    foreach w [_text_windows .] {
        if {![catch {$w mark names} marks] && [lsearch -exact $marks $probe] >= 0} {
            set found $w
            break
        }
    }
    $t mark unset $probe
    set win($t) $found
    return $found
}

proc ::vmdai::md::_text_windows {w} {
    set out {}
    if {[winfo class $w] eq "Text"} {
        lappend out $w
    }
    foreach c [winfo children $w] {
        set out [concat $out [_text_windows $c]]
    }
    return $out
}

# render_into t index text ?basetags?: insert the Markdown rendering of text
# into writable text widget command t at index.  Every inserted character also
# carries basetags.  Adds no trailing newline, so it can replace a plain
# "$t insert $index $text $basetags".  Returns the index after the insertion.
proc ::vmdai::md::render_into {t index text {basetags {}}} {
    configure_tags $t
    # A mark at "end" would sit after the widget's final newline; insert
    # before it instead, as "$t insert end" does.
    set index [$t index $index]
    if {[$t compare $index > "end - 1c"]} {
        set index [$t index "end - 1c"]
    }
    set mark md_ins[incr ::vmdai::md::seq]
    $t mark set $mark $index
    $t mark gravity $mark right
    set prev ""
    foreach span [spans $text] {
        foreach {kind body attrs} $span break
        if {$prev eq "code"} {
            # The newline after a code block carries its tint to the edge.
            $t insert $mark "\n" [concat $basetags md_pretail]
        } elseif {$prev ne ""} {
            $t insert $mark "\n" $basetags
        }
        set prev $kind
        set lstart [$t index "$mark linestart"]
        switch -- $kind {
            para {
                _inline $t $mark [dict get $attrs inline] $basetags
                $t tag add md_p $lstart $mark
            }
            heading {
                _inline $t $mark [dict get $attrs inline] $basetags
                $t tag add md_h[dict get $attrs level] $lstart $mark
            }
            item {
                $t insert $mark "[dict get $attrs marker]\t" [concat $basetags md_marker]
                _inline $t $mark [dict get $attrs inline] $basetags
                $t tag add md_li $lstart $mark
            }
            code {
                _code_block $t $mark $body [dict get $attrs lang] $basetags
            }
        }
    }
    set end [$t index $mark]
    $t mark unset $mark
    if {$prev eq "code" && [$t get $end] eq "\n"} {
        $t tag add md_pretail $end "$end + 1c"
    }
    return $end
}

proc ::vmdai::md::_inline {t mark inl tags} {
    foreach sp $inl {
        foreach {k s} $sp break
        switch -- $k {
            bold {
                $t insert $mark $s [concat $tags md_b]
            }
            code {
                # NBSP: Tk never wraps at U+00A0, so the span stays on one
                # display line (Part B V1, prototypes/lead/nbsp.tcl).
                $t insert $mark [string map [list " " "\u00a0"] $s] [concat $tags md_code]
            }
            default {
                $t insert $mark $s $tags
            }
        }
    }
}

proc ::vmdai::md::_code_block {t mark body lang tags} {
    set label [expr {$lang eq "" ? "code" : $lang}]
    set hdr [concat $tags md_codehdr]
    $t insert $mark $label $hdr "\t" $hdr "Copy" [concat $hdr md_copy] "\n" $hdr
    set start [$t index $mark]
    $t insert $mark $body [concat $tags md_pre]
    # The block's last line carries the 8 px below it; Tk takes a line's
    # spacing from its first character.
    $t tag add md_pretail "$mark linestart" $mark
    if {[string tolower $lang] eq "tcl"} {
        ::vmdai::syntax::highlight $t $start $body
        ::vmdai::theme::syntax_tags $t
    }
}

# copy_at w index: copy the code block whose header line holds index.
proc ::vmdai::md::copy_at {w index} {
    set next [$w index "$index linestart + 1 line"]
    set r [$w tag nextrange md_pre $next]
    if {$r eq "" || [$w compare [lindex $r 0] != $next]} {
        return
    }
    copy [$w get [lindex $r 0] [lindex $r 1]]
}

# copy code: put code on the clipboard, through the panel's clipboard seam
# when it is loaded (the Tk tests stub it, so they never touch the real
# pasteboard); plain Tk clipboard otherwise.
proc ::vmdai::md::copy {code} {
    if {[llength [info commands ::vmdai::panel::_set_clipboard]]
            && ![catch {::vmdai::panel::_set_clipboard $code}]} {
        return
    }
    clipboard clear
    clipboard append -- $code
}

# plain_text s -> s with the NBSPs of rendered inline code turned back into
# spaces, for anything that copies transcript text to the clipboard.
proc ::vmdai::md::plain_text {s} {
    return [string map [list "\u00a0" " "] $s]
}
