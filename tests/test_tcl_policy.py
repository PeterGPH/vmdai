"""C1: the critical-Tcl accident guard (runtime/vmd_ai_runtime/tcl_policy.py)."""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from vmd_ai_runtime import tcl_policy

REPO = Path(__file__).resolve().parents[1]
HOME = "/Users/tester"
ROOT = "/opt/vmdai-checkout"


def ids(command):
    return [f.id for f in tcl_policy.check(command, checkout_root=ROOT, home=HOME)]


BLOCKED = [
    ("exec ls", "cmd_exec"),
    ("set x [exec ls]", "cmd_exec"),
    ("after 0 {exec ls}", "cmd_exec"),
    ("if {1} {exec ls}", "cmd_exec"),
    ("catch {exec ls}", "cmd_exec"),
    ('puts [open "|ls"]', "open_pipe"),
    ("quit", "cmd_quit"),
    ("mol new a.pdb; exit", "cmd_quit"),
    ("file delete ~/.vmdrc", "protected_path"),
    ("source ~/.vmdai/x.tcl", "protected_path"),
    ("interp create", "interp_unsafe"),
    ('puts "[exec ls]"', "cmd_exec"),
    ("file delete -force -- ~/.ssh/x", "protected_path"),
]

ALLOWED = [
    "mol rename $m x",
    'puts "exit code"',
    "set fh [open $path w]",
    "open out.dat w",
    "interp create -safe",
    "namespace eval vmdai {}",
    'atomselect top "resname EXE"',
    "# exec ls",
    "# note \\\nexec ls",
]


@pytest.mark.parametrize("command,finding_id", BLOCKED)
def test_blocked_cases(command, finding_id):
    assert finding_id in ids(command), command


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed_cases(command):
    assert ids(command) == [], command


def test_pinned_gaps():
    # Known, documented limits of a static check (spec C1): no finding.
    assert ids("set c exec; $c ls") == []
    assert ids('eval "exec ls"') == []


def test_too_deep():
    deep = "if {1} {" * 17 + "puts x" + "}" * 17
    assert "too_deep" in ids(deep)
    shallow = "if {1} {" * 15 + "puts x" + "}" * 15
    assert ids(shallow) == []
    brackets = "set x " + "[" * 18 + "list 1" + "]" * 18
    assert "too_deep" in ids(brackets)


def test_more_protected_paths():
    assert ids("file mkdir $env(HOME)/.vmdai/x") == ["protected_path"]
    assert ids("set f [open ~/Library/LaunchAgents/x.plist w]") == ["protected_path"]
    assert ids("file copy notes.txt /") == ["protected_path"]
    assert ids("file delete " + ROOT + "/runtime/main.py") == ["protected_path"]
    assert ids("file delete ~") == ["protected_path"]
    assert ids("file delete /tmp/scratch.dat") == []
    assert ids("open ~/.vmdrc r") == []


def test_finding_fields_and_statement_index():
    found = tcl_policy.check("mol new a.pdb\nset x [exec ls]\n", checkout_root=ROOT, home=HOME)
    assert len(found) == 1
    f = found[0]
    assert (f.id, f.word, f.statement_index, f.text) == ("cmd_exec", "exec", 2, "exec ls")
    assert f.id in tcl_policy.FINDING_IDS
    pf = tcl_policy.check("file delete -force ~/.ssh/id_rsa", checkout_root=ROOT, home=HOME)[0]
    assert (pf.word, pf.text) == ("file delete", "~/.ssh/id_rsa")


def test_messages():
    exec_f = tcl_policy.check("exec curl -O x", checkout_root=ROOT, home=HOME)[0]
    assert tcl_policy.message_for(exec_f) == (
        "Not run: `exec` is never run by ChatVMD. If the user needs it, show the "
        "command in a tcl code block so they can copy it and run it in the VMD "
        "console themselves."
    )
    quit_f = tcl_policy.check("exit", checkout_root=ROOT, home=HOME)[0]
    assert tcl_policy.message_for(quit_f) == "Not run: this would close the user's VMD session."
    sock_f = tcl_policy.check("socket localhost 80", checkout_root=ROOT, home=HOME)[0]
    assert tcl_policy.message_for(sock_f).startswith("Not run: `socket` is never run by ChatVMD.")
    path_f = tcl_policy.check("source ~/.vmdai/x.tcl", checkout_root=ROOT, home=HOME)[0]
    assert tcl_policy.message_for(path_f) == "Not run: ChatVMD never writes, deletes or sources ~/.vmdai/x.tcl."


def test_split_statements_matches_executor_grouping():
    script = "mol new a.pdb\n\n# comment\nforeach i {1 2} {\n  puts $i\n}\nset a 1; set b 2\nset x {"
    assert tcl_policy.split_statements(script) == [
        "mol new a.pdb",
        "foreach i {1 2} {\n  puts $i\n}",
        "set a 1; set b 2",
        "set x {",
    ]
    assert tcl_policy.split_statements("# a \\\nexec ls\nputs ok") == ["puts ok"]


def test_never_raises_on_garbage():
    for text in ["{", "}", "[", "]", '"', "\\", "{*}", "set x [", 'puts "[exec', "{" * 500, "[" * 500]:
        tcl_policy.check(text, checkout_root=ROOT, home=HOME)


def test_corpus_zero_findings():
    files = sorted(glob.glob(str(REPO / "vmdbench" / "oracles" / "**" / "*.tcl"), recursive=True))
    files += sorted(glob.glob(str(REPO / "skills" / "*" / "scripts" / "*.tcl")))
    assert len(files) == 54, files
    offenders = {}
    for path in files:
        text = Path(path).read_text(encoding="utf-8")
        found = tcl_policy.check(text, checkout_root=str(REPO), home=HOME)
        if found:
            offenders[path] = found
    assert offenders == {}
