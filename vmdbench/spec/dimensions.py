from __future__ import annotations
from enum import Enum


class Dimension(str, Enum):
    OBSERVABILITY = "observability"
    ACTIONABILITY = "actionability"
    SEMANTIC_GROUNDING = "semantic_grounding"
    VERIFICATION_RECOVERY = "verification_recovery"
    REPRODUCIBILITY = "reproducibility"
    WORKFLOW_EFFICIENCY = "workflow_efficiency"


DEFAULT_WEIGHTS: dict[Dimension, float] = {d: 1.0 / len(Dimension) for d in Dimension}

# Which dimension each state-assertion kind contributes to. Observability and
# workflow_efficiency are driven by episode metrics (Plans 2+), not single assertions.
KIND_DIMENSIONS: dict[str, list[Dimension]] = {
    "molecule_loaded":        [Dimension.ACTIONABILITY],
    "representation_exists":  [Dimension.ACTIONABILITY],
    "representation_count":   [Dimension.ACTIONABILITY],
    "display_property":       [Dimension.ACTIONABILITY],
    "file_rendered":          [Dimension.ACTIONABILITY],
    "frames_loaded":          [Dimension.ACTIONABILITY],
    "camera_changed":         [Dimension.ACTIONABILITY],
    "file_exists":            [Dimension.REPRODUCIBILITY],
    "selection_count":        [Dimension.SEMANTIC_GROUNDING],
    "selection_visible":      [Dimension.SEMANTIC_GROUNDING],
    "distinct_chain_colors":  [Dimension.SEMANTIC_GROUNDING],
    "no_runtime_errors":      [Dimension.VERIFICATION_RECOVERY],
}
