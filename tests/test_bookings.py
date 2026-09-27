from datetime import datetime, timedelta, timezone

from app.models import UserRole
from app.time_utils import utcnow
from tests.conftest import auth_headers, make_user


def test_register_and_login(client):
    resp = client.post(
        "/auth/register",
        json={"email": "cust@example.com", "password": "password123", "role": "customer"},
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "cust@example.com"

    resp = client.post(
        "/auth/login",
        data={"username": "cust@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_duplicate_email_rejected(client):
    payload = {"email": "dup@example.com", "password": "password123", "role": "customer"}
    assert client.post("/auth/register", json=payload).status_code == 201
    assert client.post("/auth/register", json=payload).status_code == 409


def test_full_booking_and_review_flow(client, db_session):
    provider = make_user(db_session, UserRole.provider, "provider@example.com")
    customer = make_user(db_session, UserRole.customer, "customer@example.com")

    start = utcnow() + timedelta(days=1)
    end = start + timedelta(hours=1)
    resp = client.post(
        "/slots",
        json={"start_time": start.isoformat(), "end_time": end.isoformat()},
        headers=auth_headers(provider),
    )
    assert resp.status_code == 201
    slot_id = resp.json()["id"]

    # Customer sees the open slot.
    resp = client.get("/slots", headers=auth_headers(customer))
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Customer books it.
    resp = client.post("/bookings", json={"slot_id": slot_id}, headers=auth_headers(customer))
    assert resp.status_code == 201
    booking = resp.json()
    assert booking["status"] == "confirmed"

    # Slot is no longer listed as available.
    resp = client.get("/slots", headers=auth_headers(customer))
    assert resp.json() == []

    # Can't review before the booking is completed.
    resp = client.post(
        f"/bookings/{booking['id']}/review",
        json={"rating": 5, "text": "Great!"},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 409

    # Provider marks it complete.
    resp = client.patch(
        f"/bookings/{booking['id']}/complete", headers=auth_headers(provider)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    # Now the review goes through.
    resp = client.post(
        f"/bookings/{booking['id']}/review",
        json={"rating": 5, "text": "Excellent service, would book again"},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 201
    review = resp.json()
    assert review["summary_status"] == "pending"

    # Trigger summarization (Redis is mocked out in the `client` fixture).
    resp = client.post(f"/reviews/{review['id']}/summarize", headers=auth_headers(customer))
    assert resp.status_code == 202


def test_cannot_double_book_a_slot(client, db_session):
    provider = make_user(db_session, UserRole.provider, "p2@example.com")
    customer_a = make_user(db_session, UserRole.customer, "ca@example.com")
    customer_b = make_user(db_session, UserRole.customer, "cb@example.com")

    start = utcnow() + timedelta(days=2)
    end = start + timedelta(hours=1)
    resp = client.post(
        "/slots",
        json={"start_time": start.isoformat(), "end_time": end.isoformat()},
        headers=auth_headers(provider),
    )
    slot_id = resp.json()["id"]

    assert client.post(
        "/bookings", json={"slot_id": slot_id}, headers=auth_headers(customer_a)
    ).status_code == 201

    resp = client.post(
        "/bookings", json={"slot_id": slot_id}, headers=auth_headers(customer_b)
    )
    assert resp.status_code == 409


def test_delete_booking_performs_soft_cancel(client, db_session):
    """Regression test: DELETE /bookings/{id} did not exist at all."""
    provider = make_user(db_session, UserRole.provider, "delprov@example.com")
    customer = make_user(db_session, UserRole.customer, "delcust@example.com")

    start = utcnow() + timedelta(days=3)
    end = start + timedelta(hours=1)
    slot_id = client.post(
        "/slots",
        json={"start_time": start.isoformat(), "end_time": end.isoformat()},
        headers=auth_headers(provider),
    ).json()["id"]
    booking = client.post(
        "/bookings", json={"slot_id": slot_id}, headers=auth_headers(customer)
    ).json()

    resp = client.delete(f"/bookings/{booking['id']}", headers=auth_headers(customer))
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    # The slot must be bookable again — it's a soft cancel, not a hard delete.
    resp = client.get("/slots", headers=auth_headers(customer))
    assert len(resp.json()) == 1


def test_slot_creation_handles_mixed_naive_and_aware_datetimes(client, db_session):
    """
    Regression test: comparing a naive and a timezone-aware datetime
    raises TypeError in plain Python, which used to escape create_slot
    as an unhandled 500 instead of either succeeding or 422-ing cleanly.
    """
    provider = make_user(db_session, UserRole.provider, "tzmix@example.com")

    naive_start = (datetime.utcnow() + timedelta(days=5)).isoformat()  # no tzinfo
    aware_end = (datetime.now(timezone.utc) + timedelta(days=5, hours=1)).isoformat()  # tzinfo

    resp = client.post(
        "/slots",
        json={"start_time": naive_start, "end_time": aware_end},
        headers=auth_headers(provider),
    )
    assert resp.status_code == 201  # must not be 500
