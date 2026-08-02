"""
Trek Staff routes: dashboard (requires approved staff status).
"""

from flask import Blueprint, render_template

from app.models import UserRole
from app.auth import require_approved_staff, get_current_user

staff_bp = Blueprint("staff", __name__, url_prefix="/staff")


@staff_bp.route("/dashboard")
@require_approved_staff()
def dashboard():
    """Staff dashboard — simple placeholder. Only accessible by APPROVED staff."""
    user = get_current_user()
    return render_template("staff_dashboard.html", user=user)
