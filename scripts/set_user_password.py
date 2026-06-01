"""Set the password for an existing user by username.

Hashes the password via ``backend.auth`` and writes it to the database
selected by the ``ENVIRONMENT`` env var (same logic as all other scripts).

Usage::

    python scripts/set_user_password.py <username>

Examples::

    ENVIRONMENT=uat python scripts/set_user_password.py Admin
    ENVIRONMENT=prd python scripts/set_user_password.py Admin

Exit codes:

    0  — success
    1  — any failure (user not found, empty password, password too short, DB error)
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth import MIN_PASSWORD_LENGTH, hash_password
from backend.db import engine, environment
from backend.models import User


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <username>", file=sys.stderr)
        sys.exit(1)

    username = sys.argv[1]

    try:
        plain = getpass.getpass(f"New password for '{username}': ")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=sys.stderr)
        sys.exit(1)

    if not plain:
        print("Error: password must not be empty.", file=sys.stderr)
        sys.exit(1)

    if len(plain) < MIN_PASSWORD_LENGTH:
        print(
            f"Error: password must be at least {MIN_PASSWORD_LENGTH} characters.",
            file=sys.stderr,
        )
        sys.exit(1)

    with Session(engine) as session:
        user = session.execute(
            select(User).where(User.name == username)
        ).scalar_one_or_none()

        if user is None:
            print(f"Error: user '{username}' not found in [{environment}].", file=sys.stderr)
            sys.exit(1)

        user.password_hash = hash_password(plain)
        session.commit()

    print(f"Password updated for user '{username}'.")


if __name__ == "__main__":
    main()
