"""
Sets up the connection to Postgres.

Simple terms: this file just tells SQLAlchemy "here's the database,
here's how to open a conversation (session) with it." Every other
file borrows `get_db()` when it needs to talk to the database.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# In docker-compose, this points at the "postgres" service, not localhost.
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/bookings"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# All our models (User, Booking, etc.) inherit from this.
Base = declarative_base()


def get_db():
    """
    FastAPI dependency: opens one DB session per request,
    hands it to the endpoint, then always closes it afterward
    (even if the endpoint raised an error).
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
