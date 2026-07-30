"""
Seed / test data script.

Demonstrates all major database operations:
  1.  Creating a Trekker
  2.  Creating a Trek Staff user
  3.  Creating a StaffProfile
  4.  Creating a Trek
  5.  Assigning Staff to the Trek
  6.  Creating a Booking
  7.  Confirming the Booking
  8.  Querying the Trekker's bookings
  9.  Querying everyone booked on a Trek
  10. Querying all staff assigned to a Trek

The script is idempotent -- running it multiple times will NOT
create duplicate data (it checks for existing records first).

Usage:
    python -m scripts.seed_data
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
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
    confirm_booking,
    cancel_booking,
    BookingError,
)


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
                status=TrekStatus.UPCOMING,
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

        # Commit all seed data before running destructive tests
        db.commit()

        # -- Verify duplicate assignment is rejected --
        print("\n   [TEST] Testing duplicate staff assignment rejection ...")
        try:
            dup = TrekStaffAssignment(
                trek_id=trek.id,
                staff_id=staff_profile.id,
            )
            db.add(dup)
            db.flush()
            print("  [FAIL] Duplicate assignment was NOT rejected!")
        except IntegrityError:
            db.rollback()
            # Re-query objects after rollback since session is invalidated
            trekker = db.query(User).filter(User.email == "john.trekker@example.com").first()
            staff_user = db.query(User).filter(User.email == "jane.guide@example.com").first()
            staff_profile = db.query(StaffProfile).filter(StaffProfile.user_id == staff_user.id).first()
            trek = db.query(Trek).filter(Trek.trek_name == "Hampta Pass").first()
            print("  [OK] Duplicate assignment correctly rejected (IntegrityError)")

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

        # ------------------------------------------
        # 7. Confirm the Booking
        # ------------------------------------------
        print("\n[7] Confirming Booking ...")
        slots_before = trek.available_slots
        booking = confirm_booking(db, booking.id)
        db.commit()
        db.refresh(trek)
        print(f"  [OK] Booking status: {booking.booking_status.value}")
        print(f"       Payment status: {booking.payment_status.value}")
        print(f"       Slots: {slots_before} -> {trek.available_slots}")

        # -- Test re-confirmation is idempotent --
        print("\n   [TEST] Testing re-confirmation idempotency ...")
        slots_before_reconfirm = trek.available_slots
        confirm_booking(db, booking.id)
        db.commit()
        db.refresh(trek)
        if trek.available_slots == slots_before_reconfirm:
            print("  [OK] Re-confirmation did NOT reduce slots again (idempotent)")
        else:
            print("  [FAIL] Re-confirmation changed slots!")

        # -- Test overbooking rejection --
        print("\n   [TEST] Testing overbooking rejection ...")
        # Temporarily set available_slots to 0 to test
        original_slots = trek.available_slots
        trek.available_slots = 0
        db.flush()
        overbook_trekker, _ = _get_or_create_user(
            db,
            email="overbook@example.com",
            name="Over Booker",
            password_hash=hash_password("OverBook1!"),
            role=UserRole.TREKKER,
        )
        try:
            ob_booking = create_booking(db, user_id=overbook_trekker.id,
                                        trek_id=trek.id, participants=1)
            confirm_booking(db, ob_booking.id)
            print("  [FAIL] Overbooking was NOT rejected!")
        except BookingError as e:
            print(f"  [OK] Overbooking correctly rejected: {e}")
            # Remove the pending over-booking attempt
            db.rollback()
            trek = db.query(Trek).filter(Trek.trek_name == "Hampta Pass").first()
            trekker = db.query(User).filter(User.email == "john.trekker@example.com").first()
            # Restore original slots
            trek.available_slots = original_slots
            db.commit()
            db.refresh(trek)

        # ------------------------------------------
        # 8. Query Trekker's bookings
        # ------------------------------------------
        print("\n[8] Querying Trekker's bookings ...")
        trekker = db.query(User).filter(User.email == "john.trekker@example.com").first()
        for b in trekker.bookings:
            print(f"  Booking #{b.id} -- Trek: {b.trek.trek_name}, "
                  f"Status: {b.booking_status.value}, "
                  f"Participants: {b.participants}")

        # ------------------------------------------
        # 9. Query everyone booked on the Trek
        # ------------------------------------------
        print("\n[9] Querying all bookings for Trek '{}' ...".format(trek.trek_name))
        trek = db.query(Trek).filter(Trek.trek_name == "Hampta Pass").first()
        for b in trek.bookings:
            print(f"  {b.user.name} (email: {b.user.email}) -- "
                  f"Status: {b.booking_status.value}")

        # ------------------------------------------
        # 10. Query all staff assigned to the Trek
        # ------------------------------------------
        print("\n[10] Querying staff assigned to Trek '{}' ...".format(trek.trek_name))
        for a in trek.staff_assignments:
            staff_u = a.staff.user
            print(f"  {staff_u.name} -- "
                  f"Specialization: {a.staff.specialization}, "
                  f"Experience: {a.staff.experience_years} years")

        # ------------------------------------------
        # Done
        # ------------------------------------------
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
