"""keys.py's "No keychain backend" branch (C9): no keyring module at all."""
from __future__ import annotations

import os
import sys


def test_save_reports_no_keychain_backend(monkeypatch, fake_keyring_store):
    from vmd_ai_runtime.keys import KeyStore, read_keyring_for_provider

    monkeypatch.setitem(sys.modules, "keyring", None)  # `import keyring` now fails
    store = KeyStore()
    result = store.save("openrouter", "sk-or-no-backend")
    assert (result.ok, result.source, result.message) == (
        False, "none", "No keychain backend available",
    )
    assert store.test("openrouter") == {
        "ok": False, "message": "No keychain backend available", "source": "none",
    }
    key, error = read_keyring_for_provider("openrouter")
    assert key == "" and error is not None and error.startswith("keychain read failed")
    assert fake_keyring_store == {}
    assert "OPENROUTER_API_KEY" not in os.environ
