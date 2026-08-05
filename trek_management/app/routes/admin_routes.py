"""
Admin routes: Full dashboard with Trek CRUD, Staff management,
User management, Booking management, Staff Assignment, Search,
Trek History, Booking History, and Audit Log.

Every route is protected by @require_role(UserRole.ADMIN).
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request,
)
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import (
    User, UserRole, StaffProfile, ApprovalStatus,
    Trek, TrekStatus, Difficulty,
    Booking, BookingStatus,
    TrekStaffAssignment, AuditLog, Feedback, Certificate,
)
from app.auth import require_role, get_current_user
from app.security import hash_password
from app.services.trek_service import advance_trek_status, get_allowed_transitions, TrekStatusError
from app.services.booking_service import cancel_booking, complete_booking, BookingError
from app.services.audit_service import log_action

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ─────────────────────────────────────────────
# Dashboard Home
# ─────────────────────────────────────────────

@admin_bp.route("/dashboard")
@require_role(UserRole.ADMIN)
def dashboard():
    user = get_current_user()
    db = SessionLocal()
    try:
        stats = {
            "total_treks": db.query(func.count(Trek.id)).scalar() or 0,
            "total_users": db.query(func.count(User.id)).filter(User.role == UserRole.TREKKER).scalar() or 0,
            "total_staff": db.query(func.count(User.id)).filter(User.role == UserRole.TREK_STAFF).scalar() or 0,
            "total_bookings": db.query(func.count(Booking.id)).scalar() or 0,
            "pending_staff": db.query(func.count(StaffProfile.id)).filter(
                StaffProfile.approval_status == ApprovalStatus.PENDING).scalar() or 0,
            "open_treks": db.query(func.count(Trek.id)).filter(Trek.status == TrekStatus.OPEN).scalar() or 0,
            "closed_treks": db.query(func.count(Trek.id)).filter(Trek.status == TrekStatus.CLOSED).scalar() or 0,
            "completed_treks": db.query(func.count(Trek.id)).filter(Trek.status == TrekStatus.COMPLETED).scalar() or 0,
            "booked_bookings": db.query(func.count(Booking.id)).filter(
                Booking.booking_status == BookingStatus.BOOKED).scalar() or 0,
            "completed_bookings": db.query(func.count(Booking.id)).filter(
                Booking.booking_status == BookingStatus.COMPLETED).scalar() or 0,
            "cancelled_bookings": db.query(func.count(Booking.id)).filter(
                Booking.booking_status == BookingStatus.CANCELLED).scalar() or 0,
            "total_revenue": db.query(func.coalesce(func.sum(Booking.total_amount), 0)).filter(
                Booking.booking_status.in_([BookingStatus.BOOKED, BookingStatus.COMPLETED])).scalar() or 0,
        }

        recent_bookings = (
            db.query(Booking)
            .options(joinedload(Booking.user), joinedload(Booking.trek))
            .order_by(Booking.booking_date.desc())
            .limit(5).all()
        )

        recent_activities = (
            db.query(AuditLog)
            .options(joinedload(AuditLog.performer))
            .order_by(AuditLog.performed_at.desc())
            .limit(10).all()
        )

        return render_template("admin/dashboard.html",
                               user=user, stats=stats,
                               recent_bookings=recent_bookings,
                               recent_activities=recent_activities)
    finally:
        db.close()


# ─────────────────────────────────────────────
# Trek Management
# ─────────────────────────────────────────────

@admin_bp.route("/treks")
@require_role(UserRole.ADMIN)
def treks():
    user = get_current_user()
    db = SessionLocal()
    try:
        q = request.args.get("q", "").strip()
        status_filter = request.args.get("status", "").strip()
        query = db.query(Trek).options(joinedload(Trek.staff_assignments))

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

        trek_list = query.order_by(Trek.created_at.desc()).all()
        return render_template("admin/treks.html",
                               user=user, treks=trek_list, q=q,
                               status_filter=status_filter, trek_statuses=TrekStatus)
    finally:
        db.close()


@admin_bp.route("/treks/create", methods=["GET", "POST"])
@require_role(UserRole.ADMIN)
def trek_create():
    user = get_current_user()
    if request.method == "POST":
        return _trek_save(None, user)
    return render_template("admin/trek_form.html", user=user,
                           trek=None, difficulties=Difficulty,
                           statuses=TrekStatus, action="Create")


@admin_bp.route("/treks/<int:trek_id>/edit", methods=["GET", "POST"])
@require_role(UserRole.ADMIN)
def trek_edit(trek_id):
    user = get_current_user()
    if request.method == "POST":
        return _trek_save(trek_id, user)
    db = SessionLocal()
    try:
        trek = db.query(Trek).filter(Trek.id == trek_id).first()
        if not trek:
            flash("Trek not found.", "danger")
            return redirect(url_for("admin.treks"))
        return render_template("admin/trek_form.html", user=user,
                               trek=trek, difficulties=Difficulty,
                               statuses=TrekStatus, action="Edit")
    finally:
        db.close()


@admin_bp.route("/treks/<int:trek_id>")
@require_role(UserRole.ADMIN)
def trek_view(trek_id):
    user = get_current_user()
    db = SessionLocal()
    try:
        trek = (db.query(Trek)
                .options(joinedload(Trek.staff_assignments)
                         .joinedload(TrekStaffAssignment.staff)
                         .joinedload(StaffProfile.user),
                         joinedload(Trek.bookings)
                         .joinedload(Booking.user))
                .filter(Trek.id == trek_id).first())
        if not trek:
            flash("Trek not found.", "danger")
            return redirect(url_for("admin.treks"))

        allowed_transitions = get_allowed_transitions(trek.status)

        audit_trail = (
            db.query(AuditLog)
            .options(joinedload(AuditLog.performer))
            .filter(AuditLog.entity_type == "trek", AuditLog.entity_id == trek_id)
            .order_by(AuditLog.performed_at.desc())
            .all()
        )

        return render_template("admin/trek_view.html", user=user, trek=trek,
                               allowed_transitions=allowed_transitions,
                               audit_trail=audit_trail)
    finally:
        db.close()


@admin_bp.route("/treks/<int:trek_id>/update-status", methods=["POST"])
@require_role(UserRole.ADMIN)
def trek_update_status(trek_id):
    """Admin trek status update using state machine."""
    user = get_current_user()
    db = SessionLocal()
    try:
        new_status_value = request.form.get("status", "")
        try:
            new_status = TrekStatus(new_status_value)
        except (ValueError, KeyError):
            flash("Invalid trek status.", "danger")
            return redirect(url_for("admin.trek_view", trek_id=trek_id))

        try:
            advance_trek_status(db=db, trek_id=trek_id, new_status=new_status, performed_by=user.id)
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
    return redirect(url_for("admin.trek_view", trek_id=trek_id))


@admin_bp.route("/treks/<int:trek_id>/delete", methods=["POST"])
@require_role(UserRole.ADMIN)
def trek_delete(trek_id):
    db = SessionLocal()
    try:
        trek = db.query(Trek).filter(Trek.id == trek_id).first()
        if not trek:
            flash("Trek not found.", "danger")
            return redirect(url_for("admin.treks"))

        # Only delete if NO bookings exist at all
        booking_count = db.query(Booking).filter(Booking.trek_id == trek_id).count()
        if booking_count > 0:
            flash(f"Cannot delete trek — {booking_count} booking(s) exist.", "warning")
            return redirect(url_for("admin.trek_view", trek_id=trek_id))

        db.delete(trek)
        db.commit()
        flash("Trek deleted successfully.", "success")
    except Exception:
        db.rollback()
        flash("Error deleting trek.", "danger")
    finally:
        db.close()
    return redirect(url_for("admin.treks"))


def _trek_save(trek_id, current_user=None):
    """Shared create/edit logic for treks."""
    errors = []
    f = request.form
    trek_name = f.get("trek_name", "").strip()
    description = f.get("description", "").strip()
    location = f.get("location", "").strip()
    difficulty = f.get("difficulty", "")
    duration_days = f.get("duration_days", "")
    total_slots = f.get("total_slots", "")
    available_slots = f.get("available_slots", "")
    price = f.get("price", "")
    start_date = f.get("start_date", "")
    end_date = f.get("end_date", "")
    status = f.get("status", "")
    booking_deadline = f.get("booking_deadline", "")

    if not trek_name:
        errors.append("Trek name is required.")
    if not location:
        errors.append("Location is required.")

    try:
        difficulty_enum = Difficulty(difficulty)
    except (ValueError, KeyError):
        errors.append("Invalid difficulty level.")
        difficulty_enum = Difficulty.MODERATE

    try:
        status_enum = TrekStatus(status)
    except (ValueError, KeyError):
        errors.append("Invalid trek status.")
        status_enum = TrekStatus.PENDING

    try:
        dur = int(duration_days)
        if dur <= 0:
            errors.append("Duration must be > 0.")
    except (ValueError, TypeError):
        errors.append("Duration must be a number.")
        dur = 1

    try:
        ts = int(total_slots)
        if ts <= 0:
            errors.append("Total slots must be > 0.")
    except (ValueError, TypeError):
        errors.append("Total slots must be a number.")
        ts = 1

    try:
        avs = int(available_slots)
        if avs < 0:
            errors.append("Available slots cannot be negative.")
    except (ValueError, TypeError):
        errors.append("Available slots must be a number.")
        avs = 0

    if avs > ts:
        errors.append("Available slots cannot exceed total slots.")

    try:
        pr = Decimal(price)
        if pr < 0:
            errors.append("Price cannot be negative.")
    except (InvalidOperation, ValueError, TypeError):
        errors.append("Price must be a valid number.")
        pr = Decimal("0")

    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        errors.append("Start date is required (YYYY-MM-DD).")
        sd = datetime.now(timezone.utc)

    try:
        ed = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        errors.append("End date is required (YYYY-MM-DD).")
        ed = datetime.now(timezone.utc)

    if ed < sd:
        errors.append("End date must be on or after start date.")

    bd = None
    if booking_deadline:
        try:
            bd = datetime.strptime(booking_deadline, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            errors.append("Booking deadline must be a valid date (YYYY-MM-DD).")

    if errors:
        for e in errors:
            flash(e, "danger")
        endpoint = "admin.trek_edit" if trek_id else "admin.trek_create"
        if trek_id:
            return redirect(url_for(endpoint, trek_id=trek_id))
        return redirect(url_for(endpoint))

    db = SessionLocal()
    try:
        if trek_id:
            trek = db.query(Trek).filter(Trek.id == trek_id).first()
            if not trek:
                flash("Trek not found.", "danger")
                return redirect(url_for("admin.treks"))
        else:
            trek = Trek()
            trek.created_by = current_user.id if current_user else None
            db.add(trek)

        trek.trek_name = trek_name
        trek.description = description or None
        trek.location = location
        trek.difficulty = difficulty_enum
        trek.duration_days = dur
        trek.total_slots = ts
        trek.available_slots = avs
        trek.price = pr
        trek.start_date = sd
        trek.end_date = ed
        trek.status = status_enum
        trek.booking_deadline = bd

        db.flush()

        # Audit log
        if not trek_id:
            log_action(
                db=db,
                entity_type="trek",
                entity_id=trek.id,
                action="created",
                new_value=status_enum.value,
                performed_by=current_user.id if current_user else None,
                details=f"Trek '{trek_name}' created with status {status_enum.value}",
            )

        db.commit()
        flash(f"Trek {'updated' if trek_id else 'created'} successfully.", "success")
        return redirect(url_for("admin.treks"))
    except Exception:
        db.rollback()
        flash("Database error saving trek.", "danger")
        return redirect(url_for("admin.treks"))
    finally:
        db.close()


# ─────────────────────────────────────────────
# Staff Management
# ─────────────────────────────────────────────

@admin_bp.route("/staff")
@require_role(UserRole.ADMIN)
def staff_list():
    user = get_current_user()
    db = SessionLocal()
    try:
        q = request.args.get("q", "").strip()
        query = (db.query(User)
                 .options(joinedload(User.staff_profile)
                          .joinedload(StaffProfile.trek_assignments))
                 .filter(User.role == UserRole.TREK_STAFF))
        if q:
            query = query.filter(or_(
                User.name.ilike(f"%{q}%"),
                User.email.ilike(f"%{q}%"),
            ))
        staff = query.order_by(User.created_at.desc()).all()
        return render_template("admin/staff.html", user=user, staff=staff, q=q)
    finally:
        db.close()


@admin_bp.route("/staff/<int:user_id>")
@require_role(UserRole.ADMIN)
def staff_view(user_id):
    user = get_current_user()
    db = SessionLocal()
    try:
        staff_user = (db.query(User)
                      .options(joinedload(User.staff_profile)
                               .joinedload(StaffProfile.trek_assignments)
                               .joinedload(TrekStaffAssignment.trek))
                      .filter(User.id == user_id, User.role == UserRole.TREK_STAFF)
                      .first())
        if not staff_user:
            flash("Staff member not found.", "danger")
            return redirect(url_for("admin.staff_list"))
        return render_template("admin/staff_view.html", user=user, staff_user=staff_user)
    finally:
        db.close()


@admin_bp.route("/staff/create", methods=["GET", "POST"])
@require_role(UserRole.ADMIN)
def staff_create():
    user = get_current_user()
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        email = f.get("email", "").strip().lower()
        phone = f.get("phone", "").strip()
        password = f.get("password", "")
        experience_years = f.get("experience_years", "0")
        specialization = f.get("specialization", "").strip()
        certification = f.get("certification", "").strip()
        bio = f.get("bio", "").strip()

        errors = []
        if not name:
            errors.append("Name is required.")
        if not email:
            errors.append("Email is required.")
        if not password or len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        try:
            exp = int(experience_years)
        except ValueError:
            errors.append("Experience must be a number.")
            exp = 0

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("admin/staff_form.html", user=user)

        db = SessionLocal()
        try:
            if db.query(User).filter(User.email == email).first():
                flash("Email already exists.", "danger")
                return render_template("admin/staff_form.html", user=user)

            new_user = User(
                name=name, email=email,
                phone=phone or None,
                password_hash=hash_password(password),
                role=UserRole.TREK_STAFF,
                is_active=True,
            )
            db.add(new_user)
            db.flush()
            profile = StaffProfile(
                user_id=new_user.id,
                experience_years=exp,
                specialization=specialization or None,
                certification=certification or None,
                bio=bio or None,
                approval_status=ApprovalStatus.APPROVED,
            )
            db.add(profile)
            db.commit()
            flash(f"Staff member '{name}' created and auto-approved.", "success")
            return redirect(url_for("admin.staff_list"))
        except Exception:
            db.rollback()
            flash("Error creating staff.", "danger")
            return render_template("admin/staff_form.html", user=user)
        finally:
            db.close()

    return render_template("admin/staff_form.html", user=user)


@admin_bp.route("/staff/<int:user_id>/approve", methods=["POST"])
@require_role(UserRole.ADMIN)
def staff_approve(user_id):
    db = SessionLocal()
    try:
        profile = db.query(StaffProfile).filter(StaffProfile.user_id == user_id).first()
        if profile:
            profile.approval_status = ApprovalStatus.APPROVED
            db.commit()
            flash("Staff approved.", "success")
        else:
            flash("Staff profile not found.", "danger")
    except Exception:
        db.rollback()
        flash("Error approving staff.", "danger")
    finally:
        db.close()
    return redirect(request.referrer or url_for("admin.staff_list"))


@admin_bp.route("/staff/<int:user_id>/reject", methods=["POST"])
@require_role(UserRole.ADMIN)
def staff_reject(user_id):
    db = SessionLocal()
    try:
        profile = db.query(StaffProfile).filter(StaffProfile.user_id == user_id).first()
        if profile:
            profile.approval_status = ApprovalStatus.REJECTED
            db.commit()
            flash("Staff rejected.", "warning")
        else:
            flash("Staff profile not found.", "danger")
    except Exception:
        db.rollback()
        flash("Error rejecting staff.", "danger")
    finally:
        db.close()
    return redirect(request.referrer or url_for("admin.staff_list"))


@admin_bp.route("/staff/<int:user_id>/deactivate", methods=["POST"])
@require_role(UserRole.ADMIN)
def staff_deactivate(user_id):
    db = SessionLocal()
    try:
        su = db.query(User).filter(User.id == user_id).first()
        if su:
            su.is_active = False
            db.commit()
            flash(f"Staff '{su.name}' deactivated.", "warning")
        else:
            flash("User not found.", "danger")
    except Exception:
        db.rollback()
        flash("Error.", "danger")
    finally:
        db.close()
    return redirect(request.referrer or url_for("admin.staff_list"))


@admin_bp.route("/staff/<int:user_id>/activate", methods=["POST"])
@require_role(UserRole.ADMIN)
def staff_activate(user_id):
    db = SessionLocal()
    try:
        su = db.query(User).filter(User.id == user_id).first()
        if su:
            su.is_active = True
            db.commit()
            flash(f"Staff '{su.name}' activated.", "success")
        else:
            flash("User not found.", "danger")
    except Exception:
        db.rollback()
        flash("Error.", "danger")
    finally:
        db.close()
    return redirect(request.referrer or url_for("admin.staff_list"))


@admin_bp.route("/staff/<int:user_id>/delete", methods=["POST"])
@require_role(UserRole.ADMIN)
def staff_delete(user_id):
    db = SessionLocal()
    try:
        su = db.query(User).filter(User.id == user_id, User.role == UserRole.TREK_STAFF).first()
        if not su:
            flash("Staff not found.", "danger")
            return redirect(url_for("admin.staff_list"))
        profile = db.query(StaffProfile).filter(StaffProfile.user_id == user_id).first()
        if profile:
            future = (db.query(TrekStaffAssignment)
                      .join(Trek)
                      .filter(TrekStaffAssignment.staff_id == profile.id,
                              Trek.status.in_([TrekStatus.OPEN, TrekStatus.APPROVED, TrekStatus.PENDING]))
                      .count())
            if future > 0:
                flash(f"Cannot delete — staff is assigned to {future} active trek(s). "
                      "Remove assignments first or deactivate instead.", "warning")
                return redirect(url_for("admin.staff_view", user_id=user_id))
        db.delete(su)
        db.commit()
        flash("Staff member deleted.", "success")
    except Exception:
        db.rollback()
        flash("Error deleting staff.", "danger")
    finally:
        db.close()
    return redirect(url_for("admin.staff_list"))


# ─────────────────────────────────────────────
# User Management
# ─────────────────────────────────────────────

@admin_bp.route("/users")
@require_role(UserRole.ADMIN)
def users():
    user = get_current_user()
    db = SessionLocal()
    try:
        q = request.args.get("q", "").strip()
        query = (db.query(User)
                 .options(joinedload(User.bookings))
                 .filter(User.role == UserRole.TREKKER))
        if q:
            query = query.filter(or_(
                User.name.ilike(f"%{q}%"),
                User.email.ilike(f"%{q}%"),
            ))
        all_users = query.order_by(User.created_at.desc()).all()
        return render_template("admin/users.html", user=user, all_users=all_users, q=q)
    finally:
        db.close()


@admin_bp.route("/users/<int:user_id>")
@require_role(UserRole.ADMIN)
def user_view(user_id):
    user = get_current_user()
    db = SessionLocal()
    try:
        target = (db.query(User)
                  .options(joinedload(User.bookings).joinedload(Booking.trek))
                  .filter(User.id == user_id).first())
        if not target:
            flash("User not found.", "danger")
            return redirect(url_for("admin.users"))
        return render_template("admin/user_view.html", user=user, target=target)
    finally:
        db.close()


@admin_bp.route("/users/<int:user_id>/deactivate", methods=["POST"])
@require_role(UserRole.ADMIN)
def user_deactivate(user_id):
    current = get_current_user()
    if current and current.id == user_id:
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for("admin.users"))
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user_id).first()
        if u and u.role == UserRole.ADMIN:
            flash("Cannot deactivate an Admin account.", "danger")
            return redirect(url_for("admin.users"))
        if u:
            u.is_active = False
            db.commit()
            flash(f"User '{u.name}' deactivated.", "warning")
    except Exception:
        db.rollback()
        flash("Error.", "danger")
    finally:
        db.close()
    return redirect(request.referrer or url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/activate", methods=["POST"])
@require_role(UserRole.ADMIN)
def user_activate(user_id):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user_id).first()
        if u:
            u.is_active = True
            db.commit()
            flash(f"User '{u.name}' activated.", "success")
    except Exception:
        db.rollback()
        flash("Error.", "danger")
    finally:
        db.close()
    return redirect(request.referrer or url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/blacklist", methods=["POST"])
@require_role(UserRole.ADMIN)
def user_blacklist(user_id):
    current = get_current_user()
    if current and current.id == user_id:
        flash("You cannot blacklist your own account.", "danger")
        return redirect(url_for("admin.users"))
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user_id).first()
        if u and u.role == UserRole.ADMIN:
            flash("Cannot blacklist an Admin account.", "danger")
            return redirect(url_for("admin.users"))
        if u:
            u.is_blacklisted = True
            u.is_active = False
            db.commit()
            flash(f"User '{u.name}' has been blacklisted.", "warning")
    except Exception:
        db.rollback()
        flash("Error blacklisting user.", "danger")
    finally:
        db.close()
    return redirect(request.referrer or url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/unblacklist", methods=["POST"])
@require_role(UserRole.ADMIN)
def user_unblacklist(user_id):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user_id).first()
        if u:
            u.is_blacklisted = False
            u.is_active = True
            db.commit()
            flash(f"User '{u.name}' has been unblacklisted.", "success")
    except Exception:
        db.rollback()
        flash("Error unblacklisting user.", "danger")
    finally:
        db.close()
    return redirect(request.referrer or url_for("admin.users"))


# ─────────────────────────────────────────────
# Booking Management
# ─────────────────────────────────────────────

@admin_bp.route("/bookings")
@require_role(UserRole.ADMIN)
def bookings():
    user = get_current_user()
    db = SessionLocal()
    try:
        q = request.args.get("q", "").strip()
        status_filter = request.args.get("status", "").strip()
        query = (db.query(Booking)
                 .options(joinedload(Booking.user), joinedload(Booking.trek)))

        if q:
            query = query.join(User).join(Trek).filter(or_(
                User.name.ilike(f"%{q}%"),
                Trek.trek_name.ilike(f"%{q}%"),
            ))

        if status_filter:
            try:
                bs = BookingStatus(status_filter)
                query = query.filter(Booking.booking_status == bs)
            except ValueError:
                pass

        all_bookings = query.order_by(Booking.booking_date.desc()).all()
        return render_template("admin/bookings.html",
                               user=user, bookings=all_bookings, q=q,
                               status_filter=status_filter, booking_statuses=BookingStatus)
    finally:
        db.close()


@admin_bp.route("/bookings/<int:booking_id>")
@require_role(UserRole.ADMIN)
def booking_view(booking_id):
    user = get_current_user()
    db = SessionLocal()
    try:
        booking = (db.query(Booking)
                   .options(
                       joinedload(Booking.user),
                       joinedload(Booking.trek),
                       joinedload(Booking.feedback),
                       joinedload(Booking.certificate),
                       joinedload(Booking.attendance),
                   )
                   .filter(Booking.id == booking_id).first())
        if not booking:
            flash("Booking not found.", "danger")
            return redirect(url_for("admin.bookings"))

        audit_trail = (
            db.query(AuditLog)
            .options(joinedload(AuditLog.performer))
            .filter(AuditLog.entity_type == "booking", AuditLog.entity_id == booking_id)
            .order_by(AuditLog.performed_at.desc())
            .all()
        )

        return render_template("admin/booking_view.html",
                               user=user, booking=booking, audit_trail=audit_trail)
    finally:
        db.close()


@admin_bp.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@require_role(UserRole.ADMIN)
def booking_cancel(booking_id):
    user = get_current_user()
    db = SessionLocal()
    try:
        try:
            cancel_booking(db=db, booking_id=booking_id, performed_by=user.id, check_trek_started=False)
            db.commit()
            flash("Booking cancelled.", "success")
        except BookingError as e:
            db.rollback()
            flash(str(e), "danger")
    except Exception:
        db.rollback()
        flash("Error cancelling booking.", "danger")
    finally:
        db.close()
    return redirect(request.referrer or url_for("admin.bookings"))


@admin_bp.route("/bookings/<int:booking_id>/complete", methods=["POST"])
@require_role(UserRole.ADMIN)
def booking_complete(booking_id):
    user = get_current_user()
    db = SessionLocal()
    try:
        try:
            complete_booking(db=db, booking_id=booking_id, performed_by=user.id)
            db.commit()
            flash("Booking marked as Completed.", "success")
        except BookingError as e:
            db.rollback()
            flash(str(e), "danger")
    except Exception:
        db.rollback()
        flash("Error completing booking.", "danger")
    finally:
        db.close()
    return redirect(request.referrer or url_for("admin.bookings"))


# ─────────────────────────────────────────────
# Trek History
# ─────────────────────────────────────────────

@admin_bp.route("/trek-history")
@require_role(UserRole.ADMIN)
def trek_history():
    user = get_current_user()
    db = SessionLocal()
    try:
        treks = (
            db.query(Trek)
            .filter(Trek.status.in_([TrekStatus.COMPLETED, TrekStatus.CLOSED]))
            .order_by(Trek.end_date.desc())
            .all()
        )

        for trek in treks:
            trek.booking_count = db.query(func.count(Booking.id)).filter(Booking.trek_id == trek.id).scalar() or 0
            trek.completed_count = db.query(func.count(Booking.id)).filter(
                Booking.trek_id == trek.id,
                Booking.booking_status == BookingStatus.COMPLETED
            ).scalar() or 0

        return render_template("admin/trek_history.html", user=user, treks=treks)
    finally:
        db.close()


# ─────────────────────────────────────────────
# Booking History
# ─────────────────────────────────────────────

@admin_bp.route("/booking-history")
@require_role(UserRole.ADMIN)
def booking_history():
    user = get_current_user()
    db = SessionLocal()
    try:
        q = request.args.get("q", "").strip()
        status_filter = request.args.get("status", "").strip()

        query = (
            db.query(Booking)
            .options(
                joinedload(Booking.user),
                joinedload(Booking.trek),
                joinedload(Booking.feedback),
                joinedload(Booking.certificate),
            )
        )

        if q:
            query = query.join(User).join(Trek).filter(or_(
                User.name.ilike(f"%{q}%"),
                Trek.trek_name.ilike(f"%{q}%"),
            ))

        if status_filter:
            try:
                bs = BookingStatus(status_filter)
                query = query.filter(Booking.booking_status == bs)
            except ValueError:
                pass

        all_bookings = query.order_by(Booking.booking_date.desc()).all()

        return render_template("admin/booking_history.html",
                               user=user, bookings=all_bookings, q=q,
                               status_filter=status_filter, booking_statuses=BookingStatus)
    finally:
        db.close()


# ─────────────────────────────────────────────
# Staff Assignment
# ─────────────────────────────────────────────

@admin_bp.route("/assignments")
@require_role(UserRole.ADMIN)
def assignments():
    user = get_current_user()
    db = SessionLocal()
    try:
        treks = (db.query(Trek)
                 .options(joinedload(Trek.staff_assignments)
                          .joinedload(TrekStaffAssignment.staff)
                          .joinedload(StaffProfile.user))
                 .filter(Trek.status.in_([TrekStatus.PENDING, TrekStatus.APPROVED, TrekStatus.OPEN]))
                 .order_by(Trek.start_date).all())
        approved_staff = (db.query(StaffProfile)
                          .options(joinedload(StaffProfile.user))
                          .filter(StaffProfile.approval_status == ApprovalStatus.APPROVED)
                          .all())
        approved_staff = [s for s in approved_staff if s.user.is_active]
        return render_template("admin/assignments.html",
                               user=user, treks=treks,
                               approved_staff=approved_staff)
    finally:
        db.close()


@admin_bp.route("/assignments/assign", methods=["POST"])
@require_role(UserRole.ADMIN)
def assignment_assign():
    trek_id = request.form.get("trek_id", type=int)
    staff_id = request.form.get("staff_id", type=int)
    if not trek_id or not staff_id:
        flash("Trek and staff are required.", "danger")
        return redirect(url_for("admin.assignments"))

    db = SessionLocal()
    try:
        existing = db.query(TrekStaffAssignment).filter(
            TrekStaffAssignment.trek_id == trek_id,
            TrekStaffAssignment.staff_id == staff_id
        ).first()
        if existing:
            flash("This staff member is already assigned to this trek.", "warning")
            return redirect(url_for("admin.assignments"))

        assignment = TrekStaffAssignment(trek_id=trek_id, staff_id=staff_id)
        db.add(assignment)
        db.commit()
        flash("Staff assigned to trek successfully.", "success")
    except IntegrityError:
        db.rollback()
        flash("Duplicate assignment or invalid IDs.", "danger")
    except Exception:
        db.rollback()
        flash("Error assigning staff.", "danger")
    finally:
        db.close()
    return redirect(url_for("admin.assignments"))


@admin_bp.route("/assignments/<int:assignment_id>/remove", methods=["POST"])
@require_role(UserRole.ADMIN)
def assignment_remove(assignment_id):
    db = SessionLocal()
    try:
        a = db.query(TrekStaffAssignment).filter(TrekStaffAssignment.id == assignment_id).first()
        if a:
            db.delete(a)
            db.commit()
            flash("Assignment removed.", "success")
        else:
            flash("Assignment not found.", "danger")
    except Exception:
        db.rollback()
        flash("Error removing assignment.", "danger")
    finally:
        db.close()
    return redirect(url_for("admin.assignments"))


# ─────────────────────────────────────────────
# Global Search
# ─────────────────────────────────────────────

@admin_bp.route("/search")
@require_role(UserRole.ADMIN)
def search():
    user = get_current_user()
    q = request.args.get("q", "").strip()
    results = {"treks": [], "users": [], "staff": [], "bookings": []}

    if q:
        db = SessionLocal()
        try:
            results["treks"] = db.query(Trek).filter(or_(
                Trek.trek_name.ilike(f"%{q}%"),
                Trek.location.ilike(f"%{q}%"),
            )).limit(20).all()

            results["users"] = db.query(User).filter(
                User.role == UserRole.TREKKER,
                or_(User.name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%"))
            ).limit(20).all()

            results["staff"] = (db.query(User)
                                .options(joinedload(User.staff_profile))
                                .filter(
                                    User.role == UserRole.TREK_STAFF,
                                    or_(User.name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%"))
                                ).limit(20).all())

            results["bookings"] = (db.query(Booking)
                                   .options(joinedload(Booking.user), joinedload(Booking.trek))
                                   .join(User).join(Trek)
                                   .filter(or_(
                                       User.name.ilike(f"%{q}%"),
                                       Trek.trek_name.ilike(f"%{q}%"),
                                   )).limit(20).all())
        finally:
            db.close()

    return render_template("admin/search.html", user=user, q=q, results=results)


# ─────────────────────────────────────────────
# Legacy routes
# ─────────────────────────────────────────────

@admin_bp.route("/pending-staff")
@require_role(UserRole.ADMIN)
def pending_staff():
    return redirect(url_for("admin.staff_list"))


@admin_bp.route("/approve-staff/<int:profile_id>", methods=["POST"])
@require_role(UserRole.ADMIN)
def approve_staff(profile_id):
    db = SessionLocal()
    try:
        profile = db.query(StaffProfile).filter(StaffProfile.id == profile_id).first()
        if profile:
            profile.approval_status = ApprovalStatus.APPROVED
            db.commit()
            flash("Staff approved.", "success")
    except Exception:
        db.rollback()
    finally:
        db.close()
    return redirect(request.referrer or url_for("admin.staff_list"))


@admin_bp.route("/reject-staff/<int:profile_id>", methods=["POST"])
@require_role(UserRole.ADMIN)
def reject_staff(profile_id):
    db = SessionLocal()
    try:
        profile = db.query(StaffProfile).filter(StaffProfile.id == profile_id).first()
        if profile:
            profile.approval_status = ApprovalStatus.REJECTED
            db.commit()
            flash("Staff rejected.", "warning")
    except Exception:
        db.rollback()
    finally:
        db.close()
    return redirect(request.referrer or url_for("admin.staff_list"))
