# syntax.tcl - Tcl syntax tokens for the step detail and ```tcl blocks.
# ChatVMD round 1, M3 (plan 10, P10-T02).  Pure Tcl: nothing here needs Tk at
# source time, so tclsh tests and CI can load it.  Adapted from the console
# prototype's syntax::tokens (docs/design/round1/prototypes/console/proto.tcl).

namespace eval ::vmdai::syntax {
    if {![info exists ::vmdai::syntax::CLASSES]} {
        set ::vmdai::syntax::CLASSES {cmd var str num brace opt cmt}
    }
}

# tokens code -> list of {start end class}, in order.  start/end are 0-based
# character offsets into code (end exclusive), counted across lines ("\n" is
# one character), so "$index + $start chars" addresses a token in a text
# widget.  Whitespace and plain arguments are not returned.  Every line starts
# in command position; "[" and ";" start a new command.
proc ::vmdai::syntax::tokens {code} {
    set out {}
    set base 0
    foreach line [split $code "\n"] {
        set len [string length $line]
        set pos 0
        set cmdpos 1
        while {$pos < $len} {
            # -start with \A avoids a per-token copy, so the scan is linear.
            set cls ""
            if {[regexp -start $pos {\A[ \t]+} $line m]} {
                # whitespace
            } elseif {$cmdpos && [regexp -start $pos {\A#.*} $line m]} {
                set cls cmt
            } elseif {[regexp -start $pos {\A\$(\{[^\}]*\}|[A-Za-z0-9_:]+(\([^\)]*\))?)} $line m]} {
                set cls var
                set cmdpos 0
            } elseif {[regexp -start $pos {\A\[} $line m]} {
                set cls brace
                set cmdpos 1
            } elseif {[regexp -start $pos {\A[\]\{\}]} $line m]} {
                set cls brace
                set cmdpos 0
            } elseif {[regexp -start $pos {\A;} $line m]} {
                set cmdpos 1
            } elseif {[regexp -start $pos {\A"(?:[^"\\]|\\.)*"?} $line m]} {
                set cls str
                set cmdpos 0
            } elseif {!$cmdpos && [regexp -start $pos {\A-?[0-9]+(?:\.[0-9]+)?(?=[\s\]\};]|$)} $line m]} {
                set cls num
            } elseif {!$cmdpos && [regexp -start $pos {\A-[A-Za-z][A-Za-z0-9_]*} $line m]} {
                set cls opt
            } elseif {[regexp -start $pos {\A[^\s\[\]\{\}\$;"]+} $line m]} {
                if {$cmdpos} {
                    set cls cmd
                }
                set cmdpos 0
            } else {
                set m [string index $line $pos]
                set cmdpos 0
            }
            set n [string length $m]
            if {$cls ne ""} {
                lappend out [list [expr {$base + $pos}] [expr {$base + $pos + $n}] $cls]
            }
            incr pos $n
        }
        incr base [expr {$len + 1}]
    }
    return $out
}

# highlight t start code: tag the tokens of code, which the caller has just
# inserted into text widget t at index start, with syn_<class>.  Colours come
# from ::vmdai::theme::syntax_tags.
proc ::vmdai::syntax::highlight {t start code} {
    set start [$t index $start]
    foreach tok [tokens $code] {
        foreach {s e cls} $tok break
        $t tag add syn_$cls "$start + $s chars" "$start + $e chars"
    }
}

# highlight_tag t tag: highlight every range of tag (the step detail tags its
# command bytes dcmd:<call_key>).  Works through the read-only proxy.
proc ::vmdai::syntax::highlight_tag {t tag} {
    foreach {a b} [$t tag ranges $tag] {
        highlight $t $a [$t get $a $b]
    }
    catch {::vmdai::theme::syntax_tags $t}
}
