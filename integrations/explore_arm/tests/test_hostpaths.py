"""TDD tests for hostpaths.py — machine-aware VMD/runtime path resolution so the same
config runs on the Mac dev box and the GPU server (tbgl)."""
from pathlib import Path

import hostpaths
from hostpaths import default_runtime_path, resolve_vmd


def _fake_bin(tmp_path, name):
    p = tmp_path / name
    p.write_text("#!/bin/sh\n")
    return str(p)


def test_env_override_wins_over_config(monkeypatch, tmp_path):
    env_bin = _fake_bin(tmp_path, "env_vmd")
    cfg_bin = _fake_bin(tmp_path, "cfg_vmd")
    monkeypatch.setenv("VMD_AI_VMD_BIN", env_bin)
    assert resolve_vmd(cfg_bin, known=()) == env_bin


def test_nonexistent_env_is_skipped(monkeypatch, tmp_path):
    cfg_bin = _fake_bin(tmp_path, "cfg_vmd")
    monkeypatch.setenv("VMD_AI_VMD_BIN", "/nonexistent/env/vmd")
    monkeypatch.delenv("VMDBENCH_VMD_BIN", raising=False)
    assert resolve_vmd(cfg_bin, known=()) == cfg_bin


def test_vmdbench_env_var_also_honored(monkeypatch, tmp_path):
    env_bin = _fake_bin(tmp_path, "bench_vmd")
    monkeypatch.delenv("VMD_AI_VMD_BIN", raising=False)
    monkeypatch.setenv("VMDBENCH_VMD_BIN", env_bin)
    assert resolve_vmd(None, known=()) == env_bin


def test_vmd_bin_env_var_honored_like_the_server_run_scripts(monkeypatch, tmp_path):
    # the tbgl shell scripts use VMD="${VMD_BIN:-/software/...}" — same override name here
    env_bin = _fake_bin(tmp_path, "script_vmd")
    monkeypatch.delenv("VMD_AI_VMD_BIN", raising=False)
    monkeypatch.delenv("VMDBENCH_VMD_BIN", raising=False)
    monkeypatch.setenv("VMD_BIN", env_bin)
    assert resolve_vmd(None, known=()) == env_bin


def test_nonexistent_config_falls_to_first_existing_known(monkeypatch, tmp_path):
    monkeypatch.delenv("VMD_AI_VMD_BIN", raising=False)
    monkeypatch.delenv("VMDBENCH_VMD_BIN", raising=False)
    known_bin = _fake_bin(tmp_path, "known_vmd")
    got = resolve_vmd("/nonexistent/cfg/vmd",
                      known=("/nonexistent/known/a", known_bin))
    assert got == known_bin


def test_nothing_valid_returns_none(monkeypatch):
    monkeypatch.delenv("VMD_AI_VMD_BIN", raising=False)
    monkeypatch.delenv("VMDBENCH_VMD_BIN", raising=False)
    assert resolve_vmd("/nonexistent/cfg/vmd", known=("/nonexistent/known",)) is None


def test_known_paths_cover_mac_and_gpu_server():
    assert "/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64" in hostpaths.KNOWN_VMD_PATHS
    assert "/software/vmd-1.9.3/bin/vmd" in hostpaths.KNOWN_VMD_PATHS


def test_default_runtime_path_is_this_repos_runtime():
    p = Path(default_runtime_path())
    assert p.name == "runtime"
    assert (p / "vmd_ai_runtime").exists()   # true on any clone of this repo
