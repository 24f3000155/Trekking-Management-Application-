"""
Trekker/User routes: dashboard.
"""

from flask import Blueprint, render_template

from app.models import UserRole
from app.auth import require_role, get_current_user

user_bp = Blueprint("user", __name__, url_prefix="/user")


@user_bp.route("/dashboard")
@require_role(UserRole.TREKKER)
def dashboard():
    """User dashboard — simple placeholder. Only accessible by trekkers."""
    user = get_current_user()
    return render_template("user_dashboard.html", user=user)
