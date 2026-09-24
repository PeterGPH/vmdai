#!/usr/bin/env bash
# sync_hard_tier_to_server.sh — push the vmdbench HARD tier + v2 WORKBENCH tool to the GPU server.
#
# Run from your Mac (this machine). It rsyncs ONLY the hard-tier + workbench source/test files,
# never any config_arm_*.json (those carry Mac paths that would break vmd_bin on the server). It
# backs up the core files it overwrites, verifies the pure tests on the server, archives any stale
# hard gold cache, and creates config_arm_workbench.json from the server's config_arm_tools.json.
#
#   bash scripts/sync_hard_tier_to_server.sh              # sync + verify + make workbench config
#   DRY=1 bash scripts/sync_hard_tier_to_server.sh        # show what WOULD transfer, change nothing
#
# Override the defaults via env if your host/paths differ:
#   SRV=pinhao2@tbgl-gpu-01  RMT=/data/server10/pinhao2/ML/PyMolAI/vmd_ai  SRV_VMD=/software/vmd-1.9.3/bin/vmd
set -uo pipefail

LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRV="${SRV:-pinhao2@tbgl-gpu-01}"
RMT="${RMT:-/data/server10/pinhao2/ML/PyMolAI/vmd_ai}"
SRV_VMD="${SRV_VMD:-/software/vmd-1.9.3/bin/vmd}"
HARNESS_REL="integrations/scivisagentbench"

# Apple rsync (2.6.9) rejects --info=progress2, so we don't use it. -n for dry-run when DRY=1.
RSYNC_OPTS=(-avz)
[ "${DRY:-0}" = "1" ] && RSYNC_OPTS+=(-n) && echo "== DRY RUN — nothing will actually change =="

# harness files under integrations/scivisagentbench/  (hard tier + v2 workbench)
HARNESS_FILES=(
  # --- hard/reasoning tier ---
  gold_oracle_traj_hard.tcl      # hard gold oracle (composed observables)
  hard_metrics.py                # catalog + recipe-stripped prompt
  calibrate_hard.py              # oracle-derived tolerances + argmin-margin report
  run_atlas_traj.py              # --hard / select_mode (easy path unchanged)
  precompute_gold_traj.py        # --hard precompute
  run_atlas_parallel.sh          # HARD=1 knob
  test_hard_metrics.py           # pure catalog/prompt/select_mode/tol/exclusion tests
  # --- v2 workbench tool ---
  safe_eval.py                   # NEW — ast allow-list evaluator (security gate) for vmd_compute
  subprocess_vmd_bridge.py       # MODIFIED — vmd_traj_series + vmd_compute + per-task series ns
  vmd_ai_agent.py                # MODIFIED — workbench schemas + enable_workbench_tools branch
  tool_prompts.py                # MODIFIED — workbench_directive (leak-free examples)
  transcript_util.py             # MODIFIED — record vmd_traj_series/vmd_compute
  test_safe_eval.py              # NEW — 14 OK + 23 BAD security cases
  test_workbench_wiring.py       # NEW — directive/schema formula-leak + transcript checks
)
# live tests under vmdbench/tests/  (skip on the server — they need vmdbench/fixtures/2erl_A)
TEST_FILES=(
  vmdbench/tests/test_hard_oracle.py        # hard oracle live MDAnalysis cross-check
  vmdbench/tests/test_workbench_series.py   # workbench series gold-consistency
)
# core files that already exist on the server and get OVERWRITTEN -> back them up first
OVERWRITE_FILES=(run_atlas_traj.py precompute_gold_traj.py run_atlas_parallel.sh \
                 subprocess_vmd_bridge.py vmd_ai_agent.py tool_prompts.py transcript_util.py)

echo "== target: $SRV:$RMT =="

# --- preflight: confirm every local file exists before we touch the server ---
missing=0
for f in "${HARNESS_FILES[@]}"; do
  [ -f "$LOCAL/$HARNESS_REL/$f" ] || { echo "  !! local file missing: $HARNESS_REL/$f"; missing=1; }
done
for f in "${TEST_FILES[@]}"; do
  [ -f "$LOCAL/$f" ] || { echo "  !! local file missing: $f"; missing=1; }
done
[ "$missing" = "1" ] && { echo "aborting — run this from the Mac with the committed vmdbench-design branch checked out."; exit 1; }

# --- back up the core files we OVERWRITE on the server (in case of server-side hand-edits) ---
if [ "${DRY:-0}" != "1" ]; then
  echo "== backing up the overwritten core files on the server (.bak) =="
  ssh "$SRV" "cd '$RMT/$HARNESS_REL' && for f in ${OVERWRITE_FILES[*]}; do [ -f \$f ] && cp -n \$f \$f.bak.\$(date +%Y%m%d) || true; done" \
    || echo "  (backup step skipped — could not reach server; continuing)"
fi

# --- sync the harness files ---
echo "== rsync harness files -> $HARNESS_REL/ =="
SRC=()
for f in "${HARNESS_FILES[@]}"; do SRC+=("$LOCAL/$HARNESS_REL/$f"); done
rsync "${RSYNC_OPTS[@]}" "${SRC[@]}" "$SRV:$RMT/$HARNESS_REL/" || { echo "  !! rsync failed"; exit 1; }

# --- sync the live tests ---
echo "== rsync live tests -> vmdbench/tests/ =="
TSRC=()
for f in "${TEST_FILES[@]}"; do TSRC+=("$LOCAL/$f"); done
rsync "${RSYNC_OPTS[@]}" "${TSRC[@]}" "$SRV:$RMT/vmdbench/tests/" || { echo "  !! rsync failed"; exit 1; }

if [ "${DRY:-0}" = "1" ]; then
  echo "== DRY RUN complete — re-run without DRY=1 to apply. =="
  exit 0
fi

# --- ARCHIVE (not delete) any stale hard gold cache so gold recomputes WITH rg_second_min ---
# The cache is a derived artifact (deterministic from oracle + fixtures, both versioned), so we
# never rm it — we move it aside timestamped; the runner then recomputes fresh.
echo "== archiving stale hard gold caches (force fresh precompute; old values preserved) =="
ssh "$SRV" "cd '$RMT/$HARNESS_REL' && mkdir -p _gold_archive && \
  moved=0; for f in gold_cache_*_hard.json; do [ -e \"\$f\" ] && mv \"\$f\" \"_gold_archive/\$f.\$(date +%Y%m%d_%H%M%S)\" && moved=1; done; \
  [ \$moved = 1 ] && echo '  archived -> _gold_archive/' || echo '  none to archive'"

# --- create the workbench arm config from the server's config_arm_tools.json (host paths kept) ---
echo "== creating config_arm_workbench.json on the server (from config_arm_tools.json) =="
ssh "$SRV" "cd '$RMT' && python3 - <<'PY'
import json, os
src = 'integrations/scivisagentbench/config_arm_tools.json'
dst = 'integrations/scivisagentbench/config_arm_workbench.json'
if not os.path.exists(src):
    print('  !! config_arm_tools.json not found — create the workbench config by hand'); raise SystemExit
b = json.load(open(src))
b['enable_semantic_tools'] = False       # workbench replaces the v1 canned tool
b['enable_workbench_tools'] = True
b['experiment_number'] = 'workbench_hard'
json.dump(b, open(dst, 'w'), indent=2)
print('  wrote', dst, ' model=', b.get('model'), ' vmd_bin=', b.get('vmd_bin'))
PY"

# --- server-side verification (pure tests + calibration; live tests skip w/o vmdbench/fixtures) ---
echo "== verify on server: pure tests (expect ALL GOOD x3) =="
ssh "$SRV" "cd '$RMT' && \
  echo -n '  hard_metrics : '; python integrations/scivisagentbench/test_hard_metrics.py | tail -1; \
  echo -n '  safe_eval    : '; python integrations/scivisagentbench/test_safe_eval.py | tail -1; \
  echo -n '  workbench_wire: '; python integrations/scivisagentbench/test_workbench_wiring.py | tail -1"

echo "== verify on server: hard oracle loads under VMD + calibration/argmin tables =="
ssh "$SRV" "cd '$RMT' && CUDA_VISIBLE_DEVICES=-1 python integrations/scivisagentbench/calibrate_hard.py --fixtures-dir '$HARNESS_REL/atlas_fixtures' --vmd '$SRV_VMD' 2>/dev/null | tail -12"

cat <<EOF

== DONE. If you saw 3x 'ALL GOOD' + the calibration tables + 'wrote config_arm_workbench.json', the server is ready. ==

Run a 3-way HARD sweep — baseline / v1 canned tool / v2 workbench — on the same questions + gold
(needs vLLM serving a model at :8000; set RUN to match the served model):

  ssh $SRV 'cd $RMT && \\
    CUDA_VISIBLE_DEVICES=-1 HARD=1 RUN=hard_qwen14b_wb SEEDS=3 \\
    FIXDIR=\$PWD/$HARNESS_REL/atlas_fixtures \\
    bash integrations/scivisagentbench/run_atlas_parallel.sh none tools workbench'

Then score + compare (expect workbench > tools > none on the max/range metrics):

  ssh $SRV 'cd $RMT && for t in none tools workbench; do d=test_results/atlas_traj/\${t}_hard_qwen14b_wb; \\
    python3 -c "import json,os; s=\"\$d/summary.json\"; \\
    d=json.load(open(s)) if os.path.exists(s) else {}; v=[x for x in d.values() if isinstance(x,dict) and x.get(\"ok\") is not None]; \\
    ok=sum(1 for x in v if x[\"ok\"] is True); print(\"$t\".ljust(10), f\"{ok}/{len(v)}\", f\"{100*ok/len(v):.1f}%\" if v else \"-\")"; done'
EOF
