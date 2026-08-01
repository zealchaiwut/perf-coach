"""Test for the _SUMMARY_CACHE unbounded-growth fix.

Found during a pre-master-merge review: _SUMMARY_CACHE (backend/main.py) is a
plain process-lifetime dict with no eviction. Its "monthly:<iso-date>" keys
have unbounded cardinality — every distinct month a user has ever viewed adds
a permanent entry, since only a process restart clears it. Fixed keys
("performance", "weekly") are bounded by user count and stay in L1; "monthly:*"
keys now skip L1 entirely and rely on the durable L2 table instead.

Static/pure-function only — no DB, no live server, runs under
`-m "not integration"`.
"""
from __future__ import annotations

import backend.main as main


def test_fixed_keys_are_l1_cacheable():
    assert main._l1_cacheable("performance") is True
    assert main._l1_cacheable("weekly") is True


def test_monthly_keys_are_not_l1_cacheable():
    assert main._l1_cacheable("monthly:2026-08-01") is False
    assert main._l1_cacheable("monthly:2020-01-01") is False


def test_summary_cache_put_skips_l1_for_monthly_keys(monkeypatch):
    main._SUMMARY_CACHE.clear()
    # Avoid the L2 (Neon) write — this test only cares about L1 behavior.
    monkeypatch.setattr(
        main, "Session", lambda *a, **kw: (_ for _ in ()).throw(Exception("no DB in this test"))
    )
    main._summary_cache_put("user-1", "monthly:2026-08-01", "sig", {"x": 1})
    assert ("user-1", "monthly:2026-08-01") not in main._SUMMARY_CACHE


def test_summary_cache_put_still_uses_l1_for_fixed_keys(monkeypatch):
    main._SUMMARY_CACHE.clear()
    monkeypatch.setattr(
        main, "Session", lambda *a, **kw: (_ for _ in ()).throw(Exception("no DB in this test"))
    )
    main._summary_cache_put("user-1", "performance", "sig", {"x": 1})
    assert main._SUMMARY_CACHE[("user-1", "performance")] == ("sig", {"x": 1})
