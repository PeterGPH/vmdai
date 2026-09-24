#!/usr/bin/env python3
"""gen_sweep_configs.py — generate per-model arm configs for the cross-model adoption sweep.

For a model currently served on the vLLM endpoint, this copies each base arm config
(config_arm_{none,toolssoft,tools}.json) and overrides ONLY the model id + experiment tag, leaving
every host-specific field (paths, vmd_bin) and arm setting (tool_directive, enable_semantic_tools)
untouched. Then run the three cells with the existing parallel harness, e.g.:

    MODEL="Qwen/Qwen2.5-7B-Instruct" TAG=qwen7b \
        python integrations/scivisagentbench/gen_sweep_configs.py
    RUN=full SEEDS=3 bash integrations/scivisagentbench/run_atlas_parallel.sh \
        none_qwen7b toolssoft_qwen7b tools_qwen7b

Serve the next model, re-run with a new TAG, and repeat. Requires config_arm_toolssoft.json to
exist (create it once: copy config_arm_tools.json + set tool_directive='soft').
"""
import json, os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARMS = ("none", "toolssoft", "tools")   # baseline / soft-nudge / mandatory


def cell_config(base, model, experiment_number):
    """Return a copy of base arm config with the model id and experiment tag overridden; all other
    fields (host paths, vmd_bin, tool_directive, enable_semantic_tools, ...) are preserved."""
    out = dict(base)
    out["model"] = model
    out["experiment_number"] = experiment_number
    return out


def main():
    model = os.environ.get("MODEL")
    tag = os.environ.get("TAG")
    if not model or not tag:
        print("set MODEL (the served vLLM model id) and TAG (short label, e.g. qwen7b)"); return 1
    written = []
    for arm in ARMS:
        base_path = HERE / f"config_arm_{arm}.json"
        if not base_path.exists():
            print(f"!! missing base config {base_path.name}"
                  + ("  (create it: copy config_arm_tools.json + tool_directive='soft')"
                     if arm == "toolssoft" else "")); return 1
        cfg = cell_config(json.loads(base_path.read_text()), model, f"{arm}_{tag}")
        out_path = HERE / f"config_arm_{arm}_{tag}.json"
        out_path.write_text(json.dumps(cfg, indent=2))
        written.append(f"{arm}_{tag}")
    print(f"model={model}")
    print("wrote arm configs:", ", ".join(written))
    print("run:  RUN=full SEEDS=3 bash integrations/scivisagentbench/run_atlas_parallel.sh "
          + " ".join(written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
