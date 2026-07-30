"""
Database initialisation script.

Running this file creates the SQLite database file (trek_management.db)
and all tables defined in app.models.

Usage:
    python main.py
"""

from app.database import engine, Base

# Import all models so that Base.metadata is fully populated
from app.models import (  # noqa: F401
    User,
    StaffProfile,
    Trek,
    Booking,
    TrekStaffAssignment,
)


def init_db():
    """Create all tables that do not yet exist."""
    Base.metadata.create_all(bind=engine)
    print("[OK] Database initialised successfully.")
    print("     File: trek_management.db")
    print("    Tables created:")
    for table_name in Base.metadata.tables:
        print(f"      - {table_name}")


if __name__ == "__main__":
    init_db()
