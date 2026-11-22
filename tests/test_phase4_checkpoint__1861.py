"""Issue #1861 — Phase 4 checkpoint static contracts."""
import re
from pathlib import Path

ROUTES = [
    "/api/performance/anchor-lifts",
    "/api/performance/mobility-tests",
    "/api/performance/radar",
    "/api/performance/focus",
    "/api/performance/hero",
    "/api/performance/score-cards",
    "/api/performance/projection",
    "/api/performance/races",
    "/api/performance/coach-block",
]

SERVICES = [
    "axis_spec", "axis_durability", "axis_economy", "axis_strength", "axis_mobility", "axis_snapshot",
    "radar_payload", "radar_svg", "focus_ranking", "race_hero", "score_cards", "projection_view",
    "race_list", "race_roles", "coach_block", "decision_lessons",
]


def test_phase4_mock_previews_exist():
    root = Path("docs/revamp/mocks/preview")
    assert (root / "Performance.html").is_file()
    assert (root / "Main.html").is_file()


def test_phase4_routes_registered_on_the_app():
    from backend.main import app

    paths = {r.path for r in app.routes}
    for route in ROUTES:
        assert route in paths, f"missing {route}"
    assert "/v2/performance" in paths


def test_phase4_services_exist():
    for name in SERVICES:
        assert Path(f"backend/services/{name}.py").is_file(), name


def test_phase4_performance_page_wires_every_region():
    html = Path("frontend/pages/v2-performance.html").read_text(encoding="utf-8")
    for region in ("v2-perf-hero", "v2-perf-after-race", "v2-perf-radar", "v2-perf-focus", "v2-perf-score-cards",
                   "v2-perf-projection", "v2-perf-races", "v2-perf-coach", "v2-perf-mobility", "v2-perf-strength-anchors"):
        assert f'id="{region}"' in html, region
    assert html.index("app-common.js") < html.index("v2-performance.js")  # shared lib before page script
    js = Path("frontend/js/v2-performance.js").read_text(encoding="utf-8")
    radar = Path("frontend/js/lib/perf-radar.js").read_text(encoding="utf-8")  # shared with Home
    for route in ROUTES:
        assert route in js or route in radar, f"page never calls {route}"


def test_phase4_radar_on_performance_only_p5_moves_off_home():
    """P5-1: status radar lives on Performance only; Home uses revamp hero instead."""
    home = Path("frontend/pages/v2-home.html").read_text(encoding="utf-8")
    perf = Path("frontend/pages/v2-performance.html").read_text(encoding="utf-8")
    assert "data-perf-radar" not in home
    assert "v2-home.js" in home
    assert "data-perf-radar" in perf and 'data-size="large"' in perf


def test_phase4_single_snapshot_table_feeds_every_axis():
    from backend.services import axis_snapshot

    assert set(axis_snapshot._AXIS_MODULES) == {"axis_durability", "axis_economy", "axis_strength", "axis_mobility"}


def test_phase4_single_alembic_head():
    versions = Path("alembic/versions")
    revs, downs = set(), set()
    for f in versions.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        if m:
            revs.add(m.group(1))
        d = re.search(r"^down_revision[^=]*=\s*(.+)$", text, re.M)
        if d:
            downs.update(re.findall(r"['\"]([0-9a-zA-Z_]+)['\"]", d.group(1)))
    assert len(revs - downs) == 1, revs - downs


def test_phase4_checkpoint_docs_present():
    body = Path("docs/revamp/phase4-checkpoint.md").read_text(encoding="utf-8")
    assert "Performance" in body and "Record" in body and "debrief" in body.lower()
    assert "phase4-followups" in body and "alembic upgrade head" in body
    follow = Path("docs/revamp/phase4-followups.md").read_text(encoding="utf-8")
    assert follow.count("github.com/zealchaiwut/perf-coach/issues/") >= 6
