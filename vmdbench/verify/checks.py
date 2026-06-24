from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from vmdbench.env.scene_state import SceneState
from vmdbench.spec.assertions import CUSTOM_CHECKS


@dataclass
class CheckContext:
    workdir: Path


@dataclass
class CheckResult:
    kind: str
    passed: bool
    observed: Any = None
    where: dict = field(default_factory=dict)


_EVALUATORS: dict[str, Callable[[dict, SceneState, CheckContext, dict], CheckResult]] = {}


def _register(kind):
    def deco(fn):
        _EVALUATORS[kind] = fn
        return fn
    return deco


def evaluate(assertion: dict, scene: SceneState, ctx: CheckContext) -> CheckResult:
    kind = assertion["kind"]
    where = assertion.get("where", {})
    fn = _EVALUATORS.get(kind)
    if fn is None:
        raise KeyError(f"no evaluator for assertion kind {kind!r}")
    return fn(where, scene, ctx, assertion)


@_register("molecule_loaded")
def _molecule_loaded(where, scene, ctx, a):
    if not scene.molecules:
        return CheckResult("molecule_loaded", False, observed=0, where=where)
    pdb = where.get("pdb")
    if pdb:
        ok = any(pdb.lower() in (m.name or "").lower() or pdb.lower() in (m.filename or "").lower()
                 for m in scene.molecules)
        return CheckResult("molecule_loaded", ok, observed=[m.name for m in scene.molecules], where=where)
    return CheckResult("molecule_loaded", True, observed=len(scene.molecules), where=where)


@_register("representation_exists")
def _rep_exists(where, scene, ctx, a):
    sel = where.get("selection")
    style = where.get("style")
    color = where.get("color")
    material = where.get("material")
    want_vis = where.get("visible")
    matches = []
    for r in scene.representations:
        if sel is not None and r.selection != sel: continue
        if style is not None and r.style_name != style: continue
        if color is not None and color.lower() not in r.color.lower(): continue
        if material is not None and r.material != material: continue
        if want_vis is not None and r.visible != bool(want_vis): continue
        matches.append((r.selection, r.style_name, r.color))
    return CheckResult("representation_exists", bool(matches), observed=matches or
                       [(r.selection, r.style_name) for r in scene.representations], where=where)


@_register("representation_count")
def _rep_count(where, scene, ctx, a):
    n = len(scene.representations)
    ok = True
    if "min" in where: ok = ok and n >= where["min"]
    if "max" in where: ok = ok and n <= where["max"]
    if "expect" in where: ok = ok and n == where["expect"]
    return CheckResult("representation_count", ok, observed=n, where=where)


@_register("selection_visible")
def _sel_visible(where, scene, ctx, a):
    sel = where["selection"]
    want = bool(a.get("visible", True))
    shown = any(r.selection == sel and r.visible for r in scene.representations)
    return CheckResult("selection_visible", shown == want, observed=shown, where=where)


@_register("selection_count")
def _sel_count(where, scene, ctx, a):
    sel = where["selection"]
    if sel not in scene.selections:
        return CheckResult("selection_count", False, observed=f"selection {sel!r} not evaluated", where=where)
    n = scene.selections[sel]
    ok = True
    if "expect" in where: ok = ok and n == where["expect"]
    if "min" in where: ok = ok and n >= where["min"]
    if "max" in where: ok = ok and n <= where["max"]
    if where.get("nonempty"): ok = ok and n > 0
    return CheckResult("selection_count", ok, observed=n, where=where)


@_register("display_property")
def _display(where, scene, ctx, a):
    ok = True
    if "bg_color" in where: ok = ok and scene.display.background.lower() == where["bg_color"].lower()
    if "projection" in where: ok = ok and scene.display.projection.lower() == where["projection"].lower()
    if "axes" in where: ok = ok and scene.display.axes.lower() == where["axes"].lower()
    return CheckResult("display_property", ok,
                       observed={"bg": scene.display.background, "proj": scene.display.projection,
                                 "axes": scene.display.axes}, where=where)


@_register("frames_loaded")
def _frames(where, scene, ctx, a):
    n = max((m.num_frames for m in scene.molecules), default=0)
    ok = True
    if "min" in where: ok = ok and n >= where["min"]
    if "max" in where: ok = ok and n <= where["max"]
    return CheckResult("frames_loaded", ok, observed=n, where=where)


@_register("camera_changed")
def _camera(where, scene, ctx, a):
    changed = scene.camera_changed()
    want = where.get("from_default", True)
    return CheckResult("camera_changed", changed == bool(want), observed=changed, where=where)


@_register("distinct_chain_colors")
def _distinct_colors(where, scene, ctx, a):
    min_distinct = where.get("min_distinct", 2)
    by_chain = any(r.color.lower() == "chain" for r in scene.representations)
    distinct = len({r.color for r in scene.representations if r.visible})
    ok = by_chain or distinct >= min_distinct
    return CheckResult("distinct_chain_colors", ok, observed={"by_chain": by_chain, "distinct": distinct}, where=where)


@_register("no_runtime_errors")
def _no_errors(where, scene, ctx, a):
    return CheckResult("no_runtime_errors", not scene.errors, observed=scene.errors, where=where)


@_register("scalar_within")
def _scalar_within(where, scene, ctx, a):
    """Assert a named scalar the solution emitted (PROBE> measure_<name>=<val>)
    falls in a tolerance band. This checks *correctness of a computed value*
    (Rg, a distance, SASA), which outcome/LLM-judge benchmarks do not."""
    name = where["name"]
    if name not in scene.measures:
        return CheckResult("scalar_within", False,
                           observed=f"measure {name!r} not emitted by the solution", where=where)
    val = scene.measures[name]
    ok = (val == val)  # reject NaN
    if "expect" in where:
        ok = ok and abs(val - where["expect"]) <= where.get("tol", 0.0)
    if "min" in where:
        ok = ok and val >= where["min"]
    if "max" in where:
        ok = ok and val <= where["max"]
    return CheckResult("scalar_within", bool(ok), observed=val, where=where)


def _is_image(path: Path) -> bool:
    try:
        head = path.read_bytes()[:8]
    except OSError:
        return False
    # TGA has no strong magic; accept PNG magic, or non-trivial TGA (footer/size handled by min_bytes).
    if head.startswith(b"\x89PNG"): return True
    return path.suffix.lower() in {".tga", ".png", ".ppm", ".bmp"}


@_register("file_rendered")
def _file_rendered(where, scene, ctx, a):
    path = ctx.workdir / where["path"]
    min_bytes = where.get("min_bytes", 1000)
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    ok = exists and size >= min_bytes
    if where.get("must_be_image"):
        ok = ok and _is_image(path)
    return CheckResult("file_rendered", ok, observed={"exists": exists, "size": size}, where=where)


@_register("file_exists")
def _file_exists(where, scene, ctx, a):
    path = ctx.workdir / where["path"]
    return CheckResult("file_exists", path.exists(), observed=path.exists(), where=where)


@_register("custom_check")
def _custom(where, scene, ctx, a):
    fn = CUSTOM_CHECKS[where["ref"]]
    return CheckResult("custom_check", bool(fn(scene, ctx, where)), observed=where.get("ref"), where=where)
