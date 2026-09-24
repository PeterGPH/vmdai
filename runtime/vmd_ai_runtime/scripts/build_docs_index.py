"""
Build / rebuild the local VMD docs index used by the search_docs tool.

Sources (any subset; combine to get a richer index):

  - $VMD_AI_DOCS_VMD_REF       → plaintext or markdown        (scope=vmd_ref)
  - $VMD_AI_DOCS_USER_GUIDE    → plaintext, markdown, or HTML (scope=user_guide)
  - <repo>/skills              → SKILL.md files                (scope=skills)
  - --vmd-bin <path>           → run dump_help.tcl, ingest output (scope=vmd_ref)
  - --auto-detect-vmd          → search common install paths for HTML user guide
                                  and the vmd binary, then pull both

Usage examples:

    vmd-ai-index --rebuild                              # skills only
    vmd-ai-index --rebuild --auto-detect-vmd            # everything we can find
    vmd-ai-index --rebuild --vmd-bin /usr/local/bin/vmd # programmatic help dump
    vmd-ai-index --rebuild --user-guide ~/vmd-doc/ug    # explicit path
    vmd-ai-index --where                                # show stats
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

# Allow `python -m vmd_ai_runtime.scripts.build_docs_index` and
# `python build_docs_index.py` to both work.
if __package__ in (None, ""):
    HERE = Path(__file__).resolve()
    sys.path.insert(0, str(HERE.parents[2]))

from vmd_ai_runtime.docs_search import (  # noqa: E402
    Chunk,
    DocsSearch,
    build_index_from_chunks,
    chunk_html,
    chunk_markdown,
    chunk_plaintext_ref,
)


# ----------------------------------------------------------------------
# Source discovery
# ----------------------------------------------------------------------

def _default_skills_dir() -> Path:
    """Find the repo's skills/ directory by walking up from this file."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "skills"
        if candidate.is_dir():
            return candidate
    return Path("skills")


# ----------------------------------------------------------------------
# VMD install auto-detection
# ----------------------------------------------------------------------

def _candidate_vmd_install_dirs() -> List[Path]:
    """Likely locations for a VMD install on macOS / Linux / Windows.

    Order is "first match wins" — env var beats heuristic search.
    """
    candidates: List[Path] = []
    env_dir = os.getenv("VMD_INSTALL_DIR") or os.getenv("VMDDIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())

    # macOS: standard app bundle locations.
    for app_name in ("VMD 1.9.4.app", "VMD 1.9.3.app", "VMD.app"):
        candidates.append(Path("/Applications") / app_name / "Contents/vmd")
    # Linux defaults.
    candidates.extend([
        Path("/usr/local/lib/vmd"),
        Path("/opt/vmd"),
        Path.home() / "vmd",
    ])
    # Windows.
    if os.name == "nt":
        candidates.extend([
            Path(r"C:\Program Files (x86)\University of Illinois\VMD"),
            Path(r"C:\Program Files\VMD"),
        ])
    return candidates


def _detect_vmd_install() -> Optional[Path]:
    for c in _candidate_vmd_install_dirs():
        if c.is_dir():
            return c
    return None


def _detect_vmd_binary(vmd_install: Optional[Path]) -> Optional[Path]:
    # PATH first — covers Linux package managers and user-shimmed installs.
    found = shutil.which("vmd")
    if found:
        return Path(found)
    if vmd_install is None:
        return None
    # macOS app bundle: binary lives at <bundle>/Contents/vmd/vmd_MACOSXARM64
    # or similar; the wrapper `vmd` script is typically two levels up.
    for rel in ("vmd", "../MacOS/startup.command", "vmd_MACOSXARM64",
                "vmd_LINUXAMD64"):
        candidate = vmd_install / rel
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _detect_user_guide_html(vmd_install: Optional[Path]) -> Optional[Path]:
    if vmd_install is None:
        return None
    for rel in ("doc/ug", "doc/ug/html", "doc"):
        candidate = vmd_install / rel
        if candidate.is_dir():
            # Sanity: confirm at least one .html file is in there.
            for _ in candidate.rglob("*.html"):
                return candidate
    return None


# ----------------------------------------------------------------------
# Programmatic help dump via VMD itself
# ----------------------------------------------------------------------

def _dump_help_script_path() -> Path:
    """Path to the bundled dump_help.tcl script."""
    return Path(__file__).resolve().parent / "dump_help.tcl"


def _run_vmd_help_dump(vmd_bin: Path,
                       timeout_sec: float = 60.0) -> Optional[Path]:
    """Run dump_help.tcl in a headless VMD and return the output txt path.

    Returns None on failure (binary missing, non-zero exit, no output).
    The caller is responsible for cleaning up the temp file when done.
    """
    script = _dump_help_script_path()
    if not script.exists():
        print(f"[indexer] dump_help.tcl not found at {script}", file=sys.stderr)
        return None

    out_dir = Path(tempfile.mkdtemp(prefix="vmdai_help_"))
    out_path = out_dir / "vmd_help.txt"
    env = os.environ.copy()
    env["VMD_AI_HELP_OUT"] = str(out_path)

    cmd = [str(vmd_bin), "-dispdev", "text", "-e", str(script)]
    print(f"[indexer] running {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            env=env,
            timeout=timeout_sec,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print(f"[indexer] vmd binary not executable: {vmd_bin}", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"[indexer] vmd help dump timed out after {timeout_sec}s",
              file=sys.stderr)
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"[indexer] vmd help dump failed: {exc}", file=sys.stderr)
        return None

    if result.returncode != 0:
        print(f"[indexer] vmd exited with code {result.returncode}",
              file=sys.stderr)
        if result.stderr:
            print(result.stderr[:600], file=sys.stderr)
        return None
    if not out_path.exists() or out_path.stat().st_size == 0:
        print("[indexer] vmd produced no help output", file=sys.stderr)
        return None
    return out_path


# ----------------------------------------------------------------------
# Source gathering
# ----------------------------------------------------------------------

def _gather_sources(args) -> List[Tuple[Path, str, str]]:
    """Returns a list of (path, scope, kind) tuples to ingest.

    ``kind`` is one of: "markdown", "plaintext_ref", "html".
    """
    out: List[Tuple[Path, str, str]] = []

    # Auto-detect first so explicit flags can override.
    auto_install: Optional[Path] = None
    if args.auto_detect_vmd:
        auto_install = _detect_vmd_install()
        if auto_install is None:
            print("[indexer] auto-detect: no VMD install found",
                  file=sys.stderr)
        else:
            print(f"[indexer] auto-detect: VMD install at {auto_install}")

    # vmd_ref scope ----
    vmd_ref = args.vmd_ref or os.getenv("VMD_AI_DOCS_VMD_REF")
    if vmd_ref:
        out.extend(_walk_source(Path(vmd_ref).expanduser(), scope="vmd_ref"))

    # user_guide scope (now also accepts .html files) ----
    user_guide = args.user_guide or os.getenv("VMD_AI_DOCS_USER_GUIDE")
    if user_guide:
        out.extend(_walk_source(Path(user_guide).expanduser(), scope="user_guide"))
    elif auto_install is not None:
        ug_dir = _detect_user_guide_html(auto_install)
        if ug_dir is not None:
            print(f"[indexer] auto-detect: user guide HTML at {ug_dir}")
            out.extend(_walk_source(ug_dir, scope="user_guide"))

    # skills scope ----
    skills = Path(args.skills).expanduser() if args.skills else _default_skills_dir()
    if skills.is_dir():
        for f in sorted(skills.rglob("SKILL.md")):
            out.append((f, "skills", "markdown"))

    # vmd-bin help dump (appended to vmd_ref scope) ----
    vmd_bin: Optional[Path] = None
    if args.vmd_bin:
        vmd_bin = Path(args.vmd_bin).expanduser()
    elif auto_install is not None:
        vmd_bin = _detect_vmd_binary(auto_install)
        if vmd_bin is not None:
            print(f"[indexer] auto-detect: vmd binary at {vmd_bin}")

    if vmd_bin is not None:
        dump_path = _run_vmd_help_dump(vmd_bin)
        if dump_path is not None:
            out.append((dump_path, "vmd_ref", "plaintext_ref"))

    return out


def _walk_source(path: Path, *, scope: str) -> List[Tuple[Path, str, str]]:
    """Walk a single user-supplied source (file or dir) and classify
    each file by extension."""
    if not path.exists():
        print(f"[indexer] source missing: {path}", file=sys.stderr)
        return []

    out: List[Tuple[Path, str, str]] = []
    if path.is_file():
        kind = _classify_extension(path)
        if kind:
            out.append((path, scope, kind))
        return out
    # Directory walk — order is alphabetical for determinism so the same
    # corpus produces the same chunk ids across rebuilds.
    for f in sorted(path.rglob("*")):
        if not f.is_file():
            continue
        kind = _classify_extension(f)
        if kind is not None:
            out.append((f, scope, kind))
    return out


def _classify_extension(path: Path) -> Optional[str]:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return "markdown"
    if suffix in (".html", ".htm"):
        return "html"
    if suffix in (".txt", ".text"):
        return "plaintext_ref"
    return None


# ----------------------------------------------------------------------
# Build pipeline
# ----------------------------------------------------------------------

def _ingest(sources: List[Tuple[Path, str, str]]) -> List[Chunk]:
    chunks: List[Chunk] = []
    for path, scope, kind in sources:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            print(f"[indexer] skipping {path}: {exc}", file=sys.stderr)
            continue
        if kind == "markdown":
            chunks.extend(chunk_markdown(str(path), text, scope))
        elif kind == "html":
            chunks.extend(chunk_html(str(path), text, scope))
        else:
            chunks.extend(chunk_plaintext_ref(str(path), text, scope))
    return chunks


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vmd-ai-index", description=__doc__)
    p.add_argument("--rebuild", action="store_true",
                   help="Build (or rebuild) the index.")
    p.add_argument("--where", action="store_true",
                   help="Print the index location and exit.")
    p.add_argument("--out", default=None,
                   help=f"Output dir (default: {DocsSearch.DEFAULT_INDEX_DIR})")
    p.add_argument("--vmd-ref", default=None,
                   help="VMD Tcl reference dir or file (md/txt/html).")
    p.add_argument("--user-guide", default=None,
                   help="VMD user guide dir or file (md/txt/html).")
    p.add_argument("--skills", default=None,
                   help="Skills directory (auto-detected if omitted).")
    p.add_argument("--vmd-bin", default=None,
                   help=("Path to vmd binary. When set, the indexer runs "
                         "dump_help.tcl in headless mode and ingests the "
                         "result into the vmd_ref scope."))
    p.add_argument("--auto-detect-vmd", action="store_true",
                   help=("Search common locations for VMD; ingests the "
                         "user guide HTML and runs --vmd-bin if found."))
    return p


def cli(argv: List[str] | None = None) -> int:
    args = _arg_parser().parse_args(argv)

    out_dir = Path(os.path.expanduser(args.out or DocsSearch.DEFAULT_INDEX_DIR))

    if args.where:
        manifest_path = out_dir / "manifest.json"
        if not manifest_path.exists():
            print(f"index dir: {out_dir} (not built)")
            return 1
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"index dir: {out_dir}")
        print(f"chunks:    {manifest.get('chunk_count')}")
        print(f"scopes:    {manifest.get('scope_counts')}")
        print(f"built:     {manifest.get('build_ts')}")
        return 0

    if not args.rebuild:
        _arg_parser().print_help()
        return 2

    sources = _gather_sources(args)
    if not sources:
        print("[indexer] no doc sources found. Pass --skills, --vmd-ref, or "
              "--user-guide, or set VMD_AI_DOCS_VMD_REF / VMD_AI_DOCS_USER_GUIDE.",
              file=sys.stderr)
        return 1

    print(f"[indexer] ingesting {len(sources)} source files...")
    chunks = _ingest(sources)
    if not chunks:
        print("[indexer] no chunks produced — check your source paths.",
              file=sys.stderr)
        return 1

    manifest = build_index_from_chunks(out_dir, chunks)
    print(f"[indexer] indexed {manifest['chunk_count']} chunks "
          f"({manifest['scope_counts']}) into {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
