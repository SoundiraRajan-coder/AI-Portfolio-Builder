import hmac
import secrets

from flask import abort, has_request_context, jsonify, request, session

CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FIELD_NAME = "csrf_token"


def ensure_csrf_token():
    if not has_request_context():
        return ""
    token = session.get(CSRF_FIELD_NAME)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_FIELD_NAME] = token
    return token


def validate_csrf():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None

    session_token = session.get(CSRF_FIELD_NAME)
    json_token = (request.get_json(silent=True) or {}).get(CSRF_FIELD_NAME, "") if request.is_json else ""
    request_token = request.headers.get(CSRF_HEADER_NAME) or request.form.get(CSRF_FIELD_NAME, "") or json_token
    if not session_token or not request_token or not hmac.compare_digest(session_token, request_token):
        if request.is_json or request.path == "/portfolios/upload":
            return jsonify({"success": False, "error": "Invalid CSRF token."}), 400
        abort(400, description="Invalid CSRF token.")
    return None
