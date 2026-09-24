"""
A/B test for the search_docs RAG integration.

Two arms, two evals:

  Arm A (control): ClaudeToolLoop without docs_search. The model only
                   sees run_vmd_command + capture_vmd_snapshot.
  Arm B (RAG):     ClaudeToolLoop with docs_search wired in. The model
                   also sees the search_docs tool.

Eval 1 (RETRIEVAL QUALITY) — deterministic, no API needed:
  Given a fixed set of (query, expected_doc_section) pairs, measure
  recall@k and MRR for the RAG arm. The control arm scores 0 by
  construction (no retrieval). This proves the retrieval index works.

Eval 2 (AGENT BEHAVIOR) — mock provider with a "hallucinating without
docs" persona:
  Same set of user prompts. Each prompt has an expected correct VMD
  command snippet. The mock model:
    - In arm A: emits a plausible-looking but wrong command (the kind
                of mistake real models make on fine-grained syntax).
    - In arm B: when given the option, calls search_docs first, gets
                the right snippet, then emits the correct command.
  We score both arms by whether the expected substring appears in the
  emitted run_vmd_command. This proves the wiring would let a real
  model benefit from retrieval.

Important caveat: arm-B numbers in eval 2 reflect the *fake* model's
willingness to call search_docs and parse it. They do NOT predict any
specific real-model uplift — that requires API access and is left as
a follow-up the user can run by setting OPENROUTER_API_KEY and
running the integration evals against a live provider.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.claude_loop import (  # noqa: E402
    ClaudeToolLoop,
    SEARCH_DOCS_TOOL,
)
from vmd_ai_runtime.docs_search import DocsSearch  # noqa: E402
from vmd_ai_runtime.events import EventQueue  # noqa: E402
from vmd_ai_runtime.scripts.build_docs_index import cli as indexer_cli  # noqa: E402
from vmd_ai_runtime.tool_bridge import VmdToolBridge  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures" / "docs"


# ----------------------------------------------------------------------
# Eval queries
# ----------------------------------------------------------------------

# (query, expected_substring_in_top_chunk) — substring that uniquely
# identifies the right documentation chunk in the fixture corpus.
RETRIEVAL_QUERIES: List[Tuple[str, str]] = [
    ("What's the syntax for mol representation NewCartoon?",
     "NewCartoon"),
    ("How do I find atoms within 5 angstroms across two molecules?",
     "measure contacts"),
    ("How can I render with ambient occlusion?",
     "TachyonInternal"),
    ("How do I load Vina docking output with multiple poses?",
     "vina_out.pdbqt"),
    ("How do I color a representation by docking score?",
     "User"),
    ("What command sets the background color for paper figures?",
     "backgroundcolor"),
    ("How do I delete an existing representation?",
     "mol delrep"),
    ("How do I read VMD's selection language for protein within 5 of ligand?",
     "atomselect"),
    ("Where do I open VMD's Tcl console?",
     "Tk Console"),
    ("Why does measure hbonds fail across two molecules?",
     "same molecule"),
]


# (user_prompt, expected_substring_in_emitted_command, intended_doc_section)
# The "intended doc section" is what the agent should retrieve to
# correct itself in arm B.
AGENT_PROMPTS: List[Tuple[str, str, str]] = [
    ("Show the protein as a NewCartoon representation.",
     "mol representation NewCartoon",
     "mol representation"),
    ("Render a high-quality image with ambient occlusion.",
     "render TachyonInternal",
     "render TachyonInternal"),
    ("Find ligand-pocket contacts within 5 angstrom across the two molecules.",
     "measure contacts",
     "measure contacts"),
    ("Set background to white for a paper figure.",
     "color Display Background",
     "color Display Background"),
    ("Delete representation 0 from the top molecule.",
     "mol delrep",
     "mol delrep"),
]


# ----------------------------------------------------------------------
# Eval 1: pure retrieval quality
# ----------------------------------------------------------------------

@dataclass
class RetrievalEvalResult:
    arm: str
    queries: int
    hits_at_1: int
    hits_at_3: int
    hits_at_5: int
    reciprocal_ranks: List[float] = field(default_factory=list)

    @property
    def recall_at_1(self) -> float:
        return self.hits_at_1 / self.queries if self.queries else 0.0

    @property
    def recall_at_3(self) -> float:
        return self.hits_at_3 / self.queries if self.queries else 0.0

    @property
    def recall_at_5(self) -> float:
        return self.hits_at_5 / self.queries if self.queries else 0.0

    @property
    def mrr(self) -> float:
        return (sum(self.reciprocal_ranks) / self.queries
                if self.queries else 0.0)


def _build_fixture_index(out_dir: Path) -> int:
    return indexer_cli([
        "--rebuild",
        "--out", str(out_dir),
        "--vmd-ref", str(FIXTURES / "vmd_ref"),
        "--user-guide", str(FIXTURES / "user_guide"),
        "--skills", str(FIXTURES / "skills"),
    ])


def _eval_retrieval(docs: Optional[DocsSearch],
                    arm: str) -> RetrievalEvalResult:
    """Score recall@1/3/5 and MRR. ``docs=None`` is the control arm."""
    res = RetrievalEvalResult(arm=arm,
                              queries=len(RETRIEVAL_QUERIES),
                              hits_at_1=0,
                              hits_at_3=0,
                              hits_at_5=0)
    for query, needle in RETRIEVAL_QUERIES:
        if docs is None:
            # No retrieval available → no hits, RR=0.
            res.reciprocal_ranks.append(0.0)
            continue
        hit_rank = None
        out = docs.search(query, k=5)
        for rank, hit in enumerate(out.get("results") or [], start=1):
            if needle.lower() in hit["text"].lower():
                hit_rank = rank
                break
        if hit_rank is None:
            res.reciprocal_ranks.append(0.0)
            continue
        res.reciprocal_ranks.append(1.0 / hit_rank)
        if hit_rank <= 1:
            res.hits_at_1 += 1
        if hit_rank <= 3:
            res.hits_at_3 += 1
        if hit_rank <= 5:
            res.hits_at_5 += 1
    return res


# ----------------------------------------------------------------------
# Eval 2: mock-agent integration
# ----------------------------------------------------------------------

@dataclass
class AgentRunResult:
    correct_command: bool
    used_search_docs: bool
    emitted_commands: List[str] = field(default_factory=list)


def _make_hallucinating_loop(
    user_prompt: str,
    expected_substring: str,
    intended_doc_section: str,
    docs_search: Optional[DocsSearch],
) -> ClaudeToolLoop:
    """Build a ClaudeToolLoop whose `_call` runs an explicit state machine:

      State INITIAL → on first call:
        * if docs_search available: emit a search_docs tool_use.
          Move to AWAITING_DOCS.
        * else: emit one wrong run_vmd_command tool_use.
          Move to AWAITING_RUN_RESULT.

      State AWAITING_DOCS → on next call:
        * Read the search_docs result.
        * If expected_substring is in the retrieved text: emit the
          correct run_vmd_command. Move to AWAITING_RUN_RESULT.
        * Else: emit a wrong run_vmd_command. Move to AWAITING_RUN_RESULT.

      State AWAITING_RUN_RESULT → on next call: stop with a text-only
        completion. Whichever command we emitted is the one being scored.

    This avoids the loop the model could otherwise fall into when a
    tool result doesn't immediately give it what it needs, and keeps
    the per-prompt cost bounded at 3 turns.
    """
    loop = ClaudeToolLoop(
        provider_name="openrouter",
        api_key="fake",
        model="anthropic/claude-sonnet-4.6",
        docs_search=docs_search,
    )

    state = {
        "phase": "INITIAL",
        "last_search_text": "",
    }

    def _wrong_command_for(prompt: str) -> str:
        lower = prompt.lower()
        if "newcartoon" in lower or "cartoon" in lower:
            return "mol set rep cartoon"
        if "render" in lower and ("ambient" in lower or "high-quality" in lower):
            return "render tachyon high"
        if "contact" in lower:
            return "selset within 5 of ligand"
        if "background" in lower:
            return "display bgcolor white"
        if "delete" in lower or "delrep" in lower:
            return "mol drop rep 0"
        return "unknown_vmd_command"

    def _extract_last_tool_result(messages):
        """Return the textual content of the most recent tool_result."""
        # The loop appends user-role messages with content being a list
        # of tool_result blocks. Look back for the most recent.
        for msg in reversed(messages):
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    text = block.get("content", "")
                    if isinstance(text, list):
                        text = " ".join(
                            b.get("text", "") for b in text
                            if isinstance(b, dict)
                        )
                    return str(text or "")
        return ""

    def fake_call(messages, system_prompt, on_text, should_cancel):
        if state["phase"] == "INITIAL":
            if docs_search is not None and getattr(
                docs_search, "is_available", False
            ):
                state["phase"] = "AWAITING_DOCS"
                on_text("Let me check the docs.")
                return ("Let me check the docs.", [{
                    "type": "tool_use",
                    "id": "tc_docs_1",
                    "name": "search_docs",
                    "input": {"query": user_prompt},
                }])
            wrong = _wrong_command_for(user_prompt)
            state["phase"] = "AWAITING_RUN_RESULT"
            on_text(f"I'll run: {wrong}")
            return (f"I'll run: {wrong}", [{
                "type": "tool_use",
                "id": "tc_run_1",
                "name": "run_vmd_command",
                "input": {"command": wrong},
            }])

        if state["phase"] == "AWAITING_DOCS":
            state["last_search_text"] = _extract_last_tool_result(messages)
            state["phase"] = "AWAITING_RUN_RESULT"
            if expected_substring.lower() in state["last_search_text"].lower():
                return ("Using the documented syntax.", [{
                    "type": "tool_use",
                    "id": "tc_run_2",
                    "name": "run_vmd_command",
                    "input": {"command": expected_substring},
                }])
            wrong = _wrong_command_for(user_prompt)
            return (f"Even with docs I'll guess: {wrong}", [{
                "type": "tool_use",
                "id": "tc_run_2",
                "name": "run_vmd_command",
                "input": {"command": wrong},
            }])

        # AWAITING_RUN_RESULT → done.
        return ("Done.", [])

    loop._call = fake_call  # type: ignore[assignment]
    return loop


def _run_agent_once(
    user_prompt: str,
    expected_substring: str,
    intended_doc_section: str,
    docs_search: Optional[DocsSearch],
) -> AgentRunResult:
    loop = _make_hallucinating_loop(
        user_prompt, expected_substring, intended_doc_section, docs_search
    )

    bridge = VmdToolBridge()
    queue = EventQueue()
    cancel = threading.Event()

    emitted: List[str] = []
    used_search = {"v": False}

    def on_chunk(_t: str) -> None:
        pass

    # Patch the bridge so run_vmd_command resolves immediately with ok=True
    # — we don't actually have a Tcl side, we just want to capture what
    # commands the agent would have run.
    original_execute = bridge.execute_tool

    def fake_execute(*, tool_call_id, tool_name, tool_input, **kw):
        if tool_name == "run_vmd_command":
            cmd = str(tool_input.get("command") or "")
            emitted.append(cmd)
            return {"ok": True, "output": "executed", "error": ""}
        if tool_name == "capture_vmd_snapshot":
            return {"ok": True, "output": "snapshot", "error": ""}
        # Should never reach here for search_docs (Python-resident).
        return {"ok": False, "error": f"unexpected tool {tool_name}"}

    bridge.execute_tool = fake_execute  # type: ignore[assignment]

    # Wrap _dispatch_search_docs so we can detect whether the agent used it.
    original_dispatch = loop._dispatch_search_docs

    def tracked_dispatch(tool_input):
        used_search["v"] = True
        return original_dispatch(tool_input)

    loop._dispatch_search_docs = tracked_dispatch  # type: ignore[assignment]

    loop.run(
        prompt=user_prompt,
        system_prompt="",
        tool_bridge=bridge,
        session_id="sess_eval",
        session_queue=queue,
        cancel_event=cancel,
        on_chunk=on_chunk,
    )

    correct = any(expected_substring.lower() in c.lower() for c in emitted)
    return AgentRunResult(
        correct_command=correct,
        used_search_docs=used_search["v"],
        emitted_commands=emitted,
    )


@dataclass
class AgentEvalResult:
    arm: str
    n: int
    correct: int
    used_search: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0


def _eval_agent(docs_search: Optional[DocsSearch], arm: str) -> AgentEvalResult:
    correct = 0
    used_search = 0
    for prompt, expected, intended in AGENT_PROMPTS:
        out = _run_agent_once(prompt, expected, intended, docs_search)
        if out.correct_command:
            correct += 1
        if out.used_search_docs:
            used_search += 1
    return AgentEvalResult(arm=arm, n=len(AGENT_PROMPTS),
                           correct=correct, used_search=used_search)


# ----------------------------------------------------------------------
# Test cases
# ----------------------------------------------------------------------

class RagABTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        out = Path(cls._tmp.name)
        rc = _build_fixture_index(out)
        if rc != 0:
            raise RuntimeError("fixture index build failed")
        cls.docs = DocsSearch(index_dir=str(out))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # ------------------------------------------------------------------
    # Eval 1
    # ------------------------------------------------------------------

    def test_retrieval_eval_1_ab(self):
        control = _eval_retrieval(None, "control_no_rag")
        rag = _eval_retrieval(self.docs, "rag")

        # Control arm has zero retrieval by construction.
        self.assertEqual(control.hits_at_5, 0)
        self.assertEqual(control.mrr, 0.0)

        # RAG arm should beat control on every metric.
        self.assertGreater(rag.recall_at_5, 0.0)
        self.assertGreater(rag.mrr, 0.0)

        # Sanity floor: with a small focused fixture and well-aligned
        # queries, BM25 should land at least 70% of intended chunks
        # in top-5. If this regresses, the index or chunker has drifted.
        self.assertGreaterEqual(
            rag.recall_at_5, 0.7,
            f"recall@5 too low: {rag.recall_at_5:.2f}; details={rag}"
        )

        # Print results so the suite output doubles as the A/B report.
        _print_eval1(control, rag)

    # ------------------------------------------------------------------
    # Eval 2
    # ------------------------------------------------------------------

    def test_agent_eval_2_ab(self):
        control = _eval_agent(None, "control_no_rag")
        rag = _eval_agent(self.docs, "rag")

        # Control arm: no search_docs ever called.
        self.assertEqual(control.used_search, 0)
        # RAG arm: every prompt should trigger at least one search_docs.
        self.assertEqual(rag.used_search, len(AGENT_PROMPTS))

        # Accuracy is the headline. With our hallucinating-mock model,
        # control accuracy is 0% and RAG accuracy is 100% — that's
        # *because* the mock is designed to flip on retrieval. The
        # real-world signal here is that the wiring carries the doc
        # text into the next-turn prompt, where a real model could
        # use it.
        self.assertEqual(control.accuracy, 0.0)
        self.assertEqual(rag.accuracy, 1.0)

        _print_eval2(control, rag)


# ----------------------------------------------------------------------
# Pretty-printers (the suite output is the A/B report)
# ----------------------------------------------------------------------

def _print_eval1(control, rag):
    print("\n=========================================================")
    print("EVAL 1 — Retrieval quality on the fixture corpus")
    print("=========================================================")
    print(f"queries: {control.queries}")
    print(f"  arm           recall@1   recall@3   recall@5   MRR")
    print(f"  control       {control.recall_at_1:.2f}       {control.recall_at_3:.2f}       {control.recall_at_5:.2f}       {control.mrr:.3f}")
    print(f"  rag           {rag.recall_at_1:.2f}       {rag.recall_at_3:.2f}       {rag.recall_at_5:.2f}       {rag.mrr:.3f}")


def _print_eval2(control, rag):
    print("\n=========================================================")
    print("EVAL 2 — Mock agent: command-correctness with vs without RAG")
    print("=========================================================")
    print(f"prompts: {control.n}")
    print(f"  arm           accuracy   used_search_docs")
    print(f"  control       {control.accuracy:.2f}       {control.used_search}/{control.n}")
    print(f"  rag           {rag.accuracy:.2f}       {rag.used_search}/{rag.n}")
    print("\nNote: the mock model is wired to hallucinate without docs and")
    print("self-correct with docs. Real-model uplift requires API access.")


if __name__ == "__main__":
    unittest.main()
