from flask import Blueprint, current_app, jsonify

from app.services.gemini_service import GeminiConfigurationError, GeminiServiceError, ping_gemini, get_gemini_diagnostic

gemini_diag_bp = Blueprint("gemini_diag", __name__, url_prefix="/dev")


@gemini_diag_bp.get("/gemini-status")
def gemini_status():
    if not current_app.config.get("DEBUG"):
        return jsonify({"status": "not_available"}), 404

    diagnostic = get_gemini_diagnostic()
    result = {
        "Gemini configured": "YES" if diagnostic["configured"] else "NO",
        "Gemini model": diagnostic["model"],
        "google-genai installed": "YES" if diagnostic["sdk_installed"] else "NO",
    }
    if not diagnostic["configured"] or not diagnostic["sdk_installed"]:
        return jsonify({"status": "configured", "detail": result}), 200

    try:
        ping_result = ping_gemini()
        result["Gemini API request"] = "SUCCESS"
        result["Gemini response"] = "received"
        result["Gemini diagnostic reply"] = ping_result.get("response")
    except GeminiConfigurationError:
        result["Gemini API request"] = "FAILED"
        result["Reason"] = "API key is not configured."
    except GeminiServiceError as exc:
        result["Gemini API request"] = "FAILED"
        result["Reason"] = str(exc)
    return jsonify({"status": "configured", "detail": result}), 200
