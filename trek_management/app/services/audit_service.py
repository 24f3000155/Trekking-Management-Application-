"""
Audit service — immutable logging of all status changes and key actions.

Every trek status transition, booking status change, and significant
operation is recorded in the audit_logs table for compliance and traceability.
"""

from sqlalchemy.orm import Session

from app.models import AuditLog


def log_action(
    db: Session,
    entity_type: str,
    entity_id: int,
    action: str,
    old_value: str = None,
    new_value: str = None,
    performed_by: int = None,
    details: str = None,
):
    """
    Create an immutable audit log entry.

    Args:
        db: Active database session.
        entity_type: 'trek' or 'booking'.
        entity_id: Primary key of the entity.
        action: Description of the action (e.g. 'status_change').
        old_value: Previous value (for status changes).
        new_value: New value (for status changes).
        performed_by: User ID who performed the action.
        details: Additional context.
    """
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        old_value=old_value,
        new_value=new_value,
        performed_by=performed_by,
        details=details,
    )
    db.add(entry)
    db.flush()
    return entry
