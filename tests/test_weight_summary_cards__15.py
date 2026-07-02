"""
Tests for issue #15: Weight — three summary cards above chart
(This week avg / 30-day trend / Days logged)
Server under test: http://127.0.0.1:9001
"""
import datetime
import pathlib
import re
import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()

# ISO week: Monday = weekday 0
THIS_MONDAY = TODAY - datetime.timedelta(days=TODAY.weekday())
THIS_WEEK_DATES = [THIS_MONDAY + datetime.timedelta(days=i) for i in range(7)]
PREV_MONDAY = THIS_MONDAY - datetime.timedelta(weeks=1)
PREV_WEEK_DATES = [PREV_MONDAY + datetime.timedelta(days=i) for i in range(7)]
THIRTY_AGO = TODAY - datetime.timedelta(days=29)


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


@pytest.fixture(scope="module")
def bob_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    bob = next((u for u in res.json() if u["name"] == "Bob"), None)
    assert bob is not None, "Bob not found in /api/users"
    return bob["id"]


def _clean(client, user_id):
    from_d = (TODAY - datetime.timedelta(days=364)).isoformat()
    res = client.get(f"/api/weight-entries?user_id={user_id}&from={from_d}&to={TODAY_STR}")
    if res.status_code == 200:
        for e in res.json().get("entries", []):
            client.delete(f"/api/weight-entries/{e['id']}")


def _post(client, user_id, date_str, weight_kg):
    res = client.post(
        "/api/weight-entries",
        json={"user_id": user_id, "weight_kg": weight_kg, "entry_date": date_str},
    )
    assert res.status_code in (201, 409), f"Unexpected {res.status_code}: {res.text}"
    return res


# ── AC-1: Row of 3 summary cards above the chart ─────────────────────────────

def test_ac1_three_summary_card_divs_present():
    """weight.html must contain exactly 3 .summary-card elements."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    cards = re.findall(r'class="summary-card"', html)
    assert len(cards) == 3, f"Expected 3 .summary-card elements, found {len(cards)}"


def test_ac1_summary_cards_appear_before_chart():
    """#summary-cards div must appear before #weight-chart in the DOM."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    cards_pos = html.find("summary-cards")
    chart_pos = html.find("weight-chart")
    assert cards_pos != -1 and chart_pos != -1
    assert cards_pos < chart_pos, "summary-cards must come before weight-chart in HTML"


def test_ac1_summary_cards_appear_before_range_filter():
    """#summary-cards must appear before the range filter (chart wrapper)."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    cards_pos = html.find("summary-cards")
    chart_wrapper_pos = html.find("chart-wrapper")
    assert cards_pos < chart_wrapper_pos, "summary-cards must appear before chart-wrapper"


# ── AC-2: Responsive — 3-column desktop, stack vertically < 700px ────────────

def test_ac2_three_column_grid_defined():
    """CSS must define a 3-column grid for .summary-cards."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    assert "repeat(3, 1fr)" in html, "Missing 3-column grid definition for .summary-cards"


def test_ac2_max_width_700px_breakpoint():
    """CSS must include a media query at 699px or 700px to stack cards on narrow viewports."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    assert "699px" in html or "700px" in html, "No 700px breakpoint found for card stacking"


def test_ac2_narrow_viewport_uses_single_column():
    """Inside the ≤700px media query, .summary-cards must switch to single-column (grid-template-columns: 1fr)."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    # The media query block should override to 1-column
    media_block = re.search(r'@media[^{]+699px[^{]*\{(.+?)\}', html, re.DOTALL)
    if not media_block:
        media_block = re.search(r'@media[^{]+700px[^{]*\{(.+?)\}', html, re.DOTALL)
    assert media_block is not None, "No media query block found for narrow viewport"
    assert "1fr" in media_block.group(1) or "1 / 1" in media_block.group(1), \
        "Narrow-viewport media query must define single-column layout"


# ── AC-3: Card 1 — "This week avg" ───────────────────────────────────────────

def test_ac3_card1_label_and_ids_in_html():
    """weight.html must have 'This week avg' label and the required element IDs."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    assert "This week avg" in html
    assert "card-week-avg-value" in html
    assert "card-week-avg-meta" in html
    assert "card-week-avg-sub" in html


def test_ac3_card1_need_more_data_when_fewer_than_2_entries(client, alice_id):
    """API returns < 2 entries for current week → Card 1 shows 'Need more data'."""
    _clean(client, alice_id)
    # Post only 1 entry this week
    if THIS_WEEK_DATES[0] <= TODAY:
        _post(client, alice_id, THIS_WEEK_DATES[0].isoformat(), 70.0)

    entries = client.get(f"/api/weight-entries?user_id={alice_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])
    this_week = [
        e for e in entries
        if THIS_MONDAY.isoformat() <= e["entry_date"] <= THIS_WEEK_DATES[-1].isoformat()
    ]
    assert len(this_week) < 2, "Should have fewer than 2 entries to trigger 'Need more data'"


def test_ac3_card1_avg_computable_from_api(client, alice_id):
    """With ≥ 2 entries this week, API data allows computing a valid average."""
    _clean(client, alice_id)
    posted = []
    for d in THIS_WEEK_DATES:
        if d <= TODAY and len(posted) < 3:
            w = 70.0 + len(posted) * 0.5
            r = _post(client, alice_id, d.isoformat(), w)
            if r.status_code == 201:
                posted.append(w)

    assert len(posted) >= 2, f"Need at least 2 past days this week; got {len(posted)}"

    entries = client.get(f"/api/weight-entries?user_id={alice_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])
    this_week = [
        e for e in entries
        if THIS_MONDAY.isoformat() <= e["entry_date"] <= THIS_WEEK_DATES[-1].isoformat()
    ]
    assert len(this_week) >= 2
    api_avg = sum(e["weight_kg"] for e in this_week) / len(this_week)
    expected_avg = sum(posted) / len(posted)
    assert abs(api_avg - expected_avg) < 0.01, f"Avg mismatch: {api_avg} vs {expected_avg}"


def test_ac3_card1_prev_week_comparison_available(client, alice_id):
    """Card 1 sub-label needs prev-week data; API must return it from /api/weight-entries."""
    # Add previous-week entries (only dates that have already passed)
    past_prev = [d for d in PREV_WEEK_DATES if d < TODAY]
    for d in past_prev[:2]:
        _post(client, alice_id, d.isoformat(), 71.0)

    entries = client.get(f"/api/weight-entries?user_id={alice_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])
    prev_week = [
        e for e in entries
        if PREV_MONDAY.isoformat() <= e["entry_date"] <= PREV_WEEK_DATES[-1].isoformat()
    ]
    assert len(prev_week) >= 1, "Need at least 1 prev-week entry for comparison sublabel"


# ── AC-4: Card 2 — "30-day trend" ────────────────────────────────────────────

def test_ac4_card2_label_and_ids_in_html():
    """weight.html must have '30-day trend' label and required element IDs."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    assert "30-day trend" in html
    assert "card-trend-value" in html
    assert "card-trend-meta" in html
    assert "card-trend-sub" in html


def test_ac4_card2_need_more_data_when_fewer_than_14_days(client, bob_id):
    """API returns < 14 unique days in 30-day window → Card 2 shows 'Need more data'."""
    _clean(client, bob_id)
    for i in range(5):
        d = TODAY - datetime.timedelta(days=i)
        _post(client, bob_id, d.isoformat(), 75.0 - i * 0.1)

    entries = client.get(f"/api/weight-entries?user_id={bob_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])
    window = [e for e in entries if THIRTY_AGO.isoformat() <= e["entry_date"] <= TODAY_STR]
    assert len({e["entry_date"] for e in window}) < 14


def test_ac4_card2_trend_computable_with_14_plus_days(client, alice_id):
    """With ≥ 14 days, API data supports computing the 30-day change (loss)."""
    _clean(client, alice_id)
    for i in range(16):
        d = TODAY - datetime.timedelta(days=15 - i)
        if d >= THIRTY_AGO:
            _post(client, alice_id, d.isoformat(), round(73.0 - i * 0.15, 1))

    entries = client.get(f"/api/weight-entries?user_id={alice_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])
    window = sorted(
        [e for e in entries if THIRTY_AGO.isoformat() <= e["entry_date"] <= TODAY_STR],
        key=lambda e: e["entry_date"],
    )
    unique_days = len({e["entry_date"] for e in window})
    assert unique_days >= 14, f"Expected ≥ 14 days, got {unique_days}"

    change = window[-1]["weight_kg"] - window[0]["weight_kg"]
    assert change < 0, "Expected net weight loss over 30 days"


def test_ac4_card2_gain_scenario(client, bob_id):
    """With weight gain over 14+ days, API data shows positive change → ↗ (red)."""
    _clean(client, bob_id)
    for i in range(15):
        d = TODAY - datetime.timedelta(days=14 - i)
        _post(client, bob_id, d.isoformat(), round(70.0 + i * 0.2, 1))

    entries = client.get(f"/api/weight-entries?user_id={bob_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])
    window = sorted(
        [e for e in entries if THIRTY_AGO.isoformat() <= e["entry_date"] <= TODAY_STR],
        key=lambda e: e["entry_date"],
    )
    change = window[-1]["weight_kg"] - window[0]["weight_kg"]
    assert change > 0, "Expected net weight gain over 30 days"


def test_ac4_card2_date_range_sublabel_in_js():
    """weight.js must compute and display start→end date range for Card 2."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "weight.js").read_text()
    assert "trendSub" in js, "No trendSub update found in weight.js"
    assert "fmtShortDate" in js, "No date formatting function for Card 2 sublabel"


# ── AC-5: Card 3 — "Days logged" ─────────────────────────────────────────────

def test_ac5_card3_label_and_ids_in_html():
    """weight.html must have 'Days logged' label and required element IDs."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    assert "Days logged" in html
    assert "card-days-value" in html
    assert "card-days-dots" in html
    assert "card-days-sub" in html


def test_ac5_card3_days_count_matches_api(client, alice_id):
    """Card 3 N/7 value must match unique logged days this week from API."""
    _clean(client, alice_id)
    logged = []
    for d in THIS_WEEK_DATES:
        if d <= TODAY and len(logged) < 3:
            r = _post(client, alice_id, d.isoformat(), 70.0)
            if r.status_code == 201:
                logged.append(d.isoformat())

    entries = client.get(f"/api/weight-entries?user_id={alice_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])
    this_week_set = {
        e["entry_date"] for e in entries
        if THIS_MONDAY.isoformat() <= e["entry_date"] <= THIS_WEEK_DATES[-1].isoformat()
    }
    assert this_week_set == set(logged), f"API days mismatch: {this_week_set} vs {set(logged)}"


def test_ac5_card3_today_logged_state(client, alice_id):
    """When today has an entry, API confirms it — JS should show green check for today."""
    _clean(client, alice_id)
    _post(client, alice_id, TODAY_STR, 70.0)
    entries = client.get(f"/api/weight-entries?user_id={alice_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])
    assert any(e["entry_date"] == TODAY_STR for e in entries), "Today's entry must appear in API"


def test_ac5_card3_today_pending_state(client, bob_id):
    """When today has no entry, API returns empty for today — JS should show dashed circle."""
    _clean(client, bob_id)
    entries = client.get(f"/api/weight-entries?user_id={bob_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])
    assert not any(e["entry_date"] == TODAY_STR for e in entries)


def test_ac5_card3_today_not_logged_sublabel_in_js():
    """weight.js must emit 'today not logged' in Card 3 sublabel when today is missing."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "weight.js").read_text()
    assert "today not logged" in js, "Missing 'today not logged' sublabel logic"


def test_ac5_card3_7_dots_rendered_in_js():
    """weight.js must render exactly 7 day-dot spans for Mon-Sun."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "weight.js").read_text()
    assert "for (let i = 0; i < 7; i++)" in js or "i < 7" in js, \
        "weight.js must iterate over 7 days for dot row"


# ── AC-6: Consistent styling ──────────────────────────────────────────────────

def test_ac6_all_cards_have_label_class():
    """Each .summary-card must contain a .card-label (uppercase small label at top)."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    assert html.count('class="card-label"') == 3, \
        f"Expected 3 .card-label elements, found {html.count('class=\"card-label\"')}"


def test_ac6_min_height_applied_to_cards():
    """CSS must set min-height on .summary-card for consistent card heights."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    assert "min-height" in html


def test_ac6_uppercase_text_transform_for_labels():
    """CSS must use text-transform: uppercase for card labels."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    assert "uppercase" in html


def test_ac6_success_and_danger_colors_used():
    """weight.html must use --color-text-success for loss and --color-text-danger for gain."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html").read_text()
    assert "--color-text-success" in html
    assert "--color-text-danger" in html


# ── AC-7: Cards refresh on user switch ───────────────────────────────────────

def test_ac7_different_users_return_different_entries(client, alice_id, bob_id):
    """User selector refresh is backed by per-user API isolation."""
    _clean(client, alice_id)
    _clean(client, bob_id)

    for d in THIS_WEEK_DATES[:2]:
        if d <= TODAY:
            _post(client, alice_id, d.isoformat(), 65.0)

    alice_entries = client.get(f"/api/weight-entries?user_id={alice_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])
    bob_entries = client.get(f"/api/weight-entries?user_id={bob_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])

    alice_this_week = [
        e for e in alice_entries
        if THIS_MONDAY.isoformat() <= e["entry_date"] <= THIS_WEEK_DATES[-1].isoformat()
    ]
    bob_this_week = [
        e for e in bob_entries
        if THIS_MONDAY.isoformat() <= e["entry_date"] <= THIS_WEEK_DATES[-1].isoformat()
    ]

    assert len(alice_this_week) >= 1
    assert len(bob_this_week) == 0, "Bob should have no entries after clean"


def test_ac7_js_reloads_on_user_change():
    """weight.js must call loadAndRender (or equivalent) on user selector change."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "weight.js").read_text()
    assert "loadAndRender" in js
    assert "change" in js, "weight.js must listen for 'change' event on user selector"


# ── AC-8: Cards refresh after new weight entry ────────────────────────────────

def test_ac8_post_then_get_reflects_new_entry(client, alice_id):
    """After submitting a weight entry, GET /api/weight-entries immediately returns updated data."""
    _clean(client, alice_id)
    before = client.get(f"/api/weight-entries?user_id={alice_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])
    _post(client, alice_id, TODAY_STR, 69.5)
    after = client.get(f"/api/weight-entries?user_id={alice_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json().get("entries", [])
    assert len(after) == len(before) + 1, "Entry list must grow by 1 after POST"


def test_ac8_js_rerenders_after_form_submit():
    """weight.js must call loadAndRender after a successful form submission."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "weight.js").read_text()
    assert "loadAndRender" in js
    # loadAndRender calls renderSummaryCards — verify the chain exists
    assert "renderSummaryCards" in js


# ── AC-9: Computed client-side — no new endpoint ─────────────────────────────

def test_ac9_render_summary_cards_function_exists():
    """weight.js must contain a renderSummaryCards(entries) function."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "weight.js").read_text()
    assert "function renderSummaryCards" in js, \
        "Missing renderSummaryCards function in weight.js"


def test_ac9_summary_cards_called_with_api_entries():
    """renderSummaryCards must be called with entries from /api/weight-entries, not a separate fetch."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "weight.js").read_text()
    assert "renderSummaryCards(entries)" in js


def test_ac9_no_new_api_endpoints_for_summary():
    """weight.js must not introduce new API endpoints (/api/summary, /api/cards, etc.)."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "weight.js").read_text()
    for ep in ["/api/summary", "/api/cards", "/api/weekly", "/api/trend", "/api/stats"]:
        assert ep not in js, f"Unexpected new endpoint '{ep}' in weight.js"


# ── AC: New user with no data — all cards show "Need more data" ───────────────

def test_new_user_no_data_returns_empty_list(client, bob_id):
    """A user with no entries returns an empty entries list from API; all 3 cards would show 'Need more data'."""
    _clean(client, bob_id)
    data = client.get(f"/api/weight-entries?user_id={bob_id}&from={(TODAY - datetime.timedelta(days=364)).isoformat()}&to={TODAY_STR}").json()
    assert data.get("entries", []) == []
