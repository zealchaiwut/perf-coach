"""Tests for issue #752: Delete failure silently ignored in deleteEditing (training-projection.js)"""
import pytest


def test_delete_race__non_2xx_response__shows_error_message():
    # AC: When apiDelete returns a non-2xx response, an error message is displayed
    # to the user (via errEl.textContent or UIStates.showToast) instead of silently
    # doing nothing.
    pytest.skip("manual — UI-level error handling verified via design-contract gate / browser")


def test_delete_race__network_failure__shows_error_message():
    # AC: When apiDelete returns a network failure (e.g. fetch rejects), an error
    # message is displayed to the user rather than the error being swallowed.
    pytest.skip("manual — UI-level error handling verified via design-contract gate / browser")


def test_delete_race__success__no_error_message():
    # AC: When apiDelete succeeds (2xx response), the existing refresh() behavior
    # is unchanged. Verify delete removes the race from the UI.
    pytest.skip("manual — UI-level delete behavior verified via design-contract gate / browser")


def test_delete_error_handling__pattern_consistent_with_savemodal():
    # AC: The error handling pattern used in the else branch is consistent with
    # the error handling already present in saveModal() in the same file.
    pytest.skip("manual — code pattern verified via code review / static analysis")


def test_delete_error_message__cleared_before_attempt():
    # AC: The error message is cleared or hidden before a delete attempt begins
    # so stale errors do not persist across multiple actions.
    pytest.skip("manual — UI state clearing verified via design-contract gate / browser")
