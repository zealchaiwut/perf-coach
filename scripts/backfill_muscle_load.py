#!/usr/bin/env python3
"""backfill_muscle_load.py — Recompute strength muscle-load ledger for all users (issue #1367).

Usage:
    python scripts/backfill_muscle_load.py [--user-id <uuid>]

Without --user-id, processes every user in the database.
"""
from __future__ import annotations

import argparse
import sys
import uuid

# Ensure repo root is on path when run from scripts/
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import User
from backend.services.muscle_load import backfill_strength_load


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill muscle_load_daily for strength workouts")
    parser.add_argument("--user-id", help="Process only this user UUID")
    args = parser.parse_args()

    with Session(engine) as db:
        if args.user_id:
            try:
                uid = uuid.UUID(args.user_id)
            except ValueError:
                print(f"Invalid UUID: {args.user_id}", file=sys.stderr)
                sys.exit(1)
            users = [db.get(User, uid)]
            if users[0] is None:
                print(f"User not found: {args.user_id}", file=sys.stderr)
                sys.exit(1)
        else:
            users = db.query(User).filter(User.is_active.is_(True)).all()

    print(f"Processing {len(users)} user(s)...")
    for user in users:
        n = backfill_strength_load(user.id)
        print(f"  {user.name} ({user.id}): {n} date(s) processed")

    print("Done.")


if __name__ == "__main__":
    main()
