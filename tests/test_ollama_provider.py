"""
Ollama Phase 1 — provider.py tests.

Covers:
    resolve_ollama_host    · env-var precedence, default, normalization
    resolve_ollama_model   · env-var precedence, empty when nothing set
    OllamaProvider         · model resolution, ndjson streaming, error paths
    build_provider         · "ollama" routes to OllamaProvider

No tests hit a real Ollama server. ``urllib.request.urlopen`` is mocked
via a small context-manager fake so we can drive NDJSON byte streams
deterministically.
"""
from __future__ import annotations

import io
import json
import sys
import threading
import unittest
from pathlib import Path
from typing import Iterable, List
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.provider import (  # noqa: E402
    OllamaProvider,
    ProviderError,
    build_provider,
    resolve_ollama_host,
    resolve_ollama_model,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

class _FakeNdjsonResponse:
    """Mimic urlopen()'s context manager + iterable rows of bytes."""
    def __init__(self, ndjson_lines: Iterable[dict]):
        self._lines = [
            (json.dumps(obj) + "\n").encode("utf-8") for obj in ndjson_lines
        ]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)

    def read(self):
        return b"".join(self._lines)


def _mock_urlopen(lines):
    """Build a mock context manager for urllib.request.urlopen."""
    def _fn(req, timeout=None):
        return _FakeNdjsonResponse(lines)
    return _fn


# ----------------------------------------------------------------------
# resolve_ollama_host
# ----------------------------------------------------------------------

class ResolveHostTests(unittest.TestCase):

    def test_default_when_no_env(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("VMD_AI_OLLAMA_HOST", None)
            env.pop("OLLAMA_HOST", None)
            url, src = resolve_ollama_host()
        self.assertEqual(url, "http://localhost:11434")
        self.assertEqual(src, "default")

    def test_vmd_ai_prefix_wins(self):
        with mock.patch.dict("os.environ", {
            "VMD_AI_OLLAMA_HOST": "http://gpu-box:11434",
            "OLLAMA_HOST": "http://wrong:11434",
        }):
            url, src = resolve_ollama_host()
        self.assertEqual(url, "http://gpu-box:11434")
        self.assertEqual(src, "VMD_AI_OLLAMA_HOST")

    def test_ollama_host_fallback(self):
        with mock.patch.dict("os.environ", {
            "OLLAMA_HOST": "http://gpu-box:11434",
        }, clear=False) as env:
            env.pop("VMD_AI_OLLAMA_HOST", None)
            url, src = resolve_ollama_host()
        self.assertEqual(url, "http://gpu-box:11434")
        self.assertEqual(src, "OLLAMA_HOST")

    def test_bare_hostport_gets_http_scheme(self):
        with mock.patch.dict("os.environ", {
            "VMD_AI_OLLAMA_HOST": "192.168.1.5:11434",
        }):
            url, _src = resolve_ollama_host()
        self.assertEqual(url, "http://192.168.1.5:11434")

    def test_trailing_slash_stripped(self):
        with mock.patch.dict("os.environ", {
            "VMD_AI_OLLAMA_HOST": "http://localhost:11434/",
        }):
            url, _src = resolve_ollama_host()
        self.assertEqual(url, "http://localhost:11434")


# ----------------------------------------------------------------------
# resolve_ollama_model
# ----------------------------------------------------------------------

class ResolveModelTests(unittest.TestCase):

    def test_empty_when_nothing_set(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("VMD_AI_OLLAMA_MODEL", None)
            env.pop("OLLAMA_MODEL", None)
            name, src = resolve_ollama_model()
        self.assertEqual(name, "")
        self.assertEqual(src, "")

    def test_vmd_ai_model_wins(self):
        with mock.patch.dict("os.environ", {
            "VMD_AI_OLLAMA_MODEL": "qwen2.5-coder",
            "OLLAMA_MODEL": "llama3.1",
        }):
            name, src = resolve_ollama_model()
        self.assertEqual(name, "qwen2.5-coder")
        self.assertEqual(src, "VMD_AI_OLLAMA_MODEL")

    def test_ollama_model_fallback(self):
        with mock.patch.dict("os.environ", {
            "OLLAMA_MODEL": "llama3.1",
        }, clear=False) as env:
            env.pop("VMD_AI_OLLAMA_MODEL", None)
            name, src = resolve_ollama_model()
        self.assertEqual(name, "llama3.1")
        self.assertEqual(src, "OLLAMA_MODEL")


# ----------------------------------------------------------------------
# OllamaProvider — model resolution
# ----------------------------------------------------------------------

class ProviderResolveModelTests(unittest.TestCase):

    def test_explicit_model_wins(self):
        p = OllamaProvider(base_url="http://x:11434")
        self.assertEqual(p._resolve_model("qwen2.5-coder"), "qwen2.5-coder")

    def test_env_model_used_when_no_arg(self):
        p = OllamaProvider(base_url="http://x:11434")
        with mock.patch.dict("os.environ", {
            "VMD_AI_OLLAMA_MODEL": "llama3.1",
        }):
            self.assertEqual(p._resolve_model(""), "llama3.1")

    def test_unset_raises_with_helpful_message(self):
        p = OllamaProvider(base_url="http://x:11434")
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("VMD_AI_OLLAMA_MODEL", None)
            env.pop("OLLAMA_MODEL", None)
            with self.assertRaises(ProviderError) as ctx:
                p._resolve_model("")
        self.assertIn("VMD_AI_OLLAMA_MODEL", str(ctx.exception))


# ----------------------------------------------------------------------
# OllamaProvider — streaming
# ----------------------------------------------------------------------

class StreamResponseTests(unittest.TestCase):

    def setUp(self):
        self.provider = OllamaProvider(base_url="http://localhost:11434")
        self.cancel = threading.Event()
        self.chunks: List[str] = []

    def _on_chunk(self, s):
        self.chunks.append(s)

    def test_streams_content_chunks_in_order(self):
        ndjson = [
            {"message": {"role": "assistant", "content": "Hello"},  "done": False},
            {"message": {"role": "assistant", "content": ", "},     "done": False},
            {"message": {"role": "assistant", "content": "world!"}, "done": False},
            {"message": {"role": "assistant", "content": ""},       "done": True},
        ]
        with mock.patch(
            "vmd_ai_runtime.provider.urllib.request.urlopen",
            new=_mock_urlopen(ndjson),
        ):
            text = self.provider.stream_response(
                "hi", self.cancel, self._on_chunk, model="llama3.1",
            )
        self.assertEqual(text, "Hello, world!")
        self.assertEqual(self.chunks, ["Hello", ", ", "world!"])

    def test_cancel_event_stops_streaming_early(self):
        ndjson = [
            {"message": {"role": "assistant", "content": "first"},  "done": False},
            {"message": {"role": "assistant", "content": "second"}, "done": False},
            {"message": {"role": "assistant", "content": "third"},  "done": False},
            {"message": {"role": "assistant", "content": ""},       "done": True},
        ]

        def on_chunk(s):
            self.chunks.append(s)
            # Trigger cancel after the first chunk lands.
            if len(self.chunks) >= 1:
                self.cancel.set()

        with mock.patch(
            "vmd_ai_runtime.provider.urllib.request.urlopen",
            new=_mock_urlopen(ndjson),
        ):
            self.provider.stream_response(
                "hi", self.cancel, on_chunk, model="llama3.1",
            )
        self.assertEqual(self.chunks, ["first"])

    def test_error_field_in_stream_raises(self):
        ndjson = [
            {"error": "model 'badmodel' not found, try pulling it first"},
        ]
        with mock.patch(
            "vmd_ai_runtime.provider.urllib.request.urlopen",
            new=_mock_urlopen(ndjson),
        ):
            with self.assertRaises(ProviderError) as ctx:
                self.provider.stream_response(
                    "hi", self.cancel, self._on_chunk, model="badmodel",
                )
        self.assertIn("not found", str(ctx.exception))

    def test_empty_stream_raises(self):
        ndjson = [{"done": True}]
        with mock.patch(
            "vmd_ai_runtime.provider.urllib.request.urlopen",
            new=_mock_urlopen(ndjson),
        ):
            with self.assertRaises(ProviderError) as ctx:
                self.provider.stream_response(
                    "hi", self.cancel, self._on_chunk, model="llama3.1",
                )
        self.assertIn("empty", str(ctx.exception).lower())

    def test_malformed_line_is_skipped_not_fatal(self):
        # Simulate Ollama emitting a junk line in the middle of a valid
        # stream. Should be silently ignored, not crash the stream.
        class MixedResponse:
            def __init__(self):
                self.lines = [
                    b'{"message": {"role":"assistant","content":"a"},"done":false}\n',
                    b'this is not json at all\n',
                    b'{"message": {"role":"assistant","content":"b"},"done":true}\n',
                ]
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def __iter__(self): return iter(self.lines)
            def read(self): return b"".join(self.lines)

        with mock.patch(
            "vmd_ai_runtime.provider.urllib.request.urlopen",
            new=lambda req, timeout=None: MixedResponse(),
        ):
            text = self.provider.stream_response(
                "hi", self.cancel, self._on_chunk, model="llama3.1",
            )
        self.assertEqual(text, "ab")

    def test_unreachable_host_raises_with_hint(self):
        import urllib.error as _ue
        def boom(req, timeout=None):
            raise _ue.URLError("Connection refused")
        with mock.patch(
            "vmd_ai_runtime.provider.urllib.request.urlopen",
            new=boom,
        ):
            with self.assertRaises(ProviderError) as ctx:
                self.provider.stream_response(
                    "hi", self.cancel, self._on_chunk, model="llama3.1",
                )
        self.assertIn("unreachable", str(ctx.exception).lower())
        self.assertIn("ollama serve", str(ctx.exception).lower())


# ----------------------------------------------------------------------
# build_provider routing
# ----------------------------------------------------------------------

class BuildProviderTests(unittest.TestCase):

    def test_ollama_mode_returns_ollama_provider(self):
        name, provider = build_provider("ollama")
        self.assertEqual(name, "ollama")
        self.assertIsInstance(provider, OllamaProvider)

    def test_local_ollama_alias(self):
        name, provider = build_provider("local-ollama")
        self.assertEqual(name, "ollama")
        self.assertIsInstance(provider, OllamaProvider)


if __name__ == "__main__":
    unittest.main()
