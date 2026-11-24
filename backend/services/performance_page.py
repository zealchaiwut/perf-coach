"""Combined Performance-tab payload: one session, one shared context (#1939)."""
from __future__ import annotations

import copy
import logging
import uuid
from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.utils.time import today_bangkok

_log = logging.getLogger(__name__)
_UNSET = object()

PAGE_SECTIONS = (
    "hero",
    "radar",
    "score_cards",
    "readiness",
    "projection",
    "races",
    "coach",
    "mobility",
    "anchors",
)


class UnknownSectionError(ValueError):
    def __init__(self, unknown: list[str]):
        self.unknown = unknown
        self.allowed = list(PAGE_SECTIONS)
        super().__init__(f"unknown section(s): {', '.join(unknown)}")


def parse_sections(raw: Optional[str]) -> list[str]:
    if raw is None or not str(raw).strip():
        return list(PAGE_SECTIONS)
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    unknown = [p for p in parts if p not in PAGE_SECTIONS]
    if unknown:
        raise UnknownSectionError(unknown)
    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return seen


class PageCtx:
    """Lazy shared inputs for one Performance page request."""

    def __init__(self, session: Session, user_id: uuid.UUID, today: date):
        self.session = session
        self.user_id = user_id
        self.today = today
        self._race = _UNSET
        self._scores = _UNSET
        self._payload = _UNSET
        self._radar = _UNSET
        self._checklist = _UNSET

    @property
    def a_race(self):
        if self._race is _UNSET:
            from backend.services.perf_a_race import next_a_race

            self._race = next_a_race(self.session, self.user_id, self.today)
        return self._race

    @property
    def km(self) -> Optional[float]:
        race = self.a_race
        return float(race.distance_km) if race is not None and race.distance_km else None

    @property
    def overall_scores(self) -> dict[str, Any]:
        if self._scores is _UNSET:
            from backend.services.score_reader import get_scores

            self._scores = get_scores(self.user_id, as_of=self.today)
        return self._scores

    @property
    def performance_payload(self) -> dict[str, Any]:
        if self._payload is _UNSET:
            from backend.services import performance_scores as _ps

            self._payload = _ps.get_performance_payload(self.user_id)
        return self._payload

    @property
    def radar(self) -> dict[str, Any]:
        if self._radar is _UNSET:
            from backend.services.radar_cache import get_radar_payload

            self._radar = get_radar_payload(self.session, self.user_id, self.today)
        return self._radar

    @property
    def checklist(self) -> dict[str, Any]:
        if self._checklist is _UNSET:
            from backend.services.a_race_readiness_checklist import build_checklist

            self._checklist = build_checklist(
                self.session, self.user_id, self.today, race=self.a_race
            )
        return self._checklist


def _focus_block(ctx: PageCtx) -> dict[str, Any]:
    from backend.services import focus_ranking as fr

    out = fr.rank_axes(ctx.radar["axes"], ctx.km)
    queued = {r.axis: fr.item_dict(r) for r in fr.queued_items(ctx.session, ctx.user_id)}
    phase = fr._phase_lookup(ctx.session, ctx.user_id, ctx.today)
    ew = fr.earliest_queue_week(phase, ctx.today)
    out["suggested_queue_week"] = ew.isoformat() if ew else None
    out["queue"] = queued
    out["queued_focus"] = bool(out["focus"] and out["focus"]["axis"] in queued)
    out["advice"] = {a: w["advice"] for a, w in fr.WORK_MAP.items()}
    return out


def _section_hero(ctx: PageCtx, **_) -> dict[str, Any]:
    from backend.services.derived_cache import DERIVED_HERO, get_or_compute
    from backend.services.race_hero import build_hero

    return get_or_compute(
        ctx.session,
        ctx.user_id,
        DERIVED_HERO,
        ctx.today,
        lambda: build_hero(
            ctx.session,
            ctx.user_id,
            ctx.today,
            race=ctx.a_race,
            checklist=ctx.checklist,
        ),
    )


def _section_radar(ctx: PageCtx, *, size: str, **_) -> dict[str, Any]:
    from backend.services.focus_ranking import rank_axes
    from backend.services.radar_payload import apply_focus_ranker
    from backend.services.radar_svg import render_radar_svg

    km = ctx.km

    def ranker(axes):
        focus = rank_axes(axes, km)["focus"]
        return focus["axis"] if focus else None

    payload = copy.deepcopy(ctx.radar)
    apply_focus_ranker(payload, ranker)
    payload["size"] = size
    payload["svg"] = render_radar_svg(payload, size)
    payload["focus"] = _focus_block(ctx)
    return payload


def _section_score_cards(ctx: PageCtx, **_) -> dict[str, Any]:
    from backend.services.derived_cache import DERIVED_SCORE_CARDS, get_or_compute
    from backend.services.score_cards import build_cards

    return get_or_compute(
        ctx.session,
        ctx.user_id,
        DERIVED_SCORE_CARDS,
        ctx.today,
        lambda: build_cards(
            ctx.user_id,
            as_of=ctx.today,
            overall=ctx.overall_scores,
            payload=ctx.performance_payload,
        ),
    )


def _section_readiness(ctx: PageCtx, **_) -> dict[str, Any]:
    return ctx.checklist


def _section_projection(ctx: PageCtx, **_) -> dict[str, Any]:
    from backend.services.derived_cache import DERIVED_PROJECTION, get_or_compute
    from backend.services.projection_view import build_projection

    return get_or_compute(
        ctx.session,
        ctx.user_id,
        DERIVED_PROJECTION,
        ctx.today,
        lambda: build_projection(
            ctx.session,
            ctx.user_id,
            ctx.today,
            race=ctx.a_race,
            overall=ctx.overall_scores["overall"],
        ),
    )


def _section_races(ctx: PageCtx, **_) -> dict[str, Any]:
    from backend.services.derived_cache import DERIVED_RACE_LIST, get_or_compute
    from backend.services.race_list import build_race_list

    return get_or_compute(
        ctx.session,
        ctx.user_id,
        DERIVED_RACE_LIST,
        ctx.today,
        lambda: build_race_list(
            ctx.session, ctx.user_id, ctx.today, race=ctx.a_race
        ),
    )


def _section_coach(ctx: PageCtx, **_) -> dict[str, Any]:
    from backend.services.coach_block import fetch_coach_block

    return fetch_coach_block(ctx.session, ctx.user_id, ctx.today)


def _section_mobility(ctx: PageCtx, **_) -> dict[str, Any]:
    from backend.models import MobilityTest
    from backend.services import axis_mobility as _mob

    rows = (
        ctx.session.query(MobilityTest)
        .filter(MobilityTest.user_id == ctx.user_id)
        .order_by(MobilityTest.test_date.desc(), MobilityTest.created_at.desc())
        .limit(12)
        .all()
    )
    axis = _mob.get_mobility(ctx.session, ctx.user_id, ctx.today)
    return {"axis": axis, "tests": [_mob.mobility_test_dict(r) for r in rows]}


def _section_anchors(ctx: PageCtx, **_) -> dict[str, Any]:
    from backend.services.axis_strength import get_anchor_lifts

    return {"anchors": get_anchor_lifts(ctx.session, ctx.user_id)}


_BUILDERS = {
    "hero": _section_hero,
    "radar": _section_radar,
    "score_cards": _section_score_cards,
    "readiness": _section_readiness,
    "projection": _section_projection,
    "races": _section_races,
    "coach": _section_coach,
    "mobility": _section_mobility,
    "anchors": _section_anchors,
}


def build_page(
    session: Session,
    user_id: uuid.UUID,
    today: Optional[date] = None,
    sections: Optional[list[str]] = None,
    *,
    size: str = "large",
) -> dict[str, Any]:
    today = today or today_bangkok()
    wanted = list(sections or PAGE_SECTIONS)
    ctx = PageCtx(session, uuid.UUID(str(user_id)), today)
    out: dict[str, Any] = {}
    for name in wanted:
        try:
            out[name] = _BUILDERS[name](ctx, size=size)
        except Exception:
            _log.exception(
                "performance page section %s failed user=%s", name, user_id
            )
            out[name] = {"error": "failed"}
    return out
