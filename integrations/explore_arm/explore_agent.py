"""explore_agent.py — the explore arm's agent: VmdAiAgent with the lab surface swapped in.

Subclasses the unchanged VmdAiAgent (integrations/scivisagentbench) and, after its normal
setup, replaces the action surface with the knowledge-free lab protocol:

- the bridge is wrapped in ExploreScaffoldBridge (lab_try / lab_note / lab_commit + gate);
- ONLY the three lab tools are advertised — run_vmd_command and capture_vmd_snapshot are
  filtered out of the per-turn tool list (fewer tools → more environment engagement);
- the shared base system prompt is retargeted at the lab surface and the (lint-enforced,
  domain-free) EXPLORE_DIRECTIVE is appended.

Per task, the protocol summary is attached to the result metadata and written next to the
other artifacts as <case>.lab.json — the transcript record for the process metrics
(experiments, errors, recoveries, gate rejections, notes).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCIVIS = _HERE.parent / "scivisagentbench"
for _p in (str(_HERE), str(_SCIVIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from vmd_ai_agent import VmdAiAgent                                   # noqa: E402
from explore_bridge import ExploreScaffoldBridge                      # noqa: E402
from scaffold import (HIDDEN_BUILTIN_TOOLS, LabProtocol,              # noqa: E402
                      directive_for, rewrite_system_prompt, schemas_for)


class ExploreAgent(VmdAiAgent):
    """The knowledge-free self-exploration arm."""

    async def setup(self):
        await super().setup()
        if self.config.get("enable_semantic_tools") or self.config.get("enable_workbench_tools"):
            print("[explore] WARNING: semantic/workbench tools were enabled in the config — "
                  "they are REPLACED by the lab surface (this arm must stay knowledge-free)")

        # elicitation ladder knobs (E-T1/E-T2): enforced (default) / invited / free.
        level = str(self.config.get("explore_directive", "full")).lower()
        enforce = bool(self.config.get("explore_enforce", True))
        protocol = LabProtocol(
            min_experiments=int(self.config.get("explore_min_experiments", 3)),
            max_experiments=int(self.config.get("explore_max_experiments", 15)),
            enforce=enforce,
        )
        self._protocol = protocol
        self._bridge = ExploreScaffoldBridge(self._bridge, protocol)

        # the lab tools are the ONLY extra tools; hidden built-ins are filtered per turn.
        self._loop.extra_tools = [dict(s) for s in schemas_for(level)]
        _orig_tools_for_turn = self._loop._tools_for_turn
        self._loop._tools_for_turn = lambda: [
            t for t in _orig_tools_for_turn()
            if t.get("name") not in HIDDEN_BUILTIN_TOOLS
        ]

        self._system_prompt = rewrite_system_prompt(self._system_prompt) + directive_for(level)
        print(f"[explore] lab surface on: directive={level} enforce={enforce} "
              f"min_experiments={protocol.min_experiments} "
              f"max_experiments={protocol.max_experiments} hidden={HIDDEN_BUILTIN_TOOLS}")

    async def run_task(self, task_description, task_config):
        result = await super().run_task(task_description, task_config)
        # attach + persist the per-task process metrics (the bridge reset at task start
        # cleared the protocol, so the summary here is this task's alone).
        try:
            summary = self._protocol.summary()
            md = getattr(result, "metadata", None)
            if isinstance(md, dict):
                md["explore"] = {k: v for k, v in summary.items() if k != "events"}
            case = str((task_config or {}).get("case_name") or "task")
            wd = str((task_config or {}).get("working_dir") or os.getcwd())
            with open(os.path.join(wd, f"{case}.lab.json"), "w") as fh:
                json.dump(summary, fh, indent=2)
        except Exception:  # noqa: BLE001 — metrics are best-effort, never fail the task
            pass
        return result
