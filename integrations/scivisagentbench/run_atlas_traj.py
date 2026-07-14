#!/usr/bin/env python3
"""run_atlas_traj.py — agent-vs-ATLAS trajectory test (sibling of run_multistructure.py).

Same arms (none / rag / wiki / inject) and the SAME agent, but each task loads a STRUCTURE +
its MD TRAJECTORY and asks for a trajectory-AVERAGED observable (mean Rg / RMSD-to-frame0 /
RMSF / SASA, and the frame count), scored against gold_oracle_traj.tcl. This is the harder,
dynamics-aware analogue of the static 25-cell grid.

Fixture pairs live in --fixtures-dir as  <chain>.pdb  +  <chain>_*.dcd.

  python run_atlas_traj.py --config config_arm_none.json --tag none --seeds 3 \
      --fixtures-dir atlas_fixtures --vmd /software/vmd-1.9.3/bin/vmd
"""
import argparse, asyncio, glob, json, os, re, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORACLE = HERE / "gold_oracle_traj.tcl"
HARD_ORACLE = HERE / "gold_oracle_traj_hard.tcl"
DEFAULT_VMD = "/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64"
FLOAT = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

# metric key -> (prompt phrase, absolute tolerance, scored?)
METRICS = {
    "nframes":   ("the number of trajectory frames loaded into the molecule "
                  "(molinfo top get numframes), as one integer", 0.5, True),
    "meanrg":    ("the MEAN radius of gyration of the protein AVERAGED over ALL trajectory "
                  "frames, in Angstroms", 0.4, True),
    "meanrmsd":  ("the MEAN alpha-carbon RMSD to the FIRST frame, averaged over all frames "
                  "(align each frame to frame 0 first with 'measure fit'), in Angstroms", 0.5, True),
    "mean_rmsf": ("the MEAN per-residue alpha-carbon RMSF over the trajectory (align the frames "
                  "to frame 0 first, then average VMD's per-residue 'measure rmsf'), in Angstroms", 0.3, True),
    "meansasa":  ("the MEAN solvent-accessible surface area of the protein averaged over all "
                  "frames, using Tcl 'measure sasa 1.4', in square Angstroms", 400.0, True),
}


def compute_gold(vmd, pdb, dcd, oracle=ORACLE):
    env = dict(os.environ, GOLD_STRUCT=pdb, GOLD_TRAJ=dcd)
    try:
        out = subprocess.run([vmd, "-dispdev", "text", "-e", str(oracle)], env=env,
                             capture_output=True, text=True, timeout=600).stdout
    except Exception as e:
        return {}, f"VMD failed: {e}"
    gold = {}
    for line in out.splitlines():
        m = re.match(r"\s*GOLD\s+(\S+)\s+(\S+)", line)
        if m:
            try: gold[m.group(1)] = float(m.group(2))
            except ValueError: pass
    return gold, (None if gold else "no GOLD lines (check VMD path / files)")


def build_prompt(pdb, dcd, phrase, answer_path):
    return (
        "You are controlling VMD headlessly through the run_vmd_command tool (Tcl).\n"
        "1. Load the structure and ITS TRAJECTORY (both files):\n"
        f'     mol new "{pdb}" waitfor all\n'
        f'     mol addfile "{dcd}" waitfor all\n'
        f"2. Compute {phrase}. Loop over all frames: 'set n [molinfo top get numframes]', then "
        "for each frame set the selection's frame with '$sel frame $i' before measuring.\n"
        "3. Write ONLY that single numeric value (digits only, no words) to this exact file:\n"
        f'   set f [open "{answer_path}" w]; puts $f $value; close $f\n'
        "Finish in as few commands as possible."
    )


def select_mode(hard):
    """Return (metrics, prompt_builder, oracle) for the easy or hard tier. Pure — unit-tested."""
    if hard:
        from hard_metrics import HARD_METRICS, build_hard_prompt
        return HARD_METRICS, build_hard_prompt, HARD_ORACLE
    return METRICS, build_prompt, ORACLE


def pairs_in(fixtures_dir):
    """(name, abs_pdb, abs_dcd) for each <chain>.pdb that has a sibling <chain>_*.dcd."""
    out = []
    for pdb in sorted(glob.glob(os.path.join(fixtures_dir, "*.pdb"))):
        name = Path(pdb).stem
        dcds = sorted(glob.glob(os.path.join(fixtures_dir, f"{name}_*.dcd")))
        if dcds:
            out.append((name, os.path.abspath(pdb), os.path.abspath(dcds[0])))
    return out


def load_gold(pairs, vmd, cache_path=None, oracle=ORACLE):
    """Return {name: {metric: value}} for all pairs. Gold is deterministic, so when a
    cache_path is given (populated once by precompute_gold_traj.py) we reuse cached chains and
    only run VMD for misses — then write the merged cache back atomically. This keeps concurrent
    arms from each recomputing the same gold."""
    cache = {}
    if cache_path and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path))
        except (ValueError, OSError):
            cache = {}
    gold, computed = {}, False
    for name, pdb, dcd in pairs:
        c = cache.get(name)
        if c:
            gold[name] = {k: float(v) for k, v in c.items()}
            print(f"[gold] {name}: (cached)")
        else:
            g, err = compute_gold(vmd, pdb, dcd, oracle=oracle)
            gold[name] = g
            computed = True
            print(f"[gold] {name}: " + (", ".join(f"{k}={v}" for k, v in sorted(g.items()))
                                        if g else f"(FAILED: {err})"))
    if cache_path and computed:                      # persist any freshly-computed chains
        merged = {**cache, **{k: v for k, v in gold.items() if v}}
        tmp = f"{cache_path}.tmp.{os.getpid()}"
        try:
            json.dump(merged, open(tmp, "w"), indent=2, default=str)
            os.replace(tmp, cache_path)              # atomic — safe under concurrent writers
        except OSError:
            pass
    return gold


async def _run_worklist(items, agents, run_one):
    """Drain `items` across len(agents) worker coroutines, one agent each. run_one(agent, item) is
    awaited per task. Bounded concurrency = len(agents); each item runs exactly once on some agent.
    Single-threaded asyncio: `cursor` read+increment has no await between it, so it is atomic."""
    cursor = {"i": 0}

    async def worker(agent):
        while True:
            i = cursor["i"]
            if i >= len(items):
                return
            cursor["i"] = i + 1
            await run_one(agent, items[i])

    await asyncio.gather(*(worker(a) for a in agents))


async def run_arm(args):
    bench = Path(os.path.expanduser(args.bench)).resolve()
    sys.path.insert(0, str(bench / "benchmark"))   # evaluation_framework
    sys.path.insert(0, str(HERE))                  # vmd_ai_agent + run_multistructure
    import vmd_ai_agent  # noqa: F401  (registers @register_agent("vmd_ai"))
    from evaluation_framework import get_agent
    from run_multistructure import _save_failure    # reuse the failure-saving verbatim

    config = json.load(open(args.config))
    metrics, prompt_builder, oracle = select_mode(getattr(args, "hard", False))
    skip_fn = None
    if getattr(args, "hard", False):
        from hard_metrics import skip_metric_for_chain as skip_fn
    pairs = pairs_in(args.fixtures_dir)
    if not pairs:
        print(f"No <chain>.pdb + <chain>_*.dcd pairs in {args.fixtures_dir}")
        return 1
    outdir = Path(os.path.expanduser(args.out_dir)) / args.tag
    outdir.mkdir(parents=True, exist_ok=True)

    gold = load_gold(pairs, os.path.expanduser(args.vmd), args.gold_cache, oracle=oracle)

    seeds = max(1, int(args.seeds))
    conc = max(1, int(getattr(args, "concurrency", 1)))
    save_fails = os.environ.get("VMD_AI_SAVE_FAILURES", "1") != "0"
    if save_fails:
        (outdir / "failures.jsonl").unlink(missing_ok=True)

    # ---- flat work-list (skip_fn applied once, up front) ----
    items = []
    for seed in range(1, seeds + 1):
        for name, pdb, dcd in pairs:
            for mkey, (phrase, tol, scored) in metrics.items():
                if skip_fn and skip_fn(mkey, gold.get(name, {})):
                    continue
                items.append((seed, name, pdb, dcd, mkey, phrase, tol, scored))

    results, detail = {}, {}
    counters = {"fail_saved": 0}

    async def run_one(agent, item):
        seed, name, pdb, dcd, mkey, phrase, tol, scored = item
        ans_path = str(outdir / f"{name}__{mkey}__s{seed}.txt")
        if os.path.exists(ans_path):
            os.remove(ans_path)
        prompt = prompt_builder(pdb, dcd, phrase, ans_path)
        case_name = f"{name}_{mkey}_s{seed}"
        tcfg = {"working_dir": str(outdir), "case_dir": str(outdir),
                "case_name": case_name, "timeout": args.timeout}
        result = None
        try:
            result = await agent.run_task(prompt, tcfg)
        except Exception as exc:  # noqa: BLE001
            print(f"  [s{seed}] {name}/{mkey}: run error: {exc}")
        g = gold.get(name, {}).get(mkey)
        val = None
        if os.path.exists(ans_path):
            fs = [float(x) for x in FLOAT.findall(open(ans_path, errors="replace").read())]
            if fs and g is not None:
                val = min(fs, key=lambda x: abs(x - g))
        ok = (val is not None and g is not None and abs(val - g) <= tol) if scored else None
        results.setdefault((name, mkey), []).append(ok)
        detail[f"{name}__{mkey}__s{seed}"] = {"gold": g, "agent": val, "ok": ok}
        print(f"  [s{seed}] {name:8} {mkey:10} gold={g} agent={val} -> "
              + ("PASS" if ok else ("FAIL" if ok is False else "-")))
        if save_fails and scored and ok is False:
            _save_failure(outdir, name, mkey, seed, phrase, tol, g, val, ans_path, result, args.tag)
            counters["fail_saved"] += 1

    # ---- pool of `conc` isolated agents (each own bridge/VMD/_series) ----
    print(f"  [arm {args.tag}] {len(items)} tasks over {conc} concurrent agent(s)")
    agents = []
    try:
        for _ in range(conc):
            a = get_agent("vmd_ai")(config)
            agents.append(a)            # append BEFORE setup so a mid-pool setup failure still tears down
            await a.setup()
        await _run_worklist(items, agents, run_one)
    finally:
        for a in agents:
            try:
                await a.teardown()
            except Exception:  # noqa: BLE001
                pass

    n_fail_saved = counters["fail_saved"]

    names = [p[0] for p in pairs]
    print(f"\n=== ATLAS-TRAJ CORRECTNESS (pass-rate over {seeds} seed(s)) — arm: {args.tag} ===")
    print(f"  {'metric':10} " + " ".join(f"{n:>9}" for n in names) + "    total")
    gp = gt = 0
    for m, (_, _, sc) in metrics.items():
        if not sc:
            continue
        cells, mp, mt = [], 0, 0
        for n in names:
            oks = [x for x in results.get((n, m), []) if x is not None]
            p, t = sum(1 for x in oks if x), len(oks)
            cells.append(f"{p}/{t}" if t else "-"); mp += p; mt += t
        gp += mp; gt += mt
        print(f"  {m:10} " + " ".join(f"{c:>9}" for c in cells) + f"    {mp}/{mt}")
    print(f"  => overall: {gp}/{gt} checks passed (chains x metrics x seeds)")
    json.dump(detail, open(outdir / "summary.json", "w"), indent=2, default=str)
    print(f"  saved -> {outdir / 'summary.json'}")
    if n_fail_saved:
        print(f"  saved {n_fail_saved} failure bundle(s) -> {outdir / 'failures'}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default=os.environ.get("BENCH_DIR", str(Path.home() / "SciVisAgentBench")))
    ap.add_argument("--config", required=True)
    ap.add_argument("--fixtures-dir", default=str(HERE / "atlas_fixtures"))
    ap.add_argument("--vmd", default=DEFAULT_VMD)
    ap.add_argument("--out-dir", default=str(HERE.parent.parent / "test_results" / "atlas_traj"))
    ap.add_argument("--tag", default="none")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--seeds", type=int, default=1, help="repeats per task; >1 de-noises no-answers")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="tasks run concurrently within the arm, each on its own agent+VMD "
                         "(default 1 = sequential; try 8 to saturate vLLM's KV cache)")
    ap.add_argument("--gold-cache", default=None,
                    help="JSON gold cache (from precompute_gold_traj.py) — load it instead of "
                         "recomputing gold per run; misses are computed and appended")
    ap.add_argument("--hard", action="store_true",
                    help="use the HARD/reasoning tier (hard_metrics + gold_oracle_traj_hard.tcl)")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run_arm(args)))


if __name__ == "__main__":
    main()
