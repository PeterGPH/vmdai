#!/usr/bin/env python3
"""test_gen_sweep.py — cell_config() overrides just the model (and experiment tag) on a base arm
config, preserving every host-specific field (paths, vmd_bin, tool_directive, enable_semantic_tools).
Pure dict logic — no files.

  python integrations/scivisagentbench/test_gen_sweep.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gen_sweep_configs import cell_config  # noqa: E402

BASE = {"model": "Qwen/Qwen2.5-72B-Instruct-AWQ", "base_url": "http://localhost:8000/v1",
        "vmd_bin": "/software/vmd-1.9.3/bin/vmd", "enable_semantic_tools": True,
        "tool_directive": "soft", "experiment_number": "toolssoft"}


def main():
    fails = 0

    def check(label, cond):
        nonlocal fails
        fails += not cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    out = cell_config(BASE, "Qwen/Qwen2.5-7B-Instruct", "toolssoft_qwen7b")
    check("model is overridden", out["model"] == "Qwen/Qwen2.5-7B-Instruct")
    check("experiment_number is set to the cell tag", out["experiment_number"] == "toolssoft_qwen7b")
    check("host-specific vmd_bin preserved", out["vmd_bin"] == "/software/vmd-1.9.3/bin/vmd")
    check("arm settings preserved (tool_directive, enable_semantic_tools)",
          out["tool_directive"] == "soft" and out["enable_semantic_tools"] is True)
    check("base_url preserved (same vLLM endpoint)", out["base_url"] == "http://localhost:8000/v1")
    check("input dict is not mutated", BASE["model"] == "Qwen/Qwen2.5-72B-Instruct-AWQ")

    print("ALL GOOD — cell_config overrides only the model + tag." if not fails
          else f"{fails} case(s) FAILED.")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
