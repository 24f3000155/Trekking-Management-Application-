"""
Booking service — business logic for creating, completing,
and cancelling bookings with transactional slot management.

All slot mutations happen inside a database transaction to
prevent race conditions and ensure consistency.

Booking lifecycle: Booked → Cancelled  OR  Booked → Completed
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    Booking,
    BookingStatus,
    Certificate,
    Trek,
    TrekStatus,
)
from app.services.audit_service import log_action


class BookingError(Exception):
    """Raised when a booking operation violates business rules."""


def create_booking(
    db: Session,
    user_id: int,
    trek_id: int,
    participants: int = 1,
    performed_by: int = None,
) -> Booking:
    """
    Create a new BOOKED booking and atomically decrement slots.

    Validates:
    - participants >= 1
    - Trek exists
    - Trek status == OPEN
    - Available slots >= participants
    - User has not already booked this trek
    - Booking deadline not exceeded

    Raises:
        BookingError: If any business rule is violated.
    """
    if participants < 1:
        raise BookingError("participants must be at least 1")

    trek = db.query(Trek).filter(Trek.id == trek_id).first()
    if trek is None:
        raise BookingError(f"Trek with id {trek_id} does not exist")

    # Trek must be OPEN for booking
    if trek.status != TrekStatus.OPEN:
        raise BookingError(
            f"Cannot book a trek with status '{trek.status.value}'. "
            f"Only 'Open' treks accept bookings."
        )

    # Check booking deadline
    if trek.booking_deadline:
        now = datetime.now(timezone.utc)
        deadline = trek.booking_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            raise BookingError("Booking deadline has passed for this trek.")

    # Check available slots
    if trek.available_slots < participants:
        raise BookingError(
            f"Insufficient slots: requested {participants}, "
            f"available {trek.available_slots}"
        )

    # Prevent duplicate active booking
    existing = (
        db.query(Booking)
        .filter(
            Booking.user_id == user_id,
            Booking.trek_id == trek_id,
            Booking.booking_status.in_([BookingStatus.BOOKED, BookingStatus.COMPLETED]),
        )
        .first()
    )
    if existing:
        raise BookingError("You already have an active booking for this trek.")

    total_amount = float(trek.price) * participants

    # Atomically create booking and decrement slots
    booking = Booking(
        user_id=user_id,
        trek_id=trek_id,
        participants=participants,
        total_amount=total_amount,
        booking_status=BookingStatus.BOOKED,
    )
    db.add(booking)
    trek.available_slots -= participants
    db.flush()  # Assign booking.id

    # Audit log
    log_action(
        db=db,
        entity_type="booking",
        entity_id=booking.id,
        action="created",
        new_value=BookingStatus.BOOKED.value,
        performed_by=performed_by or user_id,
        details=f"Booked {participants} slot(s) for trek '{trek.trek_name}'",
    )

    return booking


def cancel_booking(
    db: Session,
    booking_id: int,
    performed_by: int = None,
    check_trek_started: bool = True,
) -> Booking:
    """
    Cancel a booking and restore slots.

    Rules:
    - Only BOOKED bookings can be cancelled.
    - Users can only cancel before the trek starts (if check_trek_started=True).
    - Staff/Admin can cancel anytime (set check_trek_started=False).
    - Re-cancelling is idempotent.

    Raises:
        BookingError: If the booking cannot be cancelled.
    """
    now = datetime.now(timezone.utc)

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if booking is None:
        raise BookingError(f"Booking with id {booking_id} does not exist")

    # Idempotent: already cancelled → no-op
    if booking.booking_status == BookingStatus.CANCELLED:
        return booking

    if booking.booking_status == BookingStatus.COMPLETED:
        raise BookingError("Cannot cancel a completed booking")

    # Check if trek has already started (for user-initiated cancellations)
    if check_trek_started:
        trek = db.query(Trek).filter(Trek.id == booking.trek_id).first()
        if trek and trek.start_date:
            start_date = trek.start_date
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            if now >= start_date:
                raise BookingError("Cannot cancel booking — the trek has already started.")

    old_status = booking.booking_status.value
    booking.booking_status = BookingStatus.CANCELLED
    booking.cancelled_date = now
    booking.updated_at = now

    # Restore slots (only if trek is still Open)
    trek = db.query(Trek).filter(Trek.id == booking.trek_id).first()
    if trek and trek.status == TrekStatus.OPEN:
        trek.available_slots += booking.participants

    # Audit log
    log_action(
        db=db,
        entity_type="booking",
        entity_id=booking_id,
        action="cancelled",
        old_value=old_status,
        new_value=BookingStatus.CANCELLED.value,
        performed_by=performed_by,
        details=f"Booking cancelled, {booking.participants} slot(s) restored",
    )

    db.flush()
    return booking


def complete_booking(
    db: Session,
    booking_id: int,
    performed_by: int = None,
) -> Booking:
    """
    Mark a single booking as Completed and generate certificate.

    Only BOOKED bookings can be completed.

    Raises:
        BookingError: If the booking cannot be completed.
    """
    now = datetime.now(timezone.utc)

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if booking is None:
        raise BookingError(f"Booking with id {booking_id} does not exist")

    # Idempotent
    if booking.booking_status == BookingStatus.COMPLETED:
        return booking

    if booking.booking_status != BookingStatus.BOOKED:
        raise BookingError(
            f"Cannot complete a booking with status '{booking.booking_status.value}'"
        )

    old_status = booking.booking_status.value
    booking.booking_status = BookingStatus.COMPLETED
    booking.completion_date = now
    booking.updated_at = now

    # Auto-generate certificate
    if not booking.certificate:
        cert = Certificate(booking_id=booking.id)
        db.add(cert)

    # Audit log
    log_action(
        db=db,
        entity_type="booking",
        entity_id=booking_id,
        action="completed",
        old_value=old_status,
        new_value=BookingStatus.COMPLETED.value,
        performed_by=performed_by,
        details=f"Booking marked as Completed",
    )

    db.flush()
    return booking
