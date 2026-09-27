"""
Pydantic schemas: what JSON goes IN to an endpoint and what JSON comes OUT.
Deliberately separate from models.py — models.py is "what's in the
database", schemas.py is "what's in the API". Keeping them separate means
a hashed_password can never accidentally leak out through a response.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import BookingStatus, SummaryStatus, UserRole

# ---------- Auth ----------

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: UserRole


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: UserRole

    model_config = ConfigDict(from_attributes=True)  # build directly from a User instance


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Time Slots ----------

class TimeSlotCreate(BaseModel):
    start_time: datetime
    end_time: datetime


class TimeSlotOut(BaseModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    is_booked: bool

    model_config = ConfigDict(from_attributes=True)


# ---------- Bookings ----------

class BookingCreate(BaseModel):
    slot_id: uuid.UUID


class BookingOut(BaseModel):
    id: uuid.UUID
    slot_id: uuid.UUID
    customer_id: uuid.UUID
    provider_id: uuid.UUID
    status: BookingStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- Reviews ----------

class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: Optional[str] = None


class ReviewOut(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    rating: int
    text: Optional[str]
    summary: Optional[str]
    summary_status: SummaryStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
