"""Create (or ensure) an "Admin" user in the current ENVIRONMENT's database.

Idempotent:
  - if no "Admin" user exists, create one with is_admin=True;
  - if it exists but isn't flagged, promote it;
  - otherwise do nothing.

Requires the is_admin column (migration l5f6a7b8c9d0) to be applied first.

Usage:
    ENVIRONMENT=uat python scripts/create_admin_user.py
    ENVIRONMENT=prd python scripts/create_admin_user.py   # via your release process
"""
import sys
from pathlib import Path

# Allow running as `python scripts/create_admin_user.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db import engine, environment
from backend.models import User

ADMIN_NAME = "Admin"


def main() -> None:
    with Session(engine) as session:
        user = session.execute(
            select(User).where(User.name == ADMIN_NAME)
        ).scalar_one_or_none()

        if user is None:
            user = User(name=ADMIN_NAME, is_admin=True)
            session.add(user)
            session.commit()
            session.refresh(user)
            print(f"[{environment}] created Admin user id={user.id} is_admin={user.is_admin}")
        elif not user.is_admin:
            user.is_admin = True
            session.commit()
            print(f"[{environment}] promoted existing 'Admin' user to is_admin=True (id={user.id})")
        else:
            print(f"[{environment}] Admin user already present id={user.id} is_admin=True (no-op)")


if __name__ == "__main__":
    main()
