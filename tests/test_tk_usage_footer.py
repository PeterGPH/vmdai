"""P10-T05: the run footer's usage line (Part B V4 Run footer; spec 2c Usage)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pytest

from helpers import tcl
from helpers.tk_cases import assert_case, run_tk_file

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
TK_TOTAL = 2
DOT = "·"

# Pure Tcl, like plan 08's view-model tests: config.tcl and viewmodel.tcl only.
VM_PRELUDE = (
    "fconfigure stdout -encoding utf-8\n"
    "source %s\n" % tcl.tcl_word(str(PLUGIN / "config.tcl"))
    + "source %s\n" % tcl.tcl_word(str(PLUGIN / "viewmodel.tcl"))
    + "proc ev {role type text meta} {\n"
    "    dict create seq 0 ts 1790208000.0 role $role type $type text $text \\\n"
    "        metadata [dict merge [dict create v 2] $meta]\n"
    "}\n"
    "proc finished_ops {rid usage} {\n"
    "    ::vmdai::vm::init st\n"
    "    set ops {}\n"
    "    foreach e [list \\\n"
    "        [ev system state {} [dict create kind request.started request_id $rid \\\n"
    "            chat_id chat_000000000091 provider ollama model qwen3.8:27b max_turns 28 \\\n"
    "            vision true think false]] \\\n"
    "        [ev system state {} [dict create kind request.finished request_id $rid \\\n"
    "            status complete wrapped_up false turns 1 tool_calls 0 final_text_empty false \\\n"
    "            duration_ms 1200 usage $usage error null run_dir null]]] {\n"
    "        set ops [concat $ops [::vmdai::vm::apply st $e]]\n"
    "    }\n"
    "    return $ops\n"
    "}\n"
    "proc footers {ops} {\n"
    "    set out {}\n"
    "    foreach op $ops { if {[lindex $op 0] eq \"footer\"} { lappend out $op } }\n"
    "    return $out\n"
    "}\n"
)

USAGE_CASES = [
    ("input_tokens_evaluated 20100 output_tokens 640", "20.1k evaluated %s 640 out" % DOT),
    ("input_tokens_evaluated 5120 output_tokens null", "5.1k evaluated"),
    ("input_tokens_evaluated null output_tokens 211", "211 out"),
    ("output_tokens 0", "0 out"),
    ("input_tokens_evaluated 999 output_tokens 1000", "999 evaluated %s 1k out" % DOT),
    ("input_tokens_evaluated 999949 output_tokens 999950", "999.9k evaluated %s 1M out" % DOT),
    ("input_tokens_evaluated 1234567 output_tokens 5000", "1.2M evaluated %s 5k out" % DOT),
    ("input_tokens_evaluated {} output_tokens -3", ""),
]


def _tcl_lines(script: str) -> List[str]:
    proc = tcl.run_tcl(VM_PRELUDE + script)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.splitlines()


@pytest.fixture(scope="module")
def tk_results():
    return run_tk_file("test_usage_footer.tcl")


def test_usage_text():
    script = "".join("puts [::vmdai::vm::usage_text {%s}]\n" % usage for usage, _ in USAGE_CASES)
    assert _tcl_lines(script) == [text for _, text in USAGE_CASES]


def test_null_usage_omitted():
    lines = _tcl_lines(
        "puts [::vmdai::vm::usage_text {input_tokens_evaluated null output_tokens null}]\n"
        "puts [::vmdai::vm::usage_text {}]\n"
        "puts [::vmdai::vm::usage_text null]\n"
        "set ops [finished_ops req_000000000091 {input_tokens_evaluated null output_tokens null}]\n"
        "set texts {}\n"
        "foreach f [footers $ops] { lappend texts [lindex $f 3] }\n"
        "puts [llength [lsearch -all -inline -not -exact $texts {}]]\n"
        "puts [expr {[string first \"0 out\" $ops] >= 0 || [string first evaluated $ops] >= 0}]\n"
        "set ops [finished_ops req_000000000094 {input_tokens_evaluated 5120 output_tokens null}]\n"
        "puts [lindex [footers $ops] 0 3]\n"
    )
    assert lines == ["", "", "", "0", "0", "5.1k evaluated"]


def test_footer_without_statements():
    lines = _tcl_lines(
        "set f [footers [finished_ops req_000000000095 {input_tokens_evaluated 20100 output_tokens 640}]]\n"
        "puts [llength $f]\n"
        "puts [lindex $f 0 2]\n"
        "puts [lindex $f 0 3]\n"
    )
    assert lines == ["1", "0", "20.1k evaluated %s 640 out" % DOT]


def test_never_context_used():
    offenders = [p.name for p in sorted(PLUGIN.glob("*.tcl"))
                 if re.search(r"context\s+used", p.read_text(encoding="utf-8"), re.IGNORECASE)]
    assert offenders == []
    lines = _tcl_lines("puts [::vmdai::vm::usage_text {input_tokens_evaluated 20100 output_tokens 640}]\n")
    assert "context" not in lines[0].lower()


def test_usage_line_rendered(tk_results):
    assert_case(tk_results, "usage-line", TK_TOTAL)


def test_no_usage_line_when_null(tk_results):
    assert_case(tk_results, "usage-null-no-line", TK_TOTAL)
