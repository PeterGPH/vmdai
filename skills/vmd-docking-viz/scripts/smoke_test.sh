#!/usr/bin/env bash
# Complete end-to-end regression test for the vmd-docking-viz skill.
#
# Exercises every public proc:
#   detect_format, has_plugin, load_format, load_receptor, load_poses,
#   load_docking, vina_scores, sdf_scores, write_score_to_user,
#   score_range, pocket_resids, scene_pocket, scene_pose_ensemble,
#   frame_scene, highlight_clashes, pose_hbonds, pose_contacts,
#   pose_rmsd_matrix, pose_clashes, pose_clash_summary,
#   write_clash_dat, write_dat
#
# Plus:
#   - PDBQT->PDB fallback path (macOS ARM64)
#   - TachyonInternal headless render
#   - TGA->PNG conversion via Pillow
#   - Python unit tests
#
# Usage:
#   ./smoke_test.sh             # run everything
#   ./smoke_test.sh --no-render # skip render + image conversion
#   ./smoke_test.sh --keep      # keep /tmp fixtures after test
#
# Environment overrides:
#   VMD_BIN  path to vmd binary (auto-discovered on macOS if unset)
#   PY       python interpreter to use (auto-prefers anaconda's if present)
#
# Exit code 0 = all green; non-zero = at least one stage failed.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../../.." && pwd)"

REC=/tmp/vmdai_test_rec.pdb
LIG=/tmp/vmdai_test_vina.pdbqt
TGA=/tmp/vmdai_test_scene.tga
PNG=/tmp/vmdai_test_scene.png
TCL=/tmp/vmdai_test_run.tcl
LOG=/tmp/vmdai_test_run.log
CLASH_DAT=/tmp/vmdai_test_clashes.dat
RMSD_DAT=/tmp/vmdai_test_rmsd.dat

DO_RENDER=1
KEEP=0
for arg in "$@"; do
    case "$arg" in
        --no-render) DO_RENDER=0 ;;
        --keep)      KEEP=1 ;;
        -h|--help)
            sed -n '2,30p' "$0"
            exit 0
            ;;
    esac
done

# Pick the right python — Pillow is usually in anaconda
PY=python3
if [[ -x /opt/anaconda3/bin/python3 ]]; then PY=/opt/anaconda3/bin/python3; fi

# Discover VMD. User aliases/functions don't propagate to subshells, so we
# probe common macOS install locations in addition to PATH.
discover_vmd() {
    if [[ -n "${VMD_BIN:-}" ]] && [[ -x "$VMD_BIN" ]]; then
        echo "$VMD_BIN"; return 0
    fi
    if command -v vmd >/dev/null 2>&1; then
        command -v vmd; return 0
    fi
    for cand in \
        /Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64 \
        /Applications/VMD.app/Contents/vmd/vmd_MACOSXX86_64 \
        "/Applications/VMD 1.9.4.app/Contents/vmd/vmd_MACOSXARM64" \
        "/Applications/VMD 1.9.4.app/Contents/vmd/vmd_MACOSXX86_64" \
        /opt/homebrew/bin/vmd \
        /usr/local/bin/vmd
    do
        if [[ -x "$cand" ]]; then echo "$cand"; return 0; fi
    done
    # Last resort: glob anything that looks right
    local hit
    hit=$(ls /Applications/VMD*.app/Contents/vmd/vmd_MACOSX* 2>/dev/null | head -1)
    if [[ -n "$hit" ]] && [[ -x "$hit" ]]; then echo "$hit"; return 0; fi
    return 1
}
VMD="$(discover_vmd)" || true

PASS_COUNT=0
FAIL_COUNT=0

step() {
    local name=$1; shift
    printf "\n\033[1;36m[%s]\033[0m %s\n" "STEP" "$name"
    if "$@"; then
        printf "  \033[0;32mPASS\033[0m\n"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        printf "  \033[0;31mFAIL\033[0m\n"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# ---------------------------------------------------------------------------
# Stage 1: prerequisites
# ---------------------------------------------------------------------------

check_vmd() { [[ -n "$VMD" ]] && [[ -x "$VMD" ]]; }
check_python() { command -v "$PY" >/dev/null 2>&1; }

step "VMD discovered ($VMD)"  check_vmd
step "Python ($PY) on PATH"   check_python

# ---------------------------------------------------------------------------
# Stage 2: fixtures
# ---------------------------------------------------------------------------

prepare_receptor() {
    if [[ -f "$REC" ]] && [[ -s "$REC" ]]; then return 0; fi
    curl -fsSL https://files.rcsb.org/download/1UBQ.pdb -o "$REC"
    [[ -s "$REC" ]]
}

prepare_ligand() {
    cat > "$LIG" <<'PDBQT'
MODEL 1
REMARK VINA RESULT:    -9.4      0.000      0.000
HETATM    1  C   LIG A   1       0.000   0.000   0.000  0.00  0.00     0.000 C
HETATM    2  C   LIG A   1       1.500   0.000   0.000  0.00  0.00     0.000 C
HETATM    3  O   LIG A   1       2.250   1.300   0.000  0.00  0.00     0.000 O
ENDMDL
MODEL 2
REMARK VINA RESULT:    -8.7      1.200      2.100
HETATM    1  C   LIG A   1       0.200   0.100   0.100  0.00  0.00     0.000 C
HETATM    2  C   LIG A   1       1.700   0.100   0.100  0.00  0.00     0.000 C
HETATM    3  O   LIG A   1       2.450   1.400   0.100  0.00  0.00     0.000 O
ENDMDL
MODEL 3
REMARK VINA RESULT:    -8.2      2.500      3.800
HETATM    1  C   LIG A   1      -0.300   0.200  -0.100  0.00  0.00     0.000 C
HETATM    2  C   LIG A   1       1.200   0.200  -0.100  0.00  0.00     0.000 C
HETATM    3  O   LIG A   1       1.950   1.500  -0.100  0.00  0.00     0.000 O
ENDMDL
PDBQT
    [[ -s "$LIG" ]]
}

step "Fetch receptor (1UBQ.pdb)"   prepare_receptor
step "Write synthetic vina output" prepare_ligand

# ---------------------------------------------------------------------------
# Stage 3: Python unit tests
# ---------------------------------------------------------------------------

run_python_tests() {
    cd "$REPO_ROOT" || return 1
    "$PY" -m unittest vmd_ai.tests.test_vmd_docking_viz_skill > "$LOG.unit" 2>&1
}

step "Python unit tests (29 tests)" run_python_tests
if [[ -s "$LOG.unit" ]]; then
    tail -3 "$LOG.unit" | sed 's/^/    /'
fi

# ---------------------------------------------------------------------------
# Stage 4: VMD-driven smoke test
# ---------------------------------------------------------------------------

cat > "$TCL" <<TCLEOF
set DIR $SCRIPT_DIR
foreach f [lsort [glob \$DIR/*.tcl]] {
    if {[string match "*smoke_test*" \$f]} { continue }
    if {[catch {source \$f} err]} {
        puts "ERROR sourcing \$f: \$err"
        quit
    }
}

# --- detect_format
set fmt_pdb   [vmdai::detect_format $REC]
set fmt_pdbqt [vmdai::detect_format $LIG]
puts "ASSERT detect_format pdb     = \$fmt_pdb"
puts "ASSERT detect_format pdbqt   = \$fmt_pdbqt"
if {\$fmt_pdb ne "pdb"}     { puts "FAIL detect_format pdb"; quit }
if {\$fmt_pdbqt ne "pdbqt"} { puts "FAIL detect_format pdbqt"; quit }
puts "OK detect_format"

# --- has_plugin / load_format fallback
set has_pdb   [vmdai::has_plugin pdb]
set has_pdbqt [vmdai::has_plugin pdbqt]
puts "ASSERT has_plugin pdb=\$has_pdb pdbqt=\$has_pdbqt"
set lf [vmdai::load_format $LIG]
puts "ASSERT load_format($LIG) -> \$lf"
puts "OK has_plugin / load_format"

# --- load_docking
set ids [vmdai::load_docking $REC $LIG]
set rec [dict get \$ids rec_id]
set lig [dict get \$ids lig_id]
set npose [dict get \$ids npose]
puts "ASSERT npose=\$npose"
if {\$npose != 3} { puts "FAIL load_docking npose"; quit }
puts "OK load_docking"

# --- vina_scores + score_range
set scores [vmdai::vina_scores $LIG]
set rng [vmdai::score_range \$scores]
puts "ASSERT vina_scores count=[llength \$scores]"
puts "ASSERT score_range = \$rng"
if {[llength \$scores] != 3} { puts "FAIL vina_scores count"; quit }
if {[lindex \$rng 0] > -9.0} { puts "FAIL score_range min"; quit }
puts "OK vina_scores"

# --- write_score_to_user
vmdai::write_score_to_user \$lig \$scores
set s [atomselect \$lig "all" frame 0]
set u [lindex [\$s get user] 0]
\$s delete
puts "ASSERT user(frame0,atom0) = \$u (expect ~-9.4)"
if {[expr {\$u > -9.0}]} { puts "FAIL write_score_to_user"; quit }
puts "OK write_score_to_user"

# --- fixture move (push poses into pocket region)
set rsel [atomselect \$rec "protein"]
set rcom [measure center \$rsel weight mass]
\$rsel delete
set lsel [atomselect \$lig "all"]
for {set f 0} {\$f < \$npose} {incr f} {
    \$lsel frame \$f
    \$lsel moveby \$rcom
}
\$lsel delete

# --- pocket_resids (cross-molecule)
set pocket [vmdai::pocket_resids \$rec \$lig 8.0 0]
puts "ASSERT pocket_resids count=[llength \$pocket]"
if {[llength \$pocket] < 5} { puts "FAIL pocket_resids empty"; quit }
puts "OK pocket_resids"

# --- pose_rmsd_matrix
set mat [vmdai::pose_rmsd_matrix \$lig "noh"]
set diag00 [lindex [lindex \$mat 0] 0]
set off01  [lindex [lindex \$mat 0] 1]
puts "ASSERT rmsd diag(0,0)=\$diag00 off(0,1)=\$off01"
if {\$diag00 ne "0.000"} { puts "FAIL rmsd diagonal"; quit }
puts "OK pose_rmsd_matrix"

# --- pose_hbonds (polar contact proxy)
set hb [vmdai::pose_hbonds \$lig \$rec 3.5 30]
puts "ASSERT pose_hbonds = \$hb"
if {[llength \$hb] != 3} { puts "FAIL pose_hbonds length"; quit }
puts "OK pose_hbonds"

# --- pose_contacts
set cmap [vmdai::pose_contacts \$lig \$rec 4.0]
foreach f [lsort -integer [dict keys \$cmap]] {
    puts "ASSERT contacts pose \$f -> [dict get \$cmap \$f]"
}
puts "OK pose_contacts"

# --- pose_clashes + summary
set clashes [vmdai::pose_clashes \$lig \$rec 0.4]
puts "ASSERT clash dict has 3 poses: [llength [dict keys \$clashes]]"
if {[llength [dict keys \$clashes]] != 3} { puts "FAIL pose_clashes pose count"; quit }
puts ""
puts [vmdai::pose_clash_summary \$lig \$rec 0.4]
puts ""
puts "OK pose_clashes"

# --- write_clash_dat + write_dat
vmdai::write_clash_dat $CLASH_DAT \$clashes
vmdai::write_dat $RMSD_DAT "all-vs-all RMSD" \$mat
if {![file exists $CLASH_DAT]} { puts "FAIL write_clash_dat"; quit }
if {![file exists $RMSD_DAT]}  { puts "FAIL write_dat"; quit }
puts "OK write_clash_dat / write_dat"

# --- scene_pose_ensemble + frame_scene
vmdai::scene_pose_ensemble \$rec \$lig -cutoff 8.0
set scl [vmdai::frame_scene \$rec "protein" -padding 1.4]
puts "ASSERT frame_scene scale = \$scl"
puts "OK scene_pose_ensemble + frame_scene"

# --- highlight_clashes (only meaningful if there are clashes; safe regardless)
set added [vmdai::highlight_clashes \$rec \$lig \$clashes 0]
puts "ASSERT highlight_clashes added [llength \$added] reps for pose 0"
puts "OK highlight_clashes"

if {$DO_RENDER} {
    render TachyonInternal $TGA
    puts "OK render TachyonInternal -> $TGA"
}

puts "ALL_TCL_GREEN"
quit
TCLEOF

run_vmd_smoke() {
    if [[ -z "$VMD" ]]; then return 1; fi
    "$VMD" -dispdev text -e "$TCL" > "$LOG" 2>&1
    grep -q "ALL_TCL_GREEN" "$LOG"
}

step "VMD-driven helper smoke test" run_vmd_smoke

# Echo the assertions / OK lines to stdout
echo "  ----- VMD log highlights -----"
grep -E "^(ASSERT|OK|FAIL|ERROR|pose ) " "$LOG" | sed 's/^/    /'
echo "  ------------------------------"

# ---------------------------------------------------------------------------
# Stage 5: render & convert (optional)
# ---------------------------------------------------------------------------

if [[ $DO_RENDER -eq 1 ]]; then
    check_render_size() {
        [[ -s "$TGA" ]] && [[ $(wc -c < "$TGA") -gt 100000 ]]
    }
    convert_png() {
        "$PY" -c "from PIL import Image; Image.open('$TGA').save('$PNG')" 2>>"$LOG"
        [[ -s "$PNG" ]]
    }
    step "TGA file is real (>100 KB)" check_render_size
    step "Convert TGA -> PNG (Pillow)" convert_png
fi

# ---------------------------------------------------------------------------
# Stage 6: data file sanity
# ---------------------------------------------------------------------------

check_clash_dat() { [[ -s "$CLASH_DAT" ]] && head -1 "$CLASH_DAT" | grep -q "pose"; }
check_rmsd_dat()  { [[ -s "$RMSD_DAT"  ]] && grep -q "0.000" "$RMSD_DAT"; }
step "clashes.dat has data" check_clash_dat
step "rmsd.dat has data"    check_rmsd_dat

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

if [[ $KEEP -ne 1 ]]; then
    rm -f "$TCL" "$LOG" "$LOG.unit" "$CLASH_DAT" "$RMSD_DAT"
    [[ $DO_RENDER -eq 1 ]] && rm -f "$TGA"
    # Keep PNG and PDB fixtures so the user can inspect
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
printf "\033[1m=================================\033[0m\n"
printf "  Passed: \033[0;32m%d\033[0m\n" "$PASS_COUNT"
printf "  Failed: \033[0;31m%d\033[0m\n" "$FAIL_COUNT"
printf "\033[1m=================================\033[0m\n"

if [[ $DO_RENDER -eq 1 ]] && [[ -s "$PNG" ]]; then
    echo ""
    echo "  Render available at: $PNG"
    echo "  Open with:           open $PNG"
fi

[[ $FAIL_COUNT -eq 0 ]] && exit 0 || exit 1
