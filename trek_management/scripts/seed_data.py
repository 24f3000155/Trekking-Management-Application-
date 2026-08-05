"""
Seed / test data script.

Demonstrates all major database operations with new enums:
  1. Creating a Trekker
  2. Creating a Trek Staff user
  3. Creating a StaffProfile
  4. Creating a Trek (lifecycle test)
  5. Assigning Staff to the Trek
  6. Creating a Booking
  7. Confirming (Booking -> Booked)
  8. Querying the Trekker's bookings
  9. Testing Admin workflow
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, Base, engine
from app.models import (
    User,
    UserRole,
    StaffProfile,
    Trek,
    TrekStaffAssignment,
    Difficulty,
    TrekStatus,
    Booking,
    BookingStatus,
)
from app.security import hash_password
from app.services.booking_service import (
    create_booking,
    cancel_booking,
    complete_booking,
    BookingError,
)
from app.services.trek_service import advance_trek_status


def _get_or_create_user(db, email, **kwargs):
    """Return existing user by email, or create a new one."""
    user = db.query(User).filter(User.email == email).first()
    if user:
        print(f"  -> User '{email}' already exists (id={user.id})")
        return user, False
    user = User(email=email, **kwargs)
    db.add(user)
    db.flush()
    print(f"  [OK] Created user '{email}' (id={user.id})")
    return user, True


def run_seed():
    Base.metadata.create_all(bind=engine)  # Create tables if not exists
    db = SessionLocal()
    try:
        print("=" * 60)
        print("  TREK MANAGEMENT -- SEED / TEST DATA")
        print("=" * 60)

        # ------------------------------------------
        # 1. Create a Trekker
        # ------------------------------------------
        print("\n[1] Creating Trekker user ...")
        trekker, _ = _get_or_create_user(
            db,
            email="john.trekker@example.com",
            name="John Trekker",
            password_hash=hash_password("TrekkerPass1!"),
            role=UserRole.TREKKER,
        )

        admin, _ = _get_or_create_user(
            db,
            email="admin@example.com",
            name="Admin User",
            password_hash=hash_password("AdminPass1!"),
            role=UserRole.ADMIN,
        )

        # ------------------------------------------
        # 2. Create a Trek Staff user
        # ------------------------------------------
        print("\n[2] Creating Trek Staff user ...")
        staff_user, staff_created = _get_or_create_user(
            db,
            email="jane.guide@example.com",
            name="Jane Guide",
            password_hash=hash_password("GuidePass1!"),
            role=UserRole.TREK_STAFF,
        )

        # ------------------------------------------
        # 3. Create Staff Profile
        # ------------------------------------------
        print("\n[3] Creating Staff Profile ...")
        staff_profile = (
            db.query(StaffProfile)
            .filter(StaffProfile.user_id == staff_user.id)
            .first()
        )
        if staff_profile:
            print(f"  -> StaffProfile already exists (id={staff_profile.id})")
        else:
            staff_profile = StaffProfile(
                user_id=staff_user.id,
                experience_years=5,
                specialization="High Altitude Trekking",
                certification="Wilderness First Responder",
                emergency_contact="+91-9876543210",
                bio="Experienced mountain guide with 5 years in the Himalayas.",
            )
            db.add(staff_profile)
            db.flush()
            print(f"  [OK] Created StaffProfile (id={staff_profile.id})")

        # ------------------------------------------
        # 4. Create a Trek
        # ------------------------------------------
        print("\n[4] Creating Trek ...")
        trek = db.query(Trek).filter(Trek.trek_name == "Hampta Pass").first()
        if trek:
            print(f"  -> Trek 'Hampta Pass' already exists (id={trek.id})")
        else:
            start = datetime.now(timezone.utc) + timedelta(days=30)
            trek = Trek(
                trek_name="Hampta Pass",
                description="A stunning crossover trek from Kullu to Spiti valley.",
                location="Himachal Pradesh, India",
                difficulty=Difficulty.MODERATE,
                duration_days=5,
                total_slots=20,
                available_slots=20,
                price=Decimal("12500.00"),
                start_date=start,
                end_date=start + timedelta(days=5),
                booking_deadline=start - timedelta(days=2),
                status=TrekStatus.OPEN,  # Start at Open for booking test
            )
            db.add(trek)
            db.flush()
            print(f"  [OK] Created Trek '{trek.trek_name}' (id={trek.id})")

        # ------------------------------------------
        # 5. Assign Staff to the Trek
        # ------------------------------------------
        print("\n[5] Assigning Staff to Trek ...")
        existing_assignment = (
            db.query(TrekStaffAssignment)
            .filter(
                TrekStaffAssignment.trek_id == trek.id,
                TrekStaffAssignment.staff_id == staff_profile.id,
            )
            .first()
        )
        if existing_assignment:
            print(f"  -> Assignment already exists (id={existing_assignment.id})")
        else:
            assignment = TrekStaffAssignment(
                trek_id=trek.id,
                staff_id=staff_profile.id,
            )
            db.add(assignment)
            db.flush()
            print(f"  [OK] Assigned staff '{staff_user.name}' to trek "
                  f"'{trek.trek_name}' (id={assignment.id})")

        db.commit()

        # ------------------------------------------
        # 6. Create a Booking
        # ------------------------------------------
        print("\n[6] Creating Booking ...")
        booking = (
            db.query(Booking)
            .filter(
                Booking.user_id == trekker.id,
                Booking.trek_id == trek.id,
            )
            .first()
        )
        if booking:
            print(f"  -> Booking already exists (id={booking.id}, "
                  f"status={booking.booking_status.value})")
        else:
            booking = create_booking(
                db,
                user_id=trekker.id,
                trek_id=trek.id,
                participants=2,
            )
            print(f"  [OK] Created Booking (id={booking.id}, "
                  f"participants={booking.participants}, "
                  f"amount={booking.total_amount})")
            db.commit()

        # ------------------------------------------
        # 7. Complete The Trek (Tests State Machine)
        # ------------------------------------------
        print("\n[7] Testing State Machine (Open -> Closed -> Completed)")
        advance_trek_status(db, trek.id, TrekStatus.CLOSED, admin.id)
        print(f"  [OK] Trek Closed.")
        
        # Now Complete Trek
        advance_trek_status(db, trek.id, TrekStatus.COMPLETED, admin.id)
        db.commit()
        db.refresh(trek)
        db.refresh(booking)
        print(f"  [OK] Trek Completed. Booking automatically updated to: {booking.booking_status.value}")

        print("\n" + "=" * 60)
        print("  ALL SEED DATA AND TESTS COMPLETED SUCCESSFULLY")
        print("=" * 60)

    except Exception as exc:
        db.rollback()
        print(f"\n[ERROR] Seed script failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
