from __future__ import annotations
import os, shutil, subprocess
from dataclasses import dataclass
from pathlib import Path

from vmdbench.env.scene_state import SceneState, parse_probe_lines

# Introspection idioms verified against VMD 1.9.4a57 (macOS, -dispdev text).
_INTROSPECT_PROC = r"""
proc __vb_introspect {sels} {
    set mols [molinfo list]
    puts "PROBE> mol_list=$mols"
    if {[llength $mols] == 0} { return }
    puts "PROBE> mol_top=[molinfo top]"
    foreach m $mols {
        puts "PROBE> mol${m}_name=[molinfo $m get name]"
        puts "PROBE> mol${m}_filename=[lindex [molinfo $m get filename] 0]"
        puts "PROBE> mol${m}_filetype=[lindex [molinfo $m get filetype] 0]"
        puts "PROBE> mol${m}_numatoms=[molinfo $m get numatoms]"
        puts "PROBE> mol${m}_numframes=[molinfo $m get numframes]"
        puts "PROBE> mol${m}_frame=[molinfo $m get frame]"
        set nreps [molinfo $m get numreps]
        puts "PROBE> mol${m}_numreps=$nreps"
        for {set i 0} {$i < $nreps} {incr i} {
            set f [molinfo $m get "{rep $i} {selection $i} {color $i} {material $i}"]
            puts "PROBE> rep${m}_${i}_style=[lindex $f 0]"
            puts "PROBE> rep${m}_${i}_selection=[lindex $f 1]"
            puts "PROBE> rep${m}_${i}_color=[lindex $f 2]"
            puts "PROBE> rep${m}_${i}_material=[lindex $f 3]"
            puts "PROBE> rep${m}_${i}_visible=[mol showrep $m $i]"
        }
    }
    puts "PROBE> display_background=[color Display Background]"
    puts "PROBE> display_projection=[display get projection]"
    puts "PROBE> axes_location=[axes location]"
    set top [molinfo top]
    puts "PROBE> view_center=[molinfo $top get center]"
    puts "PROBE> view_rotate_matrix=[molinfo $top get rotate_matrix]"
    puts "PROBE> view_scale_matrix=[molinfo $top get scale_matrix]"
    set i 0
    foreach st $sels {
        if {[catch {set s [atomselect $top $st]; set n [$s num]; $s delete} e]} {
            puts "PROBE> sel${i}_error=$e"
        } else {
            puts "PROBE> sel${i}_count=$n"
        }
        incr i
    }
}
"""

# Known macOS VMD app bundle location.  When the default "vmd" binary on PATH
# does not have a proper VMDDIR (i.e. the scripts directory is missing), fall
# back to the app bundle binary so that atomselect macros and other VMD
# subsystems are available.
_MACOS_VMD_APP = Path("/Applications/VMD.app/Contents/vmd")


def _has_scripts(d: Path) -> bool:
    return (Path(d) / "scripts" / "vmd" / "atomselmacros.dat").exists()


def _macos_app_binary() -> Path | None:
    """Locate the VMD app-bundle binary for the current arch.

    The binary name encodes the platform (vmd_MACOSXARM64 on Apple Silicon,
    vmd_MACOSXX86_64 on Intel), so glob rather than hardcode a single arch.
    """
    if not _MACOS_VMD_APP.exists():
        return None
    for cand in sorted(_MACOS_VMD_APP.glob("vmd_MACOSX*")):
        if os.access(cand, os.X_OK):
            return cand
    return None


def _resolve_vmd(vmd_bin: str) -> tuple[str, str | None]:
    """Return (binary_path, vmddir_or_None).

    VMD sets its own VMDDIR at startup based on the *directory of the binary as
    called* (not the resolved symlink target).  When the binary is invoked via a
    symlink that lives in a directory without the VMD scripts (e.g. a ~/.local/bin
    symlink), VMDDIR points to the wrong place and atomselect macros are missing.

    Resolution order: explicit VMDBENCH_VMD_BIN override → valid env VMDDIR →
    PATH binary that has its scripts alongside → macOS app-bundle fallback (with
    injected VMDDIR). The second element is the VMDDIR to inject into the
    subprocess environment, or None when no override is needed.
    """
    # Explicit escape hatch for any platform / non-standard install.
    override = os.environ.get("VMDBENCH_VMD_BIN")
    if override:
        if not Path(override).exists():
            raise RuntimeError(f"VMDBENCH_VMD_BIN={override!r} does not exist")
        parent = Path(override).parent
        return override, (str(parent) if _has_scripts(parent) else None)

    # If VMDDIR is already set in the environment and the scripts exist there,
    # trust it — the caller knows what they are doing.
    env_vmddir = os.environ.get("VMDDIR", "")
    if env_vmddir and _has_scripts(Path(env_vmddir)):
        path = shutil.which(vmd_bin)
        if path is None:
            raise RuntimeError(f"VMD binary '{vmd_bin}' not found on PATH")
        return path, None

    path = shutil.which(vmd_bin)
    if path is None:
        raise RuntimeError(f"VMD binary '{vmd_bin}' not found on PATH")

    # Check whether the scripts directory sits next to the *called* binary
    # (NOT the resolved symlink target — VMD uses the called path, not realpath).
    if _has_scripts(Path(path).parent):
        return path, None  # properly installed; no VMDDIR override needed

    # Scripts not found alongside the called binary — try the macOS app bundle.
    app_bin = _macos_app_binary()
    if app_bin is not None and _has_scripts(_MACOS_VMD_APP):
        return str(app_bin), str(_MACOS_VMD_APP)

    # Fall back to whatever is on PATH and hope for the best.
    return path, None


@dataclass
class VmdRunResult:
    scene: SceneState
    stdout: str
    stderr: str
    returncode: int


def _tcl_list(items: list[str]) -> str:
    # VMD selections rarely contain braces; wrap each in braces. Document the limitation.
    return "[list " + " ".join("{" + s + "}" for s in items) + "]"


class HeadlessVMDEnv:
    def __init__(self, vmd_bin: str = "vmd", timeout_s: int = 180):
        self.vmd_bin, self._vmddir = _resolve_vmd(vmd_bin)
        self.timeout_s = timeout_s

    def _wrap(self, body: str, selection_texts: list[str]) -> str:
        sels = _tcl_list(selection_texts)
        return (
            _INTROSPECT_PROC
            + f"\nset __vb_sels {sels}\n"
            + "if {[catch {\n" + body + "\n} __vb_err]} { puts \"PROBE> body_error=$__vb_err\" }\n"
            + "__vb_introspect $__vb_sels\n"
            + "quit\n"
        )

    def _env(self) -> dict[str, str]:
        """Return the subprocess environment, injecting VMDDIR when needed."""
        env = dict(os.environ)
        if self._vmddir is not None:
            env["VMDDIR"] = self._vmddir
        return env

    def run(self, body: str, workdir: Path, selection_texts: list[str] | None = None) -> VmdRunResult:
        selection_texts = selection_texts or []
        workdir = Path(workdir)
        script = workdir / "__vb_run.tcl"
        script.write_text(self._wrap(body, selection_texts))
        proc = subprocess.run(
            [self.vmd_bin, "-dispdev", "text", "-eofexit", "-e", str(script)],
            cwd=str(workdir), capture_output=True, text=True, timeout=self.timeout_s,
            env=self._env(),
        )
        scene = parse_probe_lines(proc.stdout, selection_texts=selection_texts)
        return VmdRunResult(scene=scene, stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
