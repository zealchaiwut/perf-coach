"""Coach-week import from a photo (revamp P3-7)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import CoachWeekImportPhoto
from backend.services.coach_week_import import parse_coach_week_text
from backend.services.llm import complete_structured_vision, llm_vision_enabled
from backend.services.weekly_rollup import normalize_week_start

COACH_PHOTO_MAX_BYTES = 10 * 1024 * 1024
COACH_PHOTO_MIMES = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/heic",
        "image/heif",
    }
)

_VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {"type": "string"},
            "description": "One coach session per line: day, type, duration or distance, name",
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


def photo_import_capabilities() -> dict[str, Any]:
    enabled = llm_vision_enabled()
    return {
        "vision_enabled": enabled,
        "max_bytes": COACH_PHOTO_MAX_BYTES,
        "allowed_mimes": sorted(COACH_PHOTO_MIMES),
        "message": (
            "Photo import is available — upload a coach week image to OCR."
            if enabled
            else "Photo import needs a vision-capable LLM (not configured in this environment). Use typed paste below."
        ),
    }


def extract_coach_week_lines_from_image(image_bytes: bytes, mime: str) -> Optional[str]:
    """Return newline-separated coach lines from an image, or None when vision is off / fails."""
    if not llm_vision_enabled():
        return None
    parsed = complete_structured_vision(
        "You read a photo of a coach's weekly training plan. "
        "Return ONLY session lines as plain text: weekday, run type (easy/long/tempo/interval/rest/race), "
        "duration or distance, and optional name. No commentary.",
        image_bytes,
        mime,
        "coach_week_lines",
        _VISION_SCHEMA,
    )
    if not parsed or not isinstance(parsed.get("lines"), list):
        return None
    lines = [str(x).strip() for x in parsed["lines"] if str(x).strip()]
    if not lines:
        return None
    return "\n".join(lines)


def store_coach_week_photo(
    session: Session,
    user_id: uuid.UUID,
    *,
    week_start: date,
    mime: str,
    data: bytes,
) -> uuid.UUID:
    ws = normalize_week_start(week_start)
    existing = (
        session.query(CoachWeekImportPhoto)
        .filter(CoachWeekImportPhoto.user_id == user_id, CoachWeekImportPhoto.week_start == ws)
        .one_or_none()
    )
    if existing:
        existing.mime = mime
        existing.data = data
        session.flush()
        return existing.id
    row = CoachWeekImportPhoto(user_id=user_id, week_start=ws, mime=mime, data=data)
    session.add(row)
    session.flush()
    return row.id


def parse_coach_week_photo(
    session: Session,
    user_id: uuid.UUID,
    *,
    week_start: date,
    image_bytes: bytes,
    mime: str,
    today: Optional[date] = None,
) -> dict[str, Any]:
    caps = photo_import_capabilities()
    if mime not in COACH_PHOTO_MIMES:
        raise ValueError(f"unsupported mime: {mime}")
    if len(image_bytes) > COACH_PHOTO_MAX_BYTES:
        raise ValueError("file too large")
    if not caps["vision_enabled"]:
        return {**caps, "week_start": normalize_week_start(week_start).isoformat(), "rows": [], "commit_allowed": False}

    photo_id = store_coach_week_photo(
        session, user_id, week_start=week_start, mime=mime, data=image_bytes
    )
    text = extract_coach_week_lines_from_image(image_bytes, mime)
    if not text:
        return {
            **caps,
            "week_start": normalize_week_start(week_start).isoformat(),
            "photo_id": str(photo_id),
            "rows": [],
            "commit_allowed": False,
            "message": "Could not read sessions from the photo — try typed paste.",
        }
    payload = parse_coach_week_text(session, user_id, week_start=week_start, text=text, today=today)
    for row in payload.get("rows") or []:
        if row.get("parse_status") == "ok":
            row["inferred"] = True
            row["ocr"] = True
    payload["vision_enabled"] = True
    payload["photo_id"] = str(photo_id)
    payload["source"] = "photo"
    return payload