#!/usr/bin/env python3
"""safe_eval.py — a strict allow-list evaluator for vmd_compute (the v2 workbench).

The model writes a reduction expression over per-frame series it fetched with vmd_traj_series
(e.g. "max(rmsd)", "std(rgyr)", "rgyr[-1]-rgyr[0]", "mean(rgyr > mean(rgyr))"). This evaluates it
over numpy arrays through an ast allow-list — NEVER eval() on raw input. Anything outside the
allow-list raises ComputeError. Pure module (numpy only); unit-tested in test_safe_eval.py.
"""
import ast
import math
import numbers
import numpy as np


class ComputeError(ValueError):
    """The expression used something outside the allow-list, or failed to reduce to a number."""


_FUNCS = {
    "max": np.max, "min": np.min, "mean": np.mean, "std": np.std, "var": np.var,
    "median": np.median, "sum": np.sum, "abs": np.abs, "sqrt": np.sqrt,
    "ptp": np.ptp, "argmin": np.argmin, "argmax": np.argmax, "len": len,
}
_CONSTS = {"pi": math.pi, "e": math.e}

# every ast node type the evaluator permits; anything else -> ComputeError
_ALLOWED = (
    ast.Expression, ast.Constant, ast.Name, ast.Load,
    ast.BinOp, ast.UnaryOp, ast.Call, ast.Subscript, ast.Compare,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq,
)  # NB: no ast.Index (removed in 3.12); subscript slices are plain exprs on 3.9+


def _check(node, names):
    if not isinstance(node, _ALLOWED):
        raise ComputeError(f"disallowed expression element: {type(node).__name__}")
    if isinstance(node, ast.Name):
        if node.id.startswith("__"):
            raise ComputeError(f"disallowed name: {node.id!r}")
        if node.id not in names and node.id not in _CONSTS and node.id not in _FUNCS:
            raise ComputeError(f"unknown name {node.id!r}; bound series are {sorted(names)}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ComputeError("only these functions are allowed: " + ", ".join(sorted(_FUNCS)))
        if node.keywords:
            raise ComputeError("keyword arguments are not allowed")
    for child in ast.iter_child_nodes(node):
        _check(child, names)


def safe_eval(expression, namespace):
    """Evaluate `expression` over the bound series (each coerced to a float numpy array). Returns a
    python float (or int for argmin/argmax/len). Raises ComputeError on anything unsafe or on an
    expression that does not reduce to a single number."""
    if not isinstance(expression, str) or not expression.strip():
        raise ComputeError("empty expression")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ComputeError(f"syntax error: {exc.msg}")
    names = {k: np.asarray(v, dtype=float) for k, v in (namespace or {}).items()}
    _check(tree, set(names))
    env = {"__builtins__": {}, **_FUNCS, **_CONSTS, **names}
    try:
        val = eval(compile(tree, "<vmd_compute>", "eval"), env)   # ast pre-validated by _check
    except ComputeError:
        raise
    except Exception as exc:  # noqa: BLE001  numpy/math/zero-division etc.
        raise ComputeError(f"evaluation failed: {exc}")
    if isinstance(val, np.integer) or (isinstance(val, int) and not isinstance(val, bool)):
        return int(val)
    if isinstance(val, np.floating) or isinstance(val, numbers.Real):
        return float(val)
    raise ComputeError(f"expression did not reduce to a number (got {type(val).__name__})")
