"""
Trekker/User routes: dashboard, browsing treks, booking, history, profile.

Every route is protected by @require_role(UserRole.TREKKER) ensuring that
Admin and Trek Staff cannot access these views.
"""

import sys
from decimal import Decimal
from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, session
)
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.models import (
    User, UserRole, Trek, TrekStatus, Difficulty,
    Booking, BookingStatus, PaymentStatus, TrekStaffAssignment, StaffProfile
)
from app.auth import require_role, get_current_user
from app.services.booking_service import create_booking, confirm_booking, BookingError
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
        # Calculate statistics
        stats = {
            "available_treks": 0,
            "booked_treks": 0,
            "completed_treks": 0,
            "pending_bookings": 0,
        }

        # Available open treks
        stats["available_treks"] = (
            db.query(func.count(Trek.id))
            .filter(
                Trek.status == TrekStatus.UPCOMING,
                Trek.available_slots > 0
            )
            .scalar()
        ) or 0

        # Bookings counts
        stats["booked_treks"] = (
            db.query(func.count(Booking.id))
            .filter(
                Booking.user_id == user.id,
                Booking.booking_status == BookingStatus.CONFIRMED
            )
            .scalar()
        ) or 0

        stats["completed_treks"] = (
            db.query(func.count(Booking.id))
            .filter(
                Booking.user_id == user.id,
                Booking.booking_status == BookingStatus.COMPLETED
            )
            .scalar()
        ) or 0

        stats["pending_bookings"] = (
            db.query(func.count(Booking.id))
            .filter(
                Booking.user_id == user.id,
                Booking.booking_status == BookingStatus.PENDING
            )
            .scalar()
        ) or 0

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
            recent_bookings=recent_bookings
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
        # Base query: only OPEN ('UPCOMING') treks with available slots
        query = db.query(Trek).filter(
            Trek.status == TrekStatus.UPCOMING,
            Trek.available_slots > 0
        )

        # Filters
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

        # Get unique locations for the filter dropdown
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

        # Check if user already booked this trek (active booking)
        existing_booking = (
            db.query(Booking)
            .filter(
                Booking.user_id == user.id,
                Booking.trek_id == trek_id,
                Booking.booking_status.in_([
                    BookingStatus.PENDING, 
                    BookingStatus.CONFIRMED, 
                    BookingStatus.COMPLETED
                ])
            )
            .first()
        )

        # Logic for allowing booking
        can_book = True
        booking_reason = ""
        
        if existing_booking:
            can_book = False
            # We already have a specific alert message in the template for this
        elif trek.status != TrekStatus.UPCOMING:
            can_book = False
            booking_reason = f"Registration closed. Trek is currently {trek.status.value}."
        elif trek.available_slots <= 0:
            can_book = False
            booking_reason = "No slots available for this trek."

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
    """
    Handle booking submission.
    
    Verifies:
    - User is Trekker (handled by decorator)
    - Trek exists, is OPEN, has positive slots
    - User hasn't already booked the trek
    - Creates booking and immediately confirms it (decrementing slots)
      inside a transaction.
    """
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
        # Pre-check for duplicate active bookings
        existing = db.query(Booking).filter(
            Booking.user_id == user.id,
            Booking.trek_id == trek_id,
            Booking.booking_status.in_([
                BookingStatus.PENDING, 
                BookingStatus.CONFIRMED, 
                BookingStatus.COMPLETED
            ])
        ).first()

        if existing:
            flash("You already have an active booking for this trek.", "danger")
            return redirect(url_for("user.trek_detail", trek_id=trek_id))

        # Booking process using the booking_service (transactional)
        try:
            # 1. Create PENDING booking
            new_booking = create_booking(
                db=db,
                user_id=user.id,
                trek_id=trek_id,
                participants=participants
            )
            
            # 2. Automatically Confirm the booking (deducts slots)
            confirm_booking(db=db, booking_id=new_booking.id)
            
            db.commit()
            flash(f"Booking confirmed! You have successfully booked {participants} slot(s).", "success")
            return redirect(url_for("user.my_bookings"))
            
        except BookingError as e:
            db.rollback()
            flash(str(e), "danger")
            return redirect(url_for("user.trek_detail", trek_id=trek_id))
            
    except SQLAlchemyError as e:
        db.rollback()
        flash("A database error occurred during booking.", "danger")
        return redirect(url_for("user.trek_detail", trek_id=trek_id))
    finally:
        db.close()


# ─────────────────────────────────────────────
# My Bookings
# ─────────────────────────────────────────────

@user_bp.route("/bookings")
@require_role(UserRole.TREKKER)
def my_bookings():
    """List current active and recent bookings."""
    user = get_current_user()
    db = SessionLocal()
    try:
        bookings = (
            db.query(Booking)
            .options(joinedload(Booking.trek))
            .filter(
                Booking.user_id == user.id,
                # Show active bookings and recently cancelled ones
                Booking.booking_status != BookingStatus.COMPLETED
            )
            .order_by(Booking.booking_date.desc())
            .all()
        )

        return render_template(
            "user/bookings.html",
            user=user,
            bookings=bookings
        )
    finally:
        db.close()


# ─────────────────────────────────────────────
# Cancel Booking
# ─────────────────────────────────────────────

@user_bp.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@require_role(UserRole.TREKKER)
def cancel_booking_route(booking_id):
    """
    Cancel a booking and restore slots using booking_service.
    Uses 'route' in the function name to avoid shadowing the service method.
    """
    user = get_current_user()
    db = SessionLocal()
    
    from app.services.booking_service import cancel_booking
    
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
            cancel_booking(db=db, booking_id=booking_id)
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
# Trekking History
# ─────────────────────────────────────────────

@user_bp.route("/history")
@require_role(UserRole.TREKKER)
def history():
    """Display completed or past treks."""
    user = get_current_user()
    db = SessionLocal()
    try:
        # History includes completed bookings, or active bookings 
        # on treks that have finished (Completed/Cancelled).
        history_bookings = (
            db.query(Booking)
            .options(joinedload(Booking.trek))
            .join(Trek)
            .filter(
                Booking.user_id == user.id,
                or_(
                    Booking.booking_status == BookingStatus.COMPLETED,
                    Trek.status.in_([TrekStatus.COMPLETED, TrekStatus.CANCELLED])
                )
            )
            .order_by(Booking.booking_date.desc())
            .all()
        )

        return render_template(
            "user/history.html",
            user=user,
            history=history_bookings
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

        # Role & Email update preventions are handled by simply not capturing them from form
        
        if not name:
            flash("Name cannot be empty.", "danger")
            return redirect(url_for("user.profile"))
            
        user.name = name
        user.phone = phone if phone else None

        # Password Update Logic
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
    except Exception as e:
        db.rollback()
        flash("Error updating profile.", "danger")
    finally:
        db.close()

    return redirect(url_for("user.profile"))
