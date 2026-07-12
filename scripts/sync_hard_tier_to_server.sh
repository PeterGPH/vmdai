#!/usr/bin/env bash
# sync_hard_tier_to_server.sh — push the vmdbench HARD/reasoning tier to the GPU server and verify.
#
# Run from your Mac (this machine). It rsyncs ONLY the 8 hard-tier files, never any
# config_arm_*.json (those carry Mac paths that would break vmd_bin on the server), then runs
# the server-side smoke checks and clears any stale hard gold cache so the sweep recomputes gold
# with the new rg_second_min key.
#
#   bash scripts/sync_hard_tier_to_server.sh              # sync + verify
#   DRY=1 bash scripts/sync_hard_tier_to_server.sh        # show what WOULD transfer, change nothing
#
# Override the defaults via env if your host/paths differ:
#   SRV=pinhao2@tbgl-gpu-01  RMT=/data/server10/pinhao2/ML/PyMolAI/vmd_ai  SRV_VMD=/software/vmd-1.9.3/bin/vmd
set -uo pipefail

LOCAL="/Users/pinhaogu/Documents/GitHub/PyMolAI/vmd_ai"
SRV="${SRV:-pinhao2@tbgl-gpu-01}"
RMT="${RMT:-/data/server10/pinhao2/ML/PyMolAI/vmd_ai}"
SRV_VMD="${SRV_VMD:-/software/vmd-1.9.3/bin/vmd}"
HARNESS_REL="integrations/scivisagentbench"

# Apple rsync (2.6.9) rejects --info=progress2, so we don't use it. -n for dry-run when DRY=1.
RSYNC_OPTS=(-avz)
[ "${DRY:-0}" = "1" ] && RSYNC_OPTS+=(-n) && echo "== DRY RUN — nothing will actually change =="

# the 8 files this feature added/changed (verified against git: b745c360..HEAD)
HARNESS_FILES=(
  gold_oracle_traj_hard.tcl      # new — hard gold oracle (composed observables)
  hard_metrics.py                # new — catalog + recipe-stripped prompt
  calibrate_hard.py              # new — oracle-derived tolerances + argmin-margin report
  run_atlas_traj.py              # MODIFIED — adds --hard / select_mode (easy path unchanged)
  precompute_gold_traj.py        # MODIFIED — adds --hard precompute
  run_atlas_parallel.sh          # MODIFIED — adds HARD=1 knob
  test_hard_metrics.py           # new — pure catalog/prompt/select_mode/tol/exclusion tests
)
TEST_FILE="vmdbench/tests/test_hard_oracle.py"   # new — live MDAnalysis cross-check

echo "== target: $SRV:$RMT =="

# --- preflight: confirm every local file exists before we touch the server ---
missing=0
for f in "${HARNESS_FILES[@]}"; do
  [ -f "$LOCAL/$HARNESS_REL/$f" ] || { echo "  !! local file missing: $HARNESS_REL/$f"; missing=1; }
done
[ -f "$LOCAL/$TEST_FILE" ] || { echo "  !! local file missing: $TEST_FILE"; missing=1; }
[ "$missing" = "1" ] && { echo "aborting — run this from the Mac with the committed hard-tier branch checked out."; exit 1; }

# --- backup the 3 files we OVERWRITE on the server (in case of server-side hand-edits) ---
if [ "${DRY:-0}" != "1" ]; then
  echo "== backing up the 3 overwritten files on the server (.bak) =="
  ssh "$SRV" "cd '$RMT/$HARNESS_REL' && for f in run_atlas_traj.py precompute_gold_traj.py run_atlas_parallel.sh; do [ -f \$f ] && cp -n \$f \$f.bak.\$(date +%Y%m%d) || true; done" \
    || echo "  (backup step skipped — could not reach server; continuing)"
fi

# --- sync the harness files ---
echo "== rsync harness files -> $HARNESS_REL/ =="
SRC=()
for f in "${HARNESS_FILES[@]}"; do SRC+=("$LOCAL/$HARNESS_REL/$f"); done
rsync "${RSYNC_OPTS[@]}" "${SRC[@]}" "$SRV:$RMT/$HARNESS_REL/" || { echo "  !! rsync failed"; exit 1; }

# --- sync the live test ---
echo "== rsync test -> vmdbench/tests/ =="
rsync "${RSYNC_OPTS[@]}" "$LOCAL/$TEST_FILE" "$SRV:$RMT/vmdbench/tests/" || { echo "  !! rsync failed"; exit 1; }

if [ "${DRY:-0}" = "1" ]; then
  echo "== DRY RUN complete — re-run without DRY=1 to apply. =="
  exit 0
fi

# --- clear any stale hard gold cache so gold recomputes WITH rg_second_min ---
echo "== removing stale hard gold caches (force fresh precompute) =="
ssh "$SRV" "rm -f '$RMT/$HARNESS_REL'/gold_cache_*_hard.json && echo '  cleared' || echo '  none'"

# --- server-side verification ---
echo "== verify on server: pure tests =="
ssh "$SRV" "cd '$RMT' && python integrations/scivisagentbench/test_hard_metrics.py | tail -1"

echo "== verify on server: oracle loads under VMD + calibration table =="
ssh "$SRV" "cd '$RMT' && CUDA_VISIBLE_DEVICES=-1 python integrations/scivisagentbench/calibrate_hard.py --fixtures-dir vmdbench/fixtures --vmd '$SRV_VMD' 2>/dev/null | tail -12"

cat <<EOF

== DONE. If you saw 'ALL GOOD' + the calibration/argmin-margin tables above, the server is ready. ==

Run the HARD sweep (needs vLLM serving a model at :8000; config_arm_{none,toolssoft,tools}.json present):

  ssh $SRV 'cd $RMT && \\
    CUDA_VISIBLE_DEVICES=-1 HARD=1 RUN=hard_qwen7b SEEDS=3 \\
    bash integrations/scivisagentbench/run_atlas_parallel.sh none toolssoft tools'

Then score with (glob the hard tags):

  ssh $SRV 'cd $RMT && for t in none toolssoft tools; do d=test_results/atlas_traj/\${t}_hard_qwen7b; \\
    python3 -c "import json,sys; s=\"\$d/summary.json\"; import os; \\
    d=json.load(open(s)) if os.path.exists(s) else {}; v=[x for x in d.values() if isinstance(x,dict) and x.get(\"ok\") is not None]; \\
    ok=sum(1 for x in v if x[\"ok\"] is True); print(\"$t\".ljust(10), f\"{ok}/{len(v)}\", f\"{100*ok/len(v):.1f}%\" if v else \"-\")"; done'
EOF
