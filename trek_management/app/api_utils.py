"""
API utility functions: response helpers, authentication decorators,
pagination, and rate limiting.

Provides a consistent JSON envelope for all API responses and reusable
decorators for authentication and authorization.
"""

import time
import threading
from functools import wraps

from flask import jsonify, request, session
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models import User, UserRole, ApprovalStatus


# ──────────────────────────────────────────────
# JSON Response Helpers
# ──────────────────────────────────────────────

def json_response(success=True, message="", data=None, status_code=200, meta=None):
    """
    Return a consistent JSON envelope.

    Format:
        {
            "success": true/false,
            "message": "...",
            "data": { ... },
            "meta": { ... }       # optional pagination info
        }
    """
    body = {
        "success": success,
        "message": message,
        "data": data if data is not None else {},
    }
    if meta is not None:
        body["meta"] = meta
    return jsonify(body), status_code


def api_error(message="An error occurred", errors=None, status_code=400):
    """
    Return a consistent JSON error response.

    Format:
        {
            "success": false,
            "message": "...",
            "errors": { "field": "error message", ... }
        }
    """
    body = {
        "success": False,
        "message": message,
    }
    if errors:
        body["errors"] = errors
    return jsonify(body), status_code


# ──────────────────────────────────────────────
# Authentication / Authorization Decorators
# ──────────────────────────────────────────────

def _get_api_user():
    """
    Retrieve the current user for API requests.

    Checks Flask session (for browser AJAX calls from dashboards).
    Returns (User, None) on success or (None, error_response) on failure.
    """
    user_id = session.get("user_id")
    if user_id is None:
        return None, api_error("Authentication required", status_code=401)

    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .options(joinedload(User.staff_profile))
            .filter(User.id == user_id)
            .first()
        )
        if user is None:
            return None, api_error("User not found", status_code=401)
        if not user.is_active:
            return None, api_error("Account is deactivated", status_code=403)
        if user.is_blacklisted:
            return None, api_error("Account is blacklisted", status_code=403)
        return user, None
    finally:
        db.close()


def require_api_auth(f):
    """Decorator: require authenticated user for API endpoint."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user, error = _get_api_user()
        if error:
            return error
        kwargs["current_user"] = user
        return f(*args, **kwargs)
    return decorated_function


def require_api_role(*roles):
    """
    Decorator factory: restrict API access to specific roles.

    Usage:
        @require_api_role(UserRole.ADMIN)
        def admin_endpoint(current_user, ...): ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user, error = _get_api_user()
            if error:
                return error
            if user.role not in roles:
                return api_error("Insufficient permissions", status_code=403)
            # For staff, check approval status
            if user.role == UserRole.TREK_STAFF:
                if (user.staff_profile is None or
                        user.staff_profile.approval_status != ApprovalStatus.APPROVED):
                    return api_error("Staff account not approved", status_code=403)
            kwargs["current_user"] = user
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ──────────────────────────────────────────────
# Pagination
# ──────────────────────────────────────────────

def paginate_query(query, page=1, per_page=20):
    """
    Apply pagination to a SQLAlchemy query.

    Returns:
        (items, meta) where meta contains pagination info.
    """
    page = max(1, page)
    per_page = max(1, min(per_page, 100))  # Cap at 100

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    meta = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
        "has_next": page * per_page < total,
        "has_prev": page > 1,
    }
    return items, meta


# ──────────────────────────────────────────────
# Rate Limiting (in-memory, thread-safe)
# ──────────────────────────────────────────────

class _RateLimiter:
    """Simple in-memory sliding-window rate limiter."""

    def __init__(self):
        self._lock = threading.Lock()
        self._requests = {}  # key -> list of timestamps

    def is_rate_limited(self, key, max_requests=60, window_seconds=60):
        """Check if the key has exceeded the rate limit."""
        now = time.time()
        with self._lock:
            if key not in self._requests:
                self._requests[key] = []

            # Remove expired entries
            self._requests[key] = [
                t for t in self._requests[key]
                if now - t < window_seconds
            ]

            if len(self._requests[key]) >= max_requests:
                return True

            self._requests[key].append(now)
            return False


_rate_limiter = _RateLimiter()


def rate_limit(max_requests=60, window_seconds=60):
    """
    Decorator: apply rate limiting to an API endpoint.

    Uses IP address + endpoint as the rate-limit key.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            key = f"{request.remote_addr}:{request.endpoint}"
            if _rate_limiter.is_rate_limited(key, max_requests, window_seconds):
                return api_error(
                    "Rate limit exceeded. Please try again later.",
                    status_code=429,
                )
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ──────────────────────────────────────────────
# Serialization Helpers
# ──────────────────────────────────────────────

def serialize_trek(trek):
    """Convert a Trek ORM object to a JSON-serializable dict."""
    return {
        "id": trek.id,
        "trek_name": trek.trek_name,
        "description": trek.description,
        "location": trek.location,
        "difficulty": trek.difficulty.value if trek.difficulty else None,
        "duration_days": trek.duration_days,
        "total_slots": trek.total_slots,
        "available_slots": trek.available_slots,
        "price": float(trek.price) if trek.price is not None else 0,
        "start_date": trek.start_date.isoformat() if trek.start_date else None,
        "end_date": trek.end_date.isoformat() if trek.end_date else None,
        "booking_deadline": trek.booking_deadline.isoformat() if trek.booking_deadline else None,
        "status": trek.status.value if trek.status else None,
        "created_by": trek.created_by,
        "created_at": trek.created_at.isoformat() if trek.created_at else None,
        "updated_at": trek.updated_at.isoformat() if trek.updated_at else None,
    }


def serialize_booking(booking):
    """Convert a Booking ORM object to a JSON-serializable dict."""
    return {
        "id": booking.id,
        "user_id": booking.user_id,
        "trek_id": booking.trek_id,
        "booking_status": booking.booking_status.value if booking.booking_status else None,
        "booking_date": booking.booking_date.isoformat() if booking.booking_date else None,
        "completion_date": booking.completion_date.isoformat() if booking.completion_date else None,
        "cancelled_date": booking.cancelled_date.isoformat() if booking.cancelled_date else None,
        "participants": booking.participants,
        "total_amount": float(booking.total_amount) if booking.total_amount is not None else 0,
        "remarks": booking.remarks,
        "created_at": booking.created_at.isoformat() if booking.created_at else None,
        "updated_at": booking.updated_at.isoformat() if booking.updated_at else None,
        "user_name": booking.user.name if booking.user else None,
        "user_email": booking.user.email if booking.user else None,
        "trek_name": booking.trek.trek_name if booking.trek else None,
    }


def serialize_user(user, include_sensitive=False):
    """Convert a User ORM object to a JSON-serializable dict."""
    data = {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role.value if user.role else None,
        "phone": user.phone,
        "is_active": user.is_active,
        "is_blacklisted": user.is_blacklisted,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
    if include_sensitive and user.role == UserRole.TREK_STAFF and user.staff_profile:
        data["staff_profile"] = {
            "experience_years": user.staff_profile.experience_years,
            "specialization": user.staff_profile.specialization,
            "certification": user.staff_profile.certification,
            "approval_status": user.staff_profile.approval_status.value,
        }
    return data
