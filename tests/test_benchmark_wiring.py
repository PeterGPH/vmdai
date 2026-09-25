"""Benchmark wiring (spec §0): repo-relative config paths resolve inside the checkout.

Every integrations/**/config_*.json key in REPO_RELATIVE_KEYS must be a
relative path that vmd_ai_agent._resolve_repo_path maps to an existing path
inside this checkout.  Machine-specific absolute keys (vmd_bin, wiki_root,
wiki_raw_root) are allowed on purpose; any other absolute path is one
machine's layout leaking into a shared config.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from helpers.golden import import_adapter

REPO = Path(__file__).resolve().parents[1]
CONFIGS: List[Path] = sorted(REPO.glob("integrations/**/config_*.json"))
REPO_RELATIVE_KEYS = ("vmd_ai_runtime_path", "inject_reference_path")
MACHINE_ABSOLUTE_KEYS = ("vmd_bin", "wiki_root", "wiki_raw_root")


def wiring_problems(data: Dict[str, Any]) -> List[str]:
    adapter = import_adapter()
    problems: List[str] = []
    for key in REPO_RELATIVE_KEYS:
        if key not in data:
            continue
        value = str(data[key])
        if os.path.isabs(os.path.expanduser(value)):
            problems.append(f"{key}={value!r} is absolute; use a repo-relative path")
            continue
        resolved = Path(adapter._resolve_repo_path(value)).resolve()
        if not resolved.is_relative_to(REPO.resolve()):
            problems.append(f"{key}={value!r} resolves outside the checkout ({resolved})")
        elif not resolved.exists():
            problems.append(f"{key}={value!r} resolves to missing {resolved}")
    for key, value in data.items():
        if (isinstance(value, str) and value.startswith(("/", "~"))
                and key not in MACHINE_ABSOLUTE_KEYS and key not in REPO_RELATIVE_KEYS):
            problems.append(f"{key}={value!r} is a machine-specific absolute path")
    return problems


def test_adapter_resolves_against_this_checkout():
    assert Path(import_adapter()._REPO_ROOT) == REPO
    assert len(CONFIGS) >= 18


def test_wiring_rejects_bad_paths():
    assert wiring_problems({"vmd_ai_runtime_path": "/Users/someone/vmdai/runtime"}) == [
        "vmd_ai_runtime_path='/Users/someone/vmdai/runtime' is absolute; "
        "use a repo-relative path",
    ]
    assert wiring_problems({"inject_reference_path": "../elsewhere.md"})[0].startswith(
        "inject_reference_path='../elsewhere.md' resolves outside the checkout"
    )
    assert wiring_problems({"vmd_ai_runtime_path": "no_such_dir"})[0].startswith(
        "vmd_ai_runtime_path='no_such_dir' resolves to missing"
    )
    assert wiring_problems({"docs_index_dir": "/opt/index"}) == [
        "docs_index_dir='/opt/index' is a machine-specific absolute path",
    ]
    assert wiring_problems({"vmd_bin": "/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64",
                            "wiki_root": "/Users/x/.vmdai/wiki"}) == []


@pytest.mark.parametrize("config", CONFIGS, ids=[c.name for c in CONFIGS])
def test_repo_relative_paths_resolve_inside_checkout(config):
    data = json.loads(config.read_text(encoding="utf-8"))
    assert wiring_problems(data) == []
