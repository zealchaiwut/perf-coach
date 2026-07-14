"""UAT tests for issue #1372: gap analyzer load-mix rules (runs against UAT).

These tests verify the rules behavior via the HTTP API once the feature is deployed.

UAT Test Steps from Issue #1372:
1. Seed a user training 50/50 easy/hard → expect intensity_too_hard finding
   with the actual split in evidence
2. Same user but current verdict back_off (e.g. active illness via #1350/#1351)
   → finding downgraded to severity 1 with the deferred marker

NOTE: Full HTTP-level UAT tests will be written and run in the full UAT environment
after the feature branch is merged and deployed. During SIT, the rules are verified
by the comprehensive unit test suite (test_1372_gap_analyzer_load_mix.py).
"""
import pytest


def test_placeholder():
    """Placeholder — actual HTTP tests run in UAT after deployment."""
    pytest.skip("UAT tests deferred to full UAT environment after merge")
