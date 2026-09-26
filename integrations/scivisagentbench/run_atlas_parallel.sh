#!/usr/bin/env bash
# run_atlas_parallel.sh — run the ATLAS-trajectory agent test across arms IN PARALLEL.
#
# Each launch is isolated by a RUN label: distinct --tag, log file, and wiki root, so reruns
# never clobber each other. Gold is precomputed once and shared (skipped if the cache exists).
# Ends with a scoreboard.
#
#   bash run_atlas_parallel.sh                                   # arms: none rag wiki inject
#   RUN=preval SEEDS=3 TIMEOUT=300 bash run_atlas_parallel.sh none wiki
#   FIXDIR=$PWD/integrations/scivisagentbench/atlas_fix5 bash run_atlas_parallel.sh   # small subset
#
# Env knobs:  RUN (default: timestamp)  SEEDS(3)  TIMEOUT(300)  CONC(1)  VMD_BIN  FIXDIR  GOLD_CACHE
# Prereq: OpenAI-compatible model endpoint at http://localhost:8000/v1.
# Tip: launch under tmux (or `nohup … &`) so it survives disconnect.
set -uo pipefail

HARNESS="$(cd "$(dirname "$0")" && pwd)"            # this script's dir (self-locating)
REPO="$(cd "$HARNESS/../.." && pwd)"                # repo root (vmd_ai)
VMD="${VMD_BIN:-/software/vmd-1.9.3/bin/vmd}"
ENDPOINT="http://localhost:8000/v1/models"
SEEDS="${SEEDS:-3}"
TIMEOUT="${TIMEOUT:-300}"
CONC="${CONC:-1}"                                  # tasks concurrent per arm (each own agent+VMD)
RUN="${RUN:-$(date +%m%d_%H%M)}"                    # run label; default = timestamp
FIXDIR="${FIXDIR:-$HARNESS/atlas_fixtures}"
OUTBASE="$REPO/test_results/atlas_traj"
HARD="${HARD:-}"                                   # HARD=1 -> hard/reasoning tier
if [ -n "$HARD" ] && [ -z "${GOLD_CACHE:-}" ]; then
  GOLD_CACHE="$HARNESS/gold_cache_$(basename "$FIXDIR")_hard.json"
fi
GOLD_CACHE="${GOLD_CACHE:-$HARNESS/gold_cache_$(basename "$FIXDIR").json}"   # keyed by fixture set

if [ "$#" -gt 0 ]; then ARMS=("$@"); else ARMS=(none rag wiki inject); fi
cd "$REPO" || { echo "repo not found: $REPO"; exit 1; }

echo "== atlas-traj PARALLEL: RUN=$RUN  SEEDS=$SEEDS  TIMEOUT=$TIMEOUT  arms=[${ARMS[*]}]"
echo "   fixtures=$FIXDIR"
echo "   gold_cache=$GOLD_CACHE"

# ---- wait for vLLM ----
echo "Waiting for vLLM at $ENDPOINT ..."
up=0
for i in $(seq 1 60); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' -m 3 "$ENDPOINT" 2>/dev/null)" = "200" ] && { echo "  server up ✓"; up=1; break; }
  echo "  [$i/60] still down — retrying in 10s..."; sleep 10
done
[ "$up" = "1" ] || { echo "server never came up — start vLLM on :8000, then re-run."; exit 1; }

# ---- provenance: record which CODE + SETTINGS produced this run ----
# Results/logs are gitignored (large, derived), but this one-line-per-run manifest is TRACKED so
# every RUN maps back to the exact commit, model, tier and knobs. Lives next to the harness.
_model=$(curl -s "$ENDPOINT" 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null || echo unknown)

# ---- guard: served model must match the size token in RUN ----
# Prevents the "wrong model loaded" misrun: models are hot-swapped on :8000 by hand while the RUN
# label is typed manually, so a run named ...qwen14b... can be silently served by whatever is
# loaded (this bit us — a qwen14b_wb2 run was served by the 72B). If RUN encodes a size (7b/14b/
# 32b/72b) and the served model id doesn't contain it, abort before wasting a run.
_want=$(printf '%s' "$RUN" | grep -oiE '(7b|14b|32b|72b)' | head -1)
if [ -n "$_want" ] && ! printf '%s' "$_model" | grep -iq "$_want"; then
  echo "‼️  MODEL MISMATCH: RUN='$RUN' expects a '$_want' model, but :8000 serves '$_model'."
  echo "    Load the intended model (or fix the RUN label). Set ALLOW_MODEL_MISMATCH=1 to override."
  [ -n "${ALLOW_MODEL_MISMATCH:-}" ] || exit 3
  echo "    ALLOW_MODEL_MISMATCH=1 — proceeding despite mismatch."
fi

_tier=$([ -n "${HARD:-}" ] && echo hard || echo easy)
python3 "$REPO/integrations/run_provenance.py" "$HARNESS/run_manifest.jsonl" runner=run_atlas_parallel run="$RUN" model="$_model" tier="$_tier" fixtures="$(basename "$FIXDIR")" seeds="$SEEDS" conc="${CONC:-1}" arms="${ARMS[*]}" config="$HARNESS/config_arm_${ARMS[0]}.json"

# ---- gold ONCE, shared by all arms (skip if cache already present) ----
if [ -f "$GOLD_CACHE" ]; then
  echo "== gold cache exists -> $GOLD_CACHE (skipping precompute; delete it to force) =="
else
  echo "== precomputing gold -> $GOLD_CACHE =="
  python "$HARNESS/precompute_gold_traj.py" ${HARD:+--hard} --fixtures-dir "$FIXDIR" --vmd "$VMD" --out "$GOLD_CACHE" \
    || echo "!! gold precompute had failures (arms will recompute the missing chains)"
fi

# ---- launch arms in PARALLEL ----
pids=()
for arm in "${ARMS[@]}"; do
  cfg="$HARNESS/config_arm_${arm}.json"
  [ -f "$cfg" ] || { echo "!! missing config $cfg — skipping $arm"; continue; }
  log="run_${arm}_${RUN}.log"
  extra=""; [ "$arm" = wiki ] && extra="VMD_AI_WIKI_ROOT=/tmp/wiki_${arm}_${RUN}"
  echo "  launch $arm  ->  tag=${arm}_${RUN}  log=$log"
  env $extra PYTHONUNBUFFERED=1 python "$HARNESS/run_atlas_traj.py" \
    --config "$cfg" --tag "${arm}_${RUN}" --seeds "$SEEDS" \
    --vmd "$VMD" --timeout "$TIMEOUT" --fixtures-dir "$FIXDIR" \
    --gold-cache "$GOLD_CACHE" ${HARD:+--hard} --concurrency "$CONC" > "$log" 2>&1 &
  pids+=($!)
done
echo "== ${#pids[@]} arms running in parallel (PIDs: ${pids[*]}); waiting... =="
wait
echo "== all arms done: RUN=$RUN =="

# ---- scoreboard ----
echo
echo "=== ATLAS-traj scoreboard (RUN=$RUN) ==="
RUN="$RUN" OUTBASE="$OUTBASE" python3 - "${ARMS[@]}" <<'PY'
import json, os, sys
run, base, arms = os.environ["RUN"], os.environ["OUTBASE"], sys.argv[1:]
hdr = f"{'arm':<12}{'n':>4}{'correct%':>10}{'complete%':>11}{'done-but-wrong':>16}"
print(hdr); print("-" * len(hdr))
for arm in arms:
    f = os.path.join(base, f"{arm}_{run}", "summary.json")
    if not os.path.exists(f):
        print(f"{arm:<12}  (no summary)"); continue
    d = json.load(open(f)); n = len(d) or 1
    ok = sum(1 for v in d.values() if v.get("ok") is True)
    done = sum(1 for v in d.values() if v.get("agent") is not None)
    dbw = sum(1 for v in d.values() if v.get("agent") is not None and not v.get("ok"))
    print(f"{arm:<12}{n:>4}{ok/n*100:>9.1f}%{done/n*100:>10.1f}%{dbw:>16}")
PY
