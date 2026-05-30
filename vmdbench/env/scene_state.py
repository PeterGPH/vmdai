from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict

_PROBE = re.compile(r"^PROBE>\s*(?P<key>[^=]+)=(?P<val>.*)$")
_MOL = re.compile(r"^mol(?P<id>\d+)_(?P<attr>name|filename|filetype|numatoms|numframes|frame|numreps)$")
_REP = re.compile(r"^rep(?P<mol>\d+)_(?P<rep>\d+)_(?P<attr>style|selection|color|material|visible)$")
_SEL = re.compile(r"^sel(?P<idx>\d+)_(?P<attr>count|error)$")

# ERROR) lines from VMD infrastructure that are benign and should not be counted
# as user-script errors.  These arise from optional subsystems (STRIDE secondary-
# structure assignment) that degrade gracefully when they fail.
_BENIGN_ERROR = re.compile(
    r"(Unable to find Stride output file"
    r"|Stride::read_stride_record"
    r"|Call to Stride program failed)"
)

_IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


@dataclass
class Molecule:
    id: int
    name: str = ""
    filename: str = ""
    filetype: str = ""
    num_atoms: int = 0
    num_frames: int = 0
    cur_frame: int = 0


@dataclass
class Representation:
    mol_id: int
    rep_id: int
    style: str = ""        # full style string incl. params, e.g. "NewCartoon 0.3 ..."
    selection: str = ""
    color: str = ""        # coloring method, e.g. "Chain" or "ColorID 1"
    material: str = ""
    visible: bool = True

    @property
    def style_name(self) -> str:
        return self.style.split()[0] if self.style else ""


@dataclass
class Display:
    background: str = ""
    projection: str = ""
    axes: str = ""


@dataclass
class SceneState:
    molecules: list[Molecule] = field(default_factory=list)
    representations: list[Representation] = field(default_factory=list)
    selections: dict[str, int] = field(default_factory=dict)
    display: Display = field(default_factory=Display)
    camera: dict = field(default_factory=dict)   # {"center":[...], "rotate_matrix":[[...]], "scale_matrix":[[...]]}
    rendered_images: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def reps_for(self, selection: str) -> list[Representation]:
        return [r for r in self.representations if r.selection == selection]

    def camera_changed(self) -> bool:
        rot = self.camera.get("rotate_matrix")
        return rot is not None and rot != _IDENTITY


def _to_floats(tokens: list[str]) -> list[float]:
    out = []
    for x in tokens:
        try:
            out.append(float(x))
        except ValueError:
            out.append(float("nan"))  # tolerate malformed VMD output without crashing the parser
    return out


def _parse_tcl_matrix(s: str) -> list:
    """Parse VMD brace nesting like '{{1 0 0 0} {0 1 0 0}}' or '{3.9 2.6 1.5}' into nested float lists.

    Malformed numeric tokens degrade to NaN rather than raising, so one bad camera
    value cannot crash an entire benchmark run.
    """
    s = s.strip()
    if s.startswith("{{"):
        rows = re.findall(r"\{([^{}]*)\}", s)
        return [_to_floats(row.split()) for row in rows]
    inner = s.strip("{}")
    return _to_floats(inner.split()) if inner else []


def parse_probe_lines(stdout: str, selection_texts: list[str] | None = None) -> SceneState:
    selection_texts = selection_texts or []
    scene = SceneState()
    mols: dict[int, Molecule] = {}
    reps: dict[tuple[int, int], Representation] = {}

    for line in stdout.splitlines():
        line = line.rstrip()
        if line.startswith("ERROR)"):
            msg = line[len("ERROR)"):].strip()
            if not _BENIGN_ERROR.search(msg):
                scene.errors.append(msg)
            continue
        m = _PROBE.match(line)
        if not m:
            continue
        key, val = m.group("key").strip(), m.group("val").strip()

        if key == "body_error":
            scene.errors.append(val)
            continue
        mm = _MOL.match(key)
        if mm:
            mol = mols.setdefault(int(mm["id"]), Molecule(id=int(mm["id"])))
            attr = mm["attr"]
            if attr == "name": mol.name = val
            elif attr == "filename": mol.filename = val
            elif attr == "filetype": mol.filetype = val
            elif attr == "numatoms": mol.num_atoms = int(val or 0)
            elif attr == "numframes": mol.num_frames = int(val or 0)
            elif attr == "frame": mol.cur_frame = int(val or 0)
            continue
        rm = _REP.match(key)
        if rm:
            rk = (int(rm["mol"]), int(rm["rep"]))
            rep = reps.setdefault(rk, Representation(mol_id=rk[0], rep_id=rk[1]))
            attr = rm["attr"]
            if attr == "style": rep.style = val
            elif attr == "selection": rep.selection = val
            elif attr == "color": rep.color = val
            elif attr == "material": rep.material = val
            elif attr == "visible": rep.visible = (val.strip() == "1")
            continue
        sm = _SEL.match(key)
        if sm:
            idx = int(sm["idx"])
            text = selection_texts[idx] if idx < len(selection_texts) else f"sel{idx}"
            if sm["attr"] == "count":
                scene.selections[text] = int(val or 0)
            else:  # error
                scene.errors.append(val)
            continue
        if key == "display_background": scene.display.background = val
        elif key == "display_projection": scene.display.projection = val
        elif key == "axes_location": scene.display.axes = val
        elif key == "view_center": scene.camera["center"] = _parse_tcl_matrix(val)
        elif key == "view_rotate_matrix": scene.camera["rotate_matrix"] = _parse_tcl_matrix(val)
        elif key == "view_scale_matrix": scene.camera["scale_matrix"] = _parse_tcl_matrix(val)

    scene.molecules = [mols[k] for k in sorted(mols)]
    scene.representations = [reps[k] for k in sorted(reps)]
    return scene
