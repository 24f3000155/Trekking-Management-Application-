"""
Trek Management Application Entry Point.

Initializes the Flask application, database, and route blueprints.
"""

import os
from flask import Flask, redirect, url_for, request

from app.api_utils import api_error

from app.database import engine, Base
from app.models import User, StaffProfile, Trek, Booking, TrekStaffAssignment
from app.routes.auth_routes import auth_bp
from app.routes.admin_routes import admin_bp
from app.routes.staff_routes import staff_bp
from app.routes.user_routes import user_bp
from app.routes.api_routes import api_bp
from app.routes.chart_routes import chart_bp
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
    app.register_blueprint(api_bp)
    app.register_blueprint(chart_bp)

    @app.route("/")
    def index():
        return redirect(url_for('auth.login'))

    # JSON Error Handlers for API routes
    @app.errorhandler(400)
    def bad_request(e):
        if request.path.startswith('/api/'):
            return api_error("Bad Request", status_code=400)
        return "Bad Request", 400

    @app.errorhandler(401)
    def unauthorized(e):
        if request.path.startswith('/api/'):
            return api_error("Unauthorized", status_code=401)
        return "Unauthorized", 401

    @app.errorhandler(403)
    def forbidden(e):
        if request.path.startswith('/api/'):
            return api_error("Forbidden", status_code=403)
        return "Forbidden", 403

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return api_error("Not Found", status_code=404)
        return "Not Found", 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        if request.path.startswith('/api/'):
            return api_error("Method Not Allowed", status_code=405)
        return "Method Not Allowed", 405

    @app.errorhandler(500)
    def internal_server_error(e):
        if request.path.startswith('/api/'):
            return api_error("Internal Server Error", status_code=500)
        return "Internal Server Error", 500

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
