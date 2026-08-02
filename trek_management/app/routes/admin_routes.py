"""
Admin-only routes: dashboard and staff approval management.
"""

from flask import Blueprint, render_template, redirect, url_for, flash

from app.database import SessionLocal
from app.models import User, UserRole, StaffProfile, ApprovalStatus
from app.auth import require_role, get_current_user

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/dashboard")
@require_role(UserRole.ADMIN)
def dashboard():
    """Admin dashboard — simple placeholder."""
    user = get_current_user()
    return render_template("admin_dashboard.html", user=user)


@admin_bp.route("/pending-staff")
@require_role(UserRole.ADMIN)
def pending_staff():
    """View all pending Trek Staff registrations."""
    user = get_current_user()
    db = SessionLocal()
    try:
        pending = (
            db.query(StaffProfile)
            .filter(StaffProfile.approval_status == ApprovalStatus.PENDING)
            .all()
        )
        # Eagerly load user info for display
        staff_list = []
        for profile in pending:
            staff_user = db.query(User).filter(User.id == profile.user_id).first()
            staff_list.append({
                "profile_id": profile.id,
                "user_id": staff_user.id,
                "name": staff_user.name,
                "email": staff_user.email,
                "phone": staff_user.phone,
                "experience_years": profile.experience_years,
                "specialization": profile.specialization,
                "certification": profile.certification,
                "emergency_contact": profile.emergency_contact,
                "bio": profile.bio,
            })
        return render_template("pending_staff.html", user=user, staff_list=staff_list)
    finally:
        db.close()


@admin_bp.route("/approve-staff/<int:profile_id>", methods=["POST"])
@require_role(UserRole.ADMIN)
def approve_staff(profile_id):
    """Approve a pending Trek Staff member."""
    db = SessionLocal()
    try:
        profile = db.query(StaffProfile).filter(StaffProfile.id == profile_id).first()
        if profile is None:
            flash("Staff profile not found.", "danger")
            return redirect(url_for("admin.pending_staff"))

        profile.approval_status = ApprovalStatus.APPROVED
        db.commit()

        staff_user = db.query(User).filter(User.id == profile.user_id).first()
        flash(f"Staff member '{staff_user.name}' has been approved.", "success")
        return redirect(url_for("admin.pending_staff"))
    except Exception:
        db.rollback()
        flash("An error occurred while approving the staff member.", "danger")
        return redirect(url_for("admin.pending_staff"))
    finally:
        db.close()


@admin_bp.route("/reject-staff/<int:profile_id>", methods=["POST"])
@require_role(UserRole.ADMIN)
def reject_staff(profile_id):
    """Reject a pending Trek Staff member."""
    db = SessionLocal()
    try:
        profile = db.query(StaffProfile).filter(StaffProfile.id == profile_id).first()
        if profile is None:
            flash("Staff profile not found.", "danger")
            return redirect(url_for("admin.pending_staff"))

        profile.approval_status = ApprovalStatus.REJECTED
        db.commit()

        staff_user = db.query(User).filter(User.id == profile.user_id).first()
        flash(f"Staff member '{staff_user.name}' has been rejected.", "warning")
        return redirect(url_for("admin.pending_staff"))
    except Exception:
        db.rollback()
        flash("An error occurred while rejecting the staff member.", "danger")
        return redirect(url_for("admin.pending_staff"))
    finally:
        db.close()
