"""
Trek service — business logic for trek lifecycle management.

Manages the trek status state machine:
    Pending → Approved → Open → Closed → Completed

When a trek is completed, all active (Booked) bookings are also
marked as Completed, and certificates are auto-generated.
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


class TrekStatusError(Exception):
    """Raised when a trek status transition is invalid."""


# ── Valid transitions (state machine) ──
VALID_TRANSITIONS = {
    TrekStatus.PENDING:   [TrekStatus.APPROVED],
    TrekStatus.APPROVED:  [TrekStatus.OPEN],
    TrekStatus.OPEN:      [TrekStatus.CLOSED],
    TrekStatus.CLOSED:    [TrekStatus.COMPLETED],
    TrekStatus.COMPLETED: [],  # Terminal state — no further transitions
}


def get_allowed_transitions(current_status: TrekStatus):
    """Return list of valid next statuses for the given current status."""
    return VALID_TRANSITIONS.get(current_status, [])


def advance_trek_status(
    db: Session,
    trek_id: int,
    new_status: TrekStatus,
    performed_by: int = None,
) -> Trek:
    """
    Transition a trek to a new status with validation.

    When completing a trek:
    - Sets available_slots to 0
    - Marks all Booked bookings as Completed
    - Auto-generates certificates for completed bookings

    Raises:
        TrekStatusError: If the transition is invalid.
    """
    trek = db.query(Trek).filter(Trek.id == trek_id).first()
    if trek is None:
        raise TrekStatusError(f"Trek with id {trek_id} does not exist")

    allowed = get_allowed_transitions(trek.status)
    if new_status not in allowed:
        raise TrekStatusError(
            f"Invalid transition: {trek.status.value} → {new_status.value}. "
            f"Allowed: {[s.value for s in allowed]}"
        )

    old_status = trek.status
    trek.status = new_status
    trek.updated_at = datetime.now(timezone.utc)

    # When closing a trek, disable further bookings
    if new_status == TrekStatus.CLOSED:
        trek.available_slots = 0

    # When completing a trek, finalize all bookings
    if new_status == TrekStatus.COMPLETED:
        trek.available_slots = 0
        _complete_all_bookings(db, trek_id, performed_by)

    # Audit log
    log_action(
        db=db,
        entity_type="trek",
        entity_id=trek_id,
        action="status_change",
        old_value=old_status.value,
        new_value=new_status.value,
        performed_by=performed_by,
        details=f"Trek '{trek.trek_name}' status changed from {old_status.value} to {new_status.value}",
    )

    db.flush()
    return trek


def _complete_all_bookings(db: Session, trek_id: int, performed_by: int = None):
    """Mark all Booked bookings for this trek as Completed and generate certificates."""
    now = datetime.now(timezone.utc)
    bookings = (
        db.query(Booking)
        .filter(
            Booking.trek_id == trek_id,
            Booking.booking_status == BookingStatus.BOOKED,
        )
        .all()
    )

    for booking in bookings:
        booking.booking_status = BookingStatus.COMPLETED
        booking.completion_date = now
        booking.updated_at = now

        # Auto-generate certificate
        if not booking.certificate:
            cert = Certificate(booking_id=booking.id)
            db.add(cert)

        # Audit log per booking
        log_action(
            db=db,
            entity_type="booking",
            entity_id=booking.id,
            action="auto_completed",
            old_value=BookingStatus.BOOKED.value,
            new_value=BookingStatus.COMPLETED.value,
            performed_by=performed_by,
            details=f"Auto-completed when trek was marked Completed",
        )
