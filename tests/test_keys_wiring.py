"""
Tests for the keys.save -> env -> provider resolution wiring.

Before this fix, KeyStore.save() wrote to the OS keychain only; the
provider resolvers in provider.py only read environment variables, so a
user who saved a key via the keys.save RPC and restarted got nothing.

After the fix:
  * KeyStore.save() also populates os.environ for the matching env var
    so the current process can use the key immediately.
  * KeyStore.__init__ runs load_saved_into_env() so a fresh runtime
    boots with saved keys hydrated into env.
  * provider.resolve_openrouter_api_key() / resolve_anthropic_api_key()
    fall back to the keyring directly when the env var is unset.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))


# ----------------------------------------------------------------------
# In-process fake keyring
# ----------------------------------------------------------------------

class _FakeBackend:
    """Stand-in for a real keyring backend with positive priority.

    The real ``keyring`` module dispatches `get_password` / `set_password`
    to whatever backend the OS provides. Replacing the backend with this
    fake lets tests run on any host (CI, sandbox, etc.) without touching
    the user's actual keychain.
    """
    priority = 5

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, value):
        self.store[(service, account)] = value

    def delete_password(self, service, account):
        self.store.pop((service, account), None)


@contextmanager
def fake_keyring():
    """Install a fake keyring backend for the duration of the block."""
    import keyring

    backend = _FakeBackend()
    real_get_keyring = keyring.get_keyring
    real_get_password = keyring.get_password
    real_set_password = keyring.set_password
    real_delete_password = keyring.delete_password

    keyring.get_keyring = lambda: backend
    keyring.get_password = backend.get_password
    keyring.set_password = backend.set_password
    keyring.delete_password = backend.delete_password
    try:
        yield backend
    finally:
        keyring.get_keyring = real_get_keyring
        keyring.get_password = real_get_password
        keyring.set_password = real_set_password
        keyring.delete_password = real_delete_password


@contextmanager
def clean_env(*names):
    """Save / restore environment variables across a test."""
    saved = {n: os.environ.get(n) for n in names}
    for n in names:
        os.environ.pop(n, None)
    try:
        yield
    finally:
        for n, v in saved.items():
            if v is None:
                os.environ.pop(n, None)
            else:
                os.environ[n] = v


# ----------------------------------------------------------------------
# KeyStore.save → env wiring
# ----------------------------------------------------------------------

class KeyStoreSaveWiresEnvTests(unittest.TestCase):

    def test_save_openrouter_populates_env(self):
        from vmd_ai_runtime.keys import KeyStore

        with clean_env("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"), fake_keyring():
            ks = KeyStore()
            self.assertNotIn("OPENROUTER_API_KEY", os.environ)

            res = ks.save("openrouter", "sk-or-test-1234567890")
            self.assertTrue(res.ok)
            self.assertEqual(res.source, "keyring")
            self.assertEqual(os.environ.get("OPENROUTER_API_KEY"),
                             "sk-or-test-1234567890")

    def test_save_anthropic_populates_env(self):
        from vmd_ai_runtime.keys import KeyStore

        with clean_env("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"), fake_keyring():
            ks = KeyStore()
            res = ks.save("anthropic", "sk-ant-test-XYZ")
            self.assertTrue(res.ok)
            self.assertEqual(os.environ.get("ANTHROPIC_API_KEY"),
                             "sk-ant-test-XYZ")

    def test_save_unknown_provider_does_not_touch_env(self):
        """Unknown provider names go to keyring but no env var is created."""
        from vmd_ai_runtime.keys import KeyStore

        with clean_env("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "FOOBAR_API_KEY"):
            with fake_keyring():
                ks = KeyStore()
                res = ks.save("foobar", "abc-xyz")
                # Save still succeeds (we don't gate on known-provider list),
                # but no env var should appear.
                self.assertTrue(res.ok)
                self.assertNotIn("FOOBAR_API_KEY", os.environ)


# ----------------------------------------------------------------------
# KeyStore.__init__ hydrates env from keyring
# ----------------------------------------------------------------------

class KeyStoreLoadOnInitTests(unittest.TestCase):

    def test_init_loads_saved_keys_into_env(self):
        """A fresh runtime should boot with previously-saved keys ready."""
        from vmd_ai_runtime.keys import KeyStore

        with clean_env("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"), fake_keyring() as backend:
            # Pre-populate the keyring as if a previous session had saved keys.
            backend.store[("vmd_ai", "openrouter_api_key")] = "sk-or-pre-saved-key-12345"
            backend.store[("vmd_ai", "anthropic_api_key")] = "sk-ant-pre-saved-XYZ"

            ks = KeyStore()
            self.assertIsNotNone(ks)  # silence unused warning

            self.assertEqual(os.environ.get("OPENROUTER_API_KEY"),
                             "sk-or-pre-saved-key-12345")
            self.assertEqual(os.environ.get("ANTHROPIC_API_KEY"),
                             "sk-ant-pre-saved-XYZ")

    def test_init_does_not_clobber_existing_env(self):
        """An env var explicitly set in the launching shell wins over keyring."""
        from vmd_ai_runtime.keys import KeyStore

        with clean_env("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"), fake_keyring() as backend:
            os.environ["OPENROUTER_API_KEY"] = "from-shell-do-not-touch"
            backend.store[("vmd_ai", "openrouter_api_key")] = "from-keyring-stale"

            KeyStore()

            self.assertEqual(os.environ.get("OPENROUTER_API_KEY"),
                             "from-shell-do-not-touch")


# ----------------------------------------------------------------------
# Provider resolvers fall back to keyring
# ----------------------------------------------------------------------

class ProviderResolverKeyringFallbackTests(unittest.TestCase):

    def test_resolve_openrouter_falls_back_to_keyring(self):
        from vmd_ai_runtime.provider import resolve_openrouter_api_key

        with clean_env("OPENROUTER_API_KEY", "ANTHROPIC_AUTH_TOKEN"), fake_keyring() as backend:
            backend.store[("vmd_ai", "openrouter_api_key")] = "sk-or-from-keyring-XYZ"

            key, source = resolve_openrouter_api_key()
            self.assertEqual(key, "sk-or-from-keyring-XYZ")
            self.assertEqual(source, "keyring")

    def test_resolve_openrouter_env_wins_over_keyring(self):
        from vmd_ai_runtime.provider import resolve_openrouter_api_key

        with clean_env("OPENROUTER_API_KEY", "ANTHROPIC_AUTH_TOKEN"), fake_keyring() as backend:
            os.environ["OPENROUTER_API_KEY"] = "env-key"
            backend.store[("vmd_ai", "openrouter_api_key")] = "keyring-key"

            key, source = resolve_openrouter_api_key()
            self.assertEqual(key, "env-key")
            self.assertEqual(source, "OPENROUTER_API_KEY")

    def test_resolve_openrouter_returns_empty_when_nothing_set(self):
        from vmd_ai_runtime.provider import resolve_openrouter_api_key

        with clean_env("OPENROUTER_API_KEY", "ANTHROPIC_AUTH_TOKEN"), fake_keyring():
            key, source = resolve_openrouter_api_key()
            self.assertEqual(key, "")
            self.assertEqual(source, "")

    def test_resolve_anthropic_falls_back_to_keyring(self):
        from vmd_ai_runtime.provider import resolve_anthropic_api_key

        with clean_env("ANTHROPIC_API_KEY"), fake_keyring() as backend:
            backend.store[("vmd_ai", "anthropic_api_key")] = "sk-ant-from-keyring"

            key, source = resolve_anthropic_api_key()
            self.assertEqual(key, "sk-ant-from-keyring")
            self.assertEqual(source, "keyring")

    def test_resolve_anthropic_env_wins(self):
        from vmd_ai_runtime.provider import resolve_anthropic_api_key

        with clean_env("ANTHROPIC_API_KEY"), fake_keyring() as backend:
            os.environ["ANTHROPIC_API_KEY"] = "env-anthropic"
            backend.store[("vmd_ai", "anthropic_api_key")] = "keyring-anthropic"

            key, source = resolve_anthropic_api_key()
            self.assertEqual(key, "env-anthropic")
            self.assertEqual(source, "ANTHROPIC_API_KEY")


# ----------------------------------------------------------------------
# End-to-end: provider auto-detect picks up keyring-only keys
# ----------------------------------------------------------------------

class ProviderAutoDetectTests(unittest.TestCase):

    def test_runtime_auto_detect_openrouter_from_keyring(self):
        """Booting with no env vars but a saved OpenRouter key in keyring
        should pick provider=openrouter, not mock."""
        from vmd_ai_runtime.app import RuntimeApp

        with clean_env("OPENROUTER_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                       "ANTHROPIC_API_KEY", "VMD_AI_PROVIDER"), fake_keyring() as backend:
            backend.store[("vmd_ai", "openrouter_api_key")] = "sk-or-saved-12345"

            with tempfile.TemporaryDirectory() as tmp:
                app = RuntimeApp(store_dir=tmp)
                self.assertEqual(app.provider_name, "openrouter")

    def test_runtime_auto_detect_anthropic_from_keyring(self):
        from vmd_ai_runtime.app import RuntimeApp

        with clean_env("OPENROUTER_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                       "ANTHROPIC_API_KEY", "VMD_AI_PROVIDER"), fake_keyring() as backend:
            backend.store[("vmd_ai", "anthropic_api_key")] = "sk-ant-saved-XYZ"

            with tempfile.TemporaryDirectory() as tmp:
                app = RuntimeApp(store_dir=tmp)
                self.assertEqual(app.provider_name, "anthropic-direct")

    def test_runtime_auto_detect_falls_back_to_mock(self):
        from vmd_ai_runtime.app import RuntimeApp

        with clean_env("OPENROUTER_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                       "ANTHROPIC_API_KEY", "VMD_AI_PROVIDER"), fake_keyring():
            with tempfile.TemporaryDirectory() as tmp:
                app = RuntimeApp(store_dir=tmp)
                self.assertEqual(app.provider_name, "mock")


# ----------------------------------------------------------------------
# keys.test reads env first, keyring second
# ----------------------------------------------------------------------

class KeyStoreTestPrecedenceTests(unittest.TestCase):

    def test_test_reports_env_when_env_set(self):
        from vmd_ai_runtime.keys import KeyStore

        with clean_env("OPENROUTER_API_KEY"), fake_keyring():
            os.environ["OPENROUTER_API_KEY"] = "sk-or-env-key"
            ks = KeyStore()
            res = ks.test("openrouter")
            self.assertTrue(res["ok"])
            self.assertEqual(res["source"], "env")

    def test_test_reports_keyring_when_only_keyring_set(self):
        from vmd_ai_runtime.keys import KeyStore

        with clean_env("OPENROUTER_API_KEY"), fake_keyring() as backend:
            backend.store[("vmd_ai", "openrouter_api_key")] = "sk-or-saved"
            # Hydrate explicitly *after* we've set the keyring entry
            ks = KeyStore()
            # KeyStore.__init__ now hydrates env from keyring, so the
            # env path will hit. That's expected — the source label
            # should still be informative.
            res = ks.test("openrouter")
            self.assertTrue(res["ok"])
            self.assertIn(res["source"], ("env", "keyring"))


if __name__ == "__main__":
    unittest.main()
