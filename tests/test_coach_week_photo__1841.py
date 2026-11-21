"""Issue #1841 — coach week photo import."""

from datetime import date
from uuid import uuid4

from backend.services.coach_week_photo import (
    parse_coach_week_photo,
    photo_import_capabilities,
)


WEEK = date(2026, 11, 9)


def test_photo_capabilities_off_by_default():
    caps = photo_import_capabilities()
    assert caps["vision_enabled"] is False
    assert caps["max_bytes"] == 10 * 1024 * 1024
    assert "image/jpeg" in caps["allowed_mimes"]


class _Q:
    def __init__(self, rows=None):
        self._rows = rows or []

    def filter(self, *a, **k):
        return self

    def one_or_none(self):
        return self._rows[0] if self._rows else None


class _Sess:
    def __init__(self):
        self.added = []
        self.deleted = []

    def query(self, *a, **k):
        return _Q()

    def add(self, row):
        self.added.append(row)

    def flush(self):
        pass

    def delete(self, row):
        self.deleted.append(row)


def test_parse_photo_disabled_returns_no_rows(monkeypatch):
    monkeypatch.setattr(
        "backend.services.coach_week_photo.llm_vision_enabled",
        lambda: False,
    )
    out = parse_coach_week_photo(
        _Sess(),
        uuid4(),
        week_start=WEEK,
        image_bytes=b"\xff\xd8\xff",
        mime="image/jpeg",
    )
    assert out["vision_enabled"] is False
    assert out["rows"] == []
    assert out["commit_allowed"] is False


def test_mocked_vision_fills_rows_and_commit(monkeypatch):
    monkeypatch.setattr(
        "backend.services.coach_week_photo.llm_vision_enabled",
        lambda: True,
    )

    sample = "Tue easy 60min\nSat long 18km"

    monkeypatch.setattr(
        "backend.services.coach_week_photo.extract_coach_week_lines_from_image",
        lambda *_a, **_k: sample,
    )
    monkeypatch.setattr(
        "backend.services.coach_week_import.median_easy_pace_sec_per_km",
        lambda *_a, **_k: 400.0,
    )

    out = parse_coach_week_photo(
        _Sess(),
        uuid4(),
        week_start=WEEK,
        image_bytes=b"png",
        mime="image/png",
        today=WEEK,
    )
    assert out["commit_allowed"] is True
    assert len(out["rows"]) == 2
    assert all(r.get("inferred") for r in out["rows"] if r["parse_status"] == "ok")

    assert out.get("source") == "photo"
    assert out.get("photo_id")