#!/usr/bin/env python3
"""run_multistructure.py — generalize the correctness test across many structures.

Drives the VmdAiAgent (the SAME arms as the SciVisAgentBench ablation — none / inject /
autorag / …) over a structure × portable-metric grid, captures each numeric answer, and
scores it against gold computed by gold_oracle_multi.tcl. The metrics (Rg, atom / residue
counts, CA–CA first/last distance, SASA) compute on ANY protein, so adding a structure is
just dropping a .pdb/.cif into the fixtures dir.

Run on the Mac (vLLM server + tunnel up), once per arm, then compare summaries:
  python run_multistructure.py --bench ~/SciVisAgentBench --config config_arm_none.json   --tag none
  python run_multistructure.py --bench ~/SciVisAgentBench --config config_arm_inject.json --tag inject
"""
import argparse, asyncio, glob, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORACLE = HERE / "gold_oracle_multi.tcl"
DEFAULT_VMD = "/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64"
FLOAT = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

# metric key -> (prompt phrase, absolute tolerance, scored?)
METRICS = {
    "rgyr":      ("the radius of gyration of the protein, in Angstroms", 0.2, True),
    "natoms":    ("the total number of atoms loaded from the structure", 0.5, True),
    "nresidues": ("the total number of amino-acid residues in the protein across ALL chains "
                  "(residue numbers repeat between chains, so count VMD's unique 'residue' attribute, "
                  "i.e. llength [lsort -unique [$sel get residue]]), as one integer", 0.5, True),
    "ca_dist":   ("the distance in Angstroms between the FIRST and the LAST alpha-carbon "
                  "(CA) atom of the protein, in atom order", 0.2, True),
    "sasa":      ("the solvent-accessible surface area of the protein in square Angstroms, "
                  "using Tcl 'measure sasa 1.4'", 2.0, True),
}


def compute_gold(vmd, structure):
    env = dict(os.environ, GOLD_STRUCT=structure)
    try:
        out = subprocess.run([vmd, "-dispdev", "text", "-e", str(ORACLE)],
                             env=env, capture_output=True, text=True, timeout=300).stdout
    except Exception as e:
        return {}, f"VMD failed: {e}"
    gold = {}
    for line in out.splitlines():
        m = re.match(r"\s*GOLD\s+(\S+)\s+(\S+)", line)
        if m:
            try: gold[m.group(1)] = float(m.group(2))
            except ValueError: pass
    return gold, (None if gold else "no GOLD lines (check VMD path / structure)")


def build_prompt(struct_path, phrase, answer_path):
    return (
        "You are controlling VMD headlessly through the run_vmd_command tool (Tcl).\n"
        f'1. Load the structure: mol new "{struct_path}"\n'
        f"2. Compute {phrase}.\n"
        "3. Write ONLY that single numeric value (digits only, no extra words) to this exact file:\n"
        f'   set f [open "{answer_path}" w]; puts $f $value; close $f\n'
        "Create the directory first with 'file mkdir' if needed. Finish in as few commands as possible."
    )


def load_gold(structures, vmd, cache_path=None):
    """{NAME: {metric: value}} per structure. Gold is deterministic, so with a cache_path
    (populated once by precompute_gold_multi.py) we reuse cached structures and only run VMD
    for misses — then write the merged cache back atomically. Keeps concurrent arms from each
    recomputing the same gold."""
    cache = {}
    if cache_path and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path))
        except (ValueError, OSError):
            cache = {}
    gold, computed = {}, False
    for s in structures:
        name = Path(s).stem.upper()
        c = cache.get(name)
        if c:
            gold[name] = {k: float(v) for k, v in c.items()}
            print(f"[gold] {name}: (cached)")
        else:
            g, err = compute_gold(vmd, s)
            gold[name] = g
            computed = True
            print(f"[gold] {name}: " + (", ".join(f"{k}={v}" for k, v in sorted(g.items()))
                                        if g else f"(FAILED: {err})"))
    if cache_path and computed:
        merged = {**cache, **{k: v for k, v in gold.items() if v}}
        tmp = f"{cache_path}.tmp.{os.getpid()}"
        try:
            json.dump(merged, open(tmp, "w"), indent=2, default=str)
            os.replace(tmp, cache_path)              # atomic — safe under concurrent writers
        except OSError:
            pass
    return gold


def _save_failure(outdir, name, mkey, seed, phrase, tol, gold, agent_val, ans_path, result, tag):
    """Persist a failed case's generated Tcl + a debug log under outdir/failures/, and append a
    one-line record to outdir/failures.jsonl for quick scanning. Returns the failures dir.

    .tcl  — copy of the agent's run_vmd_command transcript (working cmds + errored attempts).
    .log  — prompt phrase, gold vs agent, the answer the model wrote, the full model response,
            every run_vmd_command with its ok/err, and any harness error (timeout/exception).
    failures.jsonl — {case,structure,metric,seed,gold,agent,tol,answer,harness_error,tcl,log}."""
    case_name = f"{name}_{mkey}_s{seed}"
    fails = Path(outdir) / "failures"
    fails.mkdir(exist_ok=True)
    src_tcl = Path(outdir) / f"{case_name}.tcl"          # agent wrote this in run_task()
    tcl_dst = None
    if src_tcl.exists():
        tcl_dst = fails / f"{case_name}.tcl"
        shutil.copyfile(src_tcl, tcl_dst)
    md = (getattr(result, "metadata", None) or {}) if result is not None else {}
    tcl_log = md.get("tcl_log") or []
    response = (md.get("assistant_response") or md.get("partial_response") or "").strip()
    err = getattr(result, "error", None) if result is not None else "run_task raised (see console)"
    try:
        answer = open(ans_path, errors="replace").read().strip() if os.path.exists(ans_path) else "(no answer file written)"
    except OSError:
        answer = "(unreadable)"
    lines = [
        f"=== FAIL  {case_name}  (arm {tag}) ===",
        f"metric phrase : {phrase}",
        f"gold={gold}  agent={agent_val}  tol={tol}  ok=False",
        f"answer file ({os.path.basename(ans_path)}): {answer!r}",
        f"duration={md.get('duration')}s  harness_error={err or '-'}",
        "",
        "--- model response ---",
        response or "(empty)",
        "",
        f"--- run_vmd_command calls ({len(tcl_log)}) ---",
    ]
    if tcl_log:
        for e in tcl_log:
            mark = "ok " if e.get("ok") else ("ERR" if e.get("ok") is False else "?? ")
            lines.append(f"[{mark}] {(e.get('cmd') or '').strip()}")
            if e.get("err"):
                lines.append(f"        ;# ERR: {str(e['err']).strip()}")
    else:
        lines.append("(no run_vmd_command calls recorded — model used semantic tools or stalled)")
    log_dst = fails / f"{case_name}.log"
    log_dst.write_text("\n".join(lines) + "\n")
    rec = {"case": case_name, "structure": name, "metric": mkey, "seed": seed,
           "gold": gold, "agent": agent_val, "tol": tol, "ok": False,
           "answer": answer, "harness_error": err, "duration": md.get("duration"),
           "tcl": str(tcl_dst) if tcl_dst else None, "log": str(log_dst)}
    with open(Path(outdir) / "failures.jsonl", "a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")
    return fails


async def run_arm(args):
    bench = Path(os.path.expanduser(args.bench)).resolve()
    sys.path.insert(0, str(bench / "benchmark"))   # evaluation_framework
    sys.path.insert(0, str(HERE))                  # vmd_ai_agent + bridges
    import vmd_ai_agent  # noqa: F401  (registers @register_agent("vmd_ai"))
    from evaluation_framework import get_agent

    with open(args.config) as fh:
        config = json.load(fh)

    structures = sorted(glob.glob(os.path.join(args.structures_dir, "*.pdb"))
                        + glob.glob(os.path.join(args.structures_dir, "*.cif")))
    if not structures:
        print(f"No structures in {args.structures_dir}")
        return 1

    outdir = Path(os.path.expanduser(args.out_dir)) / args.tag
    outdir.mkdir(parents=True, exist_ok=True)

    # ---- gold per structure (VMD oracle), cached across concurrent arms ----
    gold = load_gold(structures, os.path.expanduser(args.vmd), args.gold_cache)

    agent = get_agent("vmd_ai")(config)
    await agent.setup()

    seeds = max(1, int(args.seeds))
    results = {}   # (name, mkey) -> list of (ok|None) across seeds
    detail = {}    # name__mkey__sN -> {gold, agent, ok}
    n_fail_saved = 0
    save_fails = os.environ.get("VMD_AI_SAVE_FAILURES", "1") != "0"
    if save_fails:
        (outdir / "failures.jsonl").unlink(missing_ok=True)   # fresh index per run of this arm
    try:
        for seed in range(1, seeds + 1):
            for s in structures:
                name = Path(s).stem.upper()
                for mkey, (phrase, tol, scored) in METRICS.items():
                    ans_path = str(outdir / f"{name}__{mkey}__s{seed}.txt")
                    if os.path.exists(ans_path):
                        os.remove(ans_path)
                    prompt = build_prompt(os.path.abspath(s), phrase, ans_path)
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
                    print(f"  [s{seed}] {name:6} {mkey:10} gold={g} agent={val} -> "
                          + ("PASS" if ok else ("FAIL" if ok is False else "-")))
                    # persist the generated Tcl + a debug log for every FAILED scored case
                    # (wrong or missing answer) so it can be reproduced/diagnosed offline.
                    if save_fails and scored and ok is False:
                        fp = _save_failure(outdir, name, mkey, seed, phrase, tol, g, val, ans_path, result, args.tag)
                        n_fail_saved += 1
                        print(f"      ↳ failure saved -> {fp}/{case_name}.{{tcl,log}}")
    finally:
        await agent.teardown()

    # ---- report: pass-rate over seeds ----
    names = [Path(s).stem.upper() for s in structures]
    print(f"\n=== CORRECTNESS across structures (pass-rate over {seeds} seed(s)) — arm: {args.tag} ===")
    print(f"  {'metric':10} " + " ".join(f"{n:>8}" for n in names) + "    total")
    grand_pass = grand_tot = 0
    for m, (_, _, sc) in METRICS.items():
        if not sc:
            continue
        cells, mp, mt = [], 0, 0
        for n in names:
            oks = [x for x in results.get((n, m), []) if x is not None]
            p, t = sum(1 for x in oks if x), len(oks)
            cells.append(f"{p}/{t}" if t else "-")
            mp += p
            mt += t
        grand_pass += mp
        grand_tot += mt
        print(f"  {m:10} " + " ".join(f"{c:>8}" for c in cells) + f"    {mp}/{mt}")
    print(f"  => overall: {grand_pass}/{grand_tot} checks passed (structures x metrics x seeds)")
    json.dump(detail, open(outdir / "summary.json", "w"), indent=2, default=str)
    print(f"  saved -> {outdir / 'summary.json'}")
    if n_fail_saved:
        print(f"  saved {n_fail_saved} failure bundle(s) (.tcl + .log) -> {outdir / 'failures'}")
        print(f"  failure index -> {outdir / 'failures.jsonl'}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default=os.environ.get("BENCH_DIR", str(Path.home() / "SciVisAgentBench")))
    ap.add_argument("--config", required=True)
    ap.add_argument("--structures-dir", default=str(HERE / "fixtures_multi"))
    ap.add_argument("--vmd", default=DEFAULT_VMD)
    ap.add_argument("--out-dir", default=str(HERE.parent.parent / "test_results" / "multistructure"))
    ap.add_argument("--tag", default="none")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--seeds", type=int, default=1, help="repeats per task; >1 de-noises no-answers")
    ap.add_argument("--gold-cache", default=None,
                    help="JSON gold cache (from precompute_gold_multi.py) — load it instead of "
                         "recomputing gold per run; misses are computed and appended")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run_arm(args)))


if __name__ == "__main__":
    main()
