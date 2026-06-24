from __future__ import annotations
from typing import Callable

from vmdbench.spec.dimensions import KIND_DIMENSIONS


class AssertionError(Exception):
    """Raised when a task-card assertion is malformed (distinct from builtins.AssertionError)."""


# Closed set: state-assertion kinds (KIND_DIMENSIONS) + the custom_check escape hatch.
KNOWN_KINDS: frozenset[str] = frozenset(set(KIND_DIMENSIONS) | {"custom_check"})

# Registry of reviewed custom-check functions: name -> fn(scene, ctx, where) -> bool
CUSTOM_CHECKS: dict[str, Callable] = {}

# Keys an assertion's `where` MUST carry for its evaluator (verify/checks.py) to run
# without raising. Validating these at load time keeps a malformed card from aborting
# the whole verification with a mid-run KeyError instead of failing cleanly here.
_REQUIRED_WHERE: dict[str, list[str]] = {
    "selection_count": ["selection"],
    "selection_visible": ["selection"],
    "file_rendered": ["path"],
    "file_exists": ["path"],
    "scalar_within": ["name"],
    "image_foreground": ["path"],
    "image_palette": ["path"],
}


def register_custom_check(name: str, fn: Callable) -> None:
    CUSTOM_CHECKS[name] = fn


def validate_assertion(a: dict) -> None:
    if not isinstance(a, dict):
        raise AssertionError(f"assertion must be a mapping, got {type(a).__name__}")
    kind = a.get("kind")
    if kind not in KNOWN_KINDS:
        raise AssertionError(f"unknown assertion kind: {kind!r}; allowed: {sorted(KNOWN_KINDS)}")
    if "where" not in a or not isinstance(a["where"], dict):
        raise AssertionError(f"assertion {kind!r} missing 'where' mapping")
    for key in _REQUIRED_WHERE.get(kind, []):
        if key not in a["where"]:
            raise AssertionError(f"assertion {kind!r} requires where.{key!r}")
    if kind == "custom_check":
        ref = a["where"].get("ref")
        if ref not in CUSTOM_CHECKS:
            raise AssertionError(
                f"custom_check ref {ref!r} not registered; register it via register_custom_check()"
            )
    if kind == "image_palette" and not (
        "min_distinct" in a["where"] or "expect_colors" in a["where"]
    ):
        raise AssertionError("image_palette requires where.min_distinct or where.expect_colors")
