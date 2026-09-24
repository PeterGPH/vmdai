"""
wiki_store.py — persistent LLM-maintained wiki for VMD AI.

The Wiki pattern replaces query-time RAG retrieval with a compounding,
LLM-curated knowledge base. Three layers:

    raw/    — immutable source documents (VMD manual, Tcl reference, etc.)
    wiki/   — markdown pages the LLM creates and maintains
    schema  — CLAUDE.md telling the LLM how to run the wiki

Every wiki page can pin one or more raw sources. Pinning records the
file path AND a SHA-256 hash so the wiki can detect when a source has
changed and flag dependent pages as potentially stale.

Pins live in a sidecar file (`<wiki_root>/.pins/<page>.pins.json`) rather
than the page frontmatter — this keeps the human-readable markdown clean
and lets `verify_pins()` operate without re-parsing every page.

Design notes:
  * Stdlib-only (no PyYAML). Frontmatter parser is intentionally minimal
    and handles the keys we use: ``sources`` (list of strings),
    ``related`` (list of strings), ``last_updated`` (string).
  * Path safety: every page path is resolved and confined to wiki_root.
    Source paths must resolve under raw_root. Both checks reject
    symlinks that point outside their respective roots.
  * Atomicity: page writes go through a tmp-then-rename so a crashed
    update can never leave a half-written file.
  * Log format: each entry begins with ``## [YYYY-MM-DD HH:MM:SS] kind |``
    so simple grep tools can slice the timeline (matches the
    suggestion in the LLM Wiki pattern doc).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


logger = logging.getLogger("vmdai.wiki_store")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WikiError(RuntimeError):
    """Base class for wiki errors that should be surfaced to the model
    as a tool-result error (rather than crashing the loop)."""


class WikiPathError(WikiError):
    """A page path escaped wiki_root, or a source escaped raw_root."""


class WikiNotFound(WikiError):
    """Read attempted on a page that doesn't exist."""


class WikiSourceMissing(WikiError):
    """A pinned source resolves to a file that doesn't exist."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SourcePin:
    """One pinned raw-source reference for a wiki page.

    ``path`` is stored relative to ``raw_root`` so the wiki is portable
    across machines. ``sha256`` lets ``verify_pins`` detect upstream
    changes; ``size`` is a cheap pre-check that catches truncation
    before we re-hash large files.
    """
    path: str
    sha256: str
    size: int
    pinned_at: str  # ISO 8601 UTC

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "SourcePin":
        return cls(
            path=str(data["path"]),
            sha256=str(data["sha256"]),
            size=int(data["size"]),
            pinned_at=str(data["pinned_at"]),
        )


@dataclass
class PageRecord:
    """In-memory representation of one wiki page."""
    page: str                       # slug relative to wiki_root, e.g. "concepts/atomselect.md"
    content: str                    # full file content INCLUDING frontmatter
    body: str                       # content with frontmatter stripped
    frontmatter: Dict[str, Any]     # parsed frontmatter
    pins: List[SourcePin] = field(default_factory=list)

    def to_summary(self) -> Dict[str, Any]:
        """Compact representation suitable for tool results."""
        return {
            "page": self.page,
            "frontmatter": self.frontmatter,
            "pins": [p.to_json() for p in self.pins],
            "body": self.body,
        }


# ---------------------------------------------------------------------------
# Frontmatter parser (minimal YAML-ish, stdlib only)
# ---------------------------------------------------------------------------

_FRONTMATTER_FENCE = "---"


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Extract YAML-ish frontmatter from the head of ``content``.

    Supported forms (intentionally limited — keeps stdlib only):

        ---
        key: value
        sources:
          - raw/foo.html
          - raw/bar.html
        related: [other.md, another.md]
        last_updated: 2026-05-19
        ---
        # Page body...

    Returns (frontmatter_dict, body_without_frontmatter). When the file
    has no frontmatter, returns ({}, content).
    """
    if not content.startswith(_FRONTMATTER_FENCE):
        return {}, content
    lines = content.splitlines(keepends=True)
    # First line is the opening fence; find the closing fence.
    closing_idx: Optional[int] = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\n").strip() == _FRONTMATTER_FENCE:
            closing_idx = i
            break
    if closing_idx is None:
        # Unclosed frontmatter — treat as plain content rather than error.
        return {}, content

    fm_lines = lines[1:closing_idx]
    body = "".join(lines[closing_idx + 1:])
    # Strip a single leading blank line if present, so callers don't see
    # spurious leading whitespace between frontmatter and body.
    if body.startswith("\n"):
        body = body[1:]

    fm: Dict[str, Any] = {}
    current_key: Optional[str] = None
    current_list: Optional[List[str]] = None
    for raw_line in fm_lines:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        # List item under the current key
        m_list = re.match(r"^\s*-\s+(.+?)\s*$", line)
        if m_list and current_list is not None:
            current_list.append(_unquote(m_list.group(1)))
            continue
        # New key
        m_kv = re.match(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*(.*)$", line)
        if not m_kv:
            continue
        key = m_kv.group(1).strip()
        value = m_kv.group(2).strip()
        if value == "":
            # Empty value → expect a block list to follow.
            current_key = key
            current_list = []
            fm[key] = current_list
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                fm[key] = []
            else:
                fm[key] = [_unquote(x.strip()) for x in inner.split(",")]
            current_key = None
            current_list = None
            continue
        fm[key] = _unquote(value)
        current_key = None
        current_list = None
    return fm, body


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] in {'"', "'"} and text[-1] == text[0]:
        return text[1:-1]
    return text


def render_frontmatter(fm: Dict[str, Any]) -> str:
    """Render a dict back to YAML-ish frontmatter (round-trip with parse).

    Keys are emitted in insertion order. Lists use block form (one ``- item``
    per line) for readability in Obsidian and similar markdown editors.
    """
    if not fm:
        return ""
    out: List[str] = [_FRONTMATTER_FENCE]
    for key, value in fm.items():
        if isinstance(value, list):
            if not value:
                out.append(f"{key}: []")
            else:
                out.append(f"{key}:")
                for item in value:
                    out.append(f"  - {item}")
        else:
            out.append(f"{key}: {value}")
    out.append(_FRONTMATTER_FENCE)
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# WikiStore
# ---------------------------------------------------------------------------

DEFAULT_INDEX_BODY = """# Wiki Index

This index is maintained by the agent. It lists every wiki page with a
one-line summary. The agent should read this file FIRST when answering
a question, then drill into specific pages.

## Concepts
_(none yet)_

## Procs
_(none yet)_

## Skills
_(none yet)_

## Projects
_(none yet)_
"""

DEFAULT_LOG_BODY = """# Wiki Log

Append-only chronological record. Each entry begins with
``## [YYYY-MM-DD HH:MM:SS] kind | page — detail``. Greppable.

"""

DEFAULT_SCHEMA_BODY = """# VMD AI Wiki — agent instructions

You maintain a persistent wiki of VMD knowledge. The wiki is the compiled
knowledge base; raw/ is the source of truth.

## On every user turn
1. Call `wiki_list` first. The index tells you what pages exist.
2. Call `wiki_read` on the matching page(s) before answering.
3. If no relevant page exists, fall back to `search_docs` (if available)
   or your own knowledge — and consider filing a new page afterward.
4. After answering a non-trivial question, consider `wiki_update`:
   - New pattern / comparison / analysis worth keeping → file it.
   - Reading a doc from raw/ → write a concept page that cites it.
   - Working in a project folder → update `projects/<workdir>.md`.

## Page conventions
Every page begins with YAML frontmatter:

    ---
    sources:
      - raw/path/to/source1.html
      - raw/path/to/source2.html
    related:
      - concepts/related-page.md
    last_updated: 2026-05-19
    ---

Source paths MUST resolve to real files under raw/. The wiki store
hashes each source on update so drift is detectable later.

## Linting
On request, scan for: orphan pages, stale pins (hash drift), pages with
no sources, missing cross-references.
"""


class WikiStore:
    """Filesystem-backed wiki with source pinning.

    Construct with ``wiki_root`` (where pages live) and ``raw_root``
    (where pinned sources resolve). Both directories are created on
    first use; calling ``bootstrap()`` seeds an empty wiki with the
    schema, index, and log files.

    Thread-safety: a coarse instance-level lock guards all writes. The
    wiki is single-writer in practice (one agent per session), so the
    coarse lock is fine and avoids per-page bookkeeping.
    """

    PINS_DIR = ".pins"

    def __init__(self, wiki_root: Path | str, raw_root: Optional[Path | str] = None):
        self.wiki_root = Path(wiki_root).expanduser().resolve()
        self.raw_root: Optional[Path] = (
            Path(raw_root).expanduser().resolve() if raw_root else None
        )
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def bootstrap(self, *, force: bool = False) -> Dict[str, bool]:
        """Create wiki_root + the three special files if they don't exist.

        ``force`` rewrites the special files even if they exist. Used by
        tests; in production you almost never want this because the
        agent's accumulated edits would be lost.
        """
        with self._lock:
            self.wiki_root.mkdir(parents=True, exist_ok=True)
            (self.wiki_root / self.PINS_DIR).mkdir(exist_ok=True)
            created = {}
            for name, body in (
                ("CLAUDE.md", DEFAULT_SCHEMA_BODY),
                ("index.md", DEFAULT_INDEX_BODY),
                ("log.md", DEFAULT_LOG_BODY),
            ):
                path = self.wiki_root / name
                if path.exists() and not force:
                    created[name] = False
                    continue
                path.write_text(body, encoding="utf-8")
                created[name] = True
            return created

    # ------------------------------------------------------------------
    # Paths / safety
    # ------------------------------------------------------------------

    def _resolve_page_path(self, page: str) -> Path:
        """Resolve a user-supplied page slug to an absolute path under wiki_root.

        Rejects absolute paths, ``..`` traversal, and symlinks that
        escape the root. Adds ``.md`` if missing.
        """
        slug = str(page or "").strip()
        if not slug:
            raise WikiPathError("page slug is empty")
        if os.path.isabs(slug):
            raise WikiPathError(f"page path must be relative: {slug!r}")
        if not slug.endswith(".md"):
            slug = slug + ".md"
        # Disallow the pins directory and other hidden dirs from being
        # written as if they were pages.
        first_seg = slug.split("/", 1)[0]
        if first_seg.startswith("."):
            raise WikiPathError(f"page path must not start with a dot segment: {slug!r}")
        candidate = (self.wiki_root / slug).resolve()
        try:
            candidate.relative_to(self.wiki_root)
        except ValueError as exc:
            raise WikiPathError(
                f"page path escapes wiki_root: {slug!r}"
            ) from exc
        return candidate

    def _resolve_source_path(self, source: str) -> Path:
        """Resolve a source reference relative to raw_root.

        The source path may be given as:
          * relative to raw_root (preferred — portable)
          * relative starting with ``raw/`` (so frontmatter reads
            naturally — we strip the ``raw/`` prefix internally)

        Absolute paths and traversal outside raw_root are rejected.
        """
        if self.raw_root is None:
            raise WikiPathError("raw_root is not configured; cannot pin sources")
        text = str(source or "").strip()
        if not text:
            raise WikiPathError("source path is empty")
        if os.path.isabs(text):
            raise WikiPathError(f"source path must be relative: {text!r}")
        rel = text
        # Allow "raw/foo" by stripping the prefix, since raw_root IS raw/.
        # Use the basename of raw_root rather than the literal "raw" so
        # that an alternate name (e.g. raw_root="vmd_docs") still works.
        prefix = self.raw_root.name + "/"
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
        candidate = (self.raw_root / rel).resolve()
        try:
            candidate.relative_to(self.raw_root)
        except ValueError as exc:
            raise WikiPathError(
                f"source path escapes raw_root: {source!r}"
            ) from exc
        if not candidate.exists():
            raise WikiSourceMissing(f"source not found: {source!r}")
        if not candidate.is_file():
            raise WikiSourceMissing(f"source is not a regular file: {source!r}")
        return candidate

    def _pins_path_for(self, page_slug_with_md: str) -> Path:
        """Sidecar JSON path for a page's pin record.

        The sidecar lives under ``.pins/`` with the same relative slug
        plus ``.pins.json``. Subdirectories under .pins/ mirror the
        wiki's structure so a page at ``concepts/atomselect.md`` keeps
        its pins at ``.pins/concepts/atomselect.md.pins.json``.
        """
        return self.wiki_root / self.PINS_DIR / (page_slug_with_md + ".pins.json")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read_page(self, page: str) -> PageRecord:
        path = self._resolve_page_path(page)
        if not path.exists():
            raise WikiNotFound(f"page does not exist: {page}")
        content = path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        slug = str(path.relative_to(self.wiki_root)).replace(os.sep, "/")
        pins = self._load_pins(slug)
        return PageRecord(
            page=slug,
            content=content,
            body=body,
            frontmatter=fm,
            pins=pins,
        )

    def read_index(self) -> str:
        path = self.wiki_root / "index.md"
        if not path.exists():
            raise WikiNotFound("index.md does not exist; call bootstrap() first")
        return path.read_text(encoding="utf-8")

    def list_pages(self) -> List[Dict[str, Any]]:
        """Walk wiki_root and return one entry per markdown page.

        Skips the special files (CLAUDE.md, index.md, log.md) and the
        pins sidecar directory. Each entry includes the page slug, its
        frontmatter, and a pin count — enough for the index page to be
        regenerated programmatically if desired.
        """
        if not self.wiki_root.exists():
            return []
        special = {"CLAUDE.md", "index.md", "log.md"}
        out: List[Dict[str, Any]] = []
        for path in sorted(self.wiki_root.rglob("*.md")):
            rel = path.relative_to(self.wiki_root)
            slug = str(rel).replace(os.sep, "/")
            # Skip the bookkeeping files and anything inside .pins/
            if slug in special:
                continue
            if slug.startswith(self.PINS_DIR + "/"):
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            fm, _body = parse_frontmatter(content)
            pin_count = len(self._load_pins(slug))
            out.append({
                "page": slug,
                "frontmatter": fm,
                "pin_count": pin_count,
                "size_bytes": path.stat().st_size,
            })
        return out

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def update_page(
        self,
        page: str,
        content: str,
        reason: str,
        *,
        sources: Optional[List[str]] = None,
        merge_frontmatter: bool = True,
    ) -> PageRecord:
        """Create or overwrite a wiki page, pinning any cited sources.

        ``content`` is the body the agent wants to write. The store
        adds/merges a frontmatter block so the page always carries
        machine-readable metadata. When ``sources`` is provided, each
        path is resolved under raw_root, hashed, and recorded in the
        sidecar pin file; the resolved relative paths are also written
        into ``frontmatter['sources']`` so the page is self-describing
        even outside the wiki tooling.

        ``reason`` is appended to ``log.md`` so the timeline is auditable.
        """
        with self._lock:
            path = self._resolve_page_path(page)
            path.parent.mkdir(parents=True, exist_ok=True)

            # Parse whatever the agent submitted, then merge sources/
            # last_updated into its frontmatter so callers don't have to
            # care about the exact text format.
            fm, body = parse_frontmatter(content)
            if not merge_frontmatter:
                fm = {}

            pins: List[SourcePin] = []
            normalized_sources: List[str] = []
            if sources:
                for src in sources:
                    pin = self._pin_one_source(src)
                    pins.append(pin)
                    normalized_sources.append(pin.path)
                fm["sources"] = normalized_sources

            fm["last_updated"] = _utc_now_iso_date()

            rendered = render_frontmatter(fm) + body.lstrip("\n")
            _atomic_write(path, rendered)

            # Compute the canonical slug for sidecar + log so reading
            # the page back via list_pages/read_page sees consistent keys.
            slug = str(path.relative_to(self.wiki_root)).replace(os.sep, "/")
            self._save_pins(slug, pins)

            self._append_log(
                kind="update",
                page=slug,
                detail=reason or "(no reason given)",
            )

            return PageRecord(
                page=slug,
                content=rendered,
                body=body,
                frontmatter=fm,
                pins=pins,
            )

    def _pin_one_source(self, source: str) -> SourcePin:
        path = self._resolve_source_path(source)
        sha = _sha256_of_file(path)
        size = path.stat().st_size
        # Always store the path as "raw_root_basename/relpath" so the
        # pin survives changing the absolute raw_root location.
        rel = path.relative_to(self.raw_root)  # type: ignore[arg-type]
        canonical = f"{self.raw_root.name}/{rel.as_posix()}"  # type: ignore[union-attr]
        return SourcePin(
            path=canonical,
            sha256=sha,
            size=size,
            pinned_at=_utc_now_iso(),
        )

    def _save_pins(self, slug: str, pins: List[SourcePin]) -> None:
        path = self._pins_path_for(slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not pins:
            # No pins means we should remove any stale sidecar to keep
            # the directory tidy. If removal fails (race), ignore.
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return
        payload = {
            "page": slug,
            "pinned_at": _utc_now_iso(),
            "pins": [p.to_json() for p in pins],
        }
        _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True))

    def _load_pins(self, slug: str) -> List[SourcePin]:
        path = self._pins_path_for(slug)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("could not parse pins sidecar: %s", path, exc_info=True)
            return []
        items = data.get("pins") or []
        out: List[SourcePin] = []
        for item in items:
            try:
                out.append(SourcePin.from_json(item))
            except Exception:
                logger.warning("skipping malformed pin entry in %s", path)
        return out

    # ------------------------------------------------------------------
    # Verify (drift detection)
    # ------------------------------------------------------------------

    def verify_pins(self, page: Optional[str] = None) -> Dict[str, Any]:
        """Recompute hashes for every pinned source and report drift.

        Returns a dict shaped like::

            {
              "checked": [
                  {"page": "concepts/atomselect.md", "status": "fresh"},
                  {"page": "concepts/representations.md", "status": "drift",
                   "drift": [
                       {"source": "raw/manual.html", "expected": "abc...",
                        "actual": "def..."}
                   ]},
                  {"page": "concepts/foo.md", "status": "missing",
                   "missing": ["raw/old.html"]},
              ],
              "summary": {"fresh": N, "drift": M, "missing": K},
            }

        ``status`` per page:
          * ``fresh``   — all pinned sources match the recorded hash.
          * ``drift``   — at least one source's content has changed.
          * ``missing`` — at least one pinned source has been deleted.
          * ``empty``   — page has no pins recorded.
        """
        if page is not None:
            rec = self.read_page(page)
            results = [self._verify_one(rec.page, rec.pins)]
        else:
            results = []
            for entry in self.list_pages():
                slug = entry["page"]
                pins = self._load_pins(slug)
                results.append(self._verify_one(slug, pins))

        summary = {"fresh": 0, "drift": 0, "missing": 0, "empty": 0}
        for r in results:
            summary[r["status"]] = summary.get(r["status"], 0) + 1
        return {"checked": results, "summary": summary}

    def _verify_one(self, slug: str, pins: List[SourcePin]) -> Dict[str, Any]:
        if not pins:
            return {"page": slug, "status": "empty"}
        drift: List[Dict[str, str]] = []
        missing: List[str] = []
        for pin in pins:
            try:
                path = self._resolve_source_path(pin.path)
            except WikiSourceMissing:
                missing.append(pin.path)
                continue
            actual = _sha256_of_file(path)
            if actual != pin.sha256:
                drift.append({
                    "source": pin.path,
                    "expected": pin.sha256,
                    "actual": actual,
                })
        if missing:
            return {"page": slug, "status": "missing",
                    "missing": missing, "drift": drift}
        if drift:
            return {"page": slug, "status": "drift", "drift": drift}
        return {"page": slug, "status": "fresh"}

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _append_log(self, *, kind: str, page: str, detail: str) -> None:
        path = self.wiki_root / "log.md"
        # Bootstrap on demand so manual setups (without calling bootstrap)
        # still work.
        if not path.exists():
            path.write_text(DEFAULT_LOG_BODY, encoding="utf-8")
        ts = _utc_now_iso_seconds()
        entry = f"## [{ts}] {kind} | {page} — {detail}\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(entry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_of_file(path: Path, chunk_size: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_now_iso_seconds() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _utc_now_iso_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` via tmp-then-rename.

    Guarantees no half-written file survives a crash. Falls back to a
    plain write if rename across filesystems fails (rare in practice
    since tmp + final are in the same directory).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    try:
        os.replace(tmp, path)
    except OSError:
        # Fallback path — keep the partial write but rename what we can.
        path.write_text(content, encoding="utf-8")
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
