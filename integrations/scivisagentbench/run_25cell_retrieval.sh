#!/usr/bin/env bash
# run_25cell_retrieval.sh
# Run the retrieval arms on the 25-cell multistructure suite (same tasks as inject),
# then aggregate correctness/completion across all arms.
#
#   bash run_25cell_retrieval.sh                # all 4: rag wiki autorag both
#   bash run_25cell_retrieval.sh rag wiki       # just the punchline arms
#
# Prereq: Qwen vLLM reachable at http://localhost:8000/v1 (start your server + tunnel).
set -uo pipefail

REPO="${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"   # self-locating: works on Mac or server, no sed
HARNESS="$REPO/integrations/scivisagentbench"
ENDPOINT="http://localhost:8000/v1/models"
SEEDS="${SEEDS:-3}"
VMD="${VMD_BIN:-/software/vmd-1.9.3/bin/vmd}"           # gold-oracle VMD; override via VMD_BIN
GOLD_CACHE="${GOLD_CACHE:-$HARNESS/gold_cache_multi.json}"   # gold computed once, reused by all arms

if [ "$#" -gt 0 ]; then ARMS=("$@"); else ARMS=(rag wiki autorag both); fi
cd "$REPO" || { echo "repo not found: $REPO"; exit 1; }

# ---- 1. wait for the vLLM server (up to 10 min) ----
echo "Waiting for Qwen vLLM at $ENDPOINT ..."
up=0
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 3 "$ENDPOINT" 2>/dev/null)
  if [ "$code" = "200" ]; then echo "  server up ✓"; up=1; break; fi
  echo "  [$i/60] still down (HTTP $code) — retrying in 10s..."
  sleep 10
done
[ "$up" = "1" ] || { echo "server never came up — start vLLM + tunnel on :8000, then re-run."; exit 1; }

# ---- 1b. gold computed ONCE up front, reused by every arm (deterministic) ----
echo "=== precomputing gold cache -> $GOLD_CACHE ==="
python "$HARNESS/precompute_gold_multi.py" --structures-dir "$HARNESS/fixtures_multi" --vmd "$VMD" --out "$GOLD_CACHE" \
  || echo "!! gold precompute had failures (arms will recompute the missing structures)"

# ---- 2. run each arm on the 25-cell suite ----
for arm in "${ARMS[@]}"; do
  cfg="$HARNESS/config_arm_${arm}.json"
  [ -f "$cfg" ] || { echo "!! missing config $cfg — skipping $arm"; continue; }
  echo "=== arm: $arm  ($SEEDS seeds x 25 cells) ==="
  python "$HARNESS/run_multistructure.py" --config "$cfg" --tag "${arm}_s3" --seeds "$SEEDS" \
    --vmd "$VMD" --gold-cache "$GOLD_CACHE" \
    || echo "!! run_multistructure failed for $arm (continuing)"
done

# ---- 3. aggregate correctness + completion across all arms ----
echo
echo "=== 25-cell scoreboard (correctness = |agent-gold|<=tol, completion = non-null) ==="
python3 - <<'PY'
import json, os
base = "test_results/multistructure"
order = [("none_s3","none (baseline)"), ("rag_s3","rag"), ("autorag_s3","autorag"),
         ("both_s3","rag+wiki"), ("wiki_s3","wiki"), ("inject_s3","inject"),
         ("improved","improved = all 3")]
hdr = f"{'arm':<20}{'n':>4}{'correct%':>10}{'complete%':>11}{'done-but-wrong':>16}"
print(hdr); print("-"*len(hdr))
for d, label in order:
    f = os.path.join(base, d, "summary.json")
    if not os.path.exists(f):
        print(f"{label:<20}  (not run yet)"); continue
    s = json.load(open(f)); n = len(s)
    correct = sum(1 for v in s.values() if v.get("ok") is True)
    done    = sum(1 for v in s.values() if v.get("agent") is not None)
    dbw     = sum(1 for v in s.values() if v.get("agent") is not None and not v.get("ok"))
    print(f"{label:<20}{n:>4}{correct/n*100:>9.1f}%{done/n*100:>10.1f}%{dbw:>16}")
PY
echo
echo "done — paste this scoreboard back to Claude to rebuild Slide 8 (apples-to-apples)."
