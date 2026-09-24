fconfigure stdout -buffering line
wm withdraw .
set out [open /tmp/chatvmd_nbsp.out w]
puts $out "tk=[info patchlevel] isspace nbsp=[string is space  ]"
text .t -width 20 -wrap word -font {Menlo 12}; pack .t; update; puts $out "w=[winfo width .t]"
foreach {label sep} [list plain " " nbsp " "] {
  foreach pre {"aaaa bbbb cccc " "aaaa bbbb ccccc " "aaaa bbbb cccccc " "aaaa bbb "} {
    .t delete 1.0 end
    .t insert end $pre {} "measure${sep}rgyr" code " tail" {}
    update idletasks
    set r [.t tag ranges code]
    set n [.t count -displaylines [lindex $r 0] [lindex $r 1]]
    puts $out "$label pre=[string length $pre] code_crosses_lines=$n"
  }
}
close $out
exit
