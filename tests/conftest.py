"""Shared pytest fixtures for the full test suite.

require_admin bypass (fix-loopholes Task 1): GET/POST/PATCH/DELETE
/api/users were gated behind require_admin after being found unauthenticated
(anyone could enumerate/create/rename/delete any user). ~90 existing test
files across the suite use unauthenticated POST /api/users purely as fixture
plumbing to create a throwaway test user — they were never testing that
endpoint's auth. Rather than touch every one of those files, bypass
require_admin for the whole suite by default here.

The real auth behavior (401/403 unauthenticated, 200 with a valid admin
cookie) is covered by its own tests that explicitly clear this override —
see tests/test_users_admin_auth__loophole1.py.
"""
from backend.auth import require_admin
from backend.main import app


def _admin_bypass():
    return None


app.dependency_overrides[require_admin] = _admin_bypass
