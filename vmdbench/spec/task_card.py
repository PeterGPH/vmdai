from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from vmdbench.spec.assertions import validate_assertion, AssertionError as VBAssertionError
from vmdbench.spec.dimensions import Dimension

_REQUIRED_FIELDS = ["task_id", "category", "user_prompt", "verify"]
_SELECTION_KINDS = {"selection_count", "selection_visible"}


class CardError(Exception):
    pass


@dataclass
class TaskCard:
    task_id: str
    category: str
    user_prompt: str
    bucket: str = ""
    difficulty: str = "easy"
    dimensions: list[Dimension] = field(default_factory=list)
    initial_state: dict = field(default_factory=dict)
    allowed_interface: list[str] = field(default_factory=lambda: ["raw_tcl"])
    required: list[dict] = field(default_factory=list)
    optional: list[dict] = field(default_factory=list)
    observe: dict = field(default_factory=dict)
    reproducibility: dict = field(default_factory=dict)
    human_review: dict = field(default_factory=dict)
    source_path: str = ""

    def selection_texts(self) -> list[str]:
        out: list[str] = []
        for a in self.required + self.optional:
            if a.get("kind") in _SELECTION_KINDS:
                sel = a.get("where", {}).get("selection")
                if sel and sel not in out:
                    out.append(sel)
        return out


def load_card(path: str | Path) -> TaskCard:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise CardError(f"{path}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise CardError(f"{path}: card must be a YAML mapping")

    for f in _REQUIRED_FIELDS:
        if f not in data:
            raise CardError(f"{path}: missing required field '{f}'")

    verify = data["verify"] or {}
    if not isinstance(verify, dict):
        raise CardError(f"{path}: 'verify' must be a mapping")
    required = verify.get("required", []) or []
    optional = verify.get("optional", []) or []
    if not required:
        raise CardError(f"{path}: verify.required must contain at least one assertion")

    for a in required + optional:
        try:
            validate_assertion(a)
        except VBAssertionError as e:
            raise CardError(f"{path}: {e}") from e

    dims = []
    for d in data.get("dimensions", []) or []:
        try:
            dims.append(Dimension(d))
        except ValueError as e:
            raise CardError(f"{path}: unknown dimension {d!r}") from e

    return TaskCard(
        task_id=data["task_id"],
        category=data["category"],
        user_prompt=data["user_prompt"],
        bucket=data.get("bucket", ""),
        difficulty=data.get("difficulty", "easy"),
        dimensions=dims,
        initial_state=data.get("initial_state", {}) or {},
        allowed_interface=data.get("allowed_interface", ["raw_tcl"]),
        required=required,
        optional=optional,
        observe=data.get("observe", {}) or {},
        reproducibility=data.get("reproducibility", {}) or {},
        human_review=data.get("human_review", {}) or {},
        source_path=str(path),
    )
