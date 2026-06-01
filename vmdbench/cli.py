from __future__ import annotations
import argparse, json, sys, tempfile
from pathlib import Path

from vmdbench.env.headless_vmd import HeadlessVMDEnv
from vmdbench.spec.task_card import load_card
from vmdbench.verify.runner import verify_card
from vmdbench.score.scorer import score_task


def _scene_fingerprint(scene) -> tuple:
    reps = tuple(sorted((r.selection, r.style_name, r.visible) for r in scene.representations))
    sels = tuple(sorted(scene.selections.items()))
    return (len(scene.molecules), reps, sels, scene.display.background, scene.display.projection)


def _replay_clean(card, tcl, env) -> bool:
    fps = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as d:
            res = verify_card(card, tcl, Path(d), env=env)
            if not res.gate:
                return False
            fps.append(_scene_fingerprint(res.scene))
    return fps[0] == fps[1]


def cmd_score_oracle(args) -> int:
    card = load_card(args.card)
    tcl = Path(args.oracle).read_text()
    env = HeadlessVMDEnv()
    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp())

    verify = verify_card(card, tcl, workdir, env=env)
    exports_ok = "tcl" in (card.reproducibility.get("exports", []) or [])  # oracle IS reusable tcl
    replay_clean = _replay_clean(card, tcl, env) if card.reproducibility.get("replay_clean") else None
    score = score_task(
        verify, dimensions=card.dimensions,
        repro_signals={"exports_ok": exports_ok, "replay_clean": bool(replay_clean)}
                      if card.reproducibility else None,
    )
    payload = {
        "task_id": card.task_id,
        "verify": verify.to_dict(),
        "score": score.to_dict(),
        "replay_clean": replay_clean,
    }
    print(json.dumps(payload, indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="vmdbench")
    sub = p.add_subparsers(dest="cmd", required=True)
    so = sub.add_parser("score-oracle", help="run a reference Tcl against a card and score it")
    so.add_argument("card")
    so.add_argument("oracle")
    so.add_argument("--workdir", default=None)
    so.set_defaults(func=cmd_score_oracle)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
