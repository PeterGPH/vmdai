"""scaffold.py — the knowledge-free self-exploration scaffold for the `explore` arm.

Pure logic, deliberately free of VMD / LLM / framework imports so it is unit-testable
on its own (mirrors tool_prompts.py's convention in the scivisagentbench integration):

- EXPLORE_DIRECTIVE + the three lab_* tool schemas — every string the scaffold shows the
  model. By design they contain ZERO domain content (no VMD command names, no MD terms);
  `lint_texts()` enforces that mechanically and is asserted in the tests.
- LabProtocol — the enforced explore→distill→verify→commit state machine (the gate that
  rejects a premature lab_commit), plus the two generic guardrails: a loop-breaker nudge
  on an identical error twice in a row, and a soft experiment-budget warning.
- rewrite_system_prompt() — retargets the shared base system prompt's built-in tool names
  at the lab surface, so all arms share the same base prompt content.
- sanitize_env_text() — strips the ONE domain-tool advertisement the shared bridge bakes
  into its anti-thrash error message, which would otherwise leak steering-to-domain-tools
  into this arm's environment.
"""
import json

# ----------------------------------------------------------------------- directive
EXPLORE_DIRECTIVE = (
    "\n\nLAB PROTOCOL — you are driving an unfamiliar interactive interpreter, and the "
    "reference manual is the interpreter itself: discover what exists, test before you "
    "trust, and read every error message as documentation. Work in phases.\n"
    "1. EXPLORE — run small experiments with lab_try(code), one idea per call. Experiments "
    "are free: an error is information, not a failure. List what exists, invoke a candidate "
    "command with no or tiny arguments to see its usage text, and test each building block "
    "at small scale before relying on it. Investigate every unexpected observation before "
    "moving on.\n"
    "2. DISTILL — record each VERIFIED fact with lab_note(text): the exact working syntax, "
    "what it returned, and what you concluded. Notes are your only trustworthy memory and "
    "are echoed back at commit time.\n"
    "3. VERIFY — assemble the complete solution and run it with lab_try first. Check every "
    "printed value: is it finite, plausible, self-consistent? If in doubt, design one more "
    "small experiment that would expose an error.\n"
    "4. COMMIT — submit the final code with lab_commit(code). It runs end-to-end and must "
    "write any required output files itself. It is REJECTED until you have experimented "
    "enough, recorded at least one note, and re-run something after your last note.\n"
    "Act in small increments; never assume an unverified value."
)

# ----------------------------------------------------------------------- lab tools
LAB_TRY_SCHEMA = {
    "name": "lab_try",
    "description": (
        "Run one small EXPERIMENT in the live interpreter session and observe the result or "
        "the error. Errors are information and never count against you. Prefer many small "
        "probes: list what exists, print a usage text, test one building block at a time."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string",
                     "description": "a small piece of code for the interpreter — one idea per experiment"},
        },
        "required": ["code"],
    },
}
LAB_NOTE_SCHEMA = {
    "name": "lab_note",
    "description": (
        "Record one VERIFIED fact in your lab notebook: the exact working syntax, the "
        "observed value, and your conclusion. Notes are echoed back when you commit."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "one verified fact, stated precisely"},
        },
        "required": ["text"],
    },
}
LAB_COMMIT_SCHEMA = {
    "name": "lab_commit",
    "description": (
        "Submit your FINAL solution code. It runs end-to-end in the live session and must "
        "itself write any output files the task requires. It is rejected until the lab "
        "protocol is satisfied: enough experiments, at least one note, and a re-run after "
        "your last note."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "the complete final solution code"},
        },
        "required": ["code"],
    },
}
LAB_TOOL_SCHEMAS = [LAB_TRY_SCHEMA, LAB_NOTE_SCHEMA, LAB_COMMIT_SCHEMA]

# ------------------------------------------------- elicitation ladder (E-T1/E-T2)
# Three levels of elicitation strength share one lab surface:
#   free     — NEUTRAL schemas below, no directive, gate off: measures SPONTANEOUS
#              exploration (nothing suggests or requires the lab way of working).
#   invited  — framed schemas + INVITE_DIRECTIVE (advice, zero enforcement), gate off.
#   enforced — framed schemas + EXPLORE_DIRECTIVE + the commit gate (the control).
INVITE_DIRECTIVE = (
    "\n\nLAB NOTE — this interpreter rewards an experiment-first way of working: an "
    "error is information, not a failure; test a candidate at small scale with lab_try "
    "before trusting it; keep each verified fact in lab_note; and re-run your assembled "
    "solution with lab_try before submitting it with lab_commit. How you organize your "
    "work is entirely up to you."
)

NEUTRAL_LAB_SCHEMAS = [
    {"name": "lab_try",
     "description": "Run a piece of code in the live interpreter session and return its "
                    "output or its error.",
     "input_schema": {"type": "object",
                      "properties": {"code": {"type": "string",
                                              "description": "code for the interpreter"}},
                      "required": ["code"]}},
    {"name": "lab_note",
     "description": "Save a short text note for yourself; notes persist for this task.",
     "input_schema": {"type": "object",
                      "properties": {"text": {"type": "string", "description": "the note"}},
                      "required": ["text"]}},
    {"name": "lab_commit",
     "description": "Run your FINAL solution code end-to-end in the live session. It must "
                    "itself write any output files the task requires.",
     "input_schema": {"type": "object",
                      "properties": {"code": {"type": "string",
                                              "description": "the complete final solution code"}},
                      "required": ["code"]}},
]


def directive_for(level):
    """Directive text for an elicitation level ('full' | 'invite' | 'none').
    Unrecognized values fall back to the full directive (fail-safe, mirroring
    tool_prompts.tool_directive's convention)."""
    return {"full": EXPLORE_DIRECTIVE, "invite": INVITE_DIRECTIVE,
            "none": ""}.get(str(level).lower(), EXPLORE_DIRECTIVE)


def schemas_for(level):
    """Tool schemas for an elicitation level: neutral for 'none' (free), framed otherwise."""
    return NEUTRAL_LAB_SCHEMAS if str(level).lower() == "none" else LAB_TOOL_SCHEMAS

# Built-in loop tools hidden in this arm: the lab surface replaces them (fewer tools →
# more environment engagement; run_vmd_command calls are aliased to lab_try defensively).
HIDDEN_BUILTIN_TOOLS = ("run_vmd_command", "capture_vmd_snapshot")

# ------------------------------------------------------------------ genericness lint
# Any of these appearing in a scaffold-authored string is a leak of domain knowledge
# into the "knowledge-free" arm — the lint is what makes the arm's claim checkable.
FORBIDDEN_TOKENS = (
    "vmd", "measure", "atomselect", "molinfo", "mol new", "addfile", "waitfor",
    "rgyr", "radius of gyration", "rmsd", "rmsf", "sasa", "solvent", "protein",
    "residue", "alpha-carbon", "angstrom", "molecular", "dynamics", "trajectory",
    "atom", "frame 0", "gyration",
)


def scaffold_texts():
    """Every model-visible string this scaffold authors, across ALL elicitation levels
    (both directives + both schema sets) — the lint covers the whole ladder."""
    texts = [EXPLORE_DIRECTIVE, INVITE_DIRECTIVE]
    for schema in LAB_TOOL_SCHEMAS + NEUTRAL_LAB_SCHEMAS:
        texts.append("\n".join([schema["name"], schema["description"],
                                json.dumps(schema["input_schema"])]))
    return texts


def lint_texts(texts=None):
    """Return the sorted list of forbidden tokens found in `texts` (default: the scaffold's
    own strings). Empty list = the scaffold is domain-knowledge-free."""
    if texts is None:
        texts = scaffold_texts()
    lowered = [str(t).lower() for t in texts]
    return sorted({tok for tok in FORBIDDEN_TOKENS if any(tok in t for t in lowered)})


# ------------------------------------------------------------------- text transforms
def rewrite_system_prompt(text):
    """Retarget the shared base system prompt at the lab surface: the built-in tool names it
    references are hidden in this arm, so point those mentions at lab_try. All other base-prompt
    content is left identical across arms (controlled comparison)."""
    return (str(text)
            .replace("capture_vmd_snapshot", "lab_try")
            .replace("run_vmd_command", "lab_try"))


_BRIDGE_STEER_MARKER = " You have hit this repeatedly"
_GENERIC_STEER = (
    " You have hit this repeatedly — write the ENTIRE construct on one line with every "
    "brace matched, or take a structurally different approach."
)


def sanitize_env_text(text):
    """Strip the shared bridge's steer-to-domain-tools advice (its anti-thrash error suffix
    names vmd_traj_measure/vmd_measure, which do not exist in this arm) and replace it with
    generic guidance. Ordinary environment text passes through untouched — interpreter errors
    ARE the arm's documentation."""
    s = str(text)
    if "vmd_traj_measure" not in s and "vmd_measure" not in s:
        return s
    idx = s.find(_BRIDGE_STEER_MARKER)
    if idx != -1:
        s = s[:idx] + _GENERIC_STEER
    # defensive: any stray mention outside the known suffix shape
    return (s.replace("vmd_traj_measure", "a different approach")
             .replace("vmd_measure", "a different approach"))


# ----------------------------------------------------------------- protocol machine
class LabProtocol:
    """Per-task explore→distill→verify→commit state machine.

    The gate (commit_gate) is the enforcement: lab_commit is refused until
      - experiments >= min_experiments,
      - at least one lab_note exists, and
      - at least one lab_try ran AFTER the latest note (the verify run).
    The experiment budget is a SOFT cap (warn, never block) so the protocol cannot
    deadlock; the task timeout remains the hard bound.
    """

    def __init__(self, min_experiments=3, max_experiments=15, enforce=True):
        self.min_experiments = int(min_experiments)
        self.max_experiments = int(max_experiments)
        self.enforce = bool(enforce)
        self.reset()

    def reset(self):
        self.experiments = 0
        self.notes = []
        self.tries_since_last_note = 0
        self.errors = 0
        self.error_recoveries = 0
        self.commit_rejections = 0
        self.would_reject_commits = 0
        self.commits = 0
        self.loop_nudges = 0
        self.cap_warnings = 0
        self.events = []
        self._last_error = None
        self._prev_was_error = False

    # ------------------------------------------------------------------ recording
    def record_try(self, code, ok, error=""):
        """Record one lab_try; return extra guidance to append to its result, or None."""
        self.experiments += 1
        self.tries_since_last_note += 1
        guidance = None
        if ok:
            if self._prev_was_error:
                self.error_recoveries += 1
            self._prev_was_error = False
            self._last_error = None
        else:
            self.errors += 1
            norm = " ".join(str(error).split()).lower()
            if norm and norm == self._last_error:
                guidance = ("Same error twice in a row — do not resend the same thing; form a "
                            "DIFFERENT hypothesis (change the structure, test a smaller piece, "
                            "or inspect a usage text first) before retrying.")
                self.loop_nudges += 1
            self._last_error = norm
            self._prev_was_error = True
        if self.experiments > self.max_experiments:
            cap = (f"Experiment budget exceeded ({self.experiments}/{self.max_experiments}) — "
                   "distill what you verified with lab_note and submit with lab_commit now.")
            self.cap_warnings += 1
            guidance = f"{guidance} {cap}" if guidance else cap
        self.events.append({"kind": "try", "code": str(code), "ok": bool(ok),
                            "error": str(error or ""), "guidance": guidance})
        return guidance

    def record_note(self, text):
        self.notes.append(str(text))
        self.tries_since_last_note = 0
        self.events.append({"kind": "note", "text": str(text)})
        return f"noted ({len(self.notes)} note(s) in your lab notebook)."

    def commit_gate(self):
        """None if lab_commit may execute; otherwise the refusal message (and the
        rejection is recorded). With enforce=False (free/invited levels) the gate NEVER
        refuses — but it still measures spontaneous protocol compliance by recording a
        commit_check event with the would-reject verdict."""
        missing = []
        if self.experiments < self.min_experiments:
            missing.append(f"run more experiments with lab_try "
                           f"({self.experiments}/{self.min_experiments} so far)")
        if not self.notes:
            missing.append("record at least one verified fact with lab_note (0 notes so far)")
        elif self.tries_since_last_note < 1:
            missing.append("re-run your assembled solution with lab_try AFTER your last "
                           "lab_note (verify before committing)")
        if not self.enforce:
            if missing:
                self.would_reject_commits += 1
            self.events.append({"kind": "commit_check", "would_reject": bool(missing),
                                "missing": list(missing)})
            return None
        if not missing:
            return None
        self.commit_rejections += 1
        msg = ("COMMIT REJECTED — the lab protocol is not satisfied yet: "
               + "; ".join(missing) + ".")
        if self.notes:
            msg += " Your notes so far: " + " | ".join(self.notes[-5:])
        self.events.append({"kind": "commit_rejected", "message": msg})
        return msg

    def record_commit(self, ok):
        self.commits += 1
        self.events.append({"kind": "commit", "ok": bool(ok)})

    # -------------------------------------------------------------------- summary
    def summary(self):
        return {
            "experiments": self.experiments,
            "notes": len(self.notes),
            "note_texts": list(self.notes),
            "errors": self.errors,
            "error_recoveries": self.error_recoveries,
            "commit_rejections": self.commit_rejections,
            "would_reject_commits": self.would_reject_commits,
            "enforce": self.enforce,
            "commits": self.commits,
            "loop_nudges": self.loop_nudges,
            "cap_warnings": self.cap_warnings,
            "min_experiments": self.min_experiments,
            "max_experiments": self.max_experiments,
            "events": list(self.events),
        }
