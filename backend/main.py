import os
import uuid as _uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session

from backend.db import check_db, engine, environment
from backend.models import User, WeightEntry

__version__ = "0.1.0"

app = FastAPI()

# Serve static files (index.html, weight.html, habits.html, css/, js/)
_static_root = Path(__file__).parent.parent
app.mount("/css", StaticFiles(directory=str(_static_root / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(_static_root / "js")), name="js")


@app.get("/api/health")
def health():
    return JSONResponse({"status": "ok", "database": check_db(), "environment": environment})


@app.get("/api/environment")
def get_environment():
    return JSONResponse({"environment": environment, "version": __version__})


@app.get("/api/users")
def get_users():
    with Session(engine) as session:
        users = session.query(User).order_by(User.name).all()
        return JSONResponse([{"id": str(u.id), "name": u.name} for u in users])


# ── Weight endpoints (AC-1 through AC-4) ─────────────────────────────────────

class WeightEntryIn(BaseModel):
    weight_kg: float
    recorded_date: str  # YYYY-MM-DD


@app.get("/api/weight")
def get_weight(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        rows = (
            session.query(WeightEntry)
            .filter(WeightEntry.user_id == uid)
            .order_by(WeightEntry.recorded_date)
            .all()
        )
        return JSONResponse([
            {
                "id": str(r.id),
                "weight_kg": float(r.weight_kg),
                "recorded_date": str(r.recorded_date),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ])


@app.post("/api/weight", status_code=201)
def post_weight(user_id: str, body: WeightEntryIn):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        entry = WeightEntry(
            user_id=uid,
            weight_kg=body.weight_kg,
            recorded_date=body.recorded_date,
        )
        session.add(entry)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(
                status_code=409,
                content={"error": "Entry exists for this date"},
            )
        session.refresh(entry)
        return JSONResponse(
            status_code=201,
            content={
                "id": str(entry.id),
                "weight_kg": float(entry.weight_kg),
                "recorded_date": str(entry.recorded_date),
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            },
        )


@app.delete("/api/weight/{entry_id}", status_code=204)
def delete_weight(entry_id: str):
    try:
        eid = _uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id")
    with Session(engine) as session:
        entry = session.get(WeightEntry, eid)
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        session.delete(entry)
        session.commit()
    return Response(status_code=204)


@app.get("/")
def index():
    return FileResponse(str(_static_root / "index.html"))


@app.get("/weight.html")
def weight():
    return FileResponse(str(_static_root / "weight.html"))


@app.get("/habits.html")
def habits():
    return FileResponse(str(_static_root / "habits.html"))
