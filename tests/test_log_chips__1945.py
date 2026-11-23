"""Issue #1945 — Log list D chips: plan status only when it informs."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG_JS = (REPO / "frontend" / "js" / "v2-training-log.js").read_text(encoding="utf-8")


def _fn(src: str, name: str) -> str:
    needle = "function " + name + "("
    start = src.find(needle)
    assert start != -1, name
    brace = src.find("{", start)
    depth = 0
    i = brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    raise AssertionError("unclosed " + name)


def test_unplanned_only_for_typed_strength():
    chips = _fn(LOG_JS, "badgeChips")
    assert "UNPLANNED · TYPED AT THE GYM" in chips
    assert "MATCHED COACH PLAN" in chips
    assert "PLANNED, NOT DONE" in chips
    assert "rv-chip--race-flag" in chips
    assert "RACE" in chips
    assert chips.count("UNPLANNED") == 1


def test_race_like_matches_date_and_name_without_week_race_items():
    race = _fn(LOG_JS, "isRaceLike")
    known = _fn(LOG_JS, "knownRaces")
    assert "knownRaces" in race
    assert "race_date === entry.date" in race
    assert "title.indexOf(n)" in race
    assert "state.knownRaces" in known
    assert "rollupsByWeek" in known
    assert "race_items" in known
