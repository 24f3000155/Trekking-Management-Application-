"""
Authentication routes: login, logout, trekker registration, staff registration.
"""

import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.database import SessionLocal
from app.models import User, UserRole, StaffProfile, ApprovalStatus
from app.security import hash_password, verify_password

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Login page and authentication handler."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter both email and password.", "danger")
            return render_template("login.html")

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == email).first()

            # Generic message for invalid credentials — never reveal if email exists
            if user is None or not verify_password(password, user.password_hash):
                flash("Invalid email or password.", "danger")
                return render_template("login.html")

            # Check if account is active
            if not user.is_active:
                flash("Your account has been deactivated.", "danger")
                return render_template("login.html")

            # Role-specific checks for Trek Staff
            if user.role == UserRole.TREK_STAFF:
                if user.staff_profile is None:
                    flash("Staff profile not found. Please contact support.", "danger")
                    return render_template("login.html")

                if user.staff_profile.approval_status == ApprovalStatus.PENDING:
                    flash("Your Trek Staff account is awaiting Admin approval.", "info")
                    return render_template("login.html")

                if user.staff_profile.approval_status == ApprovalStatus.REJECTED:
                    flash("Your Trek Staff registration has been rejected.", "danger")
                    return render_template("login.html")

            # Authentication successful — store ONLY user_id in session
            session.clear()
            session["user_id"] = user.id

            # Redirect based on role
            if user.role == UserRole.ADMIN:
                return redirect(url_for("admin.dashboard"))
            elif user.role == UserRole.TREK_STAFF:
                return redirect(url_for("staff.dashboard"))
            else:
                return redirect(url_for("user.dashboard"))

        finally:
            db.close()

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    """Destroy session and redirect to login."""
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Trekker registration page and handler."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # Validation
        errors = []
        if not name:
            errors.append("Name is required.")
        if not email:
            errors.append("Email is required.")
        elif not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
            errors.append("Please enter a valid email address.")
        if not password:
            errors.append("Password is required.")
        elif len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm_password:
            errors.append("Passwords do not match.")

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("register.html",
                                   name=name, email=email, phone=phone)

        db = SessionLocal()
        try:
            # Check for duplicate email
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                flash("An account with this email already exists.", "danger")
                return render_template("register.html",
                                       name=name, email=email, phone=phone)

            # Create user with TREKKER role — never allow frontend to set role
            user = User(
                name=name,
                email=email,
                phone=phone if phone else None,
                password_hash=hash_password(password),
                role=UserRole.TREKKER,
                is_active=True,
            )
            db.add(user)
            db.commit()

            flash("Registration successful. Please login.", "success")
            return redirect(url_for("auth.login"))

        except Exception:
            db.rollback()
            flash("An error occurred during registration. Please try again.", "danger")
            return render_template("register.html",
                                   name=name, email=email, phone=phone)
        finally:
            db.close()

    return render_template("register.html")


@auth_bp.route("/staff/register", methods=["GET", "POST"])
def staff_register():
    """Trek Staff registration page and handler."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        experience_years = request.form.get("experience_years", "0").strip()
        specialization = request.form.get("specialization", "").strip()
        certification = request.form.get("certification", "").strip()
        emergency_contact = request.form.get("emergency_contact", "").strip()
        bio = request.form.get("bio", "").strip()

        # Validation
        errors = []
        if not name:
            errors.append("Name is required.")
        if not email:
            errors.append("Email is required.")
        elif not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
            errors.append("Please enter a valid email address.")
        if not password:
            errors.append("Password is required.")
        elif len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm_password:
            errors.append("Passwords do not match.")

        try:
            exp_years = int(experience_years)
            if exp_years < 0:
                errors.append("Experience years cannot be negative.")
        except ValueError:
            errors.append("Experience years must be a number.")
            exp_years = 0

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("staff_register.html",
                                   name=name, email=email, phone=phone,
                                   experience_years=experience_years,
                                   specialization=specialization,
                                   certification=certification,
                                   emergency_contact=emergency_contact,
                                   bio=bio)

        db = SessionLocal()
        try:
            # Check for duplicate email
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                flash("An account with this email already exists.", "danger")
                return render_template("staff_register.html",
                                       name=name, email=email, phone=phone,
                                       experience_years=experience_years,
                                       specialization=specialization,
                                       certification=certification,
                                       emergency_contact=emergency_contact,
                                       bio=bio)

            # Create user with TREK_STAFF role — hardcoded, never from frontend
            user = User(
                name=name,
                email=email,
                phone=phone if phone else None,
                password_hash=hash_password(password),
                role=UserRole.TREK_STAFF,
                is_active=True,
            )
            db.add(user)
            db.flush()  # Get user.id for the StaffProfile FK

            # Create staff profile with PENDING approval status
            staff_profile = StaffProfile(
                user_id=user.id,
                experience_years=exp_years,
                specialization=specialization if specialization else None,
                certification=certification if certification else None,
                emergency_contact=emergency_contact if emergency_contact else None,
                bio=bio if bio else None,
                approval_status=ApprovalStatus.PENDING,
            )
            db.add(staff_profile)
            db.commit()

            flash("Staff registration successful. Your account is pending Admin approval.", "success")
            return redirect(url_for("auth.login"))

        except Exception as e:
            db.rollback()
            import traceback
            traceback.print_exc()
            flash("An error occurred during registration. Please try again.", "danger")
            return render_template("staff_register.html",
                                   name=name, email=email, phone=phone,
                                   experience_years=experience_years,
                                   specialization=specialization,
                                   certification=certification,
                                   emergency_contact=emergency_contact,
                                   bio=bio)
        finally:
            db.close()

    return render_template("staff_register.html")
