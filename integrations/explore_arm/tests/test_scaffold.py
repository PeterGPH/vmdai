"""TDD tests for scaffold.py — the LabProtocol gate machine, the genericness lint,
and the two text transforms. Pure: no VMD, no LLM, no framework."""
import pytest

import scaffold
from scaffold import (
    EXPLORE_DIRECTIVE,
    INVITE_DIRECTIVE,
    LAB_TOOL_SCHEMAS,
    NEUTRAL_LAB_SCHEMAS,
    HIDDEN_BUILTIN_TOOLS,
    LabProtocol,
    directive_for,
    lint_texts,
    rewrite_system_prompt,
    sanitize_env_text,
    scaffold_texts,
    schemas_for,
)


# ------------------------------------------------------------------ gate machine
def _do_try(p, code="puts 1", ok=True, error=""):
    return p.record_try(code, ok=ok, error=error)


def test_gate_blocks_commit_before_any_experiments():
    p = LabProtocol(min_experiments=3)
    refusal = p.commit_gate()
    assert refusal is not None
    assert "0" in refusal  # tells the model where it stands


def test_gate_blocks_commit_without_note():
    p = LabProtocol(min_experiments=2)
    _do_try(p)
    _do_try(p)
    assert p.commit_gate() is not None


def test_gate_requires_verify_run_after_last_note():
    p = LabProtocol(min_experiments=2)
    _do_try(p)
    _do_try(p)
    p.record_note("fact: works")
    # experiments >= min and a note exists, but nothing re-run after the note
    assert p.commit_gate() is not None


def test_gate_opens_after_full_protocol():
    p = LabProtocol(min_experiments=2)
    _do_try(p)
    _do_try(p)
    p.record_note("fact: works")
    _do_try(p)  # the verify run
    assert p.commit_gate() is None


def test_refusal_message_names_missing_requirements():
    p = LabProtocol(min_experiments=3)
    _do_try(p)
    refusal = p.commit_gate()
    assert "1/3" in refusal            # experiment count so far
    assert "lab_note" in refusal       # what is missing, by tool name


def test_min_experiments_is_configurable():
    p = LabProtocol(min_experiments=1)
    _do_try(p)
    p.record_note("n")
    _do_try(p)
    assert p.commit_gate() is None


def test_loop_breaker_nudges_on_identical_error_twice():
    p = LabProtocol()
    g1 = p.record_try("bad", ok=False, error="syntax error in expression")
    g2 = p.record_try("bad", ok=False, error="syntax error in expression")
    assert g1 is None
    assert g2 is not None and "different" in g2.lower()


def test_no_nudge_on_different_errors():
    p = LabProtocol()
    p.record_try("bad1", ok=False, error="error A")
    g = p.record_try("bad2", ok=False, error="error B")
    assert g is None


def test_soft_cap_warns_but_does_not_block():
    p = LabProtocol(min_experiments=1, max_experiments=2)
    assert _do_try(p) is None
    assert _do_try(p) is None
    g3 = _do_try(p)                    # over budget: warned, not blocked
    assert g3 is not None and "budget" in g3.lower()
    p.record_note("n")
    _do_try(p)
    assert p.commit_gate() is None     # gate still operates normally


def test_reset_clears_state():
    p = LabProtocol(min_experiments=1)
    _do_try(p)
    p.record_note("n")
    _do_try(p)
    assert p.commit_gate() is None
    p.reset()
    assert p.commit_gate() is not None
    assert p.summary()["experiments"] == 0


def test_summary_counts_events():
    p = LabProtocol(min_experiments=5)
    _do_try(p, ok=False, error="boom")
    _do_try(p, ok=True)
    p.record_note("n")
    assert p.commit_gate() is not None        # a rejection
    s = p.summary()
    assert s["experiments"] == 2
    assert s["notes"] == 1
    assert s["errors"] == 1
    assert s["commit_rejections"] == 1
    assert s["error_recoveries"] == 1         # error followed by an ok try
    assert len(s["events"]) >= 3


# -------------------------------------------------------- elicitation ladder (E-T1/E-T2)
def test_unenforced_gate_always_allows_but_records_would_reject():
    p = LabProtocol(min_experiments=3, enforce=False)
    assert p.commit_gate() is None                      # nothing blocks in free/invited
    s = p.summary()
    assert s["would_reject_commits"] == 1               # ...but noncompliance is recorded
    assert s["commit_rejections"] == 0                  # and NOT counted as a rejection
    assert p.events[-1]["kind"] == "commit_check" and p.events[-1]["would_reject"] is True


def test_unenforced_gate_records_compliance_too():
    p = LabProtocol(min_experiments=1, enforce=False)
    p.record_try("a", ok=True)
    p.record_note("n")
    p.record_try("verify", ok=True)
    assert p.commit_gate() is None
    assert p.events[-1]["would_reject"] is False
    assert p.summary()["would_reject_commits"] == 0


def test_enforced_default_unchanged():
    p = LabProtocol(min_experiments=3)                  # enforce defaults True
    assert p.commit_gate() is not None
    assert p.summary()["enforce"] is True


def test_directive_levels():
    assert directive_for("full") == EXPLORE_DIRECTIVE
    assert directive_for("invite") == INVITE_DIRECTIVE
    assert directive_for("none") == ""
    assert directive_for("unknown-value") == EXPLORE_DIRECTIVE   # fail-safe default


def test_invite_directive_advises_without_enforcement_language():
    up = INVITE_DIRECTIVE.upper()
    assert "REJECT" not in up and "MUST" not in up and "REQUIRED" not in up
    assert "lab_note" in INVITE_DIRECTIVE and "lab_commit" in INVITE_DIRECTIVE


def test_neutral_schemas_for_free_level():
    assert [s["name"] for s in NEUTRAL_LAB_SCHEMAS] == ["lab_try", "lab_note", "lab_commit"]
    joined = " ".join(s["description"].lower() for s in NEUTRAL_LAB_SCHEMAS)
    for framing in ("experiment", "reject", "protocol", "notebook"):
        assert framing not in joined
    assert schemas_for("none") is NEUTRAL_LAB_SCHEMAS
    assert schemas_for("full") is LAB_TOOL_SCHEMAS
    assert schemas_for("invite") is LAB_TOOL_SCHEMAS


# ------------------------------------------------------------------ genericness lint
def test_scaffold_texts_cover_directive_and_schemas():
    texts = scaffold_texts()
    assert any(EXPLORE_DIRECTIVE in t for t in texts)
    for schema in LAB_TOOL_SCHEMAS:
        assert any(schema["description"] in t for t in texts)


def test_lint_scaffold_is_clean():
    assert lint_texts() == []


def test_lint_catches_planted_domain_token():
    found = lint_texts(["first call measure rgyr on the protein"])
    assert "measure" in found and "rgyr" in found and "protein" in found


def test_three_lab_tools_and_hidden_builtins():
    names = [s["name"] for s in LAB_TOOL_SCHEMAS]
    assert names == ["lab_try", "lab_note", "lab_commit"]
    assert "run_vmd_command" in HIDDEN_BUILTIN_TOOLS
    assert "capture_vmd_snapshot" in HIDDEN_BUILTIN_TOOLS


# ------------------------------------------------------------------ text transforms
def test_rewrite_system_prompt_removes_builtin_tool_names():
    src = ("Use run_vmd_command to send Tcl. capture_vmd_snapshot saves a PNG. "
           "run_vmd_command is the main tool.")
    out = rewrite_system_prompt(src)
    assert "run_vmd_command" not in out
    assert "capture_vmd_snapshot" not in out
    assert "lab_try" in out


def test_sanitize_env_text_strips_domain_tool_advice():
    # the real anti-thrash suffix authored by subprocess_vmd_bridge._run_tcl
    err = ("incomplete Tcl — unbalanced braces. NOT executed (an unbalanced command hangs the "
           "interpreter). Resend the ENTIRE command on one line with every {} and [] matched."
           " You have hit this repeatedly — STOP hand-writing this loop and call "
           "vmd_traj_measure (over-all-frames) or vmd_measure (single value) instead; "
           "they run the correct, brace-balanced Tcl for you.")
    out = sanitize_env_text(err)
    assert "vmd_traj_measure" not in out
    assert "vmd_measure" not in out
    assert "incomplete Tcl" in out            # the informative part survives


def test_sanitize_env_text_passes_ordinary_errors_through():
    err = 'wrong # args: should be "molinfo top get numframes"'
    assert sanitize_env_text(err) == err
