"""P09-T04/T05: the Settings dialog (Part B V4; C7 Visibility)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 10


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_settings.tcl")


def test_provider_fields_change(results):
    assert_case(results, "settings-provider_fields_change", TOTAL)


def test_model_hint_caps_and_ctx(results):
    assert_case(results, "settings-model_hint_caps_and_ctx", TOTAL)


def test_low_ctx_warning(results):
    assert_case(results, "settings-low_ctx_warning", TOTAL)


def test_models_timeout_hint(results):
    assert_case(results, "settings-models_timeout_hint", TOTAL)


def test_test_connection_lines(results):
    assert_case(results, "settings-test_connection_lines", TOTAL)


def test_new_delete_profile(results):
    assert_case(results, "settings-new_delete_profile", TOTAL)


def test_no_keychain_message(results):
    assert_case(results, "settings-no_keychain_message", TOTAL)


def test_panel_prefs_saved(results):
    assert_case(results, "settings-panel_prefs_saved", TOTAL)


def test_save_while_busy(results):
    assert_case(results, "settings-save_while_busy", TOTAL)


def test_return_saves_esc_cancels(results):
    assert_case(results, "settings-return_saves_esc_cancels", TOTAL)
