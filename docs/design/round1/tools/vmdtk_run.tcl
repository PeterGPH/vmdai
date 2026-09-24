# Load VMD.app's bundled Tk 8.6 into tclsh, then source the prototype given as argv[0].
set ::tk_library /Applications/VMD.app/Contents/Frameworks/Tk.framework/Versions/8.6/Resources/Scripts
load /Applications/VMD.app/Contents/Frameworks/Tk.framework/Versions/8.6/Tk Tk
set ::argv0 [lindex $::argv 0]
set ::argv [lrange $::argv 1 end]
set ::argc [llength $::argv]
source $::argv0
vwait forever
