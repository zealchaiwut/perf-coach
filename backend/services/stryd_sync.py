"""Stryd activity sync: pull activities from Stryd's PowerCenter API into the
stryd_activities cache, mirroring strava_sync. Writes SyncJob rows so the
Settings sync-history panel works the same as Strava.

Stryd has no official/public API. The calendar endpoint + field names below are
the community-known shape and are VERIFIED/ADJUSTED against a live account via
scripts/run_stryd_sync.py --inspect. raw_payload always stores the full activity
dict; every promoted field uses defensive lookups; the endpoint + field map live
in ONE place so fixing the shape is a single-file change.

reconcile.py already consumes stryd_activities, so no reconcile change is needed.
"""
import json as _json
import uuid as _uuid
import urllib.error as _urllib_error
import urllib.request as _urllib_request
from concurrent.futures import ThreadPoolExecutor as _TPool
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import StrydActivity, StrydCredentials, SyncJob
from backend.services.stryd import refresh_stryd_session_if_needed
from backend.utils.log import get_logger

logger = get_logger(__name__)

# ── Stryd PowerCenter API (verified live 2026-06-17) ─────────────────────────
# GET /users/{athlete_id}/calendar?srtDate=MM-DD-YYYY&endDate=MM-DD-YYYY
#   -> {"activities": [ {full activity incl. per-point *_list streams}, … ]}
_STRYD_API_BASE = "https://www.stryd.com/b/api/v1"
_DEFAULT_LOOKBACK_DAYS = 90
# Full-history pulls for Settings "Sync all" (Stryd PowerCenter calendar API).
_FULL_LOOKBACK_DAYS = 365 * 2


def _fmt(d: date) -> str:
    """Stryd calendar expects MM-DD-YYYY."""
    return d.strftime("%m-%d-%Y")


def fetch_stryd_activities(
    token: str,
    athlete_id: str,
    since_date: Optional[date] = None,
    before_date: Optional[date] = None,
) -> list[dict]:
    """Return raw Stryd activity dicts for the date window via the calendar API."""
    start = since_date or (datetime.now(tz=timezone.utc).date() - timedelta(days=_DEFAULT_LOOKBACK_DAYS))
    end = before_date or datetime.now(tz=timezone.utc).date()
    params = {"srtDate": _fmt(start), "endDate": _fmt(end), "sortBy": "StartDate"}
    url = f"{_STRYD_API_BASE}/users/{athlete_id}/calendar?{urlencode(params)}"
    req = _urllib_request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with _urllib_request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read())
    except _urllib_error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode()[:300]
        except Exception:
            pass
        raise RuntimeError(f"Stryd API error: {exc.code} {body}") from exc

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("activities", "data", "results", "calendar_items"):
            if isinstance(data.get(key), list):
                return data[key]
    logger.warning(
        "stryd calendar: unexpected response shape",
        extra={"keys": list(data) if isinstance(data, dict) else type(data).__name__},
    )
    return []


def fetch_stryd_activity_streams(token: str, activity_id) -> dict:
    """Full per-point streams for one activity: GET /activities/{id}
    (timestamp_list, total_power_list, heart_rate_list, cadence_list,
    stride_length_list, distance_list, speed_list, …). Verified live."""
    url = f"{_STRYD_API_BASE}/activities/{activity_id}"
    req = _urllib_request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with _urllib_request.urlopen(req, timeout=30) as resp:
        return _json.loads(resp.read())


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else None


def _normalized_power(power_list, window: int = 30):
    """Coggan NP: 4th root of the mean of 30s-rolling-avg power^4. Stream is ~1 Hz."""
    p = [x for x in power_list if isinstance(x, (int, float))]
    if len(p) < 2:
        return None
    w = min(window, len(p))
    roll = [sum(p[i:i + w]) / w for i in range(0, len(p) - w + 1)] or p
    return round((sum(x ** 4 for x in roll) / len(roll)) ** 0.25)


def compute_km_splits(streams: dict) -> list[dict]:
    """Bucket the per-point streams into 1 km splits with avg HR/power/cadence/stride.
    Cadence is normalised to steps/min (×2 when the stream is per-leg)."""
    dist = streams.get("distance_list") or []        # cumulative metres
    ts = streams.get("timestamp_list") or []
    hr = streams.get("heart_rate_list") or []
    pw = streams.get("total_power_list") or []
    cad = streams.get("cadence_list") or []
    stride = streams.get("stride_length_list") or []
    n = min(len(dist), len(ts)) if dist and ts else 0
    if n < 2:
        return []

    buckets: dict[int, dict] = {}
    for i in range(n):
        km = int(dist[i] // 1000)
        b = buckets.setdefault(km, {"t0": ts[i], "t1": ts[i], "hr": [], "pw": [], "cad": [], "stride": [], "d0": dist[i], "d1": dist[i]})
        b["t1"] = ts[i]
        b["d1"] = dist[i]
        if i < len(hr):
            b["hr"].append(hr[i])
        if i < len(pw):
            b["pw"].append(pw[i])
        if i < len(cad):
            b["cad"].append(cad[i])
        if i < len(stride):
            b["stride"].append(stride[i])

    out = []
    for km in sorted(buckets):
        b = buckets[km]
        cad_mean = _mean(b["cad"])
        if cad_mean is not None and cad_mean < 120:   # per-leg → steps/min
            cad_mean *= 2
        dist_km = round((b["d1"] - b["d0"]) / 1000, 3) or 1.0
        out.append({
            "split_index": km + 1,
            "distance_km": dist_km,
            "duration_seconds": int(b["t1"] - b["t0"]) or None,
            "avg_hr": round(_mean(b["hr"])) if b["hr"] else None,
            "avg_power": round(_mean(b["pw"])) if b["pw"] else None,
            "cadence_spm": round(cad_mean) if cad_mean is not None else None,
            "stride_length_m": round(_mean(b["stride"]), 2) if b["stride"] else None,
        })
    return out


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def _parse_start(raw: dict) -> datetime:
    ts = _first(raw, "timestamp", "start_time", "start_date", "startTime")
    if isinstance(ts, (int, float)):
        # Stryd epochs are sometimes ms; normalise.
        if ts > 1e12:
            ts = ts / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str) and ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(tz=timezone.utc)


def _slim_payload(raw: dict) -> dict:
    """Drop the per-point stream arrays (every *_list key, e.g. heart_rate_list,
    power_list, loc_list) before caching — they bloat the row and are re-fetchable.
    Keeps summary, zones, seconds_in_zones, laps, map, form."""
    return {k: v for k, v in raw.items() if not k.endswith("_list")}


def map_stryd_activity(raw: dict, user_id: str) -> dict:
    """Map a raw Stryd activity to a stryd_activities row dict. Field names
    verified against the live calendar API (2026-06-17)."""
    dist_m = _first(raw, "distance", "total_distance")
    dur = _first(raw, "moving_time", "elapsed_time")
    form = {
        "leg_spring_stiffness": _first(raw, "average_leg_spring"),
        "ground_contact_time_ms": _first(raw, "average_ground_time"),
        "vertical_oscillation_cm": _first(raw, "average_oscillation"),
        "vertical_ratio": _first(raw, "average_vertical_ratio"),
        "stride_length_m": _first(raw, "average_stride_length"),
        "cadence_spm": _first(raw, "average_cadence"),
    }
    form = {k: v for k, v in form.items() if v is not None}
    # Power zones: definition (zones[]) + time-in-zone (seconds_in_zones) + CP (ftp).
    power_zones = {
        "zones": raw.get("zones"),
        "seconds_in_zones": raw.get("seconds_in_zones"),
        "ftp": raw.get("ftp"),
    } if (raw.get("zones") or raw.get("seconds_in_zones")) else None
    raw_incline = _first(raw, "average_incline")
    return {
        "user_id": user_id,
        "stryd_activity_id": str(_first(raw, "id", "timestamp")),
        "start_time": _parse_start(raw),
        "name": _first(raw, "name") or "Stryd activity",
        "distance_km": round(float(dist_m) / 1000, 3) if dist_m else None,
        "duration_seconds": int(dur) if dur else None,
        "avg_power_w": int(raw["average_power"]) if raw.get("average_power") else None,
        "avg_hr": int(raw["average_heart_rate"]) if raw.get("average_heart_rate") else None,
        "tss": int(raw["stress"]) if raw.get("stress") else None,
        "form_metrics": form or None,
        "power_zones": power_zones,
        "splits": None,   # filled by enrichment (compute_km_splits) at sync time
        "raw_payload": _slim_payload(raw),
        "synced_at": datetime.now(tz=timezone.utc),
        "grade_percent": float(raw_incline) if raw_incline is not None else None,
    }


def _already_enriched_ids(session: Session, ids: list) -> set:
    """IDs (among ``ids``) whose row already has BOTH per-km splits and per-point
    streams. Evaluated server-side with jsonb_path_exists so the (large)
    streams_payload JSONB never leaves Postgres — pulling it client-side just to
    check timestamp_list presence costs ~600 MB of heap per sync."""
    from sqlalchemy import func, select

    return set(session.execute(
        select(StrydActivity.stryd_activity_id)
        .where(StrydActivity.stryd_activity_id.in_(ids))
        .where(func.jsonb_path_exists(StrydActivity.splits, '$[0] ? (@.type() == "object")'))
        .where(func.jsonb_path_exists(StrydActivity.streams_payload, "$.timestamp_list[0]"))
    ).scalars().all())


def _heal_candidate_ids(session: Session, uid, processed: set) -> list:
    """IDs of this user's activities still missing per-point streams, newest
    first, excluding ``processed``. Same server-side predicate rationale as
    _already_enriched_ids."""
    from sqlalchemy import func, select

    rows = session.execute(
        select(StrydActivity.stryd_activity_id)
        .where(StrydActivity.user_id == uid)
        .where(func.coalesce(
            func.jsonb_path_exists(StrydActivity.streams_payload, "$.timestamp_list[0]"),
            False,
        ).is_(False))
        .order_by(StrydActivity.start_time.desc())
    ).scalars().all()
    return [sid for sid in rows if sid not in processed]


# Max streams-less activities to backfill per full-sync heal pass (rate-limit guard).
_STREAM_HEAL_CAP = 60
# Parallel workers for per-activity stream fetches (each is an independent HTTP call).
_ENRICH_WORKERS = 4


def _enrich_one(token: str, aid, base_form: dict | None = None) -> bool:
    """Fetch one Stryd activity's streams and store streams_payload + splits +
    NP / max power. Returns True if streams were stored. Swallows errors (logged)
    so one bad activity never aborts a sync."""
    try:
        streams = fetch_stryd_activity_streams(token, aid)
        splits = compute_km_splits(streams)
        powers = [x for x in (streams.get("total_power_list") or []) if isinstance(x, (int, float))]
        fm = dict(base_form or {})
        np = _normalized_power(powers)
        if np is not None:
            fm["np_w"] = np
        if powers:
            fm["max_power_w"] = round(max(powers))
        vals: dict = {}
        if splits:
            vals["splits"] = splits
        if fm:
            vals["form_metrics"] = fm
        if streams.get("timestamp_list"):
            vals["streams_payload"] = streams
        if vals:
            with Session(engine) as session:
                session.query(StrydActivity).filter(
                    StrydActivity.stryd_activity_id == aid
                ).update(vals, synchronize_session=False)
                session.commit()
        return bool(vals.get("streams_payload"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("stryd enrich failed", extra={"activity_id": aid, "error": str(exc)})
        return False


def _enrich_many(token: str, aids: list, base_form: dict | None = None) -> None:
    """Enrich a list of activities in parallel using a thread pool."""
    bf = base_form or {}
    with _TPool(max_workers=_ENRICH_WORKERS) as pool:
        list(pool.map(lambda aid: _enrich_one(token, aid, bf.get(aid)), aids))


def sync_stryd_activities(
    user_id: str,
    since_date: Optional[date] = None,
    *,
    full: bool = False,
    heal: bool = True,
) -> dict:
    """Pull Stryd activities into stryd_activities (idempotent upsert). Writes a
    SyncJob row (source='stryd') for the history panel. Does NOT reconcile —
    caller runs reconcile. Returns counts."""
    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    now_utc = datetime.now(tz=timezone.utc)
    explicit_since = since_date is not None

    # Resolve since_date: full > explicit > last completed job > latest row > 90-day backfill.
    if full:
        since_date = now_utc.date() - timedelta(days=_FULL_LOOKBACK_DAYS)
        job_type = "full"
    elif not explicit_since:
        with Session(engine) as session:
            from sqlalchemy import func, select

            last_completed = session.execute(
                select(SyncJob.completed_at)
                .where(SyncJob.user_id == uid)
                .where(SyncJob.source == "stryd")
                .where(SyncJob.status == "completed")
                .order_by(SyncJob.completed_at.desc())
                .limit(1)
            ).scalar()
            latest_synced = session.execute(
                select(func.max(StrydActivity.synced_at))
                .where(StrydActivity.user_id == uid)
            ).scalar()
        anchor = last_completed or latest_synced
        if anchor is not None:
            since_date = anchor.date() - timedelta(days=1)
            job_type = "incremental"
        else:
            since_date = now_utc.date() - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
            job_type = "full"
    else:
        job_type = "manual"
    with Session(engine) as session:
        job = SyncJob(
            user_id=uid, source="stryd", job_type=job_type,
            status="running", started_at=now_utc, since_date=since_date,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_db_id = job.id

    created = updated = fetched = 0
    try:
        token = refresh_stryd_session_if_needed(str(uid))
        with Session(engine) as session:
            cred = session.query(StrydCredentials).filter(StrydCredentials.user_id == uid).one()
            athlete_id = cred.athlete_id
        if not athlete_id:
            raise RuntimeError("Stryd athlete_id missing; reconnect Stryd")
        raw_acts = fetch_stryd_activities(token, athlete_id, since_date=since_date)
        fetched = len(raw_acts)
        mapped = [map_stryd_activity(a, str(uid)) for a in raw_acts]
        mapped = [m for m in mapped if m["stryd_activity_id"] and m["stryd_activity_id"] != "None"]
        # The calendar API ignores srtDate/endDate and returns the full lifetime
        # list. Drop rows older than since_date here so an incremental sync only
        # upserts (and considers for enrichment) the requested window instead of
        # rewriting all history rows on every "Sync new". Full jobs (including a
        # user's first-ever sync, which resolves to job_type "full") keep the
        # whole list — storing all available history there is intentional.
        if since_date is not None and job_type in ("incremental", "manual"):
            cutoff = datetime(since_date.year, since_date.month, since_date.day, tzinfo=timezone.utc)
            mapped = [m for m in mapped if m["start_time"] >= cutoff]
        # Dedup by stryd_activity_id (keep last). A duplicate id in a single batch
        # makes ON CONFLICT DO UPDATE raise "cannot affect row a second time".
        _deduped = {m["stryd_activity_id"]: m for m in mapped}
        mapped = list(_deduped.values())
        # The Stryd calendar API ignores srtDate/endDate and always returns the full
        # lifetime activity list, newest-first. Sort ascending so that ids[-N:] in
        # the caller's _DAILY_RECONCILE_LIMIT slice reliably picks the most recent N.
        mapped.sort(key=lambda m: m["start_time"])
        ids = [m["stryd_activity_id"] for m in mapped]

        if mapped:
            with Session(engine) as session:
                existing = set(session.execute(
                    select(StrydActivity.stryd_activity_id)
                    .where(StrydActivity.stryd_activity_id.in_(ids))
                ).scalars().all())
            created = sum(1 for m in mapped if m["stryd_activity_id"] not in existing)
            updated = len(mapped) - created

            # 1) Bulk-upsert the base summaries. splits + form_metrics are owned by
            #    the enrichment step below (excluded here so re-syncs never clobber
            #    the per-km splits / NP we computed from the streams).
            now = datetime.now(tz=timezone.utc)
            with Session(engine) as session:
                ins = _pg_insert(StrydActivity).values(mapped)
                stmt = ins.on_conflict_do_update(
                    index_elements=["stryd_activity_id"],
                    set_={
                        "name": ins.excluded.name,
                        "distance_km": ins.excluded.distance_km,
                        "duration_seconds": ins.excluded.duration_seconds,
                        "avg_power_w": ins.excluded.avg_power_w,
                        "avg_hr": ins.excluded.avg_hr,
                        "tss": ins.excluded.tss,
                        "power_zones": ins.excluded.power_zones,
                        "raw_payload": ins.excluded.raw_payload,
                        "grade_percent": ins.excluded.grade_percent,
                        "synced_at": now,
                    },
                )
                session.execute(stmt)
                session.commit()

            # 2) Enrich each activity (per-km splits + NP + max power) with a
            #    direct per-row UPDATE. Skip rows already enriched (splits is a
            #    list of dicts) so re-syncs stay cheap.
            # Skip only when BOTH per-km splits AND per-point streams are present.
            # Activities enriched before streams capture have splits but no
            # streams; requiring streams here makes every sync self-heal them
            # (so manual laps / interval stats become available without a
            # separate backfill). New activities still enrich on first sync.
            with Session(engine) as session:
                already = _already_enriched_ids(session, ids)
            base_form = {m["stryd_activity_id"]: (m.get("form_metrics") or {}) for m in mapped}
            to_enrich = [aid for aid in ids if aid not in already]
            if to_enrich:
                # Store raw streams (timestamp_list + channel *_list) so manual
                # laps / interval stats can be computed; also per-km splits + NP.
                _enrich_many(token, to_enrich, base_form)

        # Self-heal: backfill streams for activities still missing them
        # (e.g. enriched before streams capture). Only runs on full syncs to
        # keep incremental "Sync new" fast. Bounded per run to respect rate limits.
        if heal:
            processed = set(ids)
            with Session(engine) as session:
                heal_ids = _heal_candidate_ids(session, uid, processed)
            remaining = len(heal_ids)
            _enrich_many(token, heal_ids[:_STREAM_HEAL_CAP])
            if remaining > _STREAM_HEAL_CAP:
                logger.info(
                    "stryd stream heal capped",
                    extra={"healed": _STREAM_HEAL_CAP, "remaining": remaining - _STREAM_HEAL_CAP},
                )

        with Session(engine) as session:
            jr = session.get(SyncJob, job_db_id)
            jr.status = "completed"
            jr.completed_at = datetime.now(tz=timezone.utc)
            jr.activities_fetched = fetched
            jr.activities_created = created
            jr.activities_updated = updated
            session.commit()

        return {
            "fetched": fetched,
            "created": created,
            "updated": updated,
            "upserted": created + updated,
            "stryd_activity_ids": ids,
        }

    except Exception as exc:
        with Session(engine) as session:
            jr = session.get(SyncJob, job_db_id)
            if jr is not None:
                jr.status = "failed"
                jr.error_message = str(exc)
                jr.completed_at = datetime.now(tz=timezone.utc)
                session.commit()
        raise
