"""
Database configuration for the Trek Management System.

Uses SQLAlchemy ORM with SQLite backend.
Designed to be reusable with FastAPI or any other Python framework.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

# SQLite database URL — file is created automatically in the project root
SQLALCHEMY_DATABASE_URL = "sqlite:///./trek_management.db"

# Create the engine with SQLite-specific settings
# check_same_thread=False is required for SQLite when used with frameworks
# like FastAPI that may access the DB from multiple threads.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,  # Set to True for SQL query debugging
)


# ---------- Enable SQLite foreign key enforcement ----------
# SQLite does NOT enforce foreign keys by default. We must issue
# PRAGMA foreign_keys=ON for every new connection.
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# Session factory — each call produces a new session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative base class for all ORM models
Base = declarative_base()


def get_db():
    """
    Database session generator.

    Yields a SQLAlchemy session and ensures it is closed after use.
    Compatible with FastAPI's Depends() dependency injection.

    Usage with FastAPI:
        @app.get("/items")
        def read_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
