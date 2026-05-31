from __future__ import annotations
import shutil
from dataclasses import dataclass
from pathlib import Path

from vmdbench.env.headless_vmd import HeadlessVMDEnv, VmdRunResult
from vmdbench.spec.task_card import TaskCard

# Fixture root: vmdbench/fixtures (parents[1] of vmdbench/adapters/oracle_tcl.py = vmdbench).
FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"


@dataclass
class OracleRun:
    result: VmdRunResult
    workdir: Path
    tcl: str


def prepare_workdir(card: TaskCard, dest: Path, fixtures_root: Path | None = None) -> Path:
    """Copy the card's initial_state files (relative to fixtures_root) into a run workdir by basename."""
    fixtures_root = Path(fixtures_root or FIXTURES_ROOT)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for rel in card.initial_state.get("files", []) or []:
        src = (fixtures_root / rel).resolve()
        shutil.copy2(src, dest / Path(rel).name)
    return dest


def run_oracle(card: TaskCard, oracle_tcl_path: str | Path, workdir: Path,
               env: HeadlessVMDEnv | None = None) -> OracleRun:
    env = env or HeadlessVMDEnv()
    prepare_workdir(card, workdir)
    tcl = Path(oracle_tcl_path).read_text()
    res = env.run(tcl, workdir=workdir, selection_texts=card.selection_texts())
    return OracleRun(result=res, workdir=Path(workdir), tcl=tcl)
