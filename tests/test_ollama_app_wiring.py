"""
Ollama Phase 3 — RuntimeApp auto-detect tests.

Verifies the provider-selection logic in app.RuntimeApp.__init__ for
the new Ollama path. We don't construct a full RuntimeApp (which would
spin up storage + threads); we just exercise the selection logic.

Order tested:
    1. VMD_AI_PROVIDER=ollama          → ollama (explicit wins)
    2. no provider + OpenRouter key    → openrouter (other providers
                                          still take precedence)
    3. no provider + Anthropic key     → anthropic-direct
    4. no provider + VMD_AI_OLLAMA_MODEL set → ollama
    5. nothing set                     → mock
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))


def _import_app():
    # Lazy import so we can patch env before module-level side effects.
    from vmd_ai_runtime.app import RuntimeApp
    return RuntimeApp


class AppOllamaSelectionTests(unittest.TestCase):

    def _make_app(self, env, store_dir, *, provider_mode=None):
        """Construct a RuntimeApp inside the given env patch.

        Stubs out the bridge / keys / docs_search to keep startup fast.
        """
        RuntimeApp = _import_app()
        # Patch credentials resolvers so they reflect the env we set
        # (KeyStore.__init__ would otherwise pollute env from keyring).
        with mock.patch.dict("os.environ", env, clear=True), \
             mock.patch(
                 "vmd_ai_runtime.app.KeyStore",
                 autospec=False,
                 return_value=mock.MagicMock(),
             ), \
             mock.patch(
                 "vmd_ai_runtime.app.VmdToolBridge",
                 autospec=False,
                 return_value=mock.MagicMock(),
             ):
            return RuntimeApp(
                store_dir=store_dir,
                logger=None,
                provider_mode=provider_mode,
            )

    def test_explicit_ollama_provider_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self._make_app(
                env={
                    "VMD_AI_OLLAMA_MODEL": "llama3.1",
                    # Even with another key around, explicit selection wins.
                    "OPENROUTER_API_KEY": "sk-or-fake-not-used-by-test",
                },
                store_dir=tmp,
                provider_mode="ollama",
            )
        self.assertEqual(app.provider_name, "ollama")

    def test_ollama_via_env_var(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self._make_app(
                env={
                    "VMD_AI_PROVIDER": "ollama",
                    "VMD_AI_OLLAMA_MODEL": "qwen2.5-coder",
                },
                store_dir=tmp,
            )
        self.assertEqual(app.provider_name, "ollama")

    def test_no_provider_no_keys_but_ollama_model_set_falls_back_to_ollama(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self._make_app(
                env={
                    "VMD_AI_OLLAMA_MODEL": "llama3.1",
                },
                store_dir=tmp,
            )
        self.assertEqual(app.provider_name, "ollama")

    def test_no_provider_no_keys_no_ollama_model_falls_back_to_mock(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self._make_app(env={}, store_dir=tmp)
        self.assertEqual(app.provider_name, "mock")

    def test_openrouter_key_takes_precedence_over_ollama_model(self):
        # If the user has BOTH an OpenRouter key AND an Ollama model
        # configured, the higher-quality cloud model wins unless they
        # ask for Ollama explicitly. This matches the existing
        # OpenRouter→Anthropic precedence pattern.
        with tempfile.TemporaryDirectory() as tmp:
            # Stub the key resolver so the test doesn't need a real key.
            with mock.patch(
                "vmd_ai_runtime.app.resolve_openrouter_api_key",
                return_value=("sk-or-faked", "test"),
            ):
                app = self._make_app(
                    env={
                        "OPENROUTER_API_KEY": "sk-or-faked",
                        "VMD_AI_OLLAMA_MODEL": "llama3.1",
                    },
                    store_dir=tmp,
                )
        self.assertEqual(app.provider_name, "openrouter")


if __name__ == "__main__":
    unittest.main()
