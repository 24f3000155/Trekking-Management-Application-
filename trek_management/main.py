"""
Trek Management Application Entry Point.

Initializes the Flask application, database, and route blueprints.
"""

import os
from datetime import timedelta
from flask import Flask, redirect, url_for, request, render_template

from app.api_utils import api_error
from app.database import engine, Base, SessionLocal
from app.models import User
from app.extensions import login_manager, csrf

from app.routes.auth_routes import auth_bp
from app.routes.admin_routes import admin_bp
from app.routes.staff_routes import staff_bp
from app.routes.user_routes import user_bp
from app.routes.api_routes import api_bp
from app.routes.chart_routes import chart_bp
from scripts.create_admin import create_admin


from sqlalchemy.orm import joinedload

@login_manager.user_loader
def load_user(user_id):
    db = SessionLocal()
    try:
        return db.query(User).options(joinedload(User.staff_profile)).filter(User.id == int(user_id)).first()
    finally:
        db.close()


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__, template_folder='templates', static_folder='static')
    
    # Secure random key for sessions
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

    # Session Security Config
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False  # Set True in prod (HTTPS)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)
    app.config["WTF_CSRF_ENABLED"] = True

    # Initialize extensions
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"
    csrf.init_app(app)

    # Register blueprints
    # Exempt API from CSRF if you plan to use tokens, otherwise leave it protected.
    csrf.exempt(api_bp)
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(chart_bp)

    @app.route("/")
    def index():
        return redirect(url_for('auth.login'))

    # Error Handlers
    @app.errorhandler(400)
    def bad_request(e):
        if request.path.startswith('/api/'):
            return api_error("Bad Request", status_code=400)
        return "Bad Request", 400

    @app.errorhandler(401)
    def unauthorized(e):
        if request.path.startswith('/api/'):
            return api_error("Unauthorized", status_code=401)
        return render_template("errors/401.html"), 401

    @app.errorhandler(403)
    def forbidden(e):
        if request.path.startswith('/api/'):
            return api_error("Forbidden", status_code=403)
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return api_error("Not Found", status_code=404)
        return render_template("errors/404.html"), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        if request.path.startswith('/api/'):
            return api_error("Method Not Allowed", status_code=405)
        return "Method Not Allowed", 405

    @app.errorhandler(500)
    def internal_server_error(e):
        if request.path.startswith('/api/'):
            return api_error("Internal Server Error", status_code=500)
        return render_template("errors/500.html"), 500

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
