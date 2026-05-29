from __future__ import annotations
from pathlib import Path

# (record, serial, name, resname, chain, resseq, x, y, z, element)
_ATOMS = [
    ("ATOM",   1, "N",   "ALA", "A", 1, 0.000,  0.000, 0.000, "N"),
    ("ATOM",   2, "CA",  "ALA", "A", 1, 1.458,  0.000, 0.000, "C"),
    ("ATOM",   3, "C",   "ALA", "A", 1, 2.009,  1.420, 0.000, "C"),
    ("ATOM",   4, "O",   "ALA", "A", 1, 1.251,  2.390, 0.000, "O"),
    ("ATOM",   5, "CB",  "ALA", "A", 1, 1.988, -0.773, 1.199, "C"),
    ("ATOM",   6, "P",   "DA",  "B", 1, 8.000,  0.000, 0.000, "P"),
    ("ATOM",   7, "C1'", "DA",  "B", 1, 9.200,  1.000, 0.000, "C"),
    ("HETATM", 8, "O",   "HOH", "W", 1, 5.000,  5.000, 0.000, "O"),
    ("HETATM", 9, "O",   "HOH", "W", 2, 6.000,  5.000, 0.000, "O"),
]


def write_mini_pdb(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for rec, serial, name, resname, chain, resseq, x, y, z, elem in _ATOMS:
        # PDB atom-name justification: 4-char names start in col 13; <4-char names get a leading space.
        nm = name if len(name) >= 4 else f" {name:<3}"
        lines.append(
            f"{rec:<6}{serial:>5} {nm:<4}{'':1}{resname:>3} {chain:1}{resseq:>4}{'':4}"
            f"{x:8.3f}{y:8.3f}{z:8.3f}{1.00:6.2f}{0.00:6.2f}{'':10}{elem:>2}"
        )
    lines.append("END")
    path.write_text("\n".join(lines) + "\n")
    return path

EXPECTED_NUMATOMS = len(_ATOMS)  # 9
