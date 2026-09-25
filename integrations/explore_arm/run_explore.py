#!/usr/bin/env python3
"""run_explore.py — run the knowledge-free `explore` arm on the atlas-traj benchmark.

All NEW code lives in integrations/explore_arm/. The benchmark machinery — gold oracle,
worklist, scoring, failure bundles, summary table — is REUSED verbatim from
run_atlas_traj.py by (a) swapping the registered "vmd_ai" agent class for ExploreAgent
and (b) retargeting the shared task prompt's tool mentions at the lab surface. Scoring,
gold, and tolerances are byte-identical to the other arms.

  python run_explore.py --config config_explore.json --seeds 3
  python run_explore.py --config config_explore.json --hard --tag explore_hard

Flags mirror run_atlas_traj.py; --min-experiments / --max-experiments override the
config's protocol knobs for sweeps without editing the config file.
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent                    # integrations/explore_arm
SCIVIS = HERE.parent / "scivisagentbench"
DEFAULT_VMD = "/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64"

for _p in (str(HERE), str(SCIVIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hostpaths import default_runtime_path, resolve_vmd  # noqa: E402

_ORIG_PROMPTS = {}


def _add_bench_path(bench):
    p = str(Path(os.path.expanduser(bench)).resolve() / "benchmark")
    if p not in sys.path:
        sys.path.insert(0, p)


def install_explore_agent():
    """Swap the registered 'vmd_ai' agent class for ExploreAgent so run_atlas_traj.run_arm
    (which hardcodes get_agent('vmd_ai')) drives the explore arm without modification."""
    import vmd_ai_agent  # noqa: F401  registers the base VmdAiAgent under "vmd_ai"
    from evaluation_framework import agent_registry
    from explore_agent import ExploreAgent
    agent_registry._AGENT_REGISTRY["vmd_ai"] = ExploreAgent
    return ExploreAgent


def _retarget(text):
    """The ONLY prompt change vs the base arms: the tool mentions point at the lab surface."""
    return str(text).replace("run_vmd_command", "lab_try / lab_commit")


def explore_build_prompt(pdb, dcd, phrase, answer_path):
    """The shared easy-tier task prompt with tool mentions retargeted; every other word is
    identical to the base arms (controlled comparison)."""
    import run_atlas_traj
    orig = _ORIG_PROMPTS.get("easy") or run_atlas_traj.build_prompt
    return _retarget(orig(pdb, dcd, phrase, answer_path))


def _patch_prompts():
    import run_atlas_traj
    if "easy" not in _ORIG_PROMPTS:
        _ORIG_PROMPTS["easy"] = run_atlas_traj.build_prompt
        run_atlas_traj.build_prompt = explore_build_prompt
    try:
        import hard_metrics
    except ImportError:
        return
    if "hard" not in _ORIG_PROMPTS:
        _ORIG_PROMPTS["hard"] = hard_metrics.build_hard_prompt
        hard_metrics.build_hard_prompt = (
            lambda *a, **k: _retarget(_ORIG_PROMPTS["hard"](*a, **k)))


def level_overrides(level):
    """Map an --explore-level to the config knobs (the elicitation ladder E-T1/E-T2)."""
    if level is None:
        return {}
    table = {
        "enforced": {"explore_enforce": True, "explore_directive": "full"},
        "invited": {"explore_enforce": False, "explore_directive": "invite"},
        "free": {"explore_enforce": False, "explore_directive": "none"},
    }
    if str(level) not in table:
        raise SystemExit(f"[explore] unknown --explore-level {level!r} "
                         f"(choose from {sorted(table)})")
    return dict(table[str(level)])


def assert_model_served(model, served_ids):
    """ABORT (SystemExit) unless `model` is among the ids the inference server actually
    serves. Fail-fast twin of the sweep script's RUN-label guard: without it, a
    config/served mismatch 404s on every call and burns the whole run (the 0/498
    explore_enf_14b_hard lesson)."""
    if model in (served_ids or []):
        return
    raise SystemExit(
        f"[explore] ABORT: config wants model {model!r} but the server serves "
        f"{served_ids or '[] (nothing)'} — fix the serve (or the config) and relaunch. "
        f"No task was run.")


def fetch_served_ids(base_url, api_key, timeout=10):
    """Return the model ids the OpenAI-compatible server reports, or raise SystemExit
    if it is unreachable (a down server must also fail fast)."""
    import urllib.request
    url = str(base_url).rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key or ''}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"[explore] ABORT: cannot reach {url} ({exc}) — is vLLM up?")
    return [str(m.get("id")) for m in (data.get("data") or []) if m.get("id")]


def _prepare_config(config_path, overrides, resolved_vmd, runtime_default):
    """Write config + CLI overrides + machine-corrected paths to a temp file (run_arm
    re-reads the config file). vmd_bin becomes the machine-resolved binary — or is
    DROPPED when nothing resolves, so the bridge's own env/PATH resolution applies
    instead of raising on another machine's path. A missing or nonexistent
    vmd_ai_runtime_path is replaced by this clone's runtime."""
    cfg = json.load(open(config_path))
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    if resolved_vmd:
        cfg["vmd_bin"] = resolved_vmd
    else:
        cfg.pop("vmd_bin", None)
    rt = cfg.get("vmd_ai_runtime_path")
    if not rt or not Path(str(rt)).exists():
        cfg["vmd_ai_runtime_path"] = runtime_default
    fh = tempfile.NamedTemporaryFile("w", suffix=".json", prefix="explore_cfg_", delete=False)
    json.dump(cfg, fh, indent=2)
    fh.close()
    return fh.name


def main():
    # line-buffer stdout even when piped (| tee): otherwise the banners and per-task
    # lines sit in an 8KB block buffer for hours and the run looks silent.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bench", default=os.environ.get(
        "BENCH_DIR", str(Path.home() / "SciVisAgentBench")))
    ap.add_argument("--config", default=str(HERE / "config_explore.json"))
    ap.add_argument("--fixtures-dir", default=str(SCIVIS / "atlas_fixtures"))
    ap.add_argument("--vmd", default=None,
                    help="VMD binary for the GOLD oracle (default: auto-resolved for "
                         "this machine — env VMD_AI_VMD_BIN, then known install paths)")
    ap.add_argument("--out-dir", default=str(SCIVIS.parent.parent / "test_results" / "atlas_traj"))
    ap.add_argument("--tag", default="explore")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--gold-cache", default=None)
    ap.add_argument("--hard", action="store_true",
                    help="use the HARD/reasoning tier (hard_metrics + hard gold oracle)")
    ap.add_argument("--min-experiments", type=int, default=None,
                    help="override config explore_min_experiments (gate threshold)")
    ap.add_argument("--max-experiments", type=int, default=None,
                    help="override config explore_max_experiments (soft budget)")
    ap.add_argument("--explore-level", choices=["enforced", "invited", "free"], default=None,
                    help="elicitation level: enforced (gate+directive, default), "
                         "invited (advice, no gate), free (neutral tools only)")
    args = ap.parse_args()

    # a fallback bench checkout shipped inside the repo (used by tests / fresh machines)
    if not (Path(os.path.expanduser(args.bench)) / "benchmark").exists():
        in_repo = SCIVIS.parent.parent / "SciVisAgentBench-main"
        if (in_repo / "benchmark").exists():
            print(f"[explore] --bench {args.bench} not found; using in-repo {in_repo}")
            args.bench = str(in_repo)

    _add_bench_path(args.bench)
    install_explore_agent()
    _patch_prompts()

    # machine-aware paths: one config runs on the Mac dev box AND the GPU server.
    resolved_vmd = resolve_vmd(json.load(open(args.config)).get("vmd_bin"))
    args.vmd = args.vmd or resolved_vmd or DEFAULT_VMD
    overrides = {"explore_min_experiments": args.min_experiments,
                 "explore_max_experiments": args.max_experiments}
    overrides.update(level_overrides(args.explore_level))
    args.config = _prepare_config(
        args.config, overrides,
        resolved_vmd=resolved_vmd,
        runtime_default=default_runtime_path(),
    )
    print(f"[explore] VMD: agent={resolved_vmd or '(bridge env/PATH resolution)'} gold={args.vmd}")

    # fail fast on a config/served mismatch (OpenAI-compatible providers only).
    cfg = json.load(open(args.config))
    if cfg.get("base_url"):
        served = fetch_served_ids(cfg["base_url"], cfg.get("api_key"))
        assert_model_served(cfg.get("model"), served)
        print(f"[explore] served-model check OK: {cfg.get('model')}")

    sys.path.insert(0, str(HERE.parent))  # integrations/ -> run_provenance
    from run_provenance import append_run_manifest
    append_run_manifest(str(SCIVIS / "run_manifest.jsonl"), str(SCIVIS.parent.parent), runner="run_explore", run=args.tag, config=args.config, model=str(cfg.get("model") or ""), seeds=str(args.seeds))
    from run_atlas_traj import run_arm
    raise SystemExit(asyncio.run(run_arm(args)))


if __name__ == "__main__":
    main()
