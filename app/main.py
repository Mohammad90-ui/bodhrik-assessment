"""
The full API. Endpoints are grouped by resource; each one states which
role(s) can call it and what row-level check (if any) applies on top.
"""

import uuid
from datetime import timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    get_current_user,
    require_role,
    verify_booking_access,
)
from app.database import get_db
from app.models import (
    Booking,
    BookingStatus,
    Review,
    SummaryStatus,
    TimeSlot,
    User,
    UserRole,
)
from app.redis_client import get_summary_queue
from app.schemas import (
    BookingCreate,
    BookingOut,
    ReviewCreate,
    ReviewOut,
    TimeSlotCreate,
    TimeSlotOut,
    Token,
    UserCreate,
    UserOut,
)
from app.security import hash_password, verify_password

app = FastAPI(title="Bodhrik Booking Service")


@app.get("/health")
def health():
    """Used by docker-compose / a load balancer to confirm the app is up."""
    return {"status": "ok"}


# ---------------------------------------------------------------- Auth ----

@app.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if payload.role == UserRole.admin:
        # Anyone could previously self-register as admin by just picking
        # that role — a real privilege-escalation hole. Admin accounts
        # are now created out-of-band; see app/create_admin.py.
        raise HTTPException(
            status_code=403,
            detail="Cannot self-register as admin. Use `python -m app.create_admin` instead.",
        )
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # OAuth2PasswordRequestForm names the field "username" — we treat it as email.
    user = db.query(User).filter(User.email == form_data.username).first()
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    token = create_access_token(user.id, user.role)
    return Token(access_token=token)


# --------------------------------------------------------------- Slots ----

@app.post("/slots", response_model=TimeSlotOut, status_code=status.HTTP_201_CREATED)
def create_slot(
    payload: TimeSlotCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.provider)),
):
    start, end = payload.start_time, payload.end_time
    # A naive and a timezone-aware datetime can't be compared directly —
    # Python raises TypeError, which used to escape as an unhandled 500.
    # Normalize both to UTC-aware first (treating a naive input as UTC)
    # so mixed inputs compare and store safely instead of crashing.
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    if end <= start:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    slot = TimeSlot(
        provider_id=current_user.id,
        start_time=start,
        end_time=end,
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


@app.get("/slots", response_model=list[TimeSlotOut])
def list_available_slots(
    provider_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # any authenticated role may browse
):
    query = db.query(TimeSlot).filter(TimeSlot.is_booked.is_(False))
    if provider_id:
        query = query.filter(TimeSlot.provider_id == provider_id)
    return query.all()


# ------------------------------------------------------------ Bookings ----

def _get_booking_or_404(db: Session, booking_id: uuid.UUID) -> Booking:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@app.post("/bookings", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking(
    payload: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.customer)),
):
    slot = db.query(TimeSlot).filter(TimeSlot.id == payload.slot_id).first()
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")

    # Atomic conditional UPDATE instead of "read is_booked in Python, then
    # write" — that read-then-write had a race window where two concurrent
    # requests could both see is_booked == False and both create a booking.
    # This single UPDATE ... WHERE is_booked = false is one statement the
    # database executes atomically, so only one concurrent request can ever
    # flip it from False -> True; the loser gets rowcount == 0 and a 409.
    updated_rows = (
        db.query(TimeSlot)
        .filter(TimeSlot.id == slot.id, TimeSlot.is_booked.is_(False))
        .update({"is_booked": True}, synchronize_session=False)
    )
    if updated_rows == 0:
        db.rollback()
        raise HTTPException(status_code=409, detail="Slot already booked")

    booking = Booking(
        slot_id=slot.id,
        customer_id=current_user.id,
        provider_id=slot.provider_id,  # copied across at creation time — see models.py
        status=BookingStatus.confirmed,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


@app.get("/bookings", response_model=list[BookingOut])
def list_my_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Filters the query itself by role, instead of checking access row-by-row."""
    query = db.query(Booking)
    if current_user.role == UserRole.provider:
        query = query.filter(Booking.provider_id == current_user.id)
    elif current_user.role == UserRole.customer:
        query = query.filter(Booking.customer_id == current_user.id)
    # admin: no filter, sees everything
    return query.all()


@app.get("/bookings/{booking_id}", response_model=BookingOut)
def get_booking(
    booking_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = _get_booking_or_404(db, booking_id)
    verify_booking_access(booking, current_user)  # the row-level check
    return booking


@app.patch("/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(
    booking_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = _get_booking_or_404(db, booking_id)
    verify_booking_access(booking, current_user)
    if current_user.role == UserRole.provider:
        raise HTTPException(status_code=403, detail="Only the customer or an admin can cancel")
    if booking.status != BookingStatus.confirmed:
        raise HTTPException(
            status_code=409, detail=f"Cannot cancel a booking in status {booking.status.value}"
        )
    booking.status = BookingStatus.cancelled
    booking.slot.is_booked = False
    db.commit()
    db.refresh(booking)
    return booking


@app.delete("/bookings/{booking_id}", response_model=BookingOut)
def delete_booking(
    booking_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Bookings are never hard-deleted — history matters (disputes, provider
    stats, audit trail). DELETE performs the exact same soft-cancel as
    PATCH .../cancel; this route exists so the CRUD verb set on this
    resource is complete rather than missing DELETE entirely.
    """
    return cancel_booking(booking_id, db, current_user)


@app.patch("/bookings/{booking_id}/complete", response_model=BookingOut)
def complete_booking(
    booking_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = _get_booking_or_404(db, booking_id)
    verify_booking_access(booking, current_user)
    if current_user.role == UserRole.customer:
        raise HTTPException(status_code=403, detail="Only the provider or an admin can complete")
    if booking.status != BookingStatus.confirmed:
        raise HTTPException(
            status_code=409, detail=f"Cannot complete a booking in status {booking.status.value}"
        )
    booking.status = BookingStatus.completed
    db.commit()
    db.refresh(booking)
    return booking


# ------------------------------------------------------------- Reviews ----

@app.post(
    "/bookings/{booking_id}/review",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_review(
    booking_id: uuid.UUID,
    payload: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.customer)),
):
    booking = _get_booking_or_404(db, booking_id)
    verify_booking_access(booking, current_user)
    if booking.customer_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Only the customer on this booking can review it"
        )
    if booking.status != BookingStatus.completed:
        raise HTTPException(status_code=409, detail="Can only review a completed booking")
    if db.query(Review).filter(Review.booking_id == booking.id).first():
        raise HTTPException(status_code=409, detail="This booking already has a review")

    review = Review(booking_id=booking.id, rating=payload.rating, text=payload.text)
    db.add(review)
    try:
        db.commit()
    except IntegrityError:
        # The check above is the fast path; this is the safety net for the
        # race window between it and the insert — two requests can both
        # pass the check, but the DB's unique constraint on
        # Review.booking_id (models.py) lets only one insert succeed. This
        # turns that into a clean 409 instead of an unhandled 500.
        db.rollback()
        raise HTTPException(status_code=409, detail="This booking already has a review")
    db.refresh(review)
    return review


@app.post("/reviews/{review_id}/summarize", status_code=status.HTTP_202_ACCEPTED)
def trigger_review_summary(
    review_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    enqueue=Depends(get_summary_queue),
):
    """
    The "endpoint that triggers a review summarisation job" the brief asks
    for. It does not call an LLM — it pushes review_id onto Redis. worker.py
    is the separate process that consumes the queue and writes the summary.
    """
    review = db.query(Review).filter(Review.id == review_id).first()
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    verify_booking_access(review.booking, current_user)

    if review.summary_status == SummaryStatus.done:
        return {"detail": "Already summarized", "summary": review.summary}

    enqueue(str(review.id))
    return {"detail": "Summarization job enqueued"}


@app.get("/reviews/{review_id}", response_model=ReviewOut)
def get_review(
    review_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    review = db.query(Review).filter(Review.id == review_id).first()
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    verify_booking_access(review.booking, current_user)
    return review
