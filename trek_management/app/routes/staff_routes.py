"""
Trek Staff routes: dashboard, trek management, participant management,
profile management, attendance, booking completion, and participant export.

Every route is protected by @require_approved_staff() — only APPROVED Trek Staff
can access these routes.

Assignment-level authorization is enforced for every trek-specific operation via
the require_assigned_staff() helper.
"""

import csv
import io
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, make_response,
)
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models import (
    User, UserRole, StaffProfile, ApprovalStatus,
    Trek, TrekStatus, Difficulty,
    Booking, BookingStatus,
    TrekStaffAssignment, Attendance, AttendanceStatus,
)
from app.auth import require_approved_staff, get_current_user
from app.services.trek_service import advance_trek_status, get_allowed_transitions, TrekStatusError
from app.services.booking_service import cancel_booking, complete_booking, BookingError

staff_bp = Blueprint("staff", __name__, url_prefix="/staff")


# ─────────────────────────────────────────────
# Authorization Helpers
# ─────────────────────────────────────────────

def _get_staff_profile(db, user):
    return (
        db.query(StaffProfile)
        .filter(StaffProfile.user_id == user.id)
        .first()
    )


def _is_assigned_to_trek(db, staff_profile_id, trek_id):
    return (
        db.query(TrekStaffAssignment)
        .filter(
            TrekStaffAssignment.staff_id == staff_profile_id,
            TrekStaffAssignment.trek_id == trek_id,
        )
        .first()
    ) is not None


def _get_assigned_trek_ids(db, staff_profile_id):
    assignments = (
        db.query(TrekStaffAssignment.trek_id)
        .filter(TrekStaffAssignment.staff_id == staff_profile_id)
        .all()
    )
    return [a.trek_id for a in assignments]


def require_assigned_staff(f):
    """Decorator: verify staff is assigned to the trek_id URL parameter."""
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

        assigned_ids = _get_assigned_trek_ids(db, profile.id)

        stats = {
            "assigned_treks": len(assigned_ids),
            "total_trekkers": 0,
            "open_treks": 0,
            "completed_treks": 0,
        }

        if assigned_ids:
            stats["total_trekkers"] = (
                db.query(func.coalesce(func.sum(Booking.participants), 0))
                .filter(
                    Booking.trek_id.in_(assigned_ids),
                    Booking.booking_status == BookingStatus.BOOKED
                )
                .scalar()
            ) or 0

            stats["open_treks"] = (
                db.query(func.count(Trek.id))
                .filter(
                    Trek.id.in_(assigned_ids),
                    Trek.status.in_([TrekStatus.OPEN, TrekStatus.APPROVED])
                )
                .scalar()
            ) or 0

            stats["completed_treks"] = (
                db.query(func.count(Trek.id))
                .filter(
                    Trek.id.in_(assigned_ids),
                    Trek.status == TrekStatus.COMPLETED
                )
                .scalar()
            ) or 0

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

        if q:
            query = query.filter(or_(
                Trek.trek_name.ilike(f"%{q}%"),
                Trek.location.ilike(f"%{q}%"),
            ))

        if status_filter:
            try:
                status_enum = TrekStatus(status_filter)
                query = query.filter(Trek.status == status_enum)
            except (ValueError, KeyError):
                pass

        treks = query.order_by(Trek.start_date.desc()).all()

        for trek in treks:
            trek.participant_count = (
                db.query(func.coalesce(func.sum(Booking.participants), 0))
                .filter(
                    Booking.trek_id == trek.id,
                    Booking.booking_status == BookingStatus.BOOKED
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
# Trek Detail
# ─────────────────────────────────────────────

@staff_bp.route("/treks/<int:trek_id>")
@require_approved_staff()
@require_assigned_staff
def trek_detail(trek_id):
    """View trek details with participants and management controls."""
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

        participant_count = (
            db.query(func.coalesce(func.sum(Booking.participants), 0))
            .filter(
                Booking.trek_id == trek_id,
                Booking.booking_status == BookingStatus.BOOKED
            )
            .scalar()
        ) or 0

        allowed_transitions = get_allowed_transitions(trek.status)

        bookings = (
            db.query(Booking)
            .options(
                joinedload(Booking.user),
                joinedload(Booking.attendance),
            )
            .filter(Booking.trek_id == trek_id)
            .order_by(Booking.booking_date.desc())
            .all()
        )

        return render_template(
            "staff/trek_detail.html",
            user=user, trek=trek,
            participant_count=participant_count,
            allowed_transitions=allowed_transitions,
            bookings=bookings,
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Update Trek Status
# ─────────────────────────────────────────────

@staff_bp.route("/treks/<int:trek_id>/update-status", methods=["POST"])
@require_approved_staff()
@require_assigned_staff
def update_status(trek_id):
    """Update trek status using the state machine."""
    user = get_current_user()
    db = SessionLocal()
    try:
        new_status_value = request.form.get("status", "")
        try:
            new_status = TrekStatus(new_status_value)
        except (ValueError, KeyError):
            flash("Invalid trek status.", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        try:
            advance_trek_status(
                db=db,
                trek_id=trek_id,
                new_status=new_status,
                performed_by=user.id,
            )
            db.commit()
            flash(f"Trek status updated to {new_status.value}.", "success")
        except TrekStatusError as e:
            db.rollback()
            flash(str(e), "danger")

    except Exception:
        db.rollback()
        flash("Error updating trek status.", "danger")
    finally:
        db.close()

    return redirect(url_for("staff.trek_detail", trek_id=trek_id))


# ─────────────────────────────────────────────
# Update Trek Slots
# ─────────────────────────────────────────────

@staff_bp.route("/treks/<int:trek_id>/update-slots", methods=["POST"])
@require_approved_staff()
@require_assigned_staff
def update_slots(trek_id):
    """Update available slots for an assigned trek."""
    db = SessionLocal()
    try:
        trek = db.query(Trek).filter(Trek.id == trek_id).first()
        if not trek:
            flash("Trek not found.", "danger")
            return redirect(url_for("staff.my_treks"))

        if trek.status in (TrekStatus.COMPLETED, TrekStatus.CLOSED):
            flash("Cannot update slots for a completed or closed trek.", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        try:
            new_slots = int(request.form.get("available_slots", ""))
        except (ValueError, TypeError):
            flash("Available slots must be a valid number.", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        if new_slots < 0:
            flash("Available slots cannot be negative.", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        if new_slots > trek.total_slots:
            flash(f"Available slots cannot exceed total slots ({trek.total_slots}).", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        booked_participants = (
            db.query(func.coalesce(func.sum(Booking.participants), 0))
            .filter(
                Booking.trek_id == trek_id,
                Booking.booking_status == BookingStatus.BOOKED
            )
            .scalar()
        ) or 0

        max_available = trek.total_slots - booked_participants
        if new_slots > max_available:
            flash(
                f"Cannot set available slots to {new_slots}. "
                f"There are {booked_participants} booked participant(s), "
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
# Mark Attendance
# ─────────────────────────────────────────────

@staff_bp.route("/treks/<int:trek_id>/bookings/<int:booking_id>/attendance", methods=["POST"])
@require_approved_staff()
@require_assigned_staff
def mark_attendance(trek_id, booking_id):
    """Mark attendance for a participant."""
    user = get_current_user()
    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.trek_id == trek_id,
        ).first()

        if not booking:
            flash("Booking not found.", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        att_status = request.form.get("attendance_status", "")
        try:
            att_enum = AttendanceStatus(att_status)
        except ValueError:
            flash("Invalid attendance status.", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        attendance = db.query(Attendance).filter(Attendance.booking_id == booking_id).first()
        if attendance:
            attendance.status = att_enum
            attendance.marked_by = user.id
            attendance.marked_at = datetime.now(timezone.utc)
        else:
            attendance = Attendance(
                booking_id=booking_id,
                status=att_enum,
                marked_by=user.id,
                marked_at=datetime.now(timezone.utc),
            )
            db.add(attendance)

        db.commit()
        flash(f"Attendance marked as {att_enum.value}.", "success")

    except Exception:
        db.rollback()
        flash("Error marking attendance.", "danger")
    finally:
        db.close()

    return redirect(url_for("staff.trek_detail", trek_id=trek_id))


# ─────────────────────────────────────────────
# Complete Individual Booking
# ─────────────────────────────────────────────

@staff_bp.route("/treks/<int:trek_id>/bookings/<int:booking_id>/complete", methods=["POST"])
@require_approved_staff()
@require_assigned_staff
def complete_participant(trek_id, booking_id):
    """Mark a single participant's booking as Completed."""
    user = get_current_user()
    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.trek_id == trek_id,
        ).first()

        if not booking:
            flash("Booking not found.", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        try:
            complete_booking(db=db, booking_id=booking_id, performed_by=user.id)
            db.commit()
            flash("Participant booking marked as Completed.", "success")
        except BookingError as e:
            db.rollback()
            flash(str(e), "danger")

    except Exception:
        db.rollback()
        flash("Error completing booking.", "danger")
    finally:
        db.close()

    return redirect(url_for("staff.trek_detail", trek_id=trek_id))


# ─────────────────────────────────────────────
# Cancel Participant Booking
# ─────────────────────────────────────────────

@staff_bp.route("/treks/<int:trek_id>/bookings/<int:booking_id>/cancel", methods=["POST"])
@require_approved_staff()
@require_assigned_staff
def cancel_participant(trek_id, booking_id):
    """Cancel a participant's booking (staff-initiated, no start-date check)."""
    user = get_current_user()
    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.trek_id == trek_id,
        ).first()

        if not booking:
            flash("Booking not found.", "danger")
            return redirect(url_for("staff.trek_detail", trek_id=trek_id))

        try:
            cancel_booking(
                db=db,
                booking_id=booking_id,
                performed_by=user.id,
                check_trek_started=False,
            )
            db.commit()
            flash("Participant booking cancelled.", "success")
        except BookingError as e:
            db.rollback()
            flash(str(e), "danger")

    except Exception:
        db.rollback()
        flash("Error cancelling booking.", "danger")
    finally:
        db.close()

    return redirect(url_for("staff.trek_detail", trek_id=trek_id))


# ─────────────────────────────────────────────
# Participants — All Assigned Treks
# ─────────────────────────────────────────────

@staff_bp.route("/participants")
@require_approved_staff()
def participants():
    """Show participants across all assigned treks."""
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

        if not assigned_ids:
            return render_template(
                "staff/participants.html",
                user=user, bookings=[], trek=None, q=q, status_filter=status_filter,
            )

        query = (
            db.query(Booking)
            .options(joinedload(Booking.user), joinedload(Booking.trek), joinedload(Booking.attendance))
            .filter(Booking.trek_id.in_(assigned_ids))
        )

        # Status filter
        if status_filter:
            try:
                bs = BookingStatus(status_filter)
                query = query.filter(Booking.booking_status == bs)
            except ValueError:
                pass

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
            user=user, bookings=bookings, trek=None, q=q, status_filter=status_filter,
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
    """Show participants for a specific assigned trek."""
    user = get_current_user()
    db = SessionLocal()
    try:
        trek = db.query(Trek).filter(Trek.id == trek_id).first()
        if not trek:
            flash("Trek not found.", "danger")
            return redirect(url_for("staff.my_treks"))

        q = request.args.get("q", "").strip()
        status_filter = request.args.get("status", "").strip()

        query = (
            db.query(Booking)
            .options(joinedload(Booking.user), joinedload(Booking.trek), joinedload(Booking.attendance))
            .filter(Booking.trek_id == trek_id)
        )

        if status_filter:
            try:
                bs = BookingStatus(status_filter)
                query = query.filter(Booking.booking_status == bs)
            except ValueError:
                pass

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
            user=user, bookings=bookings, trek=trek, q=q, status_filter=status_filter,
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Export Participants (CSV)
# ─────────────────────────────────────────────

@staff_bp.route("/treks/<int:trek_id>/export")
@require_approved_staff()
@require_assigned_staff
def export_participants(trek_id):
    """Export participant list as CSV."""
    db = SessionLocal()
    try:
        trek = db.query(Trek).filter(Trek.id == trek_id).first()
        if not trek:
            flash("Trek not found.", "danger")
            return redirect(url_for("staff.my_treks"))

        bookings = (
            db.query(Booking)
            .options(joinedload(Booking.user), joinedload(Booking.attendance))
            .filter(Booking.trek_id == trek_id)
            .order_by(Booking.booking_date.asc())
            .all()
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Booking ID", "Name", "Email", "Phone",
            "Participants", "Status", "Booking Date",
            "Attendance",
        ])

        for b in bookings:
            att = b.attendance.status.value if b.attendance else "Not Marked"
            writer.writerow([
                b.id,
                b.user.name if b.user else "N/A",
                b.user.email if b.user else "N/A",
                b.user.phone if b.user and b.user.phone else "N/A",
                b.participants,
                b.booking_status.value,
                b.booking_date.strftime("%Y-%m-%d %H:%M"),
                att,
            ])

        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = f"attachment; filename=participants_trek_{trek_id}.csv"
        response.headers["Content-type"] = "text/csv"
        return response
    finally:
        db.close()


# ─────────────────────────────────────────────
# Trek History (completed assigned treks)
# ─────────────────────────────────────────────

@staff_bp.route("/history")
@require_approved_staff()
def trek_history():
    """View completed assigned treks."""
    user = get_current_user()
    db = SessionLocal()
    try:
        profile = _get_staff_profile(db, user)
        if not profile:
            flash("Staff profile not found.", "danger")
            return redirect(url_for("auth.login"))

        assigned_ids = _get_assigned_trek_ids(db, profile.id)
        treks = []
        if assigned_ids:
            treks = (
                db.query(Trek)
                .filter(
                    Trek.id.in_(assigned_ids),
                    Trek.status == TrekStatus.COMPLETED,
                )
                .order_by(Trek.end_date.desc())
                .all()
            )

            for trek in treks:
                trek.participant_count = (
                    db.query(func.coalesce(func.sum(Booking.participants), 0))
                    .filter(
                        Booking.trek_id == trek.id,
                        Booking.booking_status.in_([BookingStatus.BOOKED, BookingStatus.COMPLETED])
                    )
                    .scalar()
                ) or 0

        return render_template(
            "staff/trek_history.html",
            user=user, treks=treks,
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
    """Update staff profile — only allowed fields."""
    user = get_current_user()
    db = SessionLocal()
    try:
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

        phone = request.form.get("phone", "").strip()
        emergency_contact = request.form.get("emergency_contact", "").strip()
        bio = request.form.get("bio", "").strip()
        specialization = request.form.get("specialization", "").strip()
        certification = request.form.get("certification", "").strip()
        experience_years = request.form.get("experience_years", "0").strip()

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
