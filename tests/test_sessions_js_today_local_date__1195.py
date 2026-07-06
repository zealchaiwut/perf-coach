"""Tests for issue #1195: sessions.js today() uses UTC date, off-by-one in Bangkok timezone.

AC anchors verified:
  (a) today() does NOT use toISOString().slice(0,10) — the UTC-based pattern that
      causes an off-by-one before 07:00 ICT (UTC+7).
  (b) today() uses local date components: either toLocaleDateString('en-CA') or
      getFullYear/getMonth/getDate to build a YYYY-MM-DD string.
  (c) The resulting format is still YYYY-MM-DD (compatible with HTML date inputs).
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SESSIONS_JS = (ROOT / "frontend" / "js" / "sessions.js").read_text()


# ── (a) UTC pattern removed ────────────────────────────────────────────────────

def test_a_today_does_not_use_toisostring_slice():
    """today() must not derive the date via toISOString().slice(0,10) (AC-a)."""
    # Find the today() function body
    m = re.search(r"function today\(\)\s*\{([^}]+)\}", SESSIONS_JS)
    assert m, "today() function not found in sessions.js"
    body = m.group(1)
    assert "toISOString" not in body, (
        "today() still uses toISOString() — this returns UTC date, causing "
        "off-by-one in Bangkok timezone before 07:00 ICT"
    )


# ── (b) Local date method present ─────────────────────────────────────────────

def test_b_today_uses_local_date_components():
    """today() must build the date from local components (AC-b)."""
    m = re.search(r"function today\(\)\s*\{([^}]+)\}", SESSIONS_JS)
    assert m, "today() function not found in sessions.js"
    body = m.group(1)
    uses_local = (
        "toLocaleDateString" in body
        or "getFullYear" in body
        or "getMonth" in body
        or "getDate" in body
    )
    assert uses_local, (
        "today() must use local date components (toLocaleDateString, "
        "getFullYear/getMonth/getDate) to match backend _today_bkk() behaviour"
    )


# ── (c) Format is YYYY-MM-DD ──────────────────────────────────────────────────

def test_c_today_produces_yyyy_mm_dd_format():
    """today() must produce a YYYY-MM-DD string compatible with HTML date inputs (AC-c)."""
    m = re.search(r"function today\(\)\s*\{([^}]+)\}", SESSIONS_JS)
    assert m, "today() function not found in sessions.js"
    body = m.group(1)
    # Either uses 'en-CA' locale (which gives YYYY-MM-DD) or manually pads
    # components with padStart/slice and joins with '-'
    uses_en_ca = "en-CA" in body
    uses_manual_pad = (
        ("padStart" in body or "slice" in body or "String(" in body)
        and '"-"' in body or "'-'" in body
    )
    # Also accept if the function contains a literal '-' separator with numeric parts
    has_dash_separator = '"-"' in body or "'-'" in body
    assert uses_en_ca or (uses_local_parts_with_dash := (
        ("getFullYear" in body or "getMonth" in body or "getDate" in body)
        and has_dash_separator
    )), (
        "today() must produce YYYY-MM-DD format: use toLocaleDateString('en-CA') "
        "or manually join getFullYear/getMonth/getDate with '-'"
    )
