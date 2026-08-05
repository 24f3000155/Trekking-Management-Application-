"""
SQLAlchemy ORM models for the Trek Management System.

Tables:
    - users
    - staff_profiles
    - treks
    - bookings
    - trek_staff_assignments
    - attendance
    - feedback
    - certificates
    - audit_logs

All enums use Python's built-in `enum.Enum` and are stored as strings
in SQLite for readability and portability.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    CheckConstraint,
)
from sqlalchemy.orm import relationship, validates

from flask_login import UserMixin
from app.database import Base


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class UserRole(str, enum.Enum):
    """Roles available in the system."""
    ADMIN = "Admin"
    TREK_STAFF = "Trek Staff"
    TREKKER = "Trekker"


class Difficulty(str, enum.Enum):
    """Trek difficulty levels."""
    EASY = "Easy"
    MODERATE = "Moderate"
    HARD = "Hard"
    EXPERT = "Expert"


class TrekStatus(str, enum.Enum):
    """
    Lifecycle status of a trek.

    Pending → Approved → Open → Closed → Completed
    """
    PENDING = "Pending"
    APPROVED = "Approved"
    OPEN = "Open"
    CLOSED = "Closed"
    COMPLETED = "Completed"


class BookingStatus(str, enum.Enum):
    """
    Status of a booking.

    Booked → Cancelled  OR  Booked → Completed
    """
    BOOKED = "Booked"
    CANCELLED = "Cancelled"
    COMPLETED = "Completed"


class ApprovalStatus(str, enum.Enum):
    """Approval status for Trek Staff accounts."""
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class AttendanceStatus(str, enum.Enum):
    """Attendance status for participants."""
    PRESENT = "Present"
    ABSENT = "Absent"
    NOT_MARKED = "Not Marked"


# ──────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────

def _utcnow():
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────

class User(Base, UserMixin):
    """
    Represents an application user (Admin, Trek Staff, or Trekker).
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.TREKKER)
    phone = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_blacklisted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    # ---- Relationships ----
    bookings = relationship(
        "Booking",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    staff_profile = relationship(
        "StaffProfile",
        back_populates="user",
        uselist=False,  # one-to-one
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    created_treks = relationship(
        "Trek",
        back_populates="creator",
        foreign_keys="Trek.created_by",
    )

    def __repr__(self):
        return f"<User(id={self.id}, name='{self.name}', role={self.role.value})>"


class StaffProfile(Base):
    """
    Extended profile for users with the TREK_STAFF role.

    One-to-one with User.
    """
    __tablename__ = "staff_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    experience_years = Column(Integer, default=0, nullable=False)
    specialization = Column(String(200), nullable=True)
    certification = Column(String(200), nullable=True)
    emergency_contact = Column(String(50), nullable=True)
    bio = Column(Text, nullable=True)
    approval_status = Column(
        Enum(ApprovalStatus),
        nullable=False,
        default=ApprovalStatus.PENDING,
    )

    # ---- Relationships ----
    user = relationship("User", back_populates="staff_profile")
    trek_assignments = relationship(
        "TrekStaffAssignment",
        back_populates="staff",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self):
        return f"<StaffProfile(id={self.id}, user_id={self.user_id})>"


class Trek(Base):
    """
    Represents a trek that trekkers can book and staff can be assigned to.

    Lifecycle: Pending → Approved → Open → Closed → Completed
    """
    __tablename__ = "treks"
    __table_args__ = (
        CheckConstraint("total_slots > 0", name="ck_treks_total_slots_positive"),
        CheckConstraint("available_slots >= 0", name="ck_treks_available_slots_non_negative"),
        CheckConstraint("available_slots <= total_slots", name="ck_treks_available_lte_total"),
        CheckConstraint("duration_days > 0", name="ck_treks_duration_positive"),
        CheckConstraint("price >= 0", name="ck_treks_price_non_negative"),
        CheckConstraint("end_date >= start_date", name="ck_treks_end_after_start"),
    )

    id = Column(Integer, primary_key=True, index=True)
    trek_name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String(200), nullable=False)
    difficulty = Column(Enum(Difficulty), nullable=False, default=Difficulty.MODERATE)
    duration_days = Column(Integer, nullable=False)
    total_slots = Column(Integer, nullable=False)
    available_slots = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    booking_deadline = Column(DateTime, nullable=True)
    status = Column(Enum(TrekStatus), nullable=False, default=TrekStatus.PENDING)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # ---- Relationships ----
    creator = relationship("User", back_populates="created_treks", foreign_keys=[created_by])
    bookings = relationship(
        "Booking",
        back_populates="trek",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    staff_assignments = relationship(
        "TrekStaffAssignment",
        back_populates="trek",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # ---- Validators (application-level) ----
    @validates("available_slots")
    def _validate_available_slots(self, key, value):
        if value is not None and value < 0:
            raise ValueError("available_slots cannot be negative")
        return value

    @validates("total_slots")
    def _validate_total_slots(self, key, value):
        if value is not None and value <= 0:
            raise ValueError("total_slots must be greater than 0")
        return value

    @validates("duration_days")
    def _validate_duration_days(self, key, value):
        if value is not None and value <= 0:
            raise ValueError("duration_days must be greater than 0")
        return value

    @validates("price")
    def _validate_price(self, key, value):
        if value is not None and value < 0:
            raise ValueError("price cannot be negative")
        return value

    def __repr__(self):
        return f"<Trek(id={self.id}, name='{self.trek_name}', status={self.status.value})>"


class Booking(Base):
    """
    Represents a trekker's booking for a specific trek.

    Lifecycle: Booked → Cancelled  OR  Booked → Completed
    """
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("participants >= 1", name="ck_bookings_participants_min"),
        CheckConstraint("total_amount >= 0", name="ck_bookings_amount_non_negative"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    trek_id = Column(
        Integer,
        ForeignKey("treks.id", ondelete="CASCADE"),
        nullable=False,
    )
    booking_status = Column(
        Enum(BookingStatus), nullable=False, default=BookingStatus.BOOKED
    )
    booking_date = Column(DateTime, default=_utcnow, nullable=False)
    completion_date = Column(DateTime, nullable=True)
    cancelled_date = Column(DateTime, nullable=True)
    staff_id = Column(
        Integer,
        ForeignKey("staff_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    participants = Column(Integer, nullable=False, default=1)
    total_amount = Column(Numeric(12, 2), nullable=False, default=0)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # ---- Relationships ----
    user = relationship("User", back_populates="bookings")
    trek = relationship("Trek", back_populates="bookings")
    assigned_staff = relationship("StaffProfile", foreign_keys=[staff_id])
    attendance = relationship(
        "Attendance",
        back_populates="booking",
        uselist=False,
        cascade="all, delete-orphan",
    )
    feedback = relationship(
        "Feedback",
        back_populates="booking",
        uselist=False,
        cascade="all, delete-orphan",
    )
    certificate = relationship(
        "Certificate",
        back_populates="booking",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # ---- Validators ----
    @validates("participants")
    def _validate_participants(self, key, value):
        if value is not None and value < 1:
            raise ValueError("participants must be at least 1")
        return value

    @validates("total_amount")
    def _validate_total_amount(self, key, value):
        if value is not None and value < 0:
            raise ValueError("total_amount cannot be negative")
        return value

    def __repr__(self):
        return (
            f"<Booking(id={self.id}, user_id={self.user_id}, "
            f"trek_id={self.trek_id}, status={self.booking_status.value})>"
        )


class TrekStaffAssignment(Base):
    """
    Junction table implementing the many-to-many relationship
    between Treks and StaffProfiles.
    """
    __tablename__ = "trek_staff_assignments"
    __table_args__ = (
        UniqueConstraint("trek_id", "staff_id", name="uq_trek_staff"),
    )

    id = Column(Integer, primary_key=True, index=True)
    trek_id = Column(
        Integer,
        ForeignKey("treks.id", ondelete="CASCADE"),
        nullable=False,
    )
    staff_id = Column(
        Integer,
        ForeignKey("staff_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_date = Column(DateTime, default=_utcnow, nullable=False)

    # ---- Relationships ----
    trek = relationship("Trek", back_populates="staff_assignments")
    staff = relationship("StaffProfile", back_populates="trek_assignments")

    def __repr__(self):
        return (
            f"<TrekStaffAssignment(trek_id={self.trek_id}, "
            f"staff_id={self.staff_id})>"
        )


class Attendance(Base):
    """
    Tracks attendance for a booking/participant on a trek.
    One-to-one with Booking.
    """
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("booking_id", name="uq_attendance_booking"),
    )

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(
        Integer,
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status = Column(
        Enum(AttendanceStatus),
        nullable=False,
        default=AttendanceStatus.NOT_MARKED,
    )
    marked_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    marked_at = Column(DateTime, nullable=True)
    remarks = Column(Text, nullable=True)

    # ---- Relationships ----
    booking = relationship("Booking", back_populates="attendance")

    def __repr__(self):
        return f"<Attendance(booking_id={self.booking_id}, status={self.status.value})>"


class Feedback(Base):
    """
    User feedback for a completed booking/trek.
    One-to-one with Booking.
    """
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("booking_id", name="uq_feedback_booking"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_feedback_rating_range"),
    )

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(
        Integer,
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    # ---- Relationships ----
    booking = relationship("Booking", back_populates="feedback")

    @validates("rating")
    def _validate_rating(self, key, value):
        if value is not None and (value < 1 or value > 5):
            raise ValueError("rating must be between 1 and 5")
        return value

    def __repr__(self):
        return f"<Feedback(booking_id={self.booking_id}, rating={self.rating})>"


class Certificate(Base):
    """
    Certificate record for a completed trek booking.
    One-to-one with Booking.
    """
    __tablename__ = "certificates"
    __table_args__ = (
        UniqueConstraint("booking_id", name="uq_certificate_booking"),
    )

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(
        Integer,
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    certificate_uid = Column(String(64), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    issued_date = Column(DateTime, default=_utcnow, nullable=False)

    # ---- Relationships ----
    booking = relationship("Booking", back_populates="certificate")

    def __repr__(self):
        return f"<Certificate(booking_id={self.booking_id}, uid={self.certificate_uid})>"


class AuditLog(Base):
    """
    Immutable audit log for tracking every status change.

    Records who changed what, when, and the old/new values.
    This table is append-only — records are never updated or deleted.
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(50), nullable=False)  # 'trek' or 'booking'
    entity_id = Column(Integer, nullable=False)
    action = Column(String(100), nullable=False)  # e.g. 'status_change', 'created', 'cancelled'
    old_value = Column(String(200), nullable=True)
    new_value = Column(String(200), nullable=True)
    performed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    performed_at = Column(DateTime, default=_utcnow, nullable=False)
    details = Column(Text, nullable=True)

    # ---- Relationships ----
    performer = relationship("User", foreign_keys=[performed_by])

    def __repr__(self):
        return (
            f"<AuditLog(entity={self.entity_type}:{self.entity_id}, "
            f"action={self.action})>"
        )
