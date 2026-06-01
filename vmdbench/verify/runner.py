from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

from vmdbench.adapters.oracle_tcl import prepare_workdir
from vmdbench.env.headless_vmd import HeadlessVMDEnv
from vmdbench.env.scene_state import SceneState
from vmdbench.spec.task_card import TaskCard
from vmdbench.verify.checks import CheckContext, CheckResult, evaluate


@dataclass
class VerifyResult:
    task_id: str
    gate: bool
    required: list[CheckResult] = field(default_factory=list)
    optional: list[CheckResult] = field(default_factory=list)
    scene: SceneState | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def cr(r): return {"kind": r.kind, "passed": r.passed, "observed": r.observed, "where": r.where}
        return {
            "task_id": self.task_id, "gate": self.gate,
            "required": [cr(r) for r in self.required],
            "optional": [cr(r) for r in self.optional],
            "errors": self.errors,
        }


def verify_card(card: TaskCard, tcl_transcript: str, workdir: Path,
                env: HeadlessVMDEnv | None = None) -> VerifyResult:
    env = env or HeadlessVMDEnv()
    workdir = Path(workdir)
    prepare_workdir(card, workdir)
    run = env.run(tcl_transcript, workdir=workdir, selection_texts=card.selection_texts())
    ctx = CheckContext(workdir=workdir)

    required = [evaluate(a, run.scene, ctx) for a in card.required]
    optional = [evaluate(a, run.scene, ctx) for a in card.optional]
    gate = all(r.passed for r in required)
    return VerifyResult(
        task_id=card.task_id, gate=gate, required=required, optional=optional,
        scene=run.scene, errors=run.scene.errors,
    )
