"""
Trek Staff routes: complete dashboard, trek management, participant management,
profile management, and search.

Every route is protected by @require_approved_staff() — only APPROVED Trek Staff
can access these routes.

Assignment-level authorization is enforced for every trek-specific operation via
the require_assigned_staff() helper, which checks that the currently logged-in
staff member is assigned to the requested trek.
"""

from functools import wraps

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort,
)
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models import (
    User, UserRole, StaffProfile, ApprovalStatus,
    Trek, TrekStatus, Difficulty,
    Booking, BookingStatus, PaymentStatus,
    TrekStaffAssignment,
)
from app.auth import require_approved_staff, get_current_user

staff_bp = Blueprint("staff", __name__, url_prefix="/staff")


# ─────────────────────────────────────────────
# Authorization Helpers
# ─────────────────────────────────────────────

def _get_staff_profile(db, user):
    """
    Retrieve the StaffProfile for the given User.
    Returns None if not found.
    """
    return (
        db.query(StaffProfile)
        .filter(StaffProfile.user_id == user.id)
        .first()
    )


def _is_assigned_to_trek(db, staff_profile_id, trek_id):
    """
    Check if a staff member (by staff_profile.id) is assigned to a specific trek.
    Returns True if assignment exists, False otherwise.
    """
    return (
        db.query(TrekStaffAssignment)
        .filter(
            TrekStaffAssignment.staff_id == staff_profile_id,
            TrekStaffAssignment.trek_id == trek_id,
        )
        .first()
    ) is not None


def _get_assigned_trek_ids(db, staff_profile_id):
    """
    Return a list of trek IDs assigned to a staff member.
    """
    assignments = (
        db.query(TrekStaffAssignment.trek_id)
        .filter(TrekStaffAssignment.staff_id == staff_profile_id)
        .all()
    )
    return [a.trek_id for a in assignments]


def require_assigned_staff(f):
    """
    Decorator: verify that the logged-in staff member is assigned to the
    trek specified by the 'trek_id' URL parameter.

    This is the CRITICAL authorization check that prevents IDOR attacks.
    Must be used on every route that operates on a specific trek.

    Chain: Authenticated → Role==TREK_STAFF → APPROVED → Assigned to Trek
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        trek_id = kwargs.get("trek_id")
        if trek_id is None:
            abort(400, "Trek ID is required.")

        user = get_current_user()
        if user is None:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login"))

        if user.role != UserRole.TREK_STAFF:
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for("auth.login"))

        db = SessionLocal()
        try:
            profile = _get_staff_profile(db, user)
            if profile is None:
                flash("Staff profile not found.", "danger")
                return redirect(url_for("auth.login"))

            if profile.approval_status != ApprovalStatus.APPROVED:
                flash("Your account is not approved.", "danger")
                return redirect(url_for("auth.login"))

            if not _is_assigned_to_trek(db, profile.id, trek_id):
                flash("You are not authorized to access this trek.", "danger")
                return redirect(url_for("staff.my_treks"))

            return f(*args, **kwargs)
        finally:
            db.close()

    return decorated_function


# ─────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────

@staff_bp.route("/dashboard")
@require_approved_staff()
def dashboard():
    """Staff dashboard with dynamic statistics."""
    user = get_current_user()
    db = SessionLocal()
    try:
        profile = _get_staff_profile(db, user)
        if not profile:
            flash("Staff profile not found.", "danger")
            return redirect(url_for("auth.login"))

        # Get assigned trek IDs
        assigned_ids = _get_assigned_trek_ids(db, profile.id)

        # Calculate statistics dynamically
        stats = {
            "assigned_treks": len(assigned_ids),
            "total_trekkers": 0,
            "open_treks": 0,
            "completed_treks": 0,
        }

        if assigned_ids:
            # Count confirmed bookings (total registered trekkers) for assigned treks
            stats["total_trekkers"] = (
                db.query(func.coalesce(func.sum(Booking.participants), 0))
                .filter(
                    Booking.trek_id.in_(assigned_ids),
                    Booking.booking_status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING])
                )
                .scalar()
            ) or 0

            # Count open/upcoming treks
            stats["open_treks"] = (
                db.query(func.count(Trek.id))
                .filter(
                    Trek.id.in_(assigned_ids),
                    Trek.status.in_([TrekStatus.UPCOMING, TrekStatus.ACTIVE])
                )
                .scalar()
            ) or 0

            # Count completed treks
            stats["completed_treks"] = (
                db.query(func.count(Trek.id))
                .filter(
                    Trek.id.in_(assigned_ids),
                    Trek.status == TrekStatus.COMPLETED
                )
                .scalar()
            ) or 0

        # Recent assigned treks (up to 5)
        recent_treks = []
        if assigned_ids:
            recent_treks = (
                db.query(Trek)
                .filter(Trek.id.in_(assigned_ids))
                .order_by(Trek.start_date.desc())
                .limit(5)
                .all()
            )

        return render_template(
            "staff/dashboard.html",
            user=user, stats=stats, recent_treks=recent_treks
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# My Assigned Treks
# ─────────────────────────────────────────────

@staff_bp.route("/treks")
@require_approved_staff()
def my_treks():
    """List ONLY treks assigned to the current staff member."""
    user = get_current_user()
    db = SessionLocal()
    try:
        profile = _get_staff_profile(db, user)
        if not profile:
            flash("Staff profile not found.", "danger")
            return redirect(url_for("auth.login"))

        assigned_ids = _get_assigned_trek_ids(db, profile.id)

        q = request.args.get("q", "").strip()
        status_filter = request.args.get("status", "").strip()

        query = db.query(Trek).filter(Trek.id.in_(assigned_ids)) if assigned_ids else db.query(Trek).filter(Trek.id == -1)

        # Apply search filters
        if q:
            query = query.filter(or_(
                Trek.trek_name.ilike(f"%{q}%"),
                Trek.location.ilike(f"%{q}%"),
                Trek.difficulty.ilike(f"%{q}%") if hasattr(Trek.difficulty, 'ilike') else True,
            ))
            # Also support search by ID
            try:
                trek_id_search = int(q)
                query = db.query(Trek).filter(
                    Trek.id.in_(assigned_ids),
                    or_(
                        Trek.id == trek_id_search,
                        Trek.trek_name.ilike(f"%{q}%"),
                        Trek.location.ilike(f"%{q}%"),
                    )
                )
            except (ValueError, TypeError):
                pass

        if status_filter:
            try:
                status_enum = TrekStatus(status_filter)
                query = query.filter(Trek.status == status_enum)
            except (ValueError, KeyError):
                pass

        treks = query.order_by(Trek.start_date.desc()).all()

        # Attach participant count to each trek
        for trek in treks:
            trek.participant_count = (
                db.query(func.coalesce(func.sum(Booking.participants), 0))
                .filter(
                    Booking.trek_id == trek.id,
                    Booking.booking_status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING])
                )
                .scalar()
            ) or 0

        return render_template(
            "staff/treks.html",
            user=user, treks=treks, q=q, status_filter=status_filter
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Trek Detail (with assignment check)
# ─────────────────────────────────────────────

@staff_bp.route("/treks/<int:trek_id>")
@require_approved_staff()
@require_assigned_staff
def trek_detail(trek_id):
    """
    View trek details — only if the staff member is assigned to it.
    Includes trek info, assigned staff, participants, and update forms.
    """
    user = get_current_user()
    db = SessionLocal()
    try:
        trek = (
            db.query(Trek)
            .options(
                joinedload(Trek.staff_assignments)
                .joinedload(TrekStaffAssignment.staff)
                .joinedload(StaffProfile.user),
                joinedload(Trek.bookings)
                .joinedload(Booking.user),
            )
            .filter(Trek.id == trek_id)
            .first()
        )

        if not trek:
            flash("Trek not found.", "danger")
            return redirect(url_for("staff.my_treks"))

        # Calculate participant count (non-cancelled bookings)
        participant_count = (
            db.query(func.coalesce(func.sum(Booking.participants), 0))
            .filter(
                Booking.trek_id == trek_id,
                Booking.booking_status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING])
            )
            .scalar()
        ) or 0

        # Confirmed participants (for slot validation message)
        confirmed_participants = (
            db.query(func.coalesce(func.sum(Booking.participants), 0))
            .filter(
                Booking.trek_id == trek_id,
                Booking.booking_status == BookingStatus.CONFIRMED
            )
            .scalar()
        ) or 0

        # Determine allowed status transitions
        allowed_transitions = _get_allowed_transitions(trek.status)

        # Get non-cancelled bookings for the participants list
        bookings = (
            db.query(Booking)
            .options(joinedload(Booking.user))
            .filter(
                Booking.trek_id == trek_id,
                Booking.booking_status != BookingStatus.CANCELLED
            )
            .order_by(Booking.booking_date.desc())
            .all()
        )

        return render_template(
            "staff/trek_detail.html",
            user=user, trek=trek,
            participant_count=participant_count,
            confirmed_participants=confirmed_participants,
            allowed_transitions=allowed_transitions,
            bookings=bookings,
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Update Trek Available Slots
# ─────────────────────────────────────────────

@staff_bp.route("/treks/<int:trek_id>/update-slots", methods=["POST"])
@require_approved_staff()
@require_assigned_staff
def update_slots(trek_id):
    """
    Update available slots for an assigned trek.

    Validation:
    - Cannot be negative
    - Cannot exceed total_slots
    - Cannot go below confirmed participant count
    """
    db = SessionLocal()
    try:
        trek = db.query(Trek).filter(Trek.id == trek_id).first()
        if not trek:
            flash("Trek not found.", "danger")
            return redirect(url_for("staff.my_treks"))

        # Prevent updates on completed/cancelled treks
        if trek.status in (TrekStatus.COMPLETED, TrekStatus.CANCELLED):
            flash("Cannot update slots for a completed or cancelled trek.", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        try:
            new_slots = int(request.form.get("available_slots", ""))
        except (ValueError, TypeError):
            flash("Available slots must be a valid number.", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        # Validation: negative
        if new_slots < 0:
            flash("Available slots cannot be negative.", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        # Validation: exceed total
        if new_slots > trek.total_slots:
            flash(f"Available slots cannot exceed total slots ({trek.total_slots}).", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        # Validation: cannot violate existing confirmed bookings
        # Confirmed participants have already "occupied" slots.
        # The max available_slots can be is: total_slots - confirmed_participants
        # (since those slots are taken by confirmed bookings)
        confirmed_participants = (
            db.query(func.coalesce(func.sum(Booking.participants), 0))
            .filter(
                Booking.trek_id == trek_id,
                Booking.booking_status == BookingStatus.CONFIRMED
            )
            .scalar()
        ) or 0

        max_available = trek.total_slots - confirmed_participants
        if new_slots > max_available:
            flash(
                f"Cannot set available slots to {new_slots}. "
                f"There are {confirmed_participants} confirmed participant(s), "
                f"so maximum available slots is {max_available}.",
                "danger"
            )
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        trek.available_slots = new_slots
        db.commit()
        flash(f"Available slots updated to {new_slots}.", "success")
    except Exception:
        db.rollback()
        flash("Error updating available slots.", "danger")
    finally:
        db.close()

    return redirect(url_for("staff.trek_detail", trek_id=trek_id))


# ─────────────────────────────────────────────
# Update Trek Status
# ─────────────────────────────────────────────

def _get_allowed_transitions(current_status):
    """
    Returns valid status transitions based on current status.

    Workflow:
      Upcoming → Active → Completed
      Upcoming → Cancelled
      Active → Cancelled

    Extended support:
      The 'Active' status maps to the user-requested "Open/Started/Ongoing" concept.
      Upcoming = Open (registration open)
      Active = Started/Ongoing
      Completed = Completed (read-only)
      Cancelled = Cancelled
    """
    transitions = {
        TrekStatus.UPCOMING: [TrekStatus.UPCOMING, TrekStatus.ACTIVE, TrekStatus.CANCELLED],
        TrekStatus.ACTIVE: [TrekStatus.ACTIVE, TrekStatus.COMPLETED, TrekStatus.CANCELLED],
        TrekStatus.COMPLETED: [TrekStatus.COMPLETED],  # Read-only
        TrekStatus.CANCELLED: [TrekStatus.CANCELLED],  # Terminal state
    }
    return transitions.get(current_status, [current_status])


@staff_bp.route("/treks/<int:trek_id>/update-status", methods=["POST"])
@require_approved_staff()
@require_assigned_staff
def update_status(trek_id):
    """
    Update trek status with transition validation.

    When a trek becomes COMPLETED:
    - It becomes read-only (no more slot or status updates)
    - Implicitly closes registration

    When a trek goes from UPCOMING to ACTIVE:
    - Trek has effectively started
    """
    db = SessionLocal()
    try:
        trek = db.query(Trek).filter(Trek.id == trek_id).first()
        if not trek:
            flash("Trek not found.", "danger")
            return redirect(url_for("staff.my_treks"))

        new_status_value = request.form.get("status", "")
        try:
            new_status = TrekStatus(new_status_value)
        except (ValueError, KeyError):
            flash("Invalid trek status.", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        # Validate transition
        allowed = _get_allowed_transitions(trek.status)
        if new_status not in allowed:
            flash(
                f"Invalid status transition: {trek.status.value} → {new_status.value}.",
                "danger"
            )
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        # Same status = no-op
        if new_status == trek.status:
            flash("Status is already set to this value.", "info")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        old_status = trek.status
        trek.status = new_status

        # When completing a trek, close registration (set available_slots to 0)
        if new_status == TrekStatus.COMPLETED:
            trek.available_slots = 0

        db.commit()
        flash(f"Trek status updated: {old_status.value} → {new_status.value}.", "success")

    except Exception:
        db.rollback()
        flash("Error updating trek status.", "danger")
    finally:
        db.close()

    return redirect(url_for("staff.trek_detail", trek_id=trek_id))


# ─────────────────────────────────────────────
# Participants — All Assigned Treks
# ─────────────────────────────────────────────

@staff_bp.route("/participants")
@require_approved_staff()
def participants():
    """
    Show participants across ALL treks assigned to the current staff member.
    Supports search by name, email, or booking ID.
    """
    user = get_current_user()
    db = SessionLocal()
    try:
        profile = _get_staff_profile(db, user)
        if not profile:
            flash("Staff profile not found.", "danger")
            return redirect(url_for("auth.login"))

        assigned_ids = _get_assigned_trek_ids(db, profile.id)
        q = request.args.get("q", "").strip()

        if not assigned_ids:
            return render_template(
                "staff/participants.html",
                user=user, bookings=[], trek=None, q=q
            )

        query = (
            db.query(Booking)
            .options(joinedload(Booking.user), joinedload(Booking.trek))
            .filter(Booking.trek_id.in_(assigned_ids))
        )

        # Search
        if q:
            # Try booking ID search
            try:
                bid = int(q)
                query = query.filter(or_(
                    Booking.id == bid,
                    Booking.user.has(User.name.ilike(f"%{q}%")),
                    Booking.user.has(User.email.ilike(f"%{q}%")),
                ))
            except (ValueError, TypeError):
                query = query.filter(or_(
                    Booking.user.has(User.name.ilike(f"%{q}%")),
                    Booking.user.has(User.email.ilike(f"%{q}%")),
                ))

        bookings = query.order_by(Booking.booking_date.desc()).all()

        return render_template(
            "staff/participants.html",
            user=user, bookings=bookings, trek=None, q=q
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Participants — Per Trek
# ─────────────────────────────────────────────

@staff_bp.route("/treks/<int:trek_id>/participants")
@require_approved_staff()
@require_assigned_staff
def trek_participants(trek_id):
    """
    Show participants for a specific assigned trek.
    Supports search by name, email, or booking ID.
    """
    user = get_current_user()
    db = SessionLocal()
    try:
        trek = db.query(Trek).filter(Trek.id == trek_id).first()
        if not trek:
            flash("Trek not found.", "danger")
            return redirect(url_for("staff.my_treks"))

        q = request.args.get("q", "").strip()

        query = (
            db.query(Booking)
            .options(joinedload(Booking.user), joinedload(Booking.trek))
            .filter(Booking.trek_id == trek_id)
        )

        # Search
        if q:
            try:
                bid = int(q)
                query = query.filter(or_(
                    Booking.id == bid,
                    Booking.user.has(User.name.ilike(f"%{q}%")),
                    Booking.user.has(User.email.ilike(f"%{q}%")),
                ))
            except (ValueError, TypeError):
                query = query.filter(or_(
                    Booking.user.has(User.name.ilike(f"%{q}%")),
                    Booking.user.has(User.email.ilike(f"%{q}%")),
                ))

        bookings = query.order_by(Booking.booking_date.desc()).all()

        return render_template(
            "staff/participants.html",
            user=user, bookings=bookings, trek=trek, q=q
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────

@staff_bp.route("/profile")
@require_approved_staff()
def profile():
    """View staff profile."""
    user = get_current_user()
    db = SessionLocal()
    try:
        staff_profile = _get_staff_profile(db, user)
        if not staff_profile:
            flash("Staff profile not found.", "danger")
            return redirect(url_for("auth.login"))

        return render_template(
            "staff/profile.html",
            user=user, profile=staff_profile
        )
    finally:
        db.close()


@staff_bp.route("/profile/update", methods=["POST"])
@require_approved_staff()
def profile_update():
    """
    Update staff profile — only allowed fields.

    Staff can update:
    - Phone
    - Emergency Contact
    - Bio
    - Experience Years
    - Specialization
    - Certification

    Staff CANNOT update:
    - Role
    - Approval status
    - Account status
    - Email (identity)
    - Name (identity)
    """
    user = get_current_user()
    db = SessionLocal()
    try:
        # Re-query user and profile in this session
        db_user = db.query(User).filter(User.id == user.id).first()
        if not db_user:
            flash("User not found.", "danger")
            return redirect(url_for("auth.login"))

        staff_profile = (
            db.query(StaffProfile)
            .filter(StaffProfile.user_id == db_user.id)
            .first()
        )
        if not staff_profile:
            flash("Staff profile not found.", "danger")
            return redirect(url_for("auth.login"))

        # Update allowed fields ONLY
        phone = request.form.get("phone", "").strip()
        emergency_contact = request.form.get("emergency_contact", "").strip()
        bio = request.form.get("bio", "").strip()
        specialization = request.form.get("specialization", "").strip()
        certification = request.form.get("certification", "").strip()
        experience_years = request.form.get("experience_years", "0").strip()

        # Validate experience years
        try:
            exp = int(experience_years)
            if exp < 0:
                flash("Experience years cannot be negative.", "danger")
                return redirect(url_for("staff.profile"))
            if exp > 50:
                flash("Experience years seems too high. Maximum is 50.", "danger")
                return redirect(url_for("staff.profile"))
        except (ValueError, TypeError):
            flash("Experience years must be a number.", "danger")
            return redirect(url_for("staff.profile"))

        # Apply updates
        db_user.phone = phone if phone else None
        staff_profile.emergency_contact = emergency_contact if emergency_contact else None
        staff_profile.bio = bio if bio else None
        staff_profile.specialization = specialization if specialization else None
        staff_profile.certification = certification if certification else None
        staff_profile.experience_years = exp

        db.commit()
        flash("Profile updated successfully.", "success")

    except Exception:
        db.rollback()
        flash("Error updating profile.", "danger")
    finally:
        db.close()

    return redirect(url_for("staff.profile"))
