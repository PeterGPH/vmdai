#!/bin/bash
# usage: capture_locked.sh <tcl-script> [args...]
# Runs a Tk prototype under VMD's bundled Tk 8.6 while holding a global screen lock, so
# concurrent agents never screenshot overlapping windows. The prototype itself must
# `raise`, `update`, call screencapture on its own window region (absolute output path),
# and `exit` within ~15 s. A watchdog kills it after 25 s. Stale locks (>90 s) are broken.
LOCK=/tmp/chatvmd_design_screen.lock
BOOT="$(cd "$(dirname "$0")" && pwd)/vmdtk_run.tcl"
nap() { perl -e 'select(undef,undef,undef,0.5)'; }
waited=0
until mkdir "$LOCK" 2>/dev/null; do
  age=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || date +%s) ))
  if [ "$age" -gt 90 ]; then rmdir "$LOCK" 2>/dev/null; fi
  nap; waited=$((waited+1))
done
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
/opt/anaconda3/bin/tclsh8.6 "$BOOT" "$@" &
p=$!
for i in $(seq 1 50); do kill -0 $p 2>/dev/null || break; nap; done
kill -0 $p 2>/dev/null && { echo "watchdog kill $p"; kill $p; }
wait $p 2>/dev/null; echo "exit=$?"
