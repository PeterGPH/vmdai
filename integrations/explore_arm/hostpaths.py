"""hostpaths.py — machine-aware path resolution for the explore arm.

The same code and config must run on both machines that host this project:

- the Mac dev box   — /Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64 (min 1.9.4a57)
- the tbgl GPU box  — /software/vmd-1.9.3/bin/vmd, model served by local vLLM

Resolution order for the VMD binary mirrors the shared bridge's _resolve_vmd (env
override first) and adds the known per-machine install paths, so a config written on
one machine never hard-crashes the other (the bridge RAISES on a nonexistent explicit
vmd_bin — this module exists so we never hand it one).
"""
import os
from pathlib import Path

KNOWN_VMD_PATHS = (
    "/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64",   # Mac dev box
    "/software/vmd-1.9.3/bin/vmd",                          # tbgl GPU server
)


def resolve_vmd(config_value=None, known=KNOWN_VMD_PATHS):
    """Return the first EXISTING binary among: the env overrides (VMD_AI_VMD_BIN,
    VMDBENCH_VMD_BIN), the config's value, then the known per-machine paths.
    None when nothing exists (callers then defer to the bridge's own resolution)."""
    candidates = [
        os.environ.get("VMD_AI_VMD_BIN"),
        os.environ.get("VMDBENCH_VMD_BIN"),
        os.environ.get("VMD_BIN"),        # the override name the tbgl run scripts use
        config_value,
        *known,
    ]
    for c in candidates:
        if c and Path(str(c)).exists():
            return str(c)
    return None


def default_runtime_path():
    """This clone's vmd_ai/runtime (explore_arm/ → integrations/ → vmd_ai/), so the
    config's runtime path never needs to be machine-specific."""
    return str(Path(__file__).resolve().parent.parent.parent / "runtime")
