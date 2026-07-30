"""
Booking service — business logic for creating, confirming,
and cancelling bookings with transactional slot management.

All slot mutations happen inside a database transaction to
prevent race conditions and ensure consistency.
"""

from sqlalchemy.orm import Session

from app.models import (
    Booking,
    BookingStatus,
    PaymentStatus,
    Trek,
    TrekStatus,
)


class BookingError(Exception):
    """Raised when a booking operation violates business rules."""


def create_booking(
    db: Session,
    user_id: int,
    trek_id: int,
    participants: int = 1,
) -> Booking:
    """
    Create a new PENDING booking.

    Does NOT reduce available_slots yet — slots are only reserved
    when the booking is confirmed.

    Raises:
        BookingError: If the trek doesn't exist, is not bookable,
                      or participants < 1.
    """
    if participants < 1:
        raise BookingError("participants must be at least 1")

    trek = db.query(Trek).filter(Trek.id == trek_id).first()
    if trek is None:
        raise BookingError(f"Trek with id {trek_id} does not exist")

    if trek.status in (TrekStatus.COMPLETED, TrekStatus.CANCELLED):
        raise BookingError(
            f"Cannot book a trek with status '{trek.status.value}'"
        )

    total_amount = float(trek.price) * participants

    booking = Booking(
        user_id=user_id,
        trek_id=trek_id,
        participants=participants,
        total_amount=total_amount,
        booking_status=BookingStatus.PENDING,
        payment_status=PaymentStatus.PENDING,
    )
    db.add(booking)
    db.flush()  # Assign booking.id without committing
    return booking


def confirm_booking(db: Session, booking_id: int) -> Booking:
    """
    Confirm a PENDING booking and reserve participant slots.

    * Only PENDING bookings can be confirmed.
    * Slot availability is checked and decremented atomically.
    * If insufficient slots exist, the booking stays PENDING and an
      error is raised.
    * Re-confirming an already-confirmed booking is a no-op
      (idempotent guard).

    Raises:
        BookingError: If the booking doesn't exist, is not in
                      PENDING status, or there are insufficient slots.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if booking is None:
        raise BookingError(f"Booking with id {booking_id} does not exist")

    # Idempotent: already confirmed → no-op
    if booking.booking_status == BookingStatus.CONFIRMED:
        return booking

    if booking.booking_status != BookingStatus.PENDING:
        raise BookingError(
            f"Cannot confirm a booking with status "
            f"'{booking.booking_status.value}'"
        )

    trek = db.query(Trek).filter(Trek.id == booking.trek_id).first()
    if trek is None:
        raise BookingError("Associated trek does not exist")

    if trek.available_slots < booking.participants:
        raise BookingError(
            f"Insufficient slots: requested {booking.participants}, "
            f"available {trek.available_slots}"
        )

    # Reserve slots
    trek.available_slots -= booking.participants
    booking.booking_status = BookingStatus.CONFIRMED
    booking.payment_status = PaymentStatus.PAID
    db.flush()
    return booking


def cancel_booking(db: Session, booking_id: int) -> Booking:
    """
    Cancel a booking.

    * If the booking was CONFIRMED, slots are restored to the trek.
    * If the booking was PENDING, it is simply cancelled (no slot
      change).
    * Re-cancelling an already-cancelled booking is a no-op
      (idempotent guard).

    Raises:
        BookingError: If the booking doesn't exist or cannot be cancelled.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if booking is None:
        raise BookingError(f"Booking with id {booking_id} does not exist")

    # Idempotent: already cancelled → no-op
    if booking.booking_status == BookingStatus.CANCELLED:
        return booking

    if booking.booking_status == BookingStatus.COMPLETED:
        raise BookingError("Cannot cancel a completed booking")

    was_confirmed = booking.booking_status == BookingStatus.CONFIRMED

    booking.booking_status = BookingStatus.CANCELLED
    booking.payment_status = PaymentStatus.REFUNDED

    if was_confirmed:
        trek = db.query(Trek).filter(Trek.id == booking.trek_id).first()
        if trek is not None:
            trek.available_slots += booking.participants

    db.flush()
    return booking
