"""Hermetic base for tests/ (spec §6 "Hermetic base", C9).

Order matters: ``helpers.live`` snapshots the opt-in live gates at import
time, before the autouse ``_hermetic`` fixture clears the environment for
each test.
"""
from __future__ import annotations

import contextlib
import importlib
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from unittest import mock

import pytest

from helpers.keyring_stub import make_stub_keyring
from helpers.live import LIVE_ENV

CLEARED_PREFIXES: Tuple[str, ...] = ("VMD_AI_", "ANTHROPIC_", "OPENROUTER_", "OLLAMA_")

# Originals of functions the hermetic fixture replaces, for the real_* fixtures.
_ORIGINALS: Dict[str, Callable[..., Any]] = {}


class HermeticState:
    def __init__(self, home: Path, keyring_module: ModuleType) -> None:
        self.home = home
        self.keyring = keyring_module
        self.keyring_store: Dict[Tuple[str, str], str] = keyring_module._store
        self.sleep_calls: List[float] = []


def _optional_module(name: str) -> Optional[ModuleType]:
    """Import ``name`` only if it exists (modules later plans add)."""
    if importlib.util.find_spec(name) is None:
        return None
    return importlib.import_module(name)


def _install_keyring(stack: contextlib.ExitStack, stub: ModuleType) -> None:
    try:
        import keyring as real  # noqa: F401
    except Exception:
        real = None
    if real is None or getattr(real, "_vmdai_stub", False):
        previous = sys.modules.get("keyring")
        sys.modules["keyring"] = stub

        def _restore() -> None:
            if previous is None:
                sys.modules.pop("keyring", None)
            else:
                sys.modules["keyring"] = previous

        stack.callback(_restore)
        return
    for name in ("get_keyring", "get_password", "set_password", "delete_password"):
        stack.enter_context(mock.patch.object(real, name, getattr(stub, name)))


@pytest.fixture(scope="session")
def live_env() -> Dict[str, str]:
    """The live gates as they were when pytest started (read-only by convention)."""
    return LIVE_ENV


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path) -> Iterator[HermeticState]:
    home = tmp_path / "home"
    home.mkdir()
    stub = make_stub_keyring()
    with contextlib.ExitStack() as stack:
        # patch.dict restores os.environ exactly, including keys code under
        # test adds (the adapter exports VMD_AI_OPENAI_BASE_URL, KeyStore.save
        # exports OPENROUTER_API_KEY).
        stack.enter_context(mock.patch.dict(os.environ))
        for key in list(os.environ):
            if key.startswith(CLEARED_PREFIXES):
                del os.environ[key]
        os.environ["HOME"] = str(home)
        _install_keyring(stack, stub)
        state = HermeticState(home, stub)

        # Backoff sleeps are recorded, never slept (spec §6: patch only _sleep).
        from vmd_ai_runtime import claude_loop

        stack.enter_context(
            mock.patch.object(claude_loop, "_sleep", state.sleep_calls.append)
        )

        settings_store = _optional_module("vmd_ai_runtime.settings_store")
        if settings_store is not None and hasattr(settings_store, "probe_local_ollama"):
            _ORIGINALS.setdefault("probe_local_ollama", settings_store.probe_local_ollama)
            stack.enter_context(
                mock.patch.object(settings_store, "probe_local_ollama", lambda *a, **k: [])
            )
        provider_catalog = _optional_module("vmd_ai_runtime.provider_catalog")
        if provider_catalog is not None and hasattr(provider_catalog, "clear_caches"):
            provider_catalog.clear_caches()

        yield state


@pytest.fixture
def fake_keyring_store(_hermetic: HermeticState) -> Dict[Tuple[str, str], str]:
    """The in-memory keyring for this test: {(service, account): secret}."""
    return _hermetic.keyring_store


@pytest.fixture
def sleep_calls(_hermetic: HermeticState) -> List[float]:
    """Every wait passed to claude_loop._sleep during this test, in order."""
    return _hermetic.sleep_calls


@pytest.fixture
def real_probe_local_ollama(_hermetic: HermeticState) -> Callable[..., Any]:
    """The unpatched settings_store.probe_local_ollama (tests that probe sockets)."""
    if "probe_local_ollama" not in _ORIGINALS:
        pytest.skip("vmd_ai_runtime.settings_store.probe_local_ollama does not exist yet")
    return _ORIGINALS["probe_local_ollama"]
