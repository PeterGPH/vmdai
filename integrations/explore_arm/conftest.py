"""pytest path setup: make the explore_arm modules, the scivisagentbench integration,
the SciVisAgentBench framework, and the vmd_ai runtime importable in tests."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent                      # integrations/explore_arm
VMD_AI = HERE.parent.parent                                  # vmd_ai/
for p in (
    HERE,                                                    # scaffold / explore_bridge / ...
    VMD_AI / "integrations" / "scivisagentbench",            # vmd_ai_agent, bridges
    VMD_AI / "SciVisAgentBench-main" / "benchmark",          # evaluation_framework
    VMD_AI / "runtime",                                      # vmd_ai_runtime
):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)
