"""plan.py — compatibility alias for backend/routers/projection.py.

This file was renamed to projection.py.  Re-export everything so that any
import of ``backend.routers.plan`` (e.g. tests compiled against the old name)
continues to resolve correctly.
"""
from backend.routers.projection import *  # noqa: F401, F403
from backend.routers.projection import router  # noqa: F401
