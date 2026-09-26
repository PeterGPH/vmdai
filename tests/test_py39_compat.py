"""Python 3.9 compatibility (spec §6, §2d): the runtime imports and starts on 3.9.

``py_compile`` misses 3.10-only syntax that is evaluated at run time (for
example ``isinstance(x, int | None)``), so these tests import every runtime
module and run ``runtime/main.py --help`` under ``/usr/bin/python3`` when that
interpreter is 3.9 (the macOS system Python), and skip otherwise.  CI's 3.9
job covers the same ground on Linux by running the whole suite under 3.9.
Later plans append each new runtime module to RUNTIME_MODULES.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Optional

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNTIME = REPO / "runtime"
PY39 = "/usr/bin/python3"

RUNTIME_MODULES: List[str] = [
    "vmd_ai_runtime",
    "vmd_ai_runtime.app",
    "vmd_ai_runtime.claude_loop",
    "vmd_ai_runtime.client",
    "vmd_ai_runtime.constants",
    "vmd_ai_runtime.docs_search",
    "vmd_ai_runtime.errors",
    "vmd_ai_runtime.events",
    "vmd_ai_runtime.image_utils",
    "vmd_ai_runtime.keys",
    "vmd_ai_runtime.logging_utils",
    "vmd_ai_runtime.protocol",
    "vmd_ai_runtime.provider",
    "vmd_ai_runtime.rag",
    "vmd_ai_runtime.rag.audit",
    "vmd_ai_runtime.rag.golden",
    "vmd_ai_runtime.rag.metrics",
    "vmd_ai_runtime.recorder",
    "vmd_ai_runtime.recorder.run",
    "vmd_ai_runtime.scripts",
    "vmd_ai_runtime.scripts.build_docs_index",
    "vmd_ai_runtime.server",
    "vmd_ai_runtime.sessions",
    "vmd_ai_runtime.store",
    "vmd_ai_runtime.tool_bridge",
    "vmd_ai_runtime.wiki_bench",
    "vmd_ai_runtime.wiki_store",
]


def _python39() -> Optional[str]:
    if not os.path.exists(PY39):
        return None
    try:
        proc = subprocess.run(
            [PY39, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return PY39 if proc.stdout.strip() == "3.9" else None


requires_py39 = pytest.mark.skipif(_python39() is None,
                                   reason=f"{PY39} is not Python 3.9")


def _import_on_39(path: Path, modules: List[str], cwd: Path) -> subprocess.CompletedProcess:
    code = (
        "import importlib, sys\n"
        f"sys.path.insert(0, {str(path)!r})\n"
        f"names = {modules!r}\n"
        "for name in names:\n"
        "    importlib.import_module(name)\n"
        "print('imported', len(names))\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run([PY39, "-c", code], cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=120)


def test_runtime_module_list_is_complete():
    found = set()
    for path in (RUNTIME / "vmd_ai_runtime").rglob("*.py"):
        parts = list(path.relative_to(RUNTIME).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        found.add(".".join(parts))
    assert sorted(found - set(RUNTIME_MODULES)) == []


@requires_py39
def test_runtime_modules_import_on_39(tmp_path):
    proc = _import_on_39(RUNTIME, RUNTIME_MODULES, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"imported {len(RUNTIME_MODULES)}"


@requires_py39
def test_import_check_catches_runtime_union(tmp_path):
    (tmp_path / "uses_union.py").write_text(
        "from __future__ import annotations\n"
        "OK = isinstance(1, int | None)\n"
    )
    proc = _import_on_39(tmp_path, ["uses_union"], tmp_path)
    assert proc.returncode != 0
    assert "unsupported operand type(s) for |" in proc.stderr


@requires_py39
def test_main_help_on_39(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run([PY39, str(RUNTIME / "main.py"), "--help"], cwd=str(tmp_path),
                          env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("usage: main.py")
