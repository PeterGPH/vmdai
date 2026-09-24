#!/usr/bin/env bash
# run_atlas_traj.sh — agent-vs-ATLAS trajectory test across arms (dynamics analogue of the
# 25-cell static grid). 5 chains x 5 trajectory metrics x SEEDS, scored vs gold_oracle_traj.tcl.
#
#   bash run_atlas_traj.sh                 # none rag wiki inject
#   bash run_atlas_traj.sh none wiki       # just those arms
#
# Prereq: OpenAI-compatible model endpoint at http://localhost:8000/v1 (local vLLM).
# Env overrides: REPO, VMD_BIN, SEEDS.
set -uo pipefail

REPO="${REPO:-/data/server10/pinhao2/ML/PyMolAI/vmd_ai}"
HARNESS="$REPO/integrations/scivisagentbench"
VMD="${VMD_BIN:-/software/vmd-1.9.3/bin/vmd}"
ENDPOINT="http://localhost:8000/v1/models"
SEEDS="${SEEDS:-3}"
TIMEOUT="${TIMEOUT:-300}"   # per-case cap (s); lower it to bound the mol-new timeout loop on big runs
GOLD_CACHE="${GOLD_CACHE:-$HARNESS/atlas_gold_cache.json}"   # gold computed once, reused by all arms
FIXDIR="${FIXDIR:-$HARNESS/atlas_fixtures}"

if [ "$#" -gt 0 ]; then ARMS=("$@"); else ARMS=(none rag wiki inject); fi
cd "$REPO" || { echo "repo not found: $REPO"; exit 1; }

echo "Waiting for vLLM at $ENDPOINT ..."
up=0
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 3 "$ENDPOINT" 2>/dev/null)
  if [ "$code" = "200" ]; then echo "  server up ✓"; up=1; break; fi
  echo "  [$i/60] still down (HTTP $code) — retrying in 10s..."; sleep 10
done
[ "$up" = "1" ] || { echo "server never came up — start vLLM on :8000, then re-run."; exit 1; }

# ---- gold computed ONCE up front, reused by every arm (deterministic) ----
echo "=== precomputing gold cache -> $GOLD_CACHE ==="
python "$HARNESS/precompute_gold_traj.py" --fixtures-dir "$FIXDIR" --vmd "$VMD" --out "$GOLD_CACHE" \
  || echo "!! gold precompute had failures (arms will recompute the missing chains)"

for arm in "${ARMS[@]}"; do
  cfg="$HARNESS/config_arm_${arm}.json"
  [ -f "$cfg" ] || { echo "!! missing config $cfg — skipping $arm"; continue; }
  echo "=== atlas-traj arm: $arm  ($SEEDS seeds x chains x 5 metrics) ==="
  python "$HARNESS/run_atlas_traj.py" --config "$cfg" --tag "$arm" --seeds "$SEEDS" --vmd "$VMD" \
    --timeout "$TIMEOUT" --fixtures-dir "$FIXDIR" --gold-cache "$GOLD_CACHE" \
    || echo "!! run_atlas_traj failed for $arm (continuing)"
done

echo
echo "=== ATLAS-traj scoreboard (correct = |agent-gold|<=tol, complete = non-null) ==="
python3 - "$REPO" <<'PY'
import json, os, sys
base = os.path.join(sys.argv[1], "test_results", "atlas_traj")
hdr = f"{'arm':<10}{'n':>4}{'correct%':>10}{'complete%':>11}{'done-but-wrong':>16}"
print(hdr); print("-"*len(hdr))
for arm in ["none", "rag", "wiki", "inject"]:
    f = os.path.join(base, arm, "summary.json")
    if not os.path.exists(f):
        print(f"{arm:<10}  (not run yet)"); continue
    d = json.load(open(f)); n = len(d)
    ok = sum(1 for v in d.values() if v.get("ok") is True)
    done = sum(1 for v in d.values() if v.get("agent") is not None)
    dbw = sum(1 for v in d.values() if v.get("agent") is not None and not v.get("ok"))
    print(f"{arm:<10}{n:>4}{ok/n*100:>9.1f}%{done/n*100:>10.1f}%{dbw:>16}")
PY
