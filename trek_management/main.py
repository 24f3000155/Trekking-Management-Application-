"""
Trek Management Application Entry Point.

Initializes the Flask application, database, and route blueprints.
"""

import os
from flask import Flask, redirect, url_for

from app.database import engine, Base
from app.models import User, StaffProfile, Trek, Booking, TrekStaffAssignment
from app.routes.auth_routes import auth_bp
from app.routes.admin_routes import admin_bp
from app.routes.staff_routes import staff_bp
from app.routes.user_routes import user_bp
from scripts.create_admin import create_admin


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__, template_folder='templates', static_folder='static')
    
    # Secure random key for sessions
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(user_bp)

    @app.route("/")
    def index():
        return redirect(url_for('auth.login'))

    return app


def init_db():
    """Create all tables that do not yet exist."""
    print("Initialising database...")
    Base.metadata.create_all(bind=engine)
    print("[OK] Database initialised successfully.")


if __name__ == "__main__":
    init_db()
    
    # Auto-create admin if env vars are present
    if os.environ.get("ADMIN_EMAIL") and os.environ.get("ADMIN_PASSWORD"):
        create_admin()

    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=True)
