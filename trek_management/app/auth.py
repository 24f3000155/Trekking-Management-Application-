"""
Authentication and authorization helpers.

Provides reusable decorators for Flask route protection:
  - get_current_user()       — fetch User from session (server-side)
  - require_authentication   — redirect to login if not logged in
  - require_role(*roles)     — restrict access to specific UserRole(s)
  - require_approved_staff() — restrict to APPROVED Trek Staff only
"""

from functools import wraps

from flask import session, redirect, url_for, flash, abort
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models import User, UserRole, ApprovalStatus


def get_current_user():
    """
    Return the currently authenticated User by querying the database
    using the user_id stored in the Flask session.

    Returns None if not authenticated or user no longer exists.
    Always fetches fresh data from the DB — never trusts frontend values.
    """
    user_id = session.get("user_id")
    if user_id is None:
        return None

    db = SessionLocal()
    try:
        user = db.query(User).options(joinedload(User.staff_profile)).filter(User.id == user_id).first()
        return user
    finally:
        db.close()


def require_authentication(f):
    """
    Decorator: redirect to login page if the user is not authenticated.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if user is None:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated_function


def require_role(*roles):
    """
    Decorator factory: restrict access to users with one of the given roles.

    Usage:
        @require_role(UserRole.ADMIN)
        def admin_view(): ...

        @require_role(UserRole.ADMIN, UserRole.TREK_STAFF)
        def shared_view(): ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if user is None:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("auth.login"))
            if user.role not in roles:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for("auth.login"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_approved_staff():
    """
    Decorator: restrict access to Trek Staff who have been APPROVED.
    Checks both role AND approval_status server-side.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if user is None:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("auth.login"))
            if user.role != UserRole.TREK_STAFF:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for("auth.login"))
            # Check approval status from the staff profile
            if user.staff_profile is None:
                flash("Staff profile not found.", "danger")
                return redirect(url_for("auth.login"))
            if user.staff_profile.approval_status == ApprovalStatus.PENDING:
                flash("Your Trek Staff account is awaiting Admin approval.", "info")
                return redirect(url_for("auth.login"))
            if user.staff_profile.approval_status == ApprovalStatus.REJECTED:
                flash("Your Trek Staff registration has been rejected.", "danger")
                return redirect(url_for("auth.login"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
