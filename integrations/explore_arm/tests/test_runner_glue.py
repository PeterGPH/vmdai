"""Tests for run_explore's config preparation: CLI overrides + machine-aware path fixing
(one config file must work on both the Mac dev box and the GPU server), and the
served-model guard (a config/served mismatch must ABORT before any task runs — the
0/498 lesson of 2026-08-28: every call 404ed for hours instead of failing fast)."""
import json

import pytest

from run_explore import _prepare_config, assert_model_served, level_overrides


def test_level_overrides_map_the_elicitation_ladder():
    assert level_overrides("enforced") == {"explore_enforce": True, "explore_directive": "full"}
    assert level_overrides("invited") == {"explore_enforce": False, "explore_directive": "invite"}
    assert level_overrides("free") == {"explore_enforce": False, "explore_directive": "none"}
    assert level_overrides(None) == {}
    with pytest.raises(SystemExit):
        level_overrides("bogus")


def test_served_guard_passes_on_exact_match():
    assert_model_served("Qwen/Qwen2.5-14B-Instruct",
                        ["Qwen/Qwen2.5-14B-Instruct"])  # no raise


def test_served_guard_aborts_on_mismatch_naming_both_sides():
    with pytest.raises(SystemExit) as e:
        assert_model_served("Qwen/Qwen2.5-14B-Instruct",
                            ["Qwen/Qwen2.5-72B-Instruct-GPTQ-Int8"])
    msg = str(e.value)
    assert "14B" in msg and "72B" in msg      # says what was wanted AND what is served


def test_served_guard_aborts_on_empty_server_list():
    with pytest.raises(SystemExit):
        assert_model_served("m", [])


def _base(tmp_path, **kw):
    cfg = {"model": "m", "explore_min_experiments": 3}
    cfg.update(kw)
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(cfg))
    return str(p)


def _load(path):
    return json.load(open(path))


def test_overrides_applied_and_base_preserved(tmp_path):
    out = _prepare_config(_base(tmp_path), {"explore_min_experiments": 5,
                                            "explore_max_experiments": None},
                          resolved_vmd=None, runtime_default="/rt")
    merged = _load(out)
    assert merged["model"] == "m"
    assert merged["explore_min_experiments"] == 5
    assert "explore_max_experiments" not in merged


def test_resolved_vmd_is_written_into_config(tmp_path):
    out = _prepare_config(_base(tmp_path, vmd_bin="/nonexistent/mac/vmd"), {},
                          resolved_vmd="/software/vmd-1.9.3/bin/vmd", runtime_default="/rt")
    assert _load(out)["vmd_bin"] == "/software/vmd-1.9.3/bin/vmd"


def test_unresolvable_vmd_bin_is_dropped_so_bridge_env_resolution_applies(tmp_path):
    out = _prepare_config(_base(tmp_path, vmd_bin="/nonexistent/mac/vmd"), {},
                          resolved_vmd=None, runtime_default="/rt")
    assert "vmd_bin" not in _load(out)


def test_missing_runtime_path_gets_default(tmp_path):
    out = _prepare_config(_base(tmp_path), {}, resolved_vmd=None, runtime_default="/rt")
    assert _load(out)["vmd_ai_runtime_path"] == "/rt"


def test_nonexistent_runtime_path_gets_default(tmp_path):
    out = _prepare_config(_base(tmp_path, vmd_ai_runtime_path="/nonexistent/runtime"), {},
                          resolved_vmd=None, runtime_default="/rt")
    assert _load(out)["vmd_ai_runtime_path"] == "/rt"


def test_existing_runtime_path_is_kept(tmp_path):
    rt = tmp_path / "myruntime"
    rt.mkdir()
    out = _prepare_config(_base(tmp_path, vmd_ai_runtime_path=str(rt)), {},
                          resolved_vmd=None, runtime_default="/rt")
    assert _load(out)["vmd_ai_runtime_path"] == str(rt)
