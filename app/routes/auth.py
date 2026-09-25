from functools import wraps

from authlib.integrations.base_client import OAuthError
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.database import DatabaseError
from app.extensions import oauth
from app.services.users import upsert_google_user

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            if request.is_json or request.path == "/portfolios/upload":
                return jsonify({"success": False, "error": "Authentication required. Please sign in again."}), 401
            flash("Please sign in to continue.", "info")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped_view


@auth_bp.get("/login")
def login():
    return render_template("login.html")


@auth_bp.get("/google")
def google_login():
    if not current_app.config.get("GOOGLE_CLIENT_ID") or not current_app.config.get(
        "GOOGLE_CLIENT_SECRET"
    ):
        flash("Google sign-in is not configured yet.", "error")
        return redirect(url_for("auth.login"))

    google = oauth.create_client("google")
    redirect_uri = url_for("auth.callback", _external=True)
    return google.authorize_redirect(redirect_uri)


@auth_bp.get("/callback")
def callback():
    try:
        google = oauth.create_client("google")
        token = google.authorize_access_token()
        profile = token.get("userinfo")
        if not profile and "id_token" in token:
            try:
                profile = google.parse_id_token(token)
            except Exception:
                profile = None
        if not profile:
            profile = google.get("https://openidconnect.googleapis.com/v1/userinfo").json()
        user = upsert_google_user(profile)
    except OAuthError:
        current_app.logger.exception("Google OAuth callback failed")
        flash("Google sign-in was cancelled or could not be completed.", "error")
        return redirect(url_for("auth.login"))
    except (DatabaseError, ValueError):
        current_app.logger.exception("Could not save the authenticated user")
        flash("We could not finish setting up your account.", "error")
        return redirect(url_for("auth.login"))

    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    flash("Welcome back.", "success")
    return redirect(url_for("main.dashboard"))


@auth_bp.get("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("main.home"))
