# tests/tcl/t_race.tcl - the New Chat / Resume race (P06-T11; spec 2d Epoch,
# 6 Bridge integration). Sourced by driver.tcl for VMDAI_SCENARIO=race.
#
# Today's bridge nests vwait inside every RPC, so a poll that fires during
# New Chat writes the old session's after_seq over the new one. Here New
# Chat and Resume are issued back to back while a poll is due: they must run
# one after the other, replies of the old session must be dropped, and the
# next request must arrive whole, with no event seen twice.

proc scenario_race {} {
    connect
    ask "First question"
    set chat_a [bstate chat_id]
    set first_session [bstate session_id]
    ::vmdai::bridge::poll_now
    ::vmdai::bridge::new_chat
    ::vmdai::bridge::resume $chat_a
    wait_for [list expr "!\$::vmdai::bridge::op_busy && \[llength \$::vmdai::bridge::op_queue\] == 0
        && \[bstate chat_id\] eq {$chat_a} && \[bstate session_id\] ne {$first_session}"] \
        10000 "New Chat then Resume"
    set mark [llength $::events]
    ask "Second question"
    set seqs {}
    set text ""
    foreach ev [lrange $::events $mark end] {
        lappend seqs [dict get $ev seq]
        if {[dict get $ev type] eq "chunk"} { append text [dict get $ev text] }
    }
    set ordered [expr {$seqs eq [lsort -integer -unique $seqs]}]
    write_out [concat [common_out] [list chat_a s $chat_a second_text s $text \
        seqs_ordered b $ordered stops i $::rpc_count(session.stop) \
        resumes i $::rpc_count(chat.resume) after_seq i [bstate after_seq]]]
}
