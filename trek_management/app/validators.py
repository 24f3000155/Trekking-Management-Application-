"""
Centralized validation functions for API inputs.

Every validate_* function returns a dict of field → error message.
An empty dict means all validations passed.
"""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def validate_trek_data(data, is_update=False):
    """
    Validate trek creation/update payload.

    Args:
        data: dict of form/JSON fields
        is_update: if True, fields are optional (partial update)

    Returns:
        dict of field → error message (empty = valid)
    """
    errors = {}

    trek_name = data.get("trek_name", "").strip() if data.get("trek_name") else ""
    location = data.get("location", "").strip() if data.get("location") else ""
    difficulty = data.get("difficulty", "")
    duration_days = data.get("duration_days")
    total_slots = data.get("total_slots")
    available_slots = data.get("available_slots")
    price = data.get("price")
    start_date = data.get("start_date", "")
    end_date = data.get("end_date", "")
    status = data.get("status", "")
    booking_deadline = data.get("booking_deadline", "")

    # Required fields (only for creation)
    if not is_update:
        if not trek_name:
            errors["trek_name"] = "Trek name is required"
        if not location:
            errors["location"] = "Location is required"
        if not start_date:
            errors["start_date"] = "Start date is required"
        if not end_date:
            errors["end_date"] = "End date is required"
        if duration_days is None or str(duration_days).strip() == "":
            errors["duration_days"] = "Duration is required"
        if total_slots is None or str(total_slots).strip() == "":
            errors["total_slots"] = "Total slots is required"
        if price is None or str(price).strip() == "":
            errors["price"] = "Price is required"

    # Field-level validation (only if provided)
    if trek_name and len(trek_name) > 200:
        errors["trek_name"] = "Trek name must be at most 200 characters"

    if location and len(location) > 200:
        errors["location"] = "Location must be at most 200 characters"

    if difficulty:
        valid_difficulties = ["Easy", "Moderate", "Hard", "Expert"]
        if difficulty not in valid_difficulties:
            errors["difficulty"] = f"Difficulty must be one of: {', '.join(valid_difficulties)}"

    if duration_days is not None and str(duration_days).strip() != "":
        try:
            dur = int(duration_days)
            if dur <= 0:
                errors["duration_days"] = "Duration must be greater than 0"
        except (ValueError, TypeError):
            errors["duration_days"] = "Duration must be a valid integer"

    if total_slots is not None and str(total_slots).strip() != "":
        try:
            ts = int(total_slots)
            if ts <= 0:
                errors["total_slots"] = "Total slots must be greater than 0"
        except (ValueError, TypeError):
            errors["total_slots"] = "Total slots must be a valid integer"

    if available_slots is not None and str(available_slots).strip() != "":
        try:
            avs = int(available_slots)
            if avs < 0:
                errors["available_slots"] = "Available slots cannot be negative"
        except (ValueError, TypeError):
            errors["available_slots"] = "Available slots must be a valid integer"

    # Cross-field: available <= total
    if (available_slots is not None and total_slots is not None and
            "available_slots" not in errors and "total_slots" not in errors):
        try:
            if int(available_slots) > int(total_slots):
                errors["available_slots"] = "Available slots cannot exceed total slots"
        except (ValueError, TypeError):
            pass

    if price is not None and str(price).strip() != "":
        try:
            pr = Decimal(str(price))
            if pr < 0:
                errors["price"] = "Price cannot be negative"
        except (InvalidOperation, ValueError, TypeError):
            errors["price"] = "Price must be a valid number"

    if start_date:
        sd = validate_date(start_date)
        if sd is None:
            errors["start_date"] = "Start date must be a valid date (YYYY-MM-DD or ISO format)"

    if end_date:
        ed = validate_date(end_date)
        if ed is None:
            errors["end_date"] = "End date must be a valid date (YYYY-MM-DD or ISO format)"

    # Cross-field: end >= start
    if start_date and end_date and "start_date" not in errors and "end_date" not in errors:
        sd = validate_date(start_date)
        ed = validate_date(end_date)
        if sd and ed and ed < sd:
            errors["end_date"] = "End date must be on or after start date"

    if booking_deadline:
        bd = validate_date(booking_deadline)
        if bd is None:
            errors["booking_deadline"] = "Booking deadline must be a valid date"

    if status:
        valid_statuses = ["Pending", "Approved", "Open", "Closed", "Completed"]
        if status not in valid_statuses:
            errors["status"] = f"Status must be one of: {', '.join(valid_statuses)}"

    return errors


def validate_booking_data(data):
    """
    Validate booking creation payload.

    Returns:
        dict of field → error message
    """
    errors = {}

    trek_id = data.get("trek_id")
    participants = data.get("participants", 1)

    if trek_id is None:
        errors["trek_id"] = "Trek ID is required"
    else:
        try:
            tid = int(trek_id)
            if tid <= 0:
                errors["trek_id"] = "Trek ID must be a positive integer"
        except (ValueError, TypeError):
            errors["trek_id"] = "Trek ID must be a valid integer"

    if participants is not None:
        try:
            p = int(participants)
            if p < 1:
                errors["participants"] = "Participants must be at least 1"
            if p > 50:
                errors["participants"] = "Participants cannot exceed 50"
        except (ValueError, TypeError):
            errors["participants"] = "Participants must be a valid integer"

    return errors


def validate_user_data(data, is_update=False):
    """
    Validate user creation/update payload.

    Returns:
        dict of field → error message
    """
    errors = {}

    name = data.get("name", "").strip() if data.get("name") else ""
    email = data.get("email", "").strip() if data.get("email") else ""
    password = data.get("password", "")
    phone = data.get("phone", "").strip() if data.get("phone") else ""
    role = data.get("role", "")

    if not is_update:
        if not name:
            errors["name"] = "Name is required"
        if not email:
            errors["email"] = "Email is required"
        if not password:
            errors["password"] = "Password is required"

    if name and len(name) > 100:
        errors["name"] = "Name must be at most 100 characters"

    if email and not validate_email(email):
        errors["email"] = "Invalid email format"

    if password:
        pwd_errors = validate_password_strength(password)
        if pwd_errors:
            errors["password"] = pwd_errors

    if phone and not validate_phone(phone):
        errors["phone"] = "Invalid phone number format"

    if role:
        valid_roles = ["Admin", "Trek Staff", "Trekker"]
        if role not in valid_roles:
            errors["role"] = f"Role must be one of: {', '.join(valid_roles)}"

    return errors


# ──────────────────────────────────────────────
# Field-level validators
# ──────────────────────────────────────────────

def validate_email(email):
    """Return True if email format is valid."""
    if not email or not isinstance(email, str):
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))


def validate_phone(phone):
    """Return True if phone format is valid (digits, spaces, +, -, parens)."""
    if not phone or not isinstance(phone, str):
        return False
    pattern = r'^[\d\s\+\-\(\)]{7,20}$'
    return bool(re.match(pattern, phone.strip()))


def validate_date(date_str):
    """
    Parse a date string in YYYY-MM-DD or ISO format.

    Returns:
        datetime object or None if invalid.
    """
    if not date_str or not isinstance(date_str, str):
        return None

    date_str = date_str.strip()

    # Try YYYY-MM-DD first
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    # Try ISO format parsing (Python 3.7+)
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        pass

    return None


def validate_password_strength(password):
    """
    Check password strength.
    Requires at least 8 characters, one uppercase, one lowercase,
    one digit, and one special character.
    Returns:
        Error message string or None if strong enough.
    """
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not re.search(r'[A-Z]', password):
        return "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return "Password must contain at least one lowercase letter"
    if not re.search(r'\d', password):
        return "Password must contain at least one digit"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return "Password must contain at least one special character"
    if len(password) > 128:
        return "Password must be at most 128 characters"
    return None


def validate_pagination(page, per_page):
    """
    Validate and sanitize pagination parameters.

    Returns:
        (page, per_page, errors) tuple
    """
    errors = {}

    try:
        page = int(page) if page else 1
        if page < 1:
            page = 1
    except (ValueError, TypeError):
        errors["page"] = "Page must be a valid integer"
        page = 1

    try:
        per_page = int(per_page) if per_page else 20
        if per_page < 1:
            per_page = 1
        if per_page > 100:
            per_page = 100
    except (ValueError, TypeError):
        errors["per_page"] = "Per page must be a valid integer"
        per_page = 20

    return page, per_page, errors
