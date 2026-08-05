"""
Trekker/User routes: dashboard, browsing treks, booking, history, profile,
booking details, feedback, and certificate download.

Every route is protected by @require_role(UserRole.TREKKER) ensuring that
Admin and Trek Staff cannot access these views.
"""

from datetime import datetime, timezone
from decimal import Decimal

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, session, make_response
)
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.models import (
    User, UserRole, Trek, TrekStatus, Difficulty,
    Booking, BookingStatus, TrekStaffAssignment, StaffProfile,
    Feedback, Certificate, Attendance,
)
from app.auth import require_role, get_current_user
from app.services.booking_service import create_booking, cancel_booking, BookingError
from app.security import hash_password, verify_password

user_bp = Blueprint("user", __name__, url_prefix="/user")


# ─────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────

@user_bp.route("/dashboard")
@require_role(UserRole.TREKKER)
def dashboard():
    """Trekker dashboard with dynamic statistics."""
    user = get_current_user()
    db = SessionLocal()
    try:
        stats = {
            "available_treks": 0,
            "booked_treks": 0,
            "completed_treks": 0,
            "cancelled_treks": 0,
        }

        # Available open treks
        stats["available_treks"] = (
            db.query(func.count(Trek.id))
            .filter(
                Trek.status == TrekStatus.OPEN,
                Trek.available_slots > 0
            )
            .scalar()
        ) or 0

        # Active bookings
        stats["booked_treks"] = (
            db.query(func.count(Booking.id))
            .filter(
                Booking.user_id == user.id,
                Booking.booking_status == BookingStatus.BOOKED
            )
            .scalar()
        ) or 0

        # Completed
        stats["completed_treks"] = (
            db.query(func.count(Booking.id))
            .filter(
                Booking.user_id == user.id,
                Booking.booking_status == BookingStatus.COMPLETED
            )
            .scalar()
        ) or 0

        # Cancelled
        stats["cancelled_treks"] = (
            db.query(func.count(Booking.id))
            .filter(
                Booking.user_id == user.id,
                Booking.booking_status == BookingStatus.CANCELLED
            )
            .scalar()
        ) or 0

        # Upcoming treks (booked treks that haven't started)
        upcoming_bookings = (
            db.query(Booking)
            .options(joinedload(Booking.trek))
            .join(Trek)
            .filter(
                Booking.user_id == user.id,
                Booking.booking_status == BookingStatus.BOOKED,
                Trek.start_date > datetime.now(timezone.utc),
            )
            .order_by(Trek.start_date.asc())
            .limit(5)
            .all()
        )

        # Recent bookings (up to 5)
        recent_bookings = (
            db.query(Booking)
            .options(joinedload(Booking.trek))
            .filter(Booking.user_id == user.id)
            .order_by(Booking.booking_date.desc())
            .limit(5)
            .all()
        )

        return render_template(
            "user/dashboard.html",
            user=user,
            stats=stats,
            recent_bookings=recent_bookings,
            upcoming_bookings=upcoming_bookings,
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Available Treks (Search & Filter)
# ─────────────────────────────────────────────

@user_bp.route("/treks")
@require_role(UserRole.TREKKER)
def available_treks():
    """Browse treks available for booking."""
    user = get_current_user()

    q = request.args.get("q", "").strip()
    difficulty_filter = request.args.get("difficulty", "").strip()
    location_filter = request.args.get("location", "").strip()
    price_min = request.args.get("price_min", "").strip()
    price_max = request.args.get("price_max", "").strip()

    db = SessionLocal()
    try:
        # Base query: only OPEN treks with available slots
        query = db.query(Trek).filter(
            Trek.status == TrekStatus.OPEN,
            Trek.available_slots > 0
        )

        if q:
            query = query.filter(
                or_(
                    Trek.trek_name.ilike(f"%{q}%"),
                    Trek.location.ilike(f"%{q}%")
                )
            )

        if difficulty_filter:
            try:
                diff_enum = Difficulty(difficulty_filter)
                query = query.filter(Trek.difficulty == diff_enum)
            except ValueError:
                pass

        if location_filter:
            query = query.filter(Trek.location == location_filter)

        if price_min:
            try:
                min_val = float(price_min)
                query = query.filter(Trek.price >= Decimal(str(min_val)))
            except ValueError:
                pass

        if price_max:
            try:
                max_val = float(price_max)
                query = query.filter(Trek.price <= Decimal(str(max_val)))
            except ValueError:
                pass

        treks = query.order_by(Trek.start_date.asc()).all()

        locations = [loc[0] for loc in db.query(Trek.location).distinct().all()]

        return render_template(
            "user/treks.html",
            user=user,
            treks=treks,
            difficulties=Difficulty,
            locations=locations,
            q=q,
            difficulty_filter=difficulty_filter,
            location_filter=location_filter,
            price_min=price_min,
            price_max=price_max
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Trek Detail & Booking UI
# ─────────────────────────────────────────────

@user_bp.route("/treks/<int:trek_id>")
@require_role(UserRole.TREKKER)
def trek_detail(trek_id):
    """View trek details and booking panel."""
    user = get_current_user()
    db = SessionLocal()
    try:
        trek = (
            db.query(Trek)
            .options(
                joinedload(Trek.staff_assignments)
                .joinedload(TrekStaffAssignment.staff)
                .joinedload(StaffProfile.user)
            )
            .filter(Trek.id == trek_id)
            .first()
        )

        if not trek:
            flash("Trek not found.", "danger")
            return redirect(url_for("user.available_treks"))

        existing_booking = (
            db.query(Booking)
            .filter(
                Booking.user_id == user.id,
                Booking.trek_id == trek_id,
                Booking.booking_status.in_([
                    BookingStatus.BOOKED,
                    BookingStatus.COMPLETED
                ])
            )
            .first()
        )

        can_book = True
        booking_reason = ""

        if existing_booking:
            can_book = False
        elif trek.status != TrekStatus.OPEN:
            can_book = False
            booking_reason = f"Registration closed. Trek is currently {trek.status.value}."
        elif trek.available_slots <= 0:
            can_book = False
            booking_reason = "No slots available for this trek."
        elif trek.booking_deadline and datetime.now(timezone.utc) > trek.booking_deadline:
            can_book = False
            booking_reason = "Booking deadline has passed."

        return render_template(
            "user/trek_detail.html",
            user=user,
            trek=trek,
            existing_booking=existing_booking,
            can_book=can_book,
            booking_reason=booking_reason
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Booking Process (Transaction)
# ─────────────────────────────────────────────

@user_bp.route("/treks/<int:trek_id>/book", methods=["POST"])
@require_role(UserRole.TREKKER)
def book_trek(trek_id):
    """Handle booking submission with full validation."""
    user = get_current_user()

    try:
        participants = int(request.form.get("participants", "1"))
    except ValueError:
        flash("Invalid number of participants.", "danger")
        return redirect(url_for("user.trek_detail", trek_id=trek_id))

    if participants < 1:
        flash("You must book for at least 1 participant.", "danger")
        return redirect(url_for("user.trek_detail", trek_id=trek_id))

    db = SessionLocal()
    try:
        try:
            new_booking = create_booking(
                db=db,
                user_id=user.id,
                trek_id=trek_id,
                participants=participants,
                performed_by=user.id,
            )
            db.commit()
            flash(f"Booking confirmed! You have successfully booked {participants} slot(s).", "success")
            return redirect(url_for("user.my_bookings"))

        except BookingError as e:
            db.rollback()
            flash(str(e), "danger")
            return redirect(url_for("user.trek_detail", trek_id=trek_id))

    except SQLAlchemyError:
        db.rollback()
        flash("A database error occurred during booking.", "danger")
        return redirect(url_for("user.trek_detail", trek_id=trek_id))
    finally:
        db.close()


# ─────────────────────────────────────────────
# My Bookings (with tab filters)
# ─────────────────────────────────────────────

@user_bp.route("/bookings")
@require_role(UserRole.TREKKER)
def my_bookings():
    """List all bookings grouped by status."""
    user = get_current_user()
    status_filter = request.args.get("status", "all").strip()

    db = SessionLocal()
    try:
        query = (
            db.query(Booking)
            .options(joinedload(Booking.trek), joinedload(Booking.certificate))
            .filter(Booking.user_id == user.id)
        )

        if status_filter == "booked":
            query = query.filter(Booking.booking_status == BookingStatus.BOOKED)
        elif status_filter == "completed":
            query = query.filter(Booking.booking_status == BookingStatus.COMPLETED)
        elif status_filter == "cancelled":
            query = query.filter(Booking.booking_status == BookingStatus.CANCELLED)

        bookings = query.order_by(Booking.booking_date.desc()).all()

        return render_template(
            "user/bookings.html",
            user=user,
            bookings=bookings,
            status_filter=status_filter,
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Booking Detail
# ─────────────────────────────────────────────

@user_bp.route("/bookings/<int:booking_id>")
@require_role(UserRole.TREKKER)
def booking_detail(booking_id):
    """View detailed booking information with status timeline."""
    user = get_current_user()
    db = SessionLocal()
    try:
        booking = (
            db.query(Booking)
            .options(
                joinedload(Booking.trek)
                .joinedload(Trek.staff_assignments)
                .joinedload(TrekStaffAssignment.staff)
                .joinedload(StaffProfile.user),
                joinedload(Booking.feedback),
                joinedload(Booking.certificate),
                joinedload(Booking.attendance),
                joinedload(Booking.assigned_staff),
            )
            .filter(Booking.id == booking_id, Booking.user_id == user.id)
            .first()
        )

        if not booking:
            flash("Booking not found.", "danger")
            return redirect(url_for("user.my_bookings"))

        return render_template(
            "user/booking_detail.html",
            user=user,
            booking=booking,
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Cancel Booking
# ─────────────────────────────────────────────

@user_bp.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@require_role(UserRole.TREKKER)
def cancel_booking_route(booking_id):
    """Cancel a booking — only before trek starts."""
    user = get_current_user()
    db = SessionLocal()

    try:
        # Verify ownership
        booking = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.user_id == user.id
        ).first()

        if not booking:
            flash("Booking not found.", "danger")
            return redirect(url_for("user.my_bookings"))

        try:
            cancel_booking(
                db=db,
                booking_id=booking_id,
                performed_by=user.id,
                check_trek_started=True,
            )
            db.commit()
            flash("Booking successfully cancelled. Slots have been restored.", "success")
        except BookingError as e:
            db.rollback()
            flash(str(e), "danger")

    except SQLAlchemyError:
        db.rollback()
        flash("Database error during cancellation.", "danger")
    finally:
        db.close()

    return redirect(url_for("user.my_bookings"))


# ─────────────────────────────────────────────
# Feedback
# ─────────────────────────────────────────────

@user_bp.route("/bookings/<int:booking_id>/feedback", methods=["POST"])
@require_role(UserRole.TREKKER)
def submit_feedback(booking_id):
    """Submit feedback for a completed booking."""
    user = get_current_user()
    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.user_id == user.id,
            Booking.booking_status == BookingStatus.COMPLETED,
        ).first()

        if not booking:
            flash("You can only submit feedback for completed bookings.", "danger")
            return redirect(url_for("user.my_bookings"))

        # Check if feedback already exists
        existing = db.query(Feedback).filter(Feedback.booking_id == booking_id).first()
        if existing:
            flash("You have already submitted feedback for this booking.", "info")
            return redirect(url_for("user.booking_detail", booking_id=booking_id))

        try:
            rating = int(request.form.get("rating", "0"))
        except ValueError:
            rating = 0

        if rating < 1 or rating > 5:
            flash("Please provide a rating between 1 and 5.", "danger")
            return redirect(url_for("user.booking_detail", booking_id=booking_id))

        comment = request.form.get("comment", "").strip()

        feedback = Feedback(
            booking_id=booking_id,
            rating=rating,
            comment=comment or None,
        )
        db.add(feedback)
        db.commit()
        flash("Thank you for your feedback!", "success")

    except Exception:
        db.rollback()
        flash("Error submitting feedback.", "danger")
    finally:
        db.close()

    return redirect(url_for("user.booking_detail", booking_id=booking_id))


# ─────────────────────────────────────────────
# Certificate Download
# ─────────────────────────────────────────────

@user_bp.route("/bookings/<int:booking_id>/certificate")
@require_role(UserRole.TREKKER)
def download_certificate(booking_id):
    """Render a printable HTML certificate for a completed booking."""
    user = get_current_user()
    db = SessionLocal()
    try:
        booking = (
            db.query(Booking)
            .options(joinedload(Booking.trek), joinedload(Booking.certificate))
            .filter(
                Booking.id == booking_id,
                Booking.user_id == user.id,
                Booking.booking_status == BookingStatus.COMPLETED,
            )
            .first()
        )

        if not booking or not booking.certificate:
            flash("Certificate not available.", "danger")
            return redirect(url_for("user.my_bookings"))

        return render_template(
            "user/certificate.html",
            user=user,
            booking=booking,
            certificate=booking.certificate,
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Trekking History (with filters)
# ─────────────────────────────────────────────

@user_bp.route("/history")
@require_role(UserRole.TREKKER)
def history():
    """Display complete trekking history with filters."""
    user = get_current_user()
    status_filter = request.args.get("status", "").strip()
    difficulty_filter = request.args.get("difficulty", "").strip()
    location_filter = request.args.get("location", "").strip()

    db = SessionLocal()
    try:
        query = (
            db.query(Booking)
            .options(
                joinedload(Booking.trek),
                joinedload(Booking.feedback),
                joinedload(Booking.certificate),
            )
            .join(Trek)
            .filter(Booking.user_id == user.id)
        )

        # Status filter
        if status_filter == "completed":
            query = query.filter(Booking.booking_status == BookingStatus.COMPLETED)
        elif status_filter == "cancelled":
            query = query.filter(Booking.booking_status == BookingStatus.CANCELLED)
        elif status_filter == "booked":
            query = query.filter(Booking.booking_status == BookingStatus.BOOKED)

        # Difficulty filter
        if difficulty_filter:
            try:
                diff_enum = Difficulty(difficulty_filter)
                query = query.filter(Trek.difficulty == diff_enum)
            except ValueError:
                pass

        # Location filter
        if location_filter:
            query = query.filter(Trek.location == location_filter)

        history_bookings = query.order_by(Booking.booking_date.desc()).all()

        # Get unique locations for filtering
        locations = [loc[0] for loc in db.query(Trek.location).distinct().all()]

        return render_template(
            "user/history.html",
            user=user,
            history=history_bookings,
            difficulties=Difficulty,
            locations=locations,
            status_filter=status_filter,
            difficulty_filter=difficulty_filter,
            location_filter=location_filter,
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Profile Management
# ─────────────────────────────────────────────

@user_bp.route("/profile")
@require_role(UserRole.TREKKER)
def profile():
    """View trekker profile and change details."""
    user = get_current_user()
    db = SessionLocal()
    try:
        total_bookings = (
            db.query(func.count(Booking.id))
            .filter(Booking.user_id == user.id)
            .scalar()
        ) or 0

        return render_template(
            "user/profile.html",
            user=user,
            total_bookings=total_bookings
        )
    finally:
        db.close()


@user_bp.route("/profile/update", methods=["POST"])
@require_role(UserRole.TREKKER)
def update_profile():
    """Update name, phone, and optional password."""
    user_data = get_current_user()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_data.id).first()
        if not user:
            flash("User not found.", "danger")
            return redirect(url_for("auth.login"))

        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()

        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name:
            flash("Name cannot be empty.", "danger")
            return redirect(url_for("user.profile"))

        user.name = name
        user.phone = phone if phone else None

        if current_password or new_password or confirm_password:
            if not current_password:
                flash("Please enter your current password to set a new one.", "danger")
                return redirect(url_for("user.profile"))

            if not verify_password(current_password, user.password_hash):
                flash("Current password is incorrect.", "danger")
                return redirect(url_for("user.profile"))

            if not new_password:
                flash("New password cannot be empty.", "danger")
                return redirect(url_for("user.profile"))

            if len(new_password) < 6:
                flash("New password must be at least 6 characters.", "danger")
                return redirect(url_for("user.profile"))

            if new_password != confirm_password:
                flash("New passwords do not match.", "danger")
                return redirect(url_for("user.profile"))

            user.password_hash = hash_password(new_password)

        db.commit()
        flash("Profile updated successfully.", "success")
    except Exception:
        db.rollback()
        flash("Error updating profile.", "danger")
    finally:
        db.close()

    return redirect(url_for("user.profile"))
