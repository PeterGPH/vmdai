from __future__ import annotations
from typing import Callable

from vmdbench.spec.dimensions import KIND_DIMENSIONS


class AssertionError(Exception):
    """Raised when a task-card assertion is malformed (distinct from builtins.AssertionError)."""


# Closed set: state-assertion kinds (KIND_DIMENSIONS) + the custom_check escape hatch.
KNOWN_KINDS: frozenset[str] = frozenset(set(KIND_DIMENSIONS) | {"custom_check"})

# Registry of reviewed custom-check functions: name -> fn(scene, ctx, where) -> bool
CUSTOM_CHECKS: dict[str, Callable] = {}


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
    if kind == "custom_check":
        ref = a["where"].get("ref")
        if ref not in CUSTOM_CHECKS:
            raise AssertionError(
                f"custom_check ref {ref!r} not registered; register it via register_custom_check()"
            )
