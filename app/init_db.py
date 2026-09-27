"""
Creates tables directly from the models. This is a stand-in for a real
migrations tool (Alembic) — flagged explicitly as a gap in WRITTEN_NOTE.md.
Deliberately kept OUT of app/main.py's import path so importing the app
(e.g. in tests) never tries to open a real database connection — this
script is the only thing that touches the DB at startup, and only when
docker-compose actually runs it.
"""

from app import models  # noqa: F401  (import registers the models with Base.metadata)
from app.database import Base, engine


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    print("Tables created (or already existed).")


if __name__ == "__main__":
    init_db()
