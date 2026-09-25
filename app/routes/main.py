from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, session, url_for

from app.database import DatabaseError, check_database_connection
from app.services.portfolios import get_dashboard_portfolios
from app.services.users import get_user_by_id
from app.routes.auth import login_required

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def home():
    return render_template("index.html")


@main_bp.get("/dashboard")
@login_required
def dashboard():
    try:
        user = get_user_by_id(session["user_id"])
        portfolio_data = get_dashboard_portfolios(session["user_id"])
    except DatabaseError:
        current_app.logger.exception("Could not load the authenticated user")
        flash("Your account could not be loaded right now.", "error")
        return redirect(url_for("main.home"))

    if not user:
        session.clear()
        flash("Please sign in again.", "info")
        return redirect(url_for("auth.login"))

    return render_template("dashboard.html", user=user, **portfolio_data)


@main_bp.get("/dev/database-health")
def database_health():
    if not current_app.config["DEBUG"]:
        abort(404)

    try:
        check_database_connection()
    except DatabaseError:
        current_app.logger.exception("Database health check failed")
        return jsonify({"status": "error", "message": "Database connection failed."}), 503

    return jsonify({"status": "ok", "message": "Database connection succeeded."})
