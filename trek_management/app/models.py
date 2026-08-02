"""
SQLAlchemy ORM models for the Trek Management System.

Tables:
    - users
    - staff_profiles
    - treks
    - bookings
    - trek_staff_assignments

All enums use Python's built-in `enum.Enum` and are stored as strings
in SQLite for readability and portability.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    CheckConstraint,
)
from sqlalchemy.orm import relationship, validates

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
    """Lifecycle status of a trek."""
    UPCOMING = "Upcoming"
    ACTIVE = "Active"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class BookingStatus(str, enum.Enum):
    """Status of a booking."""
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    CANCELLED = "Cancelled"
    COMPLETED = "Completed"


class PaymentStatus(str, enum.Enum):
    """Payment status for a booking."""
    PENDING = "Pending"
    PAID = "Paid"
    FAILED = "Failed"
    REFUNDED = "Refunded"


class ApprovalStatus(str, enum.Enum):
    """Approval status for Trek Staff accounts."""
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


# ──────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────

def _utcnow():
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────

class User(Base):
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
    price = Column(Numeric(10, 2), nullable=False)  # Money-safe storage
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    status = Column(Enum(TrekStatus), nullable=False, default=TrekStatus.UPCOMING)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    # ---- Relationships ----
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

    User 1:N Booking, Trek 1:N Booking.
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
        Enum(BookingStatus), nullable=False, default=BookingStatus.PENDING
    )
    booking_date = Column(DateTime, default=_utcnow, nullable=False)
    payment_status = Column(
        Enum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING
    )
    participants = Column(Integer, nullable=False, default=1)
    total_amount = Column(Numeric(12, 2), nullable=False, default=0)

    # ---- Relationships ----
    user = relationship("User", back_populates="bookings")
    trek = relationship("Trek", back_populates="bookings")

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

    A unique constraint on (trek_id, staff_id) prevents duplicate
    assignments.
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
