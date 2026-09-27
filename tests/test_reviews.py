from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Booking, BookingStatus, Review, TimeSlot, UserRole
from app.time_utils import utcnow
from tests.conftest import auth_headers, make_user


def _make_completed_booking(db_session):
    provider = make_user(db_session, UserRole.provider, "reviewprov@example.com")
    customer = make_user(db_session, UserRole.customer, "reviewcust@example.com")

    slot = TimeSlot(
        provider_id=provider.id,
        start_time=utcnow(),
        end_time=utcnow() + timedelta(hours=1),
        is_booked=True,
    )
    db_session.add(slot)
    db_session.commit()
    db_session.refresh(slot)

    booking = Booking(
        slot_id=slot.id,
        customer_id=customer.id,
        provider_id=provider.id,
        status=BookingStatus.completed,
    )
    db_session.add(booking)
    db_session.commit()
    db_session.refresh(booking)
    return booking, customer


def test_second_review_via_api_returns_409(client, db_session):
    """The common (non-racy) case: existence check catches the duplicate."""
    booking, customer = _make_completed_booking(db_session)

    resp1 = client.post(
        f"/bookings/{booking.id}/review",
        json={"rating": 5, "text": "First review"},
        headers=auth_headers(customer),
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        f"/bookings/{booking.id}/review",
        json={"rating": 3, "text": "Second review, should be rejected"},
        headers=auth_headers(customer),
    )
    assert resp2.status_code == 409


def test_review_booking_id_unique_constraint_is_enforced_at_db_level(db_session):
    """
    Regression test for the actual race window: two requests can both
    pass create_review's existence-check query before either commits.
    This proves the database itself still refuses the second row — the
    safety net create_review's try/except IntegrityError now relies on
    (see app/main.py's create_review). True concurrent-request timing
    isn't reproducible in this synchronous test client; this confirms the
    constraint that backs the fix actually fires.
    """
    booking, _ = _make_completed_booking(db_session)

    db_session.add(Review(booking_id=booking.id, rating=5, text="first"))
    db_session.commit()

    db_session.add(Review(booking_id=booking.id, rating=3, text="second, should violate"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
