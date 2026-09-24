#!/usr/bin/env python3
"""test_convo_recording.py — the record_transcripts flag captures the full conversation.

Pure: stubs the loop and bridge; no network, no VMD. Run: python3 test_convo_recording.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "SciVisAgentBench-main" / "benchmark"))
from vmd_ai_agent import VmdAiAgent  # noqa: E402


class StubLoop:
    """Drives the callbacks the way a real run would, then returns final text."""

    def run(self, *, prompt, system_prompt, tool_bridge, session_id, session_queue,
            cancel_event, on_chunk, on_tool_start, on_tool_result, prior_messages):
        on_chunk("I'll load the structure. ")
        on_tool_start("run_vmd_command", {"command": "mol new x.pdb waitfor all"})
        on_tool_result("t1", "run_vmd_command", {"ok": True, "output": "molecule 0 loaded", "error": ""})
        on_tool_start("run_vmd_command", {"command": "bogus_cmd"})
        on_tool_result("t2", "run_vmd_command", {"ok": False, "output": "", "error": "invalid command"})
        on_chunk("Done: 42.")
        return "Done: 42."


class StubBridge:
    def reset(self):
        pass


def check(cond, label, fails):
    print(("  [PASS] " if cond else "  [FAIL] ") + label)
    if not cond:
        fails.append(label)


def run_once(record):
    agent = VmdAiAgent({"record_transcripts": record, "agent_name": "vmd_ai"})
    agent._loop, agent._bridge, agent._system_prompt = StubLoop(), StubBridge(), "SYSPROMPT-XYZ"
    wd = tempfile.mkdtemp(prefix="convo_test_")
    asyncio.run(agent.run_task("TASK-PROMPT-ABC", {
        "working_dir": wd, "case_dir": wd, "case_name": "case1", "timeout": 30}))
    return Path(wd) / "case1.convo.jsonl"


def main():
    fails = []
    p = run_once(record=True)
    check(p.exists(), "convo.jsonl written when flag on", fails)
    ev = [json.loads(l) for l in p.read_text().splitlines()]
    kinds = [e["kind"] for e in ev]
    check(kinds[:2] == ["system", "user"], "starts with system + user prompts", fails)
    check(ev[0]["text"] == "SYSPROMPT-XYZ" and ev[1]["text"] == "TASK-PROMPT-ABC",
          "prompts captured verbatim", fails)
    check(kinds[2:] == ["text", "tool_call", "tool_result", "tool_call", "tool_result", "text"],
          "events interleaved in stream order", fails)
    calls = [e for e in ev if e["kind"] == "tool_call"]
    results = [e for e in ev if e["kind"] == "tool_result"]
    check(calls[0]["input"]["command"] == "mol new x.pdb waitfor all", "tool input captured", fails)
    check(results[0]["output"] == "molecule 0 loaded", "tool OUTPUT captured (the missing piece)", fails)
    check(results[1]["error"] == "invalid command" and results[1]["ok"] is False,
          "tool error + ok flag captured", fails)
    p_off = run_once(record=False)
    check(not p_off.exists(), "flag off -> no file (zero behavior change)", fails)
    print("ALL GOOD" if not fails else f"{len(fails)} FAILURES")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
