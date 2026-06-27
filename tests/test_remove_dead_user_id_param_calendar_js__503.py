"""
TDD tests for issue #503: Remove dead user_id query param from calendar.js weight-entries GETs

AC: Remove `user_id=${encodeURIComponent(currentUserId)}&` from the fetch URLs
    at the two /api/weight-entries GET calls in frontend/js/calendar.js
    (fetchCalendarData ~line 58 and renderModalContent ~line 439).
"""
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
CALENDAR_JS = REPO_ROOT / "frontend" / "js" / "calendar.js"

# Regex: a fetch() call to /api/weight-entries that still includes user_id= as a query param.
# Matches patterns like:
#   fetch(`/api/weight-entries?user_id=...&...`)
#   fetch(`/api/weight-entries?user_id=...`)
DEAD_PARAM_RE = re.compile(r"""fetch\(`/api/weight-entries\?[^`]*user_id=""")


def test_ac_calendar_js_no_user_id_in_weight_entries_gets():
    """AC: calendar.js must not pass user_id= to GET /api/weight-entries."""
    content = CALENDAR_JS.read_text()
    matches = DEAD_PARAM_RE.findall(content)
    assert not matches, (
        f"calendar.js still appends dead user_id param to weight-entries GET(s): {matches}"
    )


def test_ac_calendar_js_weight_entries_fetches_still_present():
    """Sanity: the two fetch calls to /api/weight-entries were not deleted entirely."""
    content = CALENDAR_JS.read_text()
    fetches = re.findall(r"fetch\(`/api/weight-entries\?", content)
    assert len(fetches) >= 2, (
        f"Expected at least 2 fetch calls to /api/weight-entries, found {len(fetches)}. "
        "The calls may have been removed rather than just cleaned up."
    )
