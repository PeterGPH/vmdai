"""
Tests for scripts/rag_ab.py — the workflow-level A/B harness.

We don't actually call a real provider. Instead we patch
``ClaudeToolLoop._call`` to drive a deterministic 3-turn agentic
sequence:

  Turn 1: model emits text + a run_vmd_command tool_use
  Turn 2: model emits text + (RAG arm) a search_docs tool_use
  Turn 3: model emits final text, no more tool calls

The harness should:
  * capture every Tcl command from both arms
  * capture search_docs ONLY on the RAG arm
  * produce a non-empty report
  * write a JSON file when --json is passed
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
SCRIPTS_DIR = ROOT / "scripts"
for p in (RUNTIME_DIR, SCRIPTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import rag_ab  # noqa: E402


# Canned, agent-like turn sequence — different per arm so we can tell
# them apart in the assertions.
CONTROL_TURNS = [
    (
        "Loading CDK2 and styling as cartoon.",
        [{"type": "tool_use", "id": "tc_1", "name": "run_vmd_command",
          "input": {"command": "mol new 1hck.pdb"}}],
    ),
    (
        "Styling protein.",
        [{"type": "tool_use", "id": "tc_2", "name": "run_vmd_command",
          "input": {"command": "mol representation NewCartoon"}}],
    ),
    ("Done — basic structure shown.", []),  # no tool calls → loop ends
]

RAG_TURNS = [
    (
        "Looking up canonical CDK2 / ATP workflow first.",
        [{"type": "tool_use", "id": "tc_a", "name": "search_docs",
          "input": {"query": "select ATP binding pocket residues"}}],
    ),
    (
        "Now loading and styling.",
        [
            {"type": "tool_use", "id": "tc_b", "name": "run_vmd_command",
             "input": {"command": "mol new 1hck.pdb"}},
            {"type": "tool_use", "id": "tc_c", "name": "run_vmd_command",
             "input": {"command": "mol representation NewCartoon\n"
                                  "mol color Structure\nmol addrep top"}},
        ],
    ),
    ("Done — academic-style figure rendered.", []),
]


class HarnessSmokeTests(unittest.TestCase):

    def _drive_arm(self, turns):
        """Closure that yields successive turns when ClaudeToolLoop._call
        is invoked.
        """
        idx = {"i": 0}

        def fake_call(self_loop, messages, system_prompt,
                      on_text, should_cancel):
            i = idx["i"]
            idx["i"] += 1
            text, tool_blocks = turns[i] if i < len(turns) else ("", [])
            if text:
                on_text(text)
            return text, tool_blocks

        return fake_call

    def test_control_arm_records_only_vmd_commands(self):
        from vmd_ai_runtime.claude_loop import ClaudeToolLoop

        # build_claude_loop("openrouter") needs an API key; the simplest
        # path is to construct ClaudeToolLoop directly and patch
        # build_claude_loop to return it.
        loop = ClaudeToolLoop(provider_name="openrouter",
                              api_key="sk-or-faked",
                              model="anthropic/claude-sonnet-4.6")

        with mock.patch("rag_ab.build_claude_loop", return_value=loop), \
             mock.patch.object(
                 ClaudeToolLoop, "_call",
                 new=self._drive_arm(CONTROL_TURNS),
             ):
            result = rag_ab._run_arm(
                "control",
                "present CDK2 academically",
                provider_mode="openrouter",
                enable_rag=False,
                docs_index_dir=None,
                system_prompt="be terse",
            )
        self.assertIsNone(result.error, msg=result.error)
        self.assertEqual(len(result.vmd_commands()), 2)
        self.assertEqual(result.search_queries(), [])
        self.assertIn("mol new 1hck.pdb", result.vmd_commands()[0])
        self.assertIn("NewCartoon", result.vmd_commands()[1])
        self.assertEqual(result.final_text, "Done — basic structure shown.")

    def test_rag_arm_records_search_and_commands(self):
        from vmd_ai_runtime.claude_loop import ClaudeToolLoop

        # Build a fake DocsSearch that looks "available" so the harness
        # doesn't bail before the loop runs.
        class FakeDocs:
            is_available = True
            def search(self, query, k=5, scope="all"):
                return {"ok": True, "results": [
                    {"source": "skills/docking/SKILL.md",
                     "section": "Pocket residue selection",
                     "score": 0.9,
                     "text": "use measure contacts"},
                ]}

        loop = ClaudeToolLoop(
            provider_name="openrouter",
            api_key="sk-or-faked",
            model="anthropic/claude-sonnet-4.6",
            docs_search=FakeDocs(),
        )

        with mock.patch("rag_ab.build_claude_loop", return_value=loop), \
             mock.patch("rag_ab.DocsSearch", return_value=FakeDocs()), \
             mock.patch.object(
                 ClaudeToolLoop, "_call",
                 new=self._drive_arm(RAG_TURNS),
             ):
            result = rag_ab._run_arm(
                "rag",
                "present CDK2 academically",
                provider_mode="openrouter",
                enable_rag=True,
                docs_index_dir=None,
                system_prompt="be terse",
            )
        self.assertIsNone(result.error, msg=result.error)
        self.assertEqual(len(result.vmd_commands()), 2)
        self.assertEqual(len(result.search_queries()), 1)
        self.assertIn("ATP", result.search_queries()[0])
        self.assertIn("mol new 1hck.pdb", result.vmd_commands()[0])

    def test_render_report_is_nonempty_and_mentions_arms(self):
        ctrl = rag_ab.ArmResult(
            name="control",
            final_text="hi",
            tool_calls=[{
                "tool_name": "run_vmd_command",
                "tool_input": {"command": "mol new x.pdb"},
                "tool_call_id": "1",
            }],
            elapsed_s=0.42,
        )
        rag = rag_ab.ArmResult(
            name="rag",
            final_text="hi rag",
            tool_calls=[
                {"tool_name": "search_docs",
                 "tool_input": {"query": "atp pocket"},
                 "tool_call_id": "sd"},
                {"tool_name": "run_vmd_command",
                 "tool_input": {"command": "mol new x.pdb"},
                 "tool_call_id": "1"},
            ],
            elapsed_s=0.99,
        )
        out = rag_ab.render_report("present CDK2", ctrl, rag)
        for needle in ["control", "rag", "VMD commands emitted",
                       "search_docs queries", "Final assistant reply",
                       "mol new x.pdb", "atp pocket"]:
            self.assertIn(needle, out, msg=f"missing in report: {needle!r}")

    def test_json_output_path(self):
        from vmd_ai_runtime.claude_loop import ClaudeToolLoop
        loop = ClaudeToolLoop(provider_name="openrouter",
                              api_key="sk-or-faked",
                              model="anthropic/claude-sonnet-4.6")
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "out.json"
            with mock.patch("rag_ab.build_claude_loop", return_value=loop), \
                 mock.patch.object(
                     ClaudeToolLoop, "_call",
                     new=self._drive_arm(CONTROL_TURNS + CONTROL_TURNS),
                 ), \
                 mock.patch("rag_ab.time.sleep") as fake_sleep:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = rag_ab.main([
                        "--provider", "openrouter",
                        "--sleep", "0",
                        "--json", str(json_path),
                        "test prompt",
                    ])
            self.assertEqual(rc, 0)
            self.assertTrue(json_path.exists())
            data = json.loads(json_path.read_text())
            self.assertIn("control", data)
            self.assertIn("rag", data)
            self.assertEqual(data["provider_mode"], "openrouter")
            self.assertIn("summary", data["control"])
            self.assertIn("summary", data["rag"])
            # --sleep 0 → time.sleep should not have been called.
            fake_sleep.assert_not_called()


# ----------------------------------------------------------------------
# Inter-arm cool-down
# ----------------------------------------------------------------------

class SleepBetweenArmsTests(unittest.TestCase):

    def test_default_sleep_cloud_is_sixty_seconds(self):
        for cloud in ("anthropic-direct", "openrouter", "claude"):
            with self.subTest(provider=cloud):
                self.assertEqual(rag_ab._default_sleep_for(cloud), 60.0)

    def test_default_sleep_local_is_zero(self):
        for local in ("ollama", "local-ollama", "mock", "unknown"):
            with self.subTest(provider=local):
                self.assertEqual(rag_ab._default_sleep_for(local), 0.0)

    def test_sleep_zero_is_no_op(self):
        with mock.patch("rag_ab.time.sleep") as fake_sleep:
            rag_ab._sleep_with_countdown(0)
            rag_ab._sleep_with_countdown(-5)
        fake_sleep.assert_not_called()

    def test_sleep_positive_actually_sleeps_summing_to_total(self):
        with mock.patch("rag_ab.time.sleep") as fake_sleep:
            rag_ab._sleep_with_countdown(60)
        total = sum(call.args[0] for call in fake_sleep.call_args_list)
        self.assertAlmostEqual(total, 60.0, places=3)

    def test_main_respects_explicit_sleep_zero(self):
        from vmd_ai_runtime.claude_loop import ClaudeToolLoop
        loop = ClaudeToolLoop(provider_name="anthropic-direct",
                              api_key="sk-faked",
                              model="claude-sonnet-4-6")
        with mock.patch("rag_ab.build_claude_loop", return_value=loop), \
             mock.patch.object(
                 ClaudeToolLoop, "_call",
                 new=HarnessSmokeTests._drive_arm(
                     HarnessSmokeTests(), CONTROL_TURNS + CONTROL_TURNS,
                 ),
             ), \
             mock.patch("rag_ab.time.sleep") as fake_sleep:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = rag_ab.main([
                    "--provider", "anthropic-direct",
                    "--sleep", "0",
                    "test prompt",
                ])
        self.assertEqual(rc, 0)
        fake_sleep.assert_not_called()

    def test_main_default_sleep_kicks_in_for_cloud_provider(self):
        from vmd_ai_runtime.claude_loop import ClaudeToolLoop
        loop = ClaudeToolLoop(provider_name="anthropic-direct",
                              api_key="sk-faked",
                              model="claude-sonnet-4-6")
        with mock.patch("rag_ab.build_claude_loop", return_value=loop), \
             mock.patch.object(
                 ClaudeToolLoop, "_call",
                 new=HarnessSmokeTests._drive_arm(
                     HarnessSmokeTests(), CONTROL_TURNS + CONTROL_TURNS,
                 ),
             ), \
             mock.patch("rag_ab.time.sleep") as fake_sleep:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = rag_ab.main([
                    "--provider", "anthropic-direct",
                    # no --sleep → default 60 for cloud
                    "test prompt",
                ])
        self.assertEqual(rc, 0)
        total = sum(c.args[0] for c in fake_sleep.call_args_list)
        # ~60s total, in 5s chunks (12 ticks)
        self.assertAlmostEqual(total, 60.0, places=3)


if __name__ == "__main__":
    unittest.main()
