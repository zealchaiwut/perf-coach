"""Tests for issue #1518: stale 'SCHEMA_VERSION 2' docstrings in daily_brief.py."""

import backend.services.daily_brief as daily_brief_module
from backend.services.daily_brief import build_brief


def test_module_docstring_references_version_3():
    """AC: module docstring must not say 'SCHEMA_VERSION 2'."""
    assert "SCHEMA_VERSION 2" not in (daily_brief_module.__doc__ or "")


def test_build_brief_docstring_references_version_3():
    """AC: build_brief docstring must not say 'SCHEMA_VERSION 2'."""
    assert "SCHEMA_VERSION 2" not in (build_brief.__doc__ or "")


def test_module_docstring_references_correct_version():
    """AC: module docstring explicitly mentions the correct SCHEMA_VERSION."""
    version = str(daily_brief_module.SCHEMA_VERSION)
    assert version in (daily_brief_module.__doc__ or "")


def test_build_brief_docstring_references_correct_version():
    """AC: build_brief docstring explicitly mentions the correct SCHEMA_VERSION."""
    version = str(daily_brief_module.SCHEMA_VERSION)
    assert version in (build_brief.__doc__ or "")
