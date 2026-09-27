from datetime import timedelta

import redis

import worker
from app.models import Booking, BookingStatus, Review, SummaryStatus, TimeSlot, UserRole
from app.time_utils import utcnow
from tests.conftest import TestingSessionLocal, make_user


class _RedisErrorConn:
    """Fake Redis connection whose brpop always raises, like a dropped connection."""

    def brpop(self, key):
        raise redis.exceptions.ConnectionError("connection dropped")


class _BadJobConn:
    """Fake Redis connection that hands back a review ID that isn't a real UUID."""

    def __init__(self, review_id):
        self._review_id = review_id

    def brpop(self, key):
        return (key, self._review_id)


def test_process_one_survives_a_redis_connection_error(monkeypatch, capsys):
    """
    Regression test: run()'s loop used to have no try/except at all, so a
    dropped Redis connection killed the entire worker process. It must
    now log and return instead of raising.
    """
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: None)  # don't actually wait in tests
    worker._process_one(_RedisErrorConn())  # should NOT raise
    assert "Redis error" in capsys.readouterr().out


def test_process_one_survives_a_malformed_review_id(capsys):
    """
    Regression test: a job with a non-UUID review ID used to crash
    process_job with an unhandled ValueError, killing the worker.
    """
    worker._process_one(_BadJobConn("not-a-real-uuid"))  # should NOT raise
    assert "Failed to process job" in capsys.readouterr().out


def test_process_job_writes_a_stub_summary(db_session, monkeypatch):
    """Confirms the actual job logic still works correctly end to end."""
    monkeypatch.setattr(worker, "SessionLocal", TestingSessionLocal)

    provider = make_user(db_session, UserRole.provider, "workerprov@example.com")
    customer = make_user(db_session, UserRole.customer, "workercust@example.com")

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

    review = Review(
        booking_id=booking.id,
        rating=5,
        text="Excellent service, showed up on time and did great work",
    )
    db_session.add(review)
    db_session.commit()
    db_session.refresh(review)

    worker.process_job(str(review.id))

    db_session.refresh(review)
    assert review.summary_status == SummaryStatus.done
    assert review.summary is not None
    assert review.summary.startswith("Summary:")
