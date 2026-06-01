from __future__ import annotations
from dataclasses import dataclass, field

from vmdbench.spec.dimensions import Dimension, DEFAULT_WEIGHTS, KIND_DIMENSIONS
from vmdbench.verify.runner import VerifyResult

# Dimensions that cannot be scored from state assertions alone in Plan 1.
_EPISODE_ONLY = {Dimension.OBSERVABILITY, Dimension.WORKFLOW_EFFICIENCY}


@dataclass
class TaskScore:
    task_id: str
    solved: bool
    dim_scores: dict[Dimension, float] = field(default_factory=dict)
    not_evaluated: list[Dimension] = field(default_factory=list)
    composite: float = 0.0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "solved": self.solved,
            "dim_scores": {d.value: v for d, v in self.dim_scores.items()},
            "not_evaluated": [d.value for d in self.not_evaluated],
            "composite": self.composite,
        }


def _passrate(results, dim: Dimension) -> float | None:
    relevant = [r for r in results if dim in KIND_DIMENSIONS.get(r.kind, [])]
    if not relevant:
        return None
    return sum(1 for r in relevant if r.passed) / len(relevant)


def score_task(vr: VerifyResult, dimensions: list[Dimension],
               repro_signals: dict | None = None,
               episode_metrics: dict | None = None,
               weights: dict[Dimension, float] | None = None) -> TaskScore:
    weights = weights or DEFAULT_WEIGHTS
    all_checks = list(vr.required) + list(vr.optional)
    score = TaskScore(task_id=vr.task_id, solved=vr.gate)

    for d in dimensions:
        raw: float | None
        if d == Dimension.REPRODUCIBILITY and repro_signals is not None:
            raw = 1.0 if (repro_signals.get("exports_ok") and repro_signals.get("replay_clean")) else 0.0
        elif d in _EPISODE_ONLY:
            raw = (episode_metrics or {}).get(d.value)  # None unless supplied (Plans 2+)
        else:
            raw = _passrate(all_checks, d)

        if raw is None:
            score.not_evaluated.append(d)
            continue
        score.dim_scores[d] = (raw if vr.gate else 0.0)

    in_play = {d: w for d, w in weights.items() if d in score.dim_scores}
    total_w = sum(in_play.values())
    if total_w > 0:
        score.composite = sum(score.dim_scores[d] * w for d, w in in_play.items()) / total_w
    return score
