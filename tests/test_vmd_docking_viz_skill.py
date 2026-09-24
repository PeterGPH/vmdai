"""
Tests for the vmd-docking-viz skill.

Validates the skill's static assets without requiring a live VMD or any
external API key:

  1. Directory layout matches the conventions used by sibling skills.
  2. SKILL.md has a well-formed YAML-ish frontmatter block with `name` and
     `description` fields and the description references the trigger
     vocabulary that makes the skill discoverable.
  3. SKILL.md covers the docking-specific VMD/Tcl primitives the agent is
     expected to use (mol new pdbqt, measure contacts, mol drawframes, etc.).
  4. evals/evals.json parses, has the right top-level fields, and every eval
     has unique id, prompt and at least three expected_assertions.
  5. Every Tcl helper in scripts/ has balanced braces, declares
     `namespace eval vmdai`, and exports at least one `proc vmdai::...`.
  6. Every proc named in SKILL.md's "Quick recipe library" actually exists
     in the helper scripts.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "vmd-docking-viz"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_frontmatter(md: str) -> dict:
    """
    Lightweight frontmatter parser. Accepts:

        ---
        name: foo
        description: >
          multi-line block
          continuation
        ---

    Returns {} if no frontmatter is found.
    """
    if not md.startswith("---\n"):
        return {}
    end = md.find("\n---\n", 4)
    if end < 0:
        return {}
    body = md[4:end]
    out: dict = {}
    current_key: str | None = None
    buf: list[str] = []
    for line in body.split("\n"):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if m:
            if current_key is not None:
                out[current_key] = "\n".join(buf).strip()
            current_key = m.group(1)
            tail = m.group(2)
            if tail.strip() in (">", "|", ""):
                buf = []
            else:
                buf = [tail]
        else:
            if current_key is not None:
                buf.append(line.strip())
    if current_key is not None:
        out[current_key] = "\n".join(buf).strip()
    return out


def _balanced_braces(text: str) -> bool:
    """Return True if {} are balanced ignoring those inside # comments and
    Tcl quoted strings. Good enough for sanity checking helper scripts."""
    depth = 0
    in_string = False
    in_comment = False
    prev = ""
    for ch in text:
        if in_comment:
            if ch == "\n":
                in_comment = False
            prev = ch
            continue
        if in_string:
            if ch == '"' and prev != "\\":
                in_string = False
            prev = ch
            continue
        if ch == "#" and (prev in ("", "\n", " ", "\t", ";")):
            in_comment = True
            prev = ch
            continue
        if ch == '"':
            in_string = True
            prev = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
        prev = ch
    return depth == 0


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

class DirectoryLayoutTests(unittest.TestCase):
    def test_skill_dir_exists(self):
        self.assertTrue(SKILL_DIR.is_dir(), f"missing {SKILL_DIR}")

    def test_required_files(self):
        for relpath in [
            "SKILL.md",
            "evals/evals.json",
            "scripts/load_docking.tcl",
            "scripts/scene_preset.tcl",
            "scripts/scoring.tcl",
            "scripts/interactions.tcl",
        ]:
            self.assertTrue(
                (SKILL_DIR / relpath).is_file(),
                f"missing required file: {relpath}",
            )


class SkillMdFrontmatterTests(unittest.TestCase):
    def setUp(self):
        self.md = _read(SKILL_DIR / "SKILL.md")
        self.fm = _parse_frontmatter(self.md)

    def test_frontmatter_present(self):
        self.assertIn("name", self.fm, "frontmatter missing 'name'")
        self.assertIn("description", self.fm, "frontmatter missing 'description'")

    def test_name_matches_dir(self):
        self.assertEqual(self.fm.get("name"), "vmd-docking-viz")

    def test_description_mentions_triggers(self):
        desc = self.fm.get("description", "").lower()
        # These trigger words are what causes the skill to fire on the
        # right user request — losing them is a regression.
        for word in [
            "docking",
            "pose",
            "vina",
            "autodock",
            "binding",
            "pdbqt",
        ]:
            self.assertIn(word, desc, f"description missing trigger word '{word}'")


class SkillMdContentTests(unittest.TestCase):
    def setUp(self):
        self.md = _read(SKILL_DIR / "SKILL.md")

    def test_three_phase_structure(self):
        for header in ["Phase 1", "Phase 2", "Phase 3"]:
            self.assertIn(header, self.md, f"SKILL.md missing '{header}' section")

    def test_workflow_checklist_present(self):
        self.assertIn("Workflow checklist", self.md)

    def test_pitfalls_section_present(self):
        self.assertIn("Common pitfalls", self.md)

    def test_mentions_key_vmd_primitives(self):
        for primitive in [
            "mol new",
            "mol addfile",
            "mol delrep",
            "mol representation",
            "mol drawframes",
            "measure contacts",
            "measure rmsd",
            "measure hbonds",
            "atomselect",
            "render snapshot",
            "TachyonInternal",
            "capture_vmd_snapshot",
            "run_vmd_command",
        ]:
            self.assertIn(
                primitive,
                self.md,
                f"SKILL.md does not mention key primitive '{primitive}'",
            )

    def test_mentions_supported_formats(self):
        for fmt in ["pdbqt", "pdb", "sdf", "mol2"]:
            self.assertIn(fmt, self.md.lower(), f"format {fmt} not documented")

    def test_publication_style_constants(self):
        # Catches accidental drift away from the publication style we share
        # with vmd-ligand-pore-viz.
        for token in ["Arial", "300", "PNG", "SVG"]:
            self.assertIn(token, self.md)

    def test_cross_references_pore_viz(self):
        # The two skills are siblings; SKILL.md should disambiguate.
        self.assertIn("vmd-ligand-pore-viz", self.md)


class EvalsJsonTests(unittest.TestCase):
    def setUp(self):
        with (SKILL_DIR / "evals" / "evals.json").open() as f:
            self.data = json.load(f)

    def test_top_level_fields(self):
        self.assertEqual(self.data.get("skill_name"), "vmd-docking-viz")
        self.assertIn("evals", self.data)
        self.assertIsInstance(self.data["evals"], list)

    def test_at_least_five_evals(self):
        # We want broad coverage of the docking workflow surface.
        self.assertGreaterEqual(len(self.data["evals"]), 5)

    def test_each_eval_well_formed(self):
        seen_ids = set()
        for ev in self.data["evals"]:
            self.assertIn("id", ev)
            self.assertIn("prompt", ev)
            self.assertIn("expected_assertions", ev)
            self.assertNotIn(
                ev["id"],
                seen_ids,
                f"duplicate eval id {ev['id']}",
            )
            seen_ids.add(ev["id"])
            self.assertIsInstance(ev["expected_assertions"], list)
            self.assertGreaterEqual(
                len(ev["expected_assertions"]),
                3,
                f"eval {ev['id']} should have >=3 assertions",
            )
            self.assertGreater(
                len(ev["prompt"].strip()),
                40,
                f"eval {ev['id']} prompt too short",
            )

    def test_eval_ids_kebab_case(self):
        for ev in self.data["evals"]:
            self.assertRegex(
                ev["id"],
                r"^[a-z][a-z0-9-]*$",
                f"id '{ev['id']}' is not kebab-case",
            )

    def test_assertions_reference_concrete_idioms(self):
        all_text = " ".join(
            " ".join(ev["expected_assertions"]) for ev in self.data["evals"]
        ).lower()
        # Across the eval suite as a whole we expect to see references to
        # most of the core docking visualization idioms.
        for needle in [
            "mol new",
            "measure contacts",
            "mol drawframes",
            "render",
            "imshow",
            "matplotlib",
            "vina",
            "rmsd",
        ]:
            self.assertIn(
                needle,
                all_text,
                f"no eval references '{needle}' — coverage gap",
            )


class TclHelperTests(unittest.TestCase):
    def setUp(self):
        self.scripts = sorted((SKILL_DIR / "scripts").glob("*.tcl"))

    def test_at_least_four_helpers(self):
        self.assertGreaterEqual(
            len(self.scripts),
            4,
            "expected at least 4 Tcl helpers (load, scene, scoring, interactions)",
        )

    def test_balanced_braces(self):
        for path in self.scripts:
            self.assertTrue(
                _balanced_braces(_read(path)),
                f"unbalanced braces in {path.name}",
            )

    def test_namespace_declared(self):
        for path in self.scripts:
            txt = _read(path)
            self.assertRegex(
                txt,
                r"namespace eval vmdai",
                f"{path.name} does not declare 'namespace eval vmdai'",
            )

    def test_each_script_exports_at_least_one_proc(self):
        for path in self.scripts:
            txt = _read(path)
            procs = re.findall(r"^proc\s+vmdai::([A-Za-z0-9_]+)", txt, re.MULTILINE)
            self.assertGreater(
                len(procs),
                0,
                f"{path.name} exports no vmdai:: procs",
            )

    def test_no_unsafe_file_writes(self):
        # The helpers should not silently overwrite arbitrary paths in a
        # user's home dir; everything writes to /tmp or via an explicit arg.
        for path in self.scripts:
            txt = _read(path)
            self.assertNotIn(
                "open /Users",
                txt,
                f"{path.name} contains a hardcoded /Users path",
            )

    def test_load_docking_exposes_expected_procs(self):
        txt = _read(SKILL_DIR / "scripts" / "load_docking.tcl")
        for proc in [
            "detect_format",
            "has_plugin",
            "load_format",
            "load_receptor",
            "load_poses",
            "load_docking",
        ]:
            self.assertIn(f"proc vmdai::{proc}", txt)

    def test_scene_preset_exposes_expected_procs(self):
        txt = _read(SKILL_DIR / "scripts" / "scene_preset.tcl")
        for proc in [
            "reset_reps",
            "display_defaults",
            "pocket_resids",
            "scene_pocket",
            "scene_pose_ensemble",
            "frame_scene",
            "highlight_clashes",
        ]:
            self.assertIn(f"proc vmdai::{proc}", txt)

    def test_scoring_exposes_expected_procs(self):
        txt = _read(SKILL_DIR / "scripts" / "scoring.tcl")
        for proc in ["vina_scores", "sdf_scores", "write_score_to_user", "score_range"]:
            self.assertIn(f"proc vmdai::{proc}", txt)

    def test_interactions_exposes_expected_procs(self):
        txt = _read(SKILL_DIR / "scripts" / "interactions.tcl")
        for proc in [
            "pose_hbonds",
            "pose_contacts",
            "pose_rmsd_matrix",
            "pose_clashes",
            "pose_clash_summary",
            "write_clash_dat",
            "write_dat",
        ]:
            self.assertIn(f"proc vmdai::{proc}", txt)


class SkillMdHelperReferencesTests(unittest.TestCase):
    """Procs advertised in SKILL.md must actually exist in the helper Tcl."""

    def setUp(self):
        self.md = _read(SKILL_DIR / "SKILL.md")
        self.helper_text = "\n".join(
            _read(p) for p in (SKILL_DIR / "scripts").glob("*.tcl")
        )

    def test_advertised_procs_exist(self):
        # Pull anything that looks like vmdai::xxx from the SKILL.md.
        advertised = sorted(set(
            re.findall(r"vmdai::([A-Za-z0-9_]+)", self.md)
        ))
        self.assertGreater(len(advertised), 0, "SKILL.md mentions no vmdai:: procs")
        missing = [
            name for name in advertised
            if f"proc vmdai::{name}" not in self.helper_text
        ]
        self.assertEqual(
            missing,
            [],
            f"SKILL.md advertises procs that don't exist: {missing}",
        )


class SiblingSkillCompatibilityTests(unittest.TestCase):
    """Light cross-checks against vmd-ligand-pore-viz so the two skills feel
    like part of the same family."""

    def setUp(self):
        sib = ROOT / "skills" / "vmd-ligand-pore-viz" / "SKILL.md"
        if not sib.is_file():
            self.skipTest("sibling skill not present")
        self.sibling_md = _read(sib)
        self.docking_md = _read(SKILL_DIR / "SKILL.md")

    def test_shares_publication_style_palette(self):
        palette = "#0072B2"
        self.assertIn(palette, self.sibling_md)
        self.assertIn(palette, self.docking_md)

    def test_both_reference_the_same_two_tools(self):
        for tool in ["run_vmd_command", "capture_vmd_snapshot"]:
            self.assertIn(tool, self.sibling_md)
            self.assertIn(tool, self.docking_md)


if __name__ == "__main__":
    unittest.main()
