"""integrations/run_provenance.py: one manifest line per benchmark run (spec §0)."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "integrations" / "run_provenance.py"


def _module():
    spec = importlib.util.spec_from_file_location("run_provenance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def test_append_fields(tmp_path):
    prov = _module()
    manifest = tmp_path / "run_manifest.jsonl"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"vmd_ai_runtime_path": "runtime"}))
    record = prov.append_run_manifest(str(manifest), str(REPO), run="r1", config=str(config))
    lines = manifest.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0]) == record
    assert list(record)[:3] == ["ts", "commit", "describe"]
    assert record["commit"] == _git("rev-parse", "--short", "HEAD")
    assert record["describe"] == _git("describe", "--tags", "--always", "--dirty")
    assert record["vmd_ai_runtime_path"] == os.path.realpath(REPO / "runtime")
    assert record["run"] == "r1"
    assert len(record["ts"]) == 20 and record["ts"].endswith("Z")

    prov.append_run_manifest(str(manifest), str(tmp_path), run="r2",
                             vmd_ai_runtime_path="/abs/runtime")
    second = json.loads(manifest.read_text().splitlines()[1])
    assert second["commit"] == "nogit" and second["describe"] == "-"
    assert second["vmd_ai_runtime_path"] == os.path.realpath("/abs/runtime")


def test_cli_key_value(tmp_path):
    manifest = tmp_path / "m.jsonl"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(manifest), "run=cli", "model=Qwen/x", "arms=none rag"],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    record = json.loads(manifest.read_text())
    assert (record["run"], record["model"], record["arms"]) == ("cli", "Qwen/x", "none rag")
    assert record["vmd_ai_runtime_path"] == os.path.realpath(REPO / "runtime")
    assert "== provenance ->" in proc.stdout

    bad = subprocess.run([sys.executable, str(SCRIPT), str(manifest), "no-equals-sign"],
                         capture_output=True, text=True, timeout=30)
    assert bad.returncode == 2
    assert "expected key=value" in bad.stderr
    assert len(manifest.read_text().splitlines()) == 1


RUNNERS = (
    "integrations/scivisagentbench/run_atlas_parallel.sh",
    "integrations/scivisagentbench/run_25cell_retrieval.sh",
    "integrations/scivisagentbench/run_multistructure.py",
    "integrations/scivisagentbench/run_heldout.py",
    "integrations/explore_arm/run_explore.py",
)


def test_every_runner_appends_provenance():
    for rel in RUNNERS:
        path = REPO / rel
        text = path.read_text(encoding="utf-8")
        assert "run_provenance" in text and "runner=" in text, rel
        if rel.endswith(".sh"):
            check = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            assert check.returncode == 0, check.stderr
        else:
            compile(text, rel, "exec")
