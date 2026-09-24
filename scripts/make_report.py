"""Markdown report of the vmdbench suite: scores every task card's
oracle and embeds the real VMD render.

Run from vmd_ai/:

    python scripts/make_report.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]  # vmd_ai/
TASKS = ROOT / "vmdbench" / "tasks"
ORACLES = ROOT / "vmdbench" / "oracles"
OUT = ROOT / "report_out"
VMD_VER = (ROOT / "vmdbench" / "VERSION").read_text().strip()


def score(card_path: Path) -> dict:
    from vmdbench.spec.task_card import load_card

    card = load_card(card_path)
    oracle = ORACLES / f"{card.task_id}.tcl"
    wd = OUT / card.task_id
    wd.mkdir(parents=True, exist_ok=True)

    if not oracle.exists():
        return {"task_id": card.task_id, "error": "no oracle"}

    p = subprocess.run(
        [
            sys.executable,
            "-m",
            "vmdbench.cli",
            "score-oracle",
            str(card_path),
            str(oracle),
            "--workdir",
            str(wd),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )

    if p.returncode != 0:
        return {
            "task_id": card.task_id,
            "error": (p.stderr or "non-zero exit")[:200],
        }

    d = json.loads(p.stdout)
    d.update(
        category=card.category,
        difficulty=card.difficulty,
        prompt=" ".join(card.user_prompt.split()),
        dimensions=[x.value for x in card.dimensions],
    )

    for tga in wd.glob("*.tga"):
        png = tga.with_suffix(".png")
        subprocess.run(
            [
                "sips",
                "-s",
                "format",
                "png",
                str(tga),
                "--out",
                str(png),
            ],
            capture_output=True,
        )
        d["image"] = f"{card.task_id}/{png.name}"

    return d


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)

    OUT.mkdir()
    (OUT / ".gitignore").write_text("*\n")  # report_out/ self-ignores

    res = [score(c) for c in sorted(TASKS.rglob("*.yaml"))]
    ok = [r for r in res if "error" not in r]

    solved = sum(r["score"]["solved"] for r in ok)
    mean_c = sum(r["score"]["composite"] for r in ok) / max(1, len(ok))

    dims: dict[str, list[float]] = {}

    for r in ok:
        for d, v in r["score"]["dim_scores"].items():
            dims.setdefault(d, []).append(v)

    L: list[str] = []

    L.append("# vmdbench report\n")
    L.append(
        f"- VMD `{VMD_VER}` - tasks **{len(res)}** - "
        f"solved **{solved}/{len(ok)}** - "
        f"mean composite **{mean_c:.2f}**\n"
    )

    L.append("\n## Per-dimension (mean over scored tasks)\n")
    L.append("| Dimension | Mean | n |\n|---|--:|:--:|")

    for d in sorted(dims):
        vs = dims[d]
        L.append(f"| {d} | {sum(vs) / len(vs):.2f} | {len(vs)} |")

    L.append("\n## Tasks\n")
    L.append(
        "| Task | Category | Diff | Gate | Solved | Composite | Req |\n"
        "|---|---|---|:--:|:--:|--:|:--:|"
    )

    for r in res:
        if "error" in r:
            L.append(
                f"| {r['task_id']} | - | - | WARN | - | - | "
                f"{r['error'][:30]} |"
            )
            continue

        v = r["verify"]
        s = r["score"]

        npass = sum(c["passed"] for c in v["required"])
        gate = "PASS" if v["gate"] else "FAIL"
        solv = "yes" if s["solved"] else "no"

        L.append(
            f"| `{r['task_id']}` | {r['category']} | {r['difficulty']} | "
            f"{gate} | {solv} | {s['composite']:.2f} | "
            f"{npass}/{len(v['required'])} |"
        )

    for r in ok:
        v = r["verify"]
        s = r["score"]

        L.append(f"\n### `{r['task_id']}`\n")
        L.append(f"**Prompt:** {r['prompt']}\n")
        L.append(
            f"**Dimensions:** {', '.join(r['dimensions'])} - "
            f"composite **{s['composite']:.2f}** - "
            f"replay_clean **{r['replay_clean']}**\n"
        )

        L.append(
            "\n| Assertion | Passed | Observed (what VMD reported) |\n"
            "|---|:--:|---|"
        )

        for c in v["required"]:
            mark = "PASS" if c["passed"] else "FAIL"
            observed = str(c["observed"])[:70]
            L.append(f"| `{c['kind']}` | {mark} | `{observed}` |")

        if r.get("image"):
            L.append(f"\n![{r['task_id']}]({r['image']})\n")

        L.append(
            f"\n_Exact Tcl VMD executed: "
            f"`{r['task_id']}/__vb_run.tcl`_\n"
        )

    (OUT / "REPORT.md").write_text("\n".join(L) + "\n")

    print(f"wrote {OUT / 'REPORT.md'}  ({len(ok)}/{len(res)} tasks scored)")


if __name__ == "__main__":
    main()