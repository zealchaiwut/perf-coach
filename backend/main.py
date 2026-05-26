import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.db import check_db, environment

app = FastAPI()

# Serve static files (index.html, weight.html, habits.html, css/, js/)
_static_root = Path(__file__).parent.parent
app.mount("/css", StaticFiles(directory=str(_static_root / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(_static_root / "js")), name="js")


@app.get("/api/health")
def health():
    return JSONResponse({"status": "ok", "database": check_db(), "environment": environment})


# Serve HTML pages at their natural paths
from fastapi.responses import FileResponse


@app.get("/")
def index():
    return FileResponse(str(_static_root / "index.html"))


@app.get("/weight.html")
def weight():
    return FileResponse(str(_static_root / "weight.html"))


@app.get("/habits.html")
def habits():
    return FileResponse(str(_static_root / "habits.html"))
