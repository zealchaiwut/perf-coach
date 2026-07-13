"""Gap analyzer service package (issue #1370).

Public API: run_gap_analysis(db, user_id, today) → payload dict
"""
from backend.services.gap_analysis.engine import run_gap_analysis

__all__ = ["run_gap_analysis"]
