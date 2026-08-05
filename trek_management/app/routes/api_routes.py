"""
REST API routes for Treks, Bookings, and Users.

All endpoints return consistent JSON responses and use proper HTTP status codes.
Authentication is session-based (for browser AJAX).
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models import (
    User, UserRole, Trek, TrekStatus, Difficulty,
    Booking, BookingStatus, StaffProfile, ApprovalStatus,
)
from app.api_utils import (
    json_response, api_error, require_api_auth, require_api_role,
    paginate_query, rate_limit,
    serialize_trek, serialize_booking, serialize_user,
)
from app.validators import (
    validate_trek_data, validate_booking_data, validate_user_data,
    validate_pagination, validate_date,
)
from app.services.booking_service import create_booking, cancel_booking, complete_booking, BookingError
from app.services.trek_service import advance_trek_status, TrekStatusError
from app.services.audit_service import log_action
from app.security import hash_password

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ═══════════════════════════════════════════════
# TREK APIs
# ═══════════════════════════════════════════════

@api_bp.route("/treks", methods=["GET"])
@rate_limit(max_requests=120, window_seconds=60)
@require_api_auth
def list_treks(current_user):
    """
    GET /api/treks
    List treks with pagination, search, and filters.

    Query params: page, per_page, q, status, difficulty, location, sort_by, sort_order
    """
    page, per_page, pag_errors = validate_pagination(
        request.args.get("page"), request.args.get("per_page")
    )
    if pag_errors:
        return api_error("Invalid pagination parameters", pag_errors, 400)

    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    difficulty_filter = request.args.get("difficulty", "").strip()
    location_filter = request.args.get("location", "").strip()
    sort_by = request.args.get("sort_by", "created_at").strip()
    sort_order = request.args.get("sort_order", "desc").strip().lower()

    db = SessionLocal()
    try:
        query = db.query(Trek)

        # Search
        if q:
            query = query.filter(or_(
                Trek.trek_name.ilike(f"%{q}%"),
                Trek.location.ilike(f"%{q}%"),
                Trek.description.ilike(f"%{q}%"),
            ))

        # Filters
        if status_filter:
            try:
                status_enum = TrekStatus(status_filter)
                query = query.filter(Trek.status == status_enum)
            except (ValueError, KeyError):
                return api_error("Invalid status filter", {"status": f"Must be one of: {[s.value for s in TrekStatus]}"}, 400)

        if difficulty_filter:
            try:
                diff_enum = Difficulty(difficulty_filter)
                query = query.filter(Trek.difficulty == diff_enum)
            except (ValueError, KeyError):
                return api_error("Invalid difficulty filter", {"difficulty": f"Must be one of: {[d.value for d in Difficulty]}"}, 400)

        if location_filter:
            query = query.filter(Trek.location.ilike(f"%{location_filter}%"))

        # Sorting
        sort_columns = {
            "created_at": Trek.created_at,
            "start_date": Trek.start_date,
            "price": Trek.price,
            "trek_name": Trek.trek_name,
            "available_slots": Trek.available_slots,
        }
        sort_col = sort_columns.get(sort_by, Trek.created_at)
        if sort_order == "asc":
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())

        items, meta = paginate_query(query, page, per_page)
        data = [serialize_trek(t) for t in items]

        return json_response(
            success=True,
            message=f"Found {meta['total']} trek(s)",
            data=data,
            meta=meta,
        )
    finally:
        db.close()


@api_bp.route("/treks/<int:trek_id>", methods=["GET"])
@rate_limit(max_requests=120, window_seconds=60)
@require_api_auth
def get_trek(trek_id, current_user):
    """GET /api/treks/{id} — Get trek details."""
    db = SessionLocal()
    try:
        trek = db.query(Trek).filter(Trek.id == trek_id).first()
        if not trek:
            return api_error("Trek not found", status_code=404)

        data = serialize_trek(trek)

        # Include booking count for admin
        if current_user.role == UserRole.ADMIN:
            booking_count = db.query(Booking).filter(Booking.trek_id == trek_id).count()
            data["booking_count"] = booking_count

        return json_response(True, "Trek retrieved successfully", data)
    finally:
        db.close()


@api_bp.route("/treks", methods=["POST"])
@rate_limit(max_requests=30, window_seconds=60)
@require_api_role(UserRole.ADMIN)
def create_trek(current_user):
    """POST /api/treks — Create a new trek (Admin only)."""
    data = request.get_json(silent=True)
    if not data:
        return api_error("Request body must be valid JSON", status_code=400)

    errors = validate_trek_data(data, is_update=False)
    if errors:
        return api_error("Validation failed", errors, 422)

    db = SessionLocal()
    try:
        # Parse dates
        sd = validate_date(data["start_date"])
        ed = validate_date(data["end_date"])
        bd = validate_date(data.get("booking_deadline", "")) if data.get("booking_deadline") else None

        trek = Trek(
            trek_name=data["trek_name"].strip(),
            description=data.get("description", "").strip() or None,
            location=data["location"].strip(),
            difficulty=Difficulty(data.get("difficulty", "Moderate")),
            duration_days=int(data["duration_days"]),
            total_slots=int(data["total_slots"]),
            available_slots=int(data.get("available_slots", data["total_slots"])),
            price=Decimal(str(data["price"])),
            start_date=sd.replace(tzinfo=timezone.utc) if sd.tzinfo is None else sd,
            end_date=ed.replace(tzinfo=timezone.utc) if ed.tzinfo is None else ed,
            booking_deadline=bd.replace(tzinfo=timezone.utc) if bd and bd.tzinfo is None else bd,
            status=TrekStatus(data.get("status", "Pending")),
            created_by=current_user.id,
        )
        db.add(trek)
        db.flush()

        log_action(
            db=db, entity_type="trek", entity_id=trek.id,
            action="created", new_value=trek.status.value,
            performed_by=current_user.id,
            details=f"Trek '{trek.trek_name}' created via API",
        )

        db.commit()
        return json_response(True, "Trek created successfully", serialize_trek(trek), 201)

    except (ValueError, InvalidOperation) as e:
        db.rollback()
        return api_error(f"Invalid data: {str(e)}", status_code=422)
    except Exception as e:
        db.rollback()
        return api_error("Error creating trek", status_code=500)
    finally:
        db.close()


@api_bp.route("/treks/<int:trek_id>", methods=["PUT"])
@rate_limit(max_requests=30, window_seconds=60)
@require_api_role(UserRole.ADMIN)
def update_trek(trek_id, current_user):
    """PUT /api/treks/{id} — Update a trek (Admin only)."""
    data = request.get_json(silent=True)
    if not data:
        return api_error("Request body must be valid JSON", status_code=400)

    errors = validate_trek_data(data, is_update=True)
    if errors:
        return api_error("Validation failed", errors, 422)

    db = SessionLocal()
    try:
        trek = db.query(Trek).filter(Trek.id == trek_id).first()
        if not trek:
            return api_error("Trek not found", status_code=404)

        # Update only provided fields
        if "trek_name" in data:
            trek.trek_name = data["trek_name"].strip()
        if "description" in data:
            trek.description = data["description"].strip() or None
        if "location" in data:
            trek.location = data["location"].strip()
        if "difficulty" in data:
            trek.difficulty = Difficulty(data["difficulty"])
        if "duration_days" in data:
            trek.duration_days = int(data["duration_days"])
        if "total_slots" in data:
            trek.total_slots = int(data["total_slots"])
        if "available_slots" in data:
            trek.available_slots = int(data["available_slots"])
        if "price" in data:
            trek.price = Decimal(str(data["price"]))
        if "start_date" in data:
            sd = validate_date(data["start_date"])
            if sd:
                trek.start_date = sd.replace(tzinfo=timezone.utc) if sd.tzinfo is None else sd
        if "end_date" in data:
            ed = validate_date(data["end_date"])
            if ed:
                trek.end_date = ed.replace(tzinfo=timezone.utc) if ed.tzinfo is None else ed
        if "booking_deadline" in data:
            if data["booking_deadline"]:
                bd = validate_date(data["booking_deadline"])
                if bd:
                    trek.booking_deadline = bd.replace(tzinfo=timezone.utc) if bd.tzinfo is None else bd
            else:
                trek.booking_deadline = None
        if "status" in data:
            new_status = TrekStatus(data["status"])
            if new_status != trek.status:
                try:
                    advance_trek_status(db=db, trek_id=trek_id, new_status=new_status, performed_by=current_user.id)
                except TrekStatusError as e:
                    db.rollback()
                    return api_error(str(e), status_code=409)

        trek.updated_at = datetime.now(timezone.utc)
        db.commit()

        return json_response(True, "Trek updated successfully", serialize_trek(trek))

    except (ValueError, InvalidOperation) as e:
        db.rollback()
        return api_error(f"Invalid data: {str(e)}", status_code=422)
    except Exception:
        db.rollback()
        return api_error("Error updating trek", status_code=500)
    finally:
        db.close()


@api_bp.route("/treks/<int:trek_id>", methods=["DELETE"])
@rate_limit(max_requests=10, window_seconds=60)
@require_api_role(UserRole.ADMIN)
def delete_trek(trek_id, current_user):
    """DELETE /api/treks/{id} — Delete a trek (Admin only, no active bookings)."""
    db = SessionLocal()
    try:
        trek = db.query(Trek).filter(Trek.id == trek_id).first()
        if not trek:
            return api_error("Trek not found", status_code=404)

        booking_count = db.query(Booking).filter(Booking.trek_id == trek_id).count()
        if booking_count > 0:
            return api_error(
                f"Cannot delete trek — {booking_count} booking(s) exist. Cancel bookings first.",
                status_code=409,
            )

        db.delete(trek)
        db.commit()
        return json_response(True, "Trek deleted successfully")
    except Exception:
        db.rollback()
        return api_error("Error deleting trek", status_code=500)
    finally:
        db.close()


# ═══════════════════════════════════════════════
# BOOKING APIs
# ═══════════════════════════════════════════════

@api_bp.route("/bookings", methods=["GET"])
@rate_limit(max_requests=120, window_seconds=60)
@require_api_auth
def list_bookings(current_user):
    """
    GET /api/bookings
    Admin: all bookings. User: own bookings only.
    """
    page, per_page, pag_errors = validate_pagination(
        request.args.get("page"), request.args.get("per_page")
    )
    if pag_errors:
        return api_error("Invalid pagination parameters", pag_errors, 400)

    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    trek_id_filter = request.args.get("trek_id", "").strip()

    db = SessionLocal()
    try:
        query = db.query(Booking).options(
            joinedload(Booking.user), joinedload(Booking.trek)
        )

        # Ownership filter for non-admin
        if current_user.role != UserRole.ADMIN:
            query = query.filter(Booking.user_id == current_user.id)

        # Status filter
        if status_filter:
            try:
                bs = BookingStatus(status_filter)
                query = query.filter(Booking.booking_status == bs)
            except (ValueError, KeyError):
                return api_error("Invalid status filter", status_code=400)

        # Trek filter
        if trek_id_filter:
            try:
                query = query.filter(Booking.trek_id == int(trek_id_filter))
            except ValueError:
                pass

        # Search (admin only — search by user name or trek name)
        if q and current_user.role == UserRole.ADMIN:
            query = query.join(User).join(Trek).filter(or_(
                User.name.ilike(f"%{q}%"),
                Trek.trek_name.ilike(f"%{q}%"),
            ))

        query = query.order_by(Booking.booking_date.desc())
        items, meta = paginate_query(query, page, per_page)
        data = [serialize_booking(b) for b in items]

        return json_response(True, f"Found {meta['total']} booking(s)", data, meta=meta)
    finally:
        db.close()


@api_bp.route("/bookings/<int:booking_id>", methods=["GET"])
@rate_limit(max_requests=120, window_seconds=60)
@require_api_auth
def get_booking(booking_id, current_user):
    """GET /api/bookings/{id} — Get booking details."""
    db = SessionLocal()
    try:
        query = db.query(Booking).options(
            joinedload(Booking.user), joinedload(Booking.trek),
            joinedload(Booking.feedback), joinedload(Booking.certificate),
        ).filter(Booking.id == booking_id)

        # Ownership check for non-admin
        if current_user.role != UserRole.ADMIN:
            query = query.filter(Booking.user_id == current_user.id)

        booking = query.first()
        if not booking:
            return api_error("Booking not found", status_code=404)

        data = serialize_booking(booking)

        # Add feedback and certificate info
        if booking.feedback:
            data["feedback"] = {
                "rating": booking.feedback.rating,
                "comment": booking.feedback.comment,
                "created_at": booking.feedback.created_at.isoformat() if booking.feedback.created_at else None,
            }
        if booking.certificate:
            data["certificate"] = {
                "certificate_uid": booking.certificate.certificate_uid,
                "issued_date": booking.certificate.issued_date.isoformat() if booking.certificate.issued_date else None,
            }

        return json_response(True, "Booking retrieved successfully", data)
    finally:
        db.close()


@api_bp.route("/bookings", methods=["POST"])
@rate_limit(max_requests=10, window_seconds=60)
@require_api_role(UserRole.TREKKER)
def create_booking_api(current_user):
    """POST /api/bookings — Create a new booking (Trekker only)."""
    data = request.get_json(silent=True)
    if not data:
        return api_error("Request body must be valid JSON", status_code=400)

    errors = validate_booking_data(data)
    if errors:
        return api_error("Validation failed", errors, 422)

    db = SessionLocal()
    try:
        try:
            booking = create_booking(
                db=db,
                user_id=current_user.id,
                trek_id=int(data["trek_id"]),
                participants=int(data.get("participants", 1)),
                performed_by=current_user.id,
            )
            db.commit()

            # Re-fetch with relationships
            booking = db.query(Booking).options(
                joinedload(Booking.user), joinedload(Booking.trek)
            ).filter(Booking.id == booking.id).first()

            return json_response(True, "Booking created successfully", serialize_booking(booking), 201)

        except BookingError as e:
            db.rollback()
            error_msg = str(e)
            status = 409 if "already" in error_msg.lower() or "duplicate" in error_msg.lower() else 422
            return api_error(error_msg, status_code=status)

    except Exception:
        db.rollback()
        return api_error("Error creating booking", status_code=500)
    finally:
        db.close()


@api_bp.route("/bookings/<int:booking_id>", methods=["PUT"])
@rate_limit(max_requests=30, window_seconds=60)
@require_api_role(UserRole.ADMIN, UserRole.TREK_STAFF)
def update_booking(booking_id, current_user):
    """PUT /api/bookings/{id} — Update booking status (Admin/Staff)."""
    data = request.get_json(silent=True)
    if not data:
        return api_error("Request body must be valid JSON", status_code=400)

    action = data.get("action", "").strip()
    if action not in ("cancel", "complete"):
        return api_error(
            "Invalid action",
            {"action": "Must be 'cancel' or 'complete'"},
            422,
        )

    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            return api_error("Booking not found", status_code=404)

        try:
            if action == "cancel":
                cancel_booking(
                    db=db, booking_id=booking_id,
                    performed_by=current_user.id,
                    check_trek_started=False,
                )
            elif action == "complete":
                complete_booking(
                    db=db, booking_id=booking_id,
                    performed_by=current_user.id,
                )
            db.commit()

            booking = db.query(Booking).options(
                joinedload(Booking.user), joinedload(Booking.trek)
            ).filter(Booking.id == booking_id).first()

            return json_response(True, f"Booking {action}d successfully", serialize_booking(booking))

        except BookingError as e:
            db.rollback()
            return api_error(str(e), status_code=409)

    except Exception:
        db.rollback()
        return api_error("Error updating booking", status_code=500)
    finally:
        db.close()


@api_bp.route("/bookings/<int:booking_id>", methods=["DELETE"])
@rate_limit(max_requests=10, window_seconds=60)
@require_api_auth
def delete_booking(booking_id, current_user):
    """DELETE /api/bookings/{id} — Cancel a booking (Admin or owner)."""
    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            return api_error("Booking not found", status_code=404)

        # Ownership check
        if current_user.role != UserRole.ADMIN and booking.user_id != current_user.id:
            return api_error("You can only cancel your own bookings", status_code=403)

        try:
            check_started = current_user.role != UserRole.ADMIN
            cancel_booking(
                db=db, booking_id=booking_id,
                performed_by=current_user.id,
                check_trek_started=check_started,
            )
            db.commit()

            booking = db.query(Booking).options(
                joinedload(Booking.user), joinedload(Booking.trek)
            ).filter(Booking.id == booking_id).first()

            return json_response(True, "Booking cancelled successfully", serialize_booking(booking))

        except BookingError as e:
            db.rollback()
            return api_error(str(e), status_code=409)

    except Exception:
        db.rollback()
        return api_error("Error cancelling booking", status_code=500)
    finally:
        db.close()


# ═══════════════════════════════════════════════
# USER APIs
# ═══════════════════════════════════════════════

@api_bp.route("/users", methods=["GET"])
@rate_limit(max_requests=60, window_seconds=60)
@require_api_role(UserRole.ADMIN)
def list_users(current_user):
    """GET /api/users — List users (Admin only)."""
    page, per_page, pag_errors = validate_pagination(
        request.args.get("page"), request.args.get("per_page")
    )
    if pag_errors:
        return api_error("Invalid pagination parameters", pag_errors, 400)

    q = request.args.get("q", "").strip()
    role_filter = request.args.get("role", "").strip()

    db = SessionLocal()
    try:
        query = db.query(User).options(joinedload(User.staff_profile))

        if q:
            query = query.filter(or_(
                User.name.ilike(f"%{q}%"),
                User.email.ilike(f"%{q}%"),
            ))

        if role_filter:
            try:
                role_enum = UserRole(role_filter)
                query = query.filter(User.role == role_enum)
            except (ValueError, KeyError):
                return api_error("Invalid role filter", status_code=400)

        query = query.order_by(User.created_at.desc())
        items, meta = paginate_query(query, page, per_page)
        data = [serialize_user(u, include_sensitive=True) for u in items]

        return json_response(True, f"Found {meta['total']} user(s)", data, meta=meta)
    finally:
        db.close()


@api_bp.route("/users/<int:user_id>", methods=["GET"])
@rate_limit(max_requests=120, window_seconds=60)
@require_api_auth
def get_user(user_id, current_user):
    """GET /api/users/{id} — Admin can view any user, users can view own profile."""
    if current_user.role != UserRole.ADMIN and current_user.id != user_id:
        return api_error("You can only view your own profile", status_code=403)

    db = SessionLocal()
    try:
        user = db.query(User).options(
            joinedload(User.staff_profile)
        ).filter(User.id == user_id).first()
        if not user:
            return api_error("User not found", status_code=404)

        include_sensitive = current_user.role == UserRole.ADMIN
        return json_response(True, "User retrieved successfully", serialize_user(user, include_sensitive))
    finally:
        db.close()


@api_bp.route("/users", methods=["POST"])
@rate_limit(max_requests=10, window_seconds=60)
@require_api_role(UserRole.ADMIN)
def create_user(current_user):
    """POST /api/users — Create a new user (Admin only)."""
    data = request.get_json(silent=True)
    if not data:
        return api_error("Request body must be valid JSON", status_code=400)

    errors = validate_user_data(data, is_update=False)
    if errors:
        return api_error("Validation failed", errors, 422)

    db = SessionLocal()
    try:
        # Check duplicate email
        existing = db.query(User).filter(User.email == data["email"].strip().lower()).first()
        if existing:
            return api_error("Email already exists", {"email": "A user with this email already exists"}, 409)

        role = UserRole(data.get("role", "Trekker"))
        new_user = User(
            name=data["name"].strip(),
            email=data["email"].strip().lower(),
            password_hash=hash_password(data["password"]),
            role=role,
            phone=data.get("phone", "").strip() or None,
            is_active=True,
        )
        db.add(new_user)
        db.flush()

        # Create staff profile if Trek Staff
        if role == UserRole.TREK_STAFF:
            profile = StaffProfile(
                user_id=new_user.id,
                experience_years=int(data.get("experience_years", 0)),
                specialization=data.get("specialization", "").strip() or None,
                certification=data.get("certification", "").strip() or None,
                bio=data.get("bio", "").strip() or None,
                approval_status=ApprovalStatus.APPROVED,
            )
            db.add(profile)

        db.commit()
        return json_response(True, "User created successfully", serialize_user(new_user), 201)

    except Exception:
        db.rollback()
        return api_error("Error creating user", status_code=500)
    finally:
        db.close()


@api_bp.route("/users/<int:user_id>", methods=["PUT"])
@rate_limit(max_requests=30, window_seconds=60)
@require_api_auth
def update_user(user_id, current_user):
    """PUT /api/users/{id} — Update user. Admin: any user. User: own profile only."""
    if current_user.role != UserRole.ADMIN and current_user.id != user_id:
        return api_error("You can only update your own profile", status_code=403)

    data = request.get_json(silent=True)
    if not data:
        return api_error("Request body must be valid JSON", status_code=400)

    errors = validate_user_data(data, is_update=True)
    if errors:
        return api_error("Validation failed", errors, 422)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return api_error("User not found", status_code=404)

        if "name" in data:
            user.name = data["name"].strip()
        if "phone" in data:
            user.phone = data["phone"].strip() or None
        if "password" in data and data["password"]:
            user.password_hash = hash_password(data["password"])

        # Admin-only fields
        if current_user.role == UserRole.ADMIN:
            if "is_active" in data:
                user.is_active = bool(data["is_active"])
            if "is_blacklisted" in data:
                user.is_blacklisted = bool(data["is_blacklisted"])

        db.commit()
        return json_response(True, "User updated successfully", serialize_user(user))

    except Exception:
        db.rollback()
        return api_error("Error updating user", status_code=500)
    finally:
        db.close()


@api_bp.route("/users/<int:user_id>", methods=["DELETE"])
@rate_limit(max_requests=10, window_seconds=60)
@require_api_role(UserRole.ADMIN)
def delete_user(user_id, current_user):
    """DELETE /api/users/{id} — Deactivate a user (Admin only)."""
    if current_user.id == user_id:
        return api_error("Cannot deactivate your own account", status_code=403)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return api_error("User not found", status_code=404)

        if user.role == UserRole.ADMIN:
            return api_error("Cannot deactivate an Admin account", status_code=403)

        user.is_active = False
        db.commit()
        return json_response(True, f"User '{user.name}' deactivated successfully", serialize_user(user))

    except Exception:
        db.rollback()
        return api_error("Error deactivating user", status_code=500)
    finally:
        db.close()
