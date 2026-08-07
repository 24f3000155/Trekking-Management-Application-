"""
Create the initial Admin user.

Reads credentials from environment variables:
    ADMIN_NAME      — display name   (default: "Admin")
    ADMIN_EMAIL     — login email    (required)
    ADMIN_PASSWORD  — login password (required)

Usage:
    # Set env vars first (PowerShell example):
    #   $env:ADMIN_NAME     = "Super Admin"
    #   $env:ADMIN_EMAIL    = "admin@trekmanagement.com"
    #   $env:ADMIN_PASSWORD = "SecureP@ss123"
    #
    python -m scripts.create_admin
"""

import os
import sys

from app.database import SessionLocal
from app.models import User, UserRole
from app.security import hash_password


def create_admin():
    """Create the admin account if it does not already exist."""

    admin_name = os.environ.get("ADMIN_NAME", "Admin")
    admin_email = os.environ.get("ADMIN_EMAIL")
    admin_password = os.environ.get("ADMIN_PASSWORD")

    if not admin_email or not admin_password:
        print("[ERROR] ADMIN_EMAIL and ADMIN_PASSWORD environment "
              "variables must be set.")
        print()
        print("   PowerShell:")
        print('     $env:ADMIN_EMAIL    = "admin@trekmanagement.com"')
        print('     $env:ADMIN_PASSWORD = "SecureP@ss123"')
        print()
        print("   Bash / Linux / macOS:")
        print('     export ADMIN_EMAIL="admin@trekmanagement.com"')
        print('     export ADMIN_PASSWORD="SecureP@ss123"')
        sys.exit(1)

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == admin_email).first()
        if existing:
            print(f"[INFO] Admin with email '{admin_email}' already exists "
                  f"(id={existing.id}). Skipping creation.")
            return

        admin = User(
            name=admin_name,
            email=admin_email,
            password_hash=hash_password(admin_password),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        print(f"[OK] Admin user created successfully!")
        print(f"    Name:  {admin.name}")
        print(f"    Email: {admin.email}")
        print(f"    Role:  {admin.role.value}")

    except Exception as exc:
        db.rollback()
        # Gracefully handle duplicate email (e.g., during hot-reload)
        if "UNIQUE constraint" in str(exc):
            print(f"[INFO] Admin '{admin_email}' already exists. Skipping.")
        else:
            print(f"[ERROR] Failed to create admin: {exc}")
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    create_admin()
