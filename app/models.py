"""
The database schema: 4 tables — User, TimeSlot, Booking, Review.

Simple terms:
- A User is an admin, a provider (offers services), or a customer (books them).
- A TimeSlot belongs to one provider — a window of time they're available.
- A Booking is a customer claiming a TimeSlot. It stores provider_id too,
  even though you could get that by joining through TimeSlot — this is the
  normalization tradeoff to mention in the written note: a little
  redundancy, in exchange for every RBAC check on a booking being a single
  `WHERE provider_id = X` instead of a join every time.
- A Review is written by the customer after a Booking is completed.

GUID type: Postgres has a native UUID column type, but plain SQLite (used
here only to run fast unit tests without a real Postgres server) doesn't.
This small TypeDecorator uses the real UUID type on Postgres and falls
back to a CHAR(36) string on anything else, so the exact same models work
against both — production stays on Postgres, tests stay fast and isolated.
"""

import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
from sqlalchemy.types import CHAR, TypeDecorator

from app.database import Base
from app.time_utils import utcnow


class GUID(TypeDecorator):
    """Platform-independent GUID: native UUID on Postgres, CHAR(36) elsewhere."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID())
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            return str(uuid.UUID(str(value)))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            return uuid.UUID(str(value))
        return value


class UserRole(str, enum.Enum):
    admin = "admin"
    provider = "provider"
    customer = "customer"


class BookingStatus(str, enum.Enum):
    confirmed = "confirmed"
    cancelled = "cancelled"
    completed = "completed"


class SummaryStatus(str, enum.Enum):
    pending = "pending"  # queued, not summarized yet
    done = "done"        # summary job finished


class User(Base):
    __tablename__ = "users"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class TimeSlot(Base):
    __tablename__ = "time_slots"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    provider_id = Column(GUID(), ForeignKey("users.id"), nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    is_booked = Column(Boolean, default=False, nullable=False)

    provider = relationship("User")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    slot_id = Column(GUID(), ForeignKey("time_slots.id"), nullable=False)
    customer_id = Column(GUID(), ForeignKey("users.id"), nullable=False, index=True)
    # Denormalized on purpose — see module docstring above.
    provider_id = Column(GUID(), ForeignKey("users.id"), nullable=False, index=True)
    status = Column(Enum(BookingStatus), default=BookingStatus.confirmed, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    slot = relationship("TimeSlot")
    customer = relationship("User", foreign_keys=[customer_id])
    provider = relationship("User", foreign_keys=[provider_id])


class Review(Base):
    __tablename__ = "reviews"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    booking_id = Column(GUID(), ForeignKey("bookings.id"), nullable=False, unique=True)
    rating = Column(Integer, nullable=False)  # 1-5, validated in the endpoint
    text = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    summary_status = Column(Enum(SummaryStatus), default=SummaryStatus.pending, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    booking = relationship("Booking")
