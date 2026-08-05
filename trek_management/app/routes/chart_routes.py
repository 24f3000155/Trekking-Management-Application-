"""
Chart data API endpoints for dashboard visualizations.

Lightweight JSON endpoints consumed by Chart.js on the frontend.
Each endpoint returns data formatted for direct use in Chart.js datasets.
"""

from datetime import datetime, timezone, timedelta
from collections import Counter

from flask import Blueprint
from sqlalchemy import func, extract
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models import (
    User, UserRole, Trek, TrekStatus, Difficulty,
    Booking, BookingStatus, StaffProfile, ApprovalStatus,
    TrekStaffAssignment, Attendance, AttendanceStatus,
)
from app.api_utils import json_response, api_error, require_api_role, require_api_auth

chart_bp = Blueprint("charts", __name__, url_prefix="/api/charts")


# ═══════════════════════════════════════════════
# ADMIN DASHBOARD CHARTS
# ═══════════════════════════════════════════════

@chart_bp.route("/admin/overview")
@require_api_role(UserRole.ADMIN)
def admin_overview(current_user):
    """Summary statistics for admin dashboard."""
    db = SessionLocal()
    try:
        data = {
            "total_treks": db.query(func.count(Trek.id)).scalar() or 0,
            "total_bookings": db.query(func.count(Booking.id)).scalar() or 0,
            "active_users": db.query(func.count(User.id)).filter(
                User.role == UserRole.TREKKER, User.is_active == True
            ).scalar() or 0,
            "total_staff": db.query(func.count(User.id)).filter(
                User.role == UserRole.TREK_STAFF
            ).scalar() or 0,
            "completed_treks": db.query(func.count(Trek.id)).filter(
                Trek.status == TrekStatus.COMPLETED
            ).scalar() or 0,
            "open_treks": db.query(func.count(Trek.id)).filter(
                Trek.status == TrekStatus.OPEN
            ).scalar() or 0,
            "cancelled_bookings": db.query(func.count(Booking.id)).filter(
                Booking.booking_status == BookingStatus.CANCELLED
            ).scalar() or 0,
            "total_revenue": float(
                db.query(func.coalesce(func.sum(Booking.total_amount), 0)).filter(
                    Booking.booking_status.in_([BookingStatus.BOOKED, BookingStatus.COMPLETED])
                ).scalar() or 0
            ),
        }
        return json_response(True, "Admin overview", data)
    finally:
        db.close()


@chart_bp.route("/admin/monthly-bookings")
@require_api_role(UserRole.ADMIN)
def admin_monthly_bookings(current_user):
    """Monthly booking count for the last 12 months (line chart)."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        twelve_months_ago = now - timedelta(days=365)

        rows = (
            db.query(
                extract("year", Booking.booking_date).label("year"),
                extract("month", Booking.booking_date).label("month"),
                func.count(Booking.id).label("count"),
            )
            .filter(Booking.booking_date >= twelve_months_ago)
            .group_by("year", "month")
            .order_by("year", "month")
            .all()
        )

        # Build full 12-month series
        labels = []
        values = []
        month_data = {(int(r.year), int(r.month)): int(r.count) for r in rows}

        for i in range(12):
            dt = now - timedelta(days=30 * (11 - i))
            key = (dt.year, dt.month)
            labels.append(dt.strftime("%b %Y"))
            values.append(month_data.get(key, 0))

        return json_response(True, "Monthly bookings", {
            "labels": labels,
            "datasets": [{
                "label": "Bookings",
                "data": values,
            }]
        })
    finally:
        db.close()


@chart_bp.route("/admin/booking-status")
@require_api_role(UserRole.ADMIN)
def admin_booking_status(current_user):
    """Booking status distribution (doughnut chart)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(
                Booking.booking_status,
                func.count(Booking.id).label("count"),
            )
            .group_by(Booking.booking_status)
            .all()
        )

        labels = []
        values = []
        colors = {
            "Booked": "#0d6efd",
            "Completed": "#6f42c1",
            "Cancelled": "#dc3545",
        }
        bg_colors = []

        for row in rows:
            status_name = row.booking_status.value
            labels.append(status_name)
            values.append(int(row.count))
            bg_colors.append(colors.get(status_name, "#6c757d"))

        return json_response(True, "Booking status distribution", {
            "labels": labels,
            "datasets": [{
                "data": values,
                "backgroundColor": bg_colors,
            }]
        })
    finally:
        db.close()


@chart_bp.route("/admin/difficulty-distribution")
@require_api_role(UserRole.ADMIN)
def admin_difficulty_distribution(current_user):
    """Trek difficulty distribution (bar chart)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(
                Trek.difficulty,
                func.count(Trek.id).label("count"),
            )
            .group_by(Trek.difficulty)
            .all()
        )

        labels = []
        values = []
        colors = {
            "Easy": "#198754",
            "Moderate": "#ffc107",
            "Hard": "#fd7e14",
            "Expert": "#dc3545",
        }
        bg_colors = []

        for row in rows:
            diff_name = row.difficulty.value
            labels.append(diff_name)
            values.append(int(row.count))
            bg_colors.append(colors.get(diff_name, "#6c757d"))

        return json_response(True, "Difficulty distribution", {
            "labels": labels,
            "datasets": [{
                "label": "Number of Treks",
                "data": values,
                "backgroundColor": bg_colors,
            }]
        })
    finally:
        db.close()


@chart_bp.route("/admin/popular-locations")
@require_api_role(UserRole.ADMIN)
def admin_popular_locations(current_user):
    """Popular trek locations by booking count (horizontal bar chart)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(
                Trek.location,
                func.count(Booking.id).label("booking_count"),
            )
            .join(Booking, Booking.trek_id == Trek.id)
            .group_by(Trek.location)
            .order_by(func.count(Booking.id).desc())
            .limit(10)
            .all()
        )

        labels = [r.location for r in rows]
        values = [int(r.booking_count) for r in rows]

        return json_response(True, "Popular locations", {
            "labels": labels,
            "datasets": [{
                "label": "Total Bookings",
                "data": values,
                "backgroundColor": "#0d6efd",
            }]
        })
    finally:
        db.close()


@chart_bp.route("/admin/trek-status")
@require_api_role(UserRole.ADMIN)
def admin_trek_status(current_user):
    """Trek status distribution (pie chart)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(
                Trek.status,
                func.count(Trek.id).label("count"),
            )
            .group_by(Trek.status)
            .all()
        )

        labels = []
        values = []
        colors = {
            "Pending": "#6c757d",
            "Approved": "#0dcaf0",
            "Open": "#198754",
            "Closed": "#ffc107",
            "Completed": "#6f42c1",
        }
        bg_colors = []

        for row in rows:
            status_name = row.status.value
            labels.append(status_name)
            values.append(int(row.count))
            bg_colors.append(colors.get(status_name, "#6c757d"))

        return json_response(True, "Trek status distribution", {
            "labels": labels,
            "datasets": [{
                "data": values,
                "backgroundColor": bg_colors,
            }]
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════
# STAFF DASHBOARD CHARTS
# ═══════════════════════════════════════════════

def _get_staff_assigned_ids(db, user):
    """Helper: get trek IDs assigned to the staff user."""
    profile = db.query(StaffProfile).filter(StaffProfile.user_id == user.id).first()
    if not profile:
        return []
    assignments = db.query(TrekStaffAssignment.trek_id).filter(
        TrekStaffAssignment.staff_id == profile.id
    ).all()
    return [a.trek_id for a in assignments]


@chart_bp.route("/staff/trek-participants")
@require_api_role(UserRole.TREK_STAFF)
def staff_trek_participants(current_user):
    """Participant count per assigned trek (bar chart)."""
    db = SessionLocal()
    try:
        assigned_ids = _get_staff_assigned_ids(db, current_user)
        if not assigned_ids:
            return json_response(True, "No assigned treks", {"labels": [], "datasets": []})

        treks = db.query(Trek).filter(Trek.id.in_(assigned_ids)).all()

        labels = []
        booked_data = []
        completed_data = []
        cancelled_data = []

        for trek in treks:
            labels.append(trek.trek_name[:25])

            booked = db.query(func.coalesce(func.sum(Booking.participants), 0)).filter(
                Booking.trek_id == trek.id, Booking.booking_status == BookingStatus.BOOKED
            ).scalar() or 0

            completed = db.query(func.coalesce(func.sum(Booking.participants), 0)).filter(
                Booking.trek_id == trek.id, Booking.booking_status == BookingStatus.COMPLETED
            ).scalar() or 0

            cancelled = db.query(func.coalesce(func.sum(Booking.participants), 0)).filter(
                Booking.trek_id == trek.id, Booking.booking_status == BookingStatus.CANCELLED
            ).scalar() or 0

            booked_data.append(int(booked))
            completed_data.append(int(completed))
            cancelled_data.append(int(cancelled))

        return json_response(True, "Trek participants", {
            "labels": labels,
            "datasets": [
                {"label": "Booked", "data": booked_data, "backgroundColor": "#0d6efd"},
                {"label": "Completed", "data": completed_data, "backgroundColor": "#6f42c1"},
                {"label": "Cancelled", "data": cancelled_data, "backgroundColor": "#dc3545"},
            ]
        })
    finally:
        db.close()


@chart_bp.route("/staff/booking-status")
@require_api_role(UserRole.TREK_STAFF)
def staff_booking_status(current_user):
    """Booking status distribution across assigned treks (pie chart)."""
    db = SessionLocal()
    try:
        assigned_ids = _get_staff_assigned_ids(db, current_user)
        if not assigned_ids:
            return json_response(True, "No data", {"labels": [], "datasets": []})

        rows = (
            db.query(
                Booking.booking_status,
                func.count(Booking.id).label("count"),
            )
            .filter(Booking.trek_id.in_(assigned_ids))
            .group_by(Booking.booking_status)
            .all()
        )

        labels = [r.booking_status.value for r in rows]
        values = [int(r.count) for r in rows]
        colors = {"Booked": "#0d6efd", "Completed": "#6f42c1", "Cancelled": "#dc3545"}
        bg_colors = [colors.get(l, "#6c757d") for l in labels]

        return json_response(True, "Booking status", {
            "labels": labels,
            "datasets": [{"data": values, "backgroundColor": bg_colors}]
        })
    finally:
        db.close()


@chart_bp.route("/staff/attendance")
@require_api_role(UserRole.TREK_STAFF)
def staff_attendance(current_user):
    """Attendance distribution across assigned treks (doughnut chart)."""
    db = SessionLocal()
    try:
        assigned_ids = _get_staff_assigned_ids(db, current_user)
        if not assigned_ids:
            return json_response(True, "No data", {"labels": [], "datasets": []})

        rows = (
            db.query(
                Attendance.status,
                func.count(Attendance.id).label("count"),
            )
            .join(Booking, Booking.id == Attendance.booking_id)
            .filter(Booking.trek_id.in_(assigned_ids))
            .group_by(Attendance.status)
            .all()
        )

        labels = [r.status.value for r in rows]
        values = [int(r.count) for r in rows]
        colors = {"Present": "#198754", "Absent": "#dc3545", "Not Marked": "#6c757d"}
        bg_colors = [colors.get(l, "#6c757d") for l in labels]

        return json_response(True, "Attendance", {
            "labels": labels,
            "datasets": [{"data": values, "backgroundColor": bg_colors}]
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════
# USER DASHBOARD CHARTS
# ═══════════════════════════════════════════════

@chart_bp.route("/user/booking-trend")
@require_api_role(UserRole.TREKKER)
def user_booking_trend(current_user):
    """User's monthly booking trend (line chart)."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        twelve_months_ago = now - timedelta(days=365)

        rows = (
            db.query(
                extract("year", Booking.booking_date).label("year"),
                extract("month", Booking.booking_date).label("month"),
                func.count(Booking.id).label("count"),
            )
            .filter(
                Booking.user_id == current_user.id,
                Booking.booking_date >= twelve_months_ago,
            )
            .group_by("year", "month")
            .order_by("year", "month")
            .all()
        )

        month_data = {(int(r.year), int(r.month)): int(r.count) for r in rows}
        labels = []
        values = []

        for i in range(12):
            dt = now - timedelta(days=30 * (11 - i))
            key = (dt.year, dt.month)
            labels.append(dt.strftime("%b %Y"))
            values.append(month_data.get(key, 0))

        return json_response(True, "Booking trend", {
            "labels": labels,
            "datasets": [{
                "label": "My Bookings",
                "data": values,
            }]
        })
    finally:
        db.close()


@chart_bp.route("/user/booking-status")
@require_api_role(UserRole.TREKKER)
def user_booking_status(current_user):
    """User's booking status distribution (pie chart)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(
                Booking.booking_status,
                func.count(Booking.id).label("count"),
            )
            .filter(Booking.user_id == current_user.id)
            .group_by(Booking.booking_status)
            .all()
        )

        labels = [r.booking_status.value for r in rows]
        values = [int(r.count) for r in rows]
        colors = {"Booked": "#0d6efd", "Completed": "#6f42c1", "Cancelled": "#dc3545"}
        bg_colors = [colors.get(l, "#6c757d") for l in labels]

        return json_response(True, "Booking status", {
            "labels": labels,
            "datasets": [{"data": values, "backgroundColor": bg_colors}]
        })
    finally:
        db.close()


@chart_bp.route("/user/difficulty-preference")
@require_api_role(UserRole.TREKKER)
def user_difficulty_preference(current_user):
    """User's preferred trek difficulties (bar chart)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(
                Trek.difficulty,
                func.count(Booking.id).label("count"),
            )
            .join(Booking, Booking.trek_id == Trek.id)
            .filter(Booking.user_id == current_user.id)
            .group_by(Trek.difficulty)
            .all()
        )

        labels = [r.difficulty.value for r in rows]
        values = [int(r.count) for r in rows]
        colors = {"Easy": "#198754", "Moderate": "#ffc107", "Hard": "#fd7e14", "Expert": "#dc3545"}
        bg_colors = [colors.get(l, "#6c757d") for l in labels]

        return json_response(True, "Difficulty preference", {
            "labels": labels,
            "datasets": [{
                "label": "Bookings",
                "data": values,
                "backgroundColor": bg_colors,
            }]
        })
    finally:
        db.close()


@chart_bp.route("/user/locations-visited")
@require_api_role(UserRole.TREKKER)
def user_locations_visited(current_user):
    """Locations visited by the user (bar chart)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(
                Trek.location,
                func.count(Booking.id).label("count"),
            )
            .join(Booking, Booking.trek_id == Trek.id)
            .filter(
                Booking.user_id == current_user.id,
                Booking.booking_status.in_([BookingStatus.BOOKED, BookingStatus.COMPLETED]),
            )
            .group_by(Trek.location)
            .order_by(func.count(Booking.id).desc())
            .limit(10)
            .all()
        )

        labels = [r.location for r in rows]
        values = [int(r.count) for r in rows]

        return json_response(True, "Locations visited", {
            "labels": labels,
            "datasets": [{
                "label": "Visits",
                "data": values,
                "backgroundColor": "#198754",
            }]
        })
    finally:
        db.close()
