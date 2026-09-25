"""In-memory stand-in for the ``keyring`` package.

``make_stub_keyring()`` returns a module object with the four functions
``vmd_ai_runtime.keys`` uses (get_keyring, get_password, set_password,
delete_password).  The backend reports ``priority = 1`` so ``KeyStore``
treats it as a usable keychain; every value lives in the module's
``_store`` dict, which the ``fake_keyring_store`` fixture exposes.
"""
from __future__ import annotations

import types
from typing import Dict, Optional, Tuple


class StubBackend:
    priority = 1

    def __init__(self, store: Dict[Tuple[str, str], str]) -> None:
        self.store = store

    def get_password(self, service: str, account: str) -> Optional[str]:
        return self.store.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.store[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.store.pop((service, account), None)


def make_stub_keyring() -> types.ModuleType:
    store: Dict[Tuple[str, str], str] = {}
    backend = StubBackend(store)
    module = types.ModuleType("keyring")
    module.__dict__.update(
        get_keyring=lambda: backend,
        get_password=backend.get_password,
        set_password=backend.set_password,
        delete_password=backend.delete_password,
        _store=store,
        _vmdai_stub=True,
    )
    return module
