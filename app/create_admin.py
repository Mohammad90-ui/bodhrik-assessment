"""
Creates an admin user directly in the database, bypassing the public API
entirely — /auth/register no longer accepts role=admin (see main.py's
register()), since letting any caller self-select "admin" was a real
privilege-escalation hole. Whoever has server/DB access runs this once
to bootstrap the first admin account.

Usage:
    python -m app.create_admin <email> <password>
"""

import sys

from app.database import SessionLocal
from app.models import User, UserRole
from app.security import hash_password


def create_admin(email: str, password: str) -> None:
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            print(f"A user with email {email} already exists.")
            return
        admin = User(email=email, hashed_password=hash_password(password), role=UserRole.admin)
        db.add(admin)
        db.commit()
        print(f"Admin user created: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m app.create_admin <email> <password>")
        sys.exit(1)
    create_admin(sys.argv[1], sys.argv[2])
