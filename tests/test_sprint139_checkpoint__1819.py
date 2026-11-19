"""Phase 1 checkpoint static contracts (#1819)."""


def test_v2_training_log_page_wires_sections():
    html = open("frontend/pages/v2-training-log.html", encoding="utf-8").read()
    assert "v2-month-section" in html
    assert "v2-chart-section" in html
    assert "v2-list-section" in html
    assert "v2-training-log.js" in html
    assert "app-common.js" in html


def test_training_month_route_registered():
    src = open("backend/main.py", encoding="utf-8").read()
    assert '"/api/training/month"' in src or "'/api/training/month'" in src


def test_sync_status_adds_providers_helper():
    src = open("backend/main.py", encoding="utf-8").read()
    assert "_sync_status_with_providers" in src
    assert "build_providers" in src