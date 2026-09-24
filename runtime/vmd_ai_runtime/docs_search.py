"""
docs_search.py — local retrieval over VMD documentation, the Tcl reference,
and the bundled skills library.

Pure stdlib BM25. No torch / no embedding model — for technical docs (where
queries reuse exact identifiers like "atomselect", "mol representation",
"NewCartoon") sparse lexical match is competitive with embeddings and adds
zero install weight.

Index files live under ~/.vmdai/docs_index/ by default:

    manifest.json    # version, source roots, build timestamp, chunk_count
    chunks.jsonl     # one chunk per line: {id, source, section, text, scope}
    bm25.json        # serialized BM25 state (df, idf, doc lengths, tokens)

The runtime constructs one ``DocsSearch`` and lazy-loads on first query so
sessions that never invoke the tool don't pay the load cost.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


# ----------------------------------------------------------------------
# Tokenization
# ----------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


def tokenize(text: str) -> List[str]:
    """Lowercase, alphanumeric+underscore tokens, length >= 2.

    No stemming. Technical reference text uses exact identifiers ("noh",
    "Licorice", "atomselect") that lemmatizers butcher. This keeps the
    index keyed on terms users actually type.
    """
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(str(text or ""))]


# ----------------------------------------------------------------------
# BM25
# ----------------------------------------------------------------------

@dataclass
class BM25State:
    """Serialization-friendly form of a fitted BM25 index."""
    N: int
    avgdl: float
    doc_lens: List[int]
    df: Dict[str, int]          # token → number of docs containing it
    idf: Dict[str, float]
    tf: List[Dict[str, int]]    # per-doc term frequency
    k1: float
    b: float

    def to_json(self) -> Dict:
        return {
            "N": self.N,
            "avgdl": self.avgdl,
            "doc_lens": self.doc_lens,
            "df": self.df,
            "idf": self.idf,
            "tf": self.tf,
            "k1": self.k1,
            "b": self.b,
        }

    @classmethod
    def from_json(cls, data: Dict) -> "BM25State":
        return cls(
            N=int(data["N"]),
            avgdl=float(data["avgdl"]),
            doc_lens=list(data["doc_lens"]),
            df={k: int(v) for k, v in data["df"].items()},
            idf={k: float(v) for k, v in data["idf"].items()},
            tf=[{k: int(v) for k, v in d.items()} for d in data["tf"]],
            k1=float(data.get("k1", 1.5)),
            b=float(data.get("b", 0.75)),
        )


def fit_bm25(corpus_tokens: List[List[str]],
             k1: float = 1.5,
             b: float = 0.75) -> BM25State:
    """Build a BM25 index from a tokenized corpus.

    Implementation note: stores per-document term frequencies eagerly so
    score() is a hash-lookup-and-multiply per query token rather than a
    re-tokenization. With ~10k chunks the in-memory size is small (a few
    MB) and search latency is sub-millisecond.
    """
    N = len(corpus_tokens)
    doc_lens = [len(d) for d in corpus_tokens]
    avgdl = (sum(doc_lens) / N) if N else 0.0

    df: Dict[str, int] = {}
    tf: List[Dict[str, int]] = []
    for doc in corpus_tokens:
        counts: Dict[str, int] = {}
        for tok in doc:
            counts[tok] = counts.get(tok, 0) + 1
        tf.append(counts)
        for tok in counts:
            df[tok] = df.get(tok, 0) + 1

    # Standard Lucene-style BM25 IDF; the +1 keeps it non-negative for
    # very common terms.
    idf = {
        tok: math.log(((N - n + 0.5) / (n + 0.5)) + 1.0)
        for tok, n in df.items()
    }
    return BM25State(
        N=N, avgdl=avgdl, doc_lens=doc_lens,
        df=df, idf=idf, tf=tf, k1=k1, b=b,
    )


def score_bm25(state: BM25State, query_tokens: Iterable[str]) -> List[float]:
    """Score every document in the corpus for a given query."""
    scores = [0.0] * state.N
    if state.N == 0 or state.avgdl == 0:
        return scores
    k1, b, avgdl = state.k1, state.b, state.avgdl
    for q in query_tokens:
        idf = state.idf.get(q)
        if idf is None:
            continue
        for i, tf_dict in enumerate(state.tf):
            f = tf_dict.get(q, 0)
            if f == 0:
                continue
            doc_len = state.doc_lens[i]
            num = f * (k1 + 1)
            den = f + k1 * (1 - b + b * doc_len / avgdl)
            scores[i] += idf * num / den
    return scores


# ----------------------------------------------------------------------
# Chunking
# ----------------------------------------------------------------------

@dataclass
class Chunk:
    id: str
    source: str
    section: str
    text: str
    scope: str

    def to_json(self) -> Dict:
        return {
            "id": self.id,
            "source": self.source,
            "section": self.section,
            "text": self.text,
            "scope": self.scope,
        }


def _slug(text: str, max_len: int = 40) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned[:max_len] or "chunk"


def chunk_markdown(path: str,
                   text: str,
                   scope: str,
                   *,
                   max_chars: int = 4000) -> List[Chunk]:
    """Split a markdown document on top-level (## ) headings.

    Sections longer than ``max_chars`` get further split on blank lines
    so a single huge section doesn't dominate the index. The ``id`` is a
    stable hash of source path + heading slug so re-indexing the same
    file produces the same chunk ids.
    """
    lines = text.splitlines()
    sections: List[Tuple[str, List[str]]] = []
    current_heading = "intro"
    current_body: List[str] = []

    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            if current_body:
                sections.append((current_heading, current_body))
            current_heading = line[3:].strip() or "section"
            current_body = []
        else:
            current_body.append(line)
    if current_body:
        sections.append((current_heading, current_body))

    out: List[Chunk] = []
    base = _slug(Path(path).stem)
    for heading, body in sections:
        body_text = "\n".join(body).strip()
        if not body_text:
            continue
        section_slug = _slug(heading)
        if len(body_text) <= max_chars:
            out.append(Chunk(
                id=f"{base}::{section_slug}::0",
                source=str(path),
                section=heading,
                text=f"## {heading}\n\n{body_text}",
                scope=scope,
            ))
            continue
        # Section too long → split on blank lines, packing into windows
        # of <= max_chars without breaking paragraphs.
        windows: List[List[str]] = [[]]
        cur_len = 0
        for paragraph in body_text.split("\n\n"):
            if cur_len + len(paragraph) > max_chars and windows[-1]:
                windows.append([])
                cur_len = 0
            windows[-1].append(paragraph)
            cur_len += len(paragraph) + 2
        for idx, window in enumerate(windows):
            chunk_text = "\n\n".join(window).strip()
            if not chunk_text:
                continue
            out.append(Chunk(
                id=f"{base}::{section_slug}::{idx}",
                source=str(path),
                section=heading,
                text=f"## {heading}\n\n{chunk_text}",
                scope=scope,
            ))
    return out


def chunk_plaintext_ref(path: str,
                        text: str,
                        scope: str,
                        *,
                        max_chars: int = 4000) -> List[Chunk]:
    """Chunk a plaintext reference file on blank-line-separated blocks.

    Used for VMD's Tcl reference output (``vmd -dispdev text -e ...``)
    where each command is a top-of-block ALLCAPS name followed by prose.
    Falls back to fixed-window chunking if no clear block structure is
    detected.
    """
    blocks = re.split(r"\n\s*\n", text)
    out: List[Chunk] = []
    base = _slug(Path(path).stem)
    for idx, block in enumerate(blocks):
        block = block.strip()
        if not block:
            continue
        first_line = block.split("\n", 1)[0].strip()
        section = first_line[:60] if first_line else f"block {idx}"
        if len(block) > max_chars:
            for j in range(0, len(block), max_chars):
                out.append(Chunk(
                    id=f"{base}::{idx}::{j}",
                    source=str(path),
                    section=section,
                    text=block[j:j + max_chars],
                    scope=scope,
                ))
        else:
            out.append(Chunk(
                id=f"{base}::{idx}::0",
                source=str(path),
                section=section,
                text=block,
                scope=scope,
            ))
    return out


# ----------------------------------------------------------------------
# HTML chunking (stdlib only — no beautifulsoup)
# ----------------------------------------------------------------------

_HTML_HEAD_TAGS = ("h1", "h2", "h3")
_HTML_SKIP_TAGS = ("script", "style", "nav", "footer", "header", "aside")
_HTML_BLOCK_TAGS = ("p", "div", "section", "article", "li", "tr", "blockquote")


class _HtmlSectionParser(HTMLParser):
    """Walk an HTML document and emit (level, heading, body_text) tuples.

    Splits on `<h1>`/`<h2>`/`<h3>`. Drops `<script>`/`<style>`/nav cruft.
    Preserves `<pre>` whitespace because VMD's user guide puts command
    examples inside `<pre>` and that's exactly where the model needs
    exact-character fidelity. Block elements get newline separators so
    the chunker output reads naturally.

    Robustness: malformed HTML (unclosed tags, stray markup) doesn't
    crash — depth counters floor at 0, and ``finalize()`` always commits
    whatever section was in progress when input ended.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._sections: List[Tuple[int, str, str]] = []
        # The section currently being filled with body content.
        self._committed_heading: Optional[Tuple[int, str]] = None
        self._committed_body: List[str] = []
        # The heading we're parsing right now, if inside an <hN>.
        self._heading_in_progress: Optional[Tuple[int, str]] = None
        self._skip_depth = 0
        self._pre_depth = 0

    @property
    def sections(self) -> List[Tuple[int, str, str]]:
        return list(self._sections)

    # ------------------------------------------------------------------
    # HTMLParser hooks
    # ------------------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _HTML_SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _HTML_HEAD_TAGS:
            # A new heading closes the prior section. Body resets.
            self._commit_section()
            self._heading_in_progress = (int(tag[1]), "")
            return
        if tag == "pre":
            self._pre_depth += 1
            self._committed_body.append("\n")
            return
        if tag == "br":
            self._committed_body.append("\n")
            return
        if tag in _HTML_BLOCK_TAGS:
            self._committed_body.append("\n\n")
            return

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _HTML_SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in _HTML_HEAD_TAGS:
            if self._heading_in_progress is not None:
                level, text = self._heading_in_progress
                self._committed_heading = (level, text.strip() or "section")
                self._heading_in_progress = None
                self._committed_body = []
            return
        if tag == "pre":
            self._pre_depth = max(0, self._pre_depth - 1)
            self._committed_body.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._heading_in_progress is not None:
            level, text = self._heading_in_progress
            self._heading_in_progress = (level, text + data)
            return
        if self._pre_depth:
            self._committed_body.append(data)
        else:
            # Collapse runs of whitespace so body text reads cleanly.
            collapsed = re.sub(r"\s+", " ", data)
            if collapsed:
                self._committed_body.append(collapsed)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _commit_section(self) -> None:
        if self._committed_heading is None and not self._committed_body:
            return
        level, heading = self._committed_heading or (1, "intro")
        body = "".join(self._committed_body)
        # Tidy whitespace: collapse 3+ newlines to 2 and trim newlines
        # at the boundaries, but preserve leading-space indentation
        # *within* lines so <pre> code blocks keep their layout.
        body = re.sub(r"\n{3,}", "\n\n", body).strip("\n").rstrip()
        # Emit when there's body content OR a real (non-fallback) heading.
        if body or self._committed_heading is not None:
            self._sections.append((level, heading, body))
        self._committed_heading = None
        self._committed_body = []

    def finalize(self) -> List[Tuple[int, str, str]]:
        # Real-world HTML often has unclosed headings ("<h1>Title" with
        # no </h1> before EOF). Treat any heading-in-progress as if it
        # were closed at end-of-input so we don't silently drop content.
        if self._heading_in_progress is not None:
            level, text = self._heading_in_progress
            heading_text = text.strip() or "section"
            # Whatever body we'd accumulated before EOF belongs to this
            # not-yet-closed heading. Promote it.
            self._committed_heading = (level, heading_text)
            self._heading_in_progress = None
        self._commit_section()
        return self.sections


def chunk_html(path: str,
               text: str,
               scope: str,
               *,
               max_chars: int = 4000) -> List[Chunk]:
    """Chunk an HTML document on H1/H2/H3 boundaries.

    Sections that exceed ``max_chars`` get split on blank lines into
    sub-chunks (same policy as ``chunk_markdown``). Headings carry into
    the chunk text as a ``## <heading>`` line so retrieval results show
    where they came from.
    """
    parser = _HtmlSectionParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        # Malformed HTML — try to recover whatever sections we got.
        pass
    sections = parser.finalize()

    out: List[Chunk] = []
    base = _slug(Path(path).stem)
    for idx, (level, heading, body) in enumerate(sections):
        if not body and not heading:
            continue
        section_slug = _slug(heading) or f"section-{idx}"
        text_with_heading = f"## {heading}\n\n{body}".strip()
        if len(text_with_heading) <= max_chars:
            out.append(Chunk(
                id=f"{base}::{section_slug}::0",
                source=str(path),
                section=heading,
                text=text_with_heading,
                scope=scope,
            ))
            continue
        # Pack paragraphs into sub-chunks of <= max_chars.
        windows: List[List[str]] = [[]]
        cur_len = 0
        for paragraph in body.split("\n\n"):
            if cur_len + len(paragraph) > max_chars and windows[-1]:
                windows.append([])
                cur_len = 0
            windows[-1].append(paragraph)
            cur_len += len(paragraph) + 2
        for sub_idx, window in enumerate(windows):
            chunk_body = "\n\n".join(window).strip()
            if not chunk_body:
                continue
            out.append(Chunk(
                id=f"{base}::{section_slug}::{sub_idx}",
                source=str(path),
                section=heading,
                text=f"## {heading}\n\n{chunk_body}",
                scope=scope,
            ))
    return out


# ----------------------------------------------------------------------
# DocsSearch — the runtime-facing API
# ----------------------------------------------------------------------

class DocsIndexMissing(RuntimeError):
    """Raised when the index files are absent or corrupt."""


_VALID_SCOPES = ("all", "vmd_ref", "user_guide", "skills")


class DocsSearch:
    """Lazy-loaded BM25 retriever.

    Construction is cheap; the index is loaded on first ``search`` call.
    Sessions that never invoke ``search_docs`` pay no I/O cost.
    """

    DEFAULT_INDEX_DIR = "~/.vmdai/docs_index"

    def __init__(self, index_dir: Optional[str] = None):
        self.index_dir = Path(os.path.expanduser(index_dir or self.DEFAULT_INDEX_DIR))
        self._chunks: Optional[List[Dict]] = None
        self._bm25: Optional[BM25State] = None
        self._loaded = False
        self._load_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Index loading
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        chunks_path = self.index_dir / "chunks.jsonl"
        bm25_path = self.index_dir / "bm25.json"
        if not chunks_path.exists() or not bm25_path.exists():
            self._load_error = (
                f"docs index not built at {self.index_dir}. "
                f"Run: vmd-ai-index --rebuild"
            )
            self._loaded = True
            return
        try:
            chunks: List[Dict] = []
            with chunks_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    chunks.append(json.loads(line))
            with bm25_path.open("r", encoding="utf-8") as f:
                bm25_data = json.load(f)
            self._chunks = chunks
            self._bm25 = BM25State.from_json(bm25_data)
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"failed to load docs index: {exc}"
            self._chunks = None
            self._bm25 = None
        self._loaded = True

    @property
    def is_available(self) -> bool:
        self._ensure_loaded()
        return self._bm25 is not None and bool(self._chunks)

    @property
    def load_error(self) -> Optional[str]:
        self._ensure_loaded()
        return self._load_error

    # ------------------------------------------------------------------
    # Search API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        k: int = 5,
        scope: str = "all",
    ) -> Dict:
        """Return up to ``k`` ranked chunks for ``query``.

        Always returns a dict with ``ok`` and either ``results`` (on
        success) or ``error`` (on failure). The shape is stable so the
        agent can read either branch without try/except.
        """
        self._ensure_loaded()
        if not self.is_available:
            return {
                "ok": False,
                "error": self._load_error or "docs index unavailable",
                "results": [],
            }
        scope = str(scope or "all").strip().lower()
        if scope not in _VALID_SCOPES:
            return {
                "ok": False,
                "error": f"scope must be one of {_VALID_SCOPES}",
                "results": [],
            }
        try:
            k_int = max(1, min(10, int(k)))
        except Exception:
            k_int = 5

        query_tokens = tokenize(query)
        if not query_tokens:
            return {"ok": True, "results": []}

        scores = score_bm25(self._bm25, query_tokens)  # type: ignore[arg-type]
        ranked = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )

        results: List[Dict] = []
        assert self._chunks is not None
        for idx in ranked:
            if scores[idx] <= 0:
                break
            chunk = self._chunks[idx]
            if scope != "all" and chunk.get("scope") != scope:
                continue
            results.append({
                "source": chunk.get("source", ""),
                "section": chunk.get("section", ""),
                "score": round(float(scores[idx]), 4),
                "text": chunk.get("text", ""),
            })
            if len(results) >= k_int:
                break

        return {"ok": True, "results": results}


# ----------------------------------------------------------------------
# Index build helpers (used by the indexer CLI and tests)
# ----------------------------------------------------------------------

def build_index_from_chunks(out_dir: Path, chunks: List[Chunk]) -> Dict:
    """Persist a manifest + chunks.jsonl + bm25.json to ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)

    tokenized = [tokenize(c.text) for c in chunks]
    bm25 = fit_bm25(tokenized)

    chunks_path = out_dir / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.to_json(), ensure_ascii=False) + "\n")

    bm25_path = out_dir / "bm25.json"
    with bm25_path.open("w", encoding="utf-8") as f:
        json.dump(bm25.to_json(), f)

    manifest = {
        "version": 1,
        "build_ts": time.time(),
        "chunk_count": len(chunks),
        "scope_counts": _scope_counts(chunks),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def _scope_counts(chunks: List[Chunk]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for c in chunks:
        out[c.scope] = out.get(c.scope, 0) + 1
    return out
