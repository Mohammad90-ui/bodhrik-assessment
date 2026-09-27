"""
Test setup. Uses SQLite in memory (via the GUID type's fallback branch)
so the whole suite runs in milliseconds with no real Postgres or Redis —
only app.main's business logic and RBAC are under test here.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models import User, UserRole
from app.redis_client import get_summary_queue
from app.security import hash_password

TEST_DB_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # keeps the single in-memory DB alive across connections
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    def override_summary_queue():
        # No real Redis in tests — just swallow the enqueue call.
        return lambda review_id: None

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_summary_queue] = override_summary_queue
    yield TestClient(app)
    app.dependency_overrides.clear()


def make_user(db_session, role: UserRole, email: str) -> User:
    user = User(email=email, hashed_password=hash_password("password123"), role=role)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def auth_headers(user: User) -> dict:
    token = create_access_token(user.id, user.role)
    return {"Authorization": f"Bearer {token}"}
