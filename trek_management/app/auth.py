"""
Authentication and authorization helpers.

Provides reusable decorators for Flask route protection using Flask-Login:
  - get_current_user()       — fetch User from session (flask_login.current_user)
  - require_authentication   — alias for flask_login.login_required
  - require_role(*roles)     — restrict access to specific UserRole(s)
  - require_approved_staff() — restrict to APPROVED Trek Staff only
"""

from functools import wraps

from flask import flash, abort
from flask_login import current_user, login_required

from app.models import UserRole, ApprovalStatus


def get_current_user():
    """
    Return the currently authenticated User.
    This now wraps flask_login.current_user.
    Returns None if not authenticated.
    """
    if current_user.is_authenticated:
        return current_user
    return None


def require_authentication(f):
    """
    Decorator: redirect to login page if the user is not authenticated.
    This is now just an alias for login_required.
    """
    return login_required(f)


def require_role(*roles):
    """
    Decorator factory: restrict access to users with one of the given roles.
    Using abort(403) for unauthorized access.
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
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
        @login_required
        def decorated_function(*args, **kwargs):
            if current_user.role != UserRole.TREK_STAFF:
                abort(403)
            # Check approval status
            if current_user.staff_profile is None:
                abort(403)
            if current_user.staff_profile.approval_status == ApprovalStatus.PENDING:
                flash("Your Trek Staff account is awaiting Admin approval.", "info")
                # Wait, redirecting isn't great inside a decorator if we have aborts. 
                # Let's abort(403) but we could also flash. The pending staff template is meant for this.
                abort(403)
            if current_user.staff_profile.approval_status == ApprovalStatus.REJECTED:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator
