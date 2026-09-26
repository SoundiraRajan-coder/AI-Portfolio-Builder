import os
import uuid
from pathlib import Path
from flask import Blueprint, current_app, flash, jsonify, make_response, redirect, render_template, request, send_file, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from app.services import gemini_service
from app.database import DatabaseError
from app.routes.auth import login_required
from app.services.export_service import ExportError, create_portfolio_export
from app.services.portfolios import (
    STATUS_VALUES,
    create_portfolio,
    delete_portfolio,
    duplicate_portfolio,
    get_portfolio,
    update_portfolio,
)
from app.services.design_spec import build_portfolio_generation_prompt, save_design_spec, validate_portfolio_spec, wizard_content
from app.services.gemini_service import (
    GeminiConfigurationError,
    GeminiRateLimitError,
    GeminiResponseError,
    GeminiServiceError,
    edit_portfolio_html_with_ai,
)
from app.services.portfolio_builder import PortfolioNotFoundError, get_builder_data, save_builder_data
from app.services.profile_image_storage import ProfileImageStorageError, upload_profile_image
from app.services.renderer import RendererError, render_portfolio

portfolios_bp = Blueprint("portfolios", __name__, url_prefix="/portfolios")

PHOTO_MAX_BYTES = 5 * 1024 * 1024
PHOTO_TYPES = {
    ".jpg": ("image/jpeg",),
    ".jpeg": ("image/jpeg",),
    ".png": ("image/png",),
    ".webp": ("image/webp",),
}
ALLOWED_RESUME_EXTENSIONS = {".pdf", ".doc", ".docx"}


def _valid_image_content(content, extension):
    if extension in {".jpg", ".jpeg"}:
        return content.startswith(b"\xff\xd8\xff")
    if extension == ".png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == ".webp":
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return False


@portfolios_bp.route("/upload", methods=["POST"])
@login_required
def upload_file():
    try:
        file = request.files.get("file")
    except RequestEntityTooLarge:
        return jsonify({"success": False, "error": "Profile image must be 5 MB or smaller."}), 413

    if not file or not file.filename:
        return jsonify({"success": False, "error": "No file selected."}), 400

    upload_type = request.form.get("type", "photo")
    ext = Path(file.filename).suffix.lower()

    if upload_type == "photo":
        allowed_mimetypes = PHOTO_TYPES.get(ext)
        if not allowed_mimetypes:
            return jsonify({"success": False, "error": "Invalid image type. Use JPG, PNG, or WEBP."}), 400
        if file.mimetype not in allowed_mimetypes:
            return jsonify({"success": False, "error": "Invalid image type. Use JPG, PNG, or WEBP."}), 400
        content = file.read(PHOTO_MAX_BYTES + 1)
        if len(content) > PHOTO_MAX_BYTES:
            return jsonify({"success": False, "error": "Profile image must be 5 MB or smaller."}), 413
        if not _valid_image_content(content, ext):
            return jsonify({"success": False, "error": "Invalid image file."}), 400

        user_id = str(session["user_id"])
        object_path = f"profiles/{user_id}/{uuid.uuid4().hex}{ext}"
        try:
            url = upload_profile_image(
                supabase_url=current_app.config.get("SUPABASE_URL"),
                service_role_key=current_app.config.get("SUPABASE_SERVICE_ROLE_KEY"),
                bucket=current_app.config.get("SUPABASE_STORAGE_BUCKET"),
                object_path=object_path,
                content=content,
                content_type=file.mimetype,
            )
        except ProfileImageStorageError:
            current_app.logger.exception("Profile image upload failed")
            return jsonify({"success": False, "error": "Profile image upload failed."}), 500

        return jsonify({"success": True, "url": url, "type": upload_type}), 201
    elif upload_type == "resume":
        if ext not in ALLOWED_RESUME_EXTENSIONS:
            return jsonify({"success": False, "error": f"Invalid resume format. Allowed formats: {', '.join(sorted(ALLOWED_RESUME_EXTENSIONS))}"}), 400
    else:
        return jsonify({"success": False, "error": "Invalid upload type."}), 400

    user_id = str(session["user_id"])
    try:
        upload_dir = Path(current_app.root_path) / "static" / "uploads" / user_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        unique_name = f"{upload_type}_{uuid.uuid4().hex[:12]}{ext}"
        target_path = upload_dir / unique_name
        file.save(str(target_path))
    except OSError:
        current_app.logger.exception("Resume upload failed")
        return jsonify({"success": False, "error": "Resume upload failed."}), 500

    url = f"/static/uploads/{user_id}/{unique_name}"
    return jsonify({
        "success": True,
        "url": url,
        "filename": file.filename,
        "type": upload_type,
    })


@portfolios_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_portfolio():
    if request.method == "GET":
        return render_template("portfolio_form.html", portfolio=None)

    try:
        name, status = _portfolio_form_data()
        portfolio_id = create_portfolio(session["user_id"], name, status)
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("portfolio_form.html", portfolio=None), 400
    except DatabaseError:
        current_app.logger.exception("Could not create portfolio")
        flash("Your portfolio could not be created.", "error")
        return render_template("portfolio_form.html", portfolio=None), 503

    flash("Portfolio created.", "success")
    return redirect(url_for("portfolios.builder", portfolio_id=portfolio_id))


@portfolios_bp.get("/<uuid:portfolio_id>/builder")
@login_required
def builder(portfolio_id):
    try:
        data = get_builder_data(session["user_id"], portfolio_id)
    except DatabaseError:
        current_app.logger.exception("Could not load portfolio builder")
        flash("That portfolio builder could not be loaded.", "error")
        return redirect(url_for("main.dashboard"))
    if not data:
        flash("Portfolio not found.", "error")
        return redirect(url_for("main.dashboard"))
    return render_template("portfolio_builder.html", builder_state=data)


@portfolios_bp.post("/<uuid:portfolio_id>/builder/save")
@login_required
def save_builder(portfolio_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "A JSON builder payload is required."}), 400
    try:
        saved = save_builder_data(session["user_id"], portfolio_id, payload)
    except PortfolioNotFoundError:
        return jsonify({"status": "error", "message": "Portfolio not found."}), 404
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except DatabaseError:
        current_app.logger.exception("Could not save portfolio builder")
        return jsonify({"status": "error", "message": "Portfolio could not be saved."}), 503
    return jsonify({"status": "saved", **saved})


@portfolios_bp.post("/<uuid:portfolio_id>/generate")
@login_required
def generate_portfolio(portfolio_id):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "A JSON payload is required."}), 400
    generation_key = f"portfolio_generation_{portfolio_id}"
    if session.get(generation_key):
        return jsonify({"status": "error", "message": "Portfolio generation is already in progress."}), 409
    session[generation_key] = True
    try:
        # Persist and validate the same wizard payload used for Gemini so a
        # failed request always leaves the user's latest draft intact.
        save_builder_data(session["user_id"], portfolio_id, payload)
        builder_state = get_builder_data(session["user_id"], portfolio_id)
        if not builder_state:
            raise ValueError("Portfolio not found.")
        wizard = builder_state["wizard"]
        design_prompt = wizard.get("portfolio", {}).get("design_prompt", "")
        custom_html = gemini_service.generate_creative_portfolio_html(wizard, design_prompt)
        spec = {
            "custom_html": custom_html,
            "visual": {"theme": "dark", "style": "modern", "layout": "custom"},
            "composition": {},
            "content": wizard_content(wizard),
        }
        save_design_spec(session["user_id"], portfolio_id, design_prompt, spec)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except GeminiConfigurationError:
        return jsonify({"status": "error", "message": "Gemini is not configured yet."}), 503
    except GeminiRateLimitError:
        return jsonify({"status": "error", "message": "AI requests are temporarily rate-limited. Try again shortly."}), 429
    except GeminiResponseError:
        return jsonify({"status": "error", "message": "Gemini returned an invalid portfolio specification."}), 502
    except GeminiServiceError:
        current_app.logger.exception("Gemini generation failed")
        return jsonify({"status": "error", "message": "Design generation is temporarily unavailable."}), 502
    except DatabaseError:
        current_app.logger.exception("Could not save generated design")
        return jsonify({"status": "error", "message": "Your generated portfolio could not be saved."}), 503
    except Exception as exc:
        current_app.logger.exception("Unexpected error during portfolio generation")
        return jsonify({"status": "error", "message": f"Portfolio generation error: {str(exc)}"}), 500
    finally:
        session.pop(generation_key, None)
    preview_url = url_for("portfolios.preview_portfolio", portfolio_id=portfolio_id)
    return jsonify({"status": "generated", "preview_url": preview_url})


@portfolios_bp.post("/<uuid:portfolio_id>/ai-edit")
@login_required
def ai_edit_portfolio(portfolio_id):
    payload = request.get_json(silent=True) or {}
    instruction = (payload.get("instruction") or "").strip()
    if not instruction:
        return jsonify({"status": "error", "message": "Please provide an edit instruction."}), 400

    try:
        builder_state = get_builder_data(session["user_id"], portfolio_id)
        if not builder_state:
            return jsonify({"status": "error", "message": "Portfolio not found."}), 404

        design_spec = builder_state.get("design_spec") or {}
        current_html = design_spec.get("custom_html")
        if not current_html:
            return jsonify({"status": "error", "message": "No portfolio design found to edit. Please generate your portfolio first."}), 400

        updated_html, reply_message = edit_portfolio_html_with_ai(current_html, instruction)
        design_spec["custom_html"] = updated_html
        validated = validate_portfolio_spec(design_spec, builder_state.get("wizard", {}))
        save_design_spec(session["user_id"], portfolio_id, instruction, validated)

        return jsonify({
            "status": "success",
            "message": reply_message or "Portfolio updated successfully with AI!",
            "content_url": url_for("portfolios.preview_content", portfolio_id=portfolio_id)
        })
    except (GeminiConfigurationError, GeminiRateLimitError, GeminiResponseError, GeminiServiceError) as exc:
        current_app.logger.warning(f"AI Edit failed: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 503
    except Exception as exc:
        current_app.logger.exception("Unexpected error during AI portfolio edit")
        return jsonify({"status": "error", "message": f"AI Edit error: {str(exc)}"}), 500


@portfolios_bp.route("/<uuid:portfolio_id>/edit", methods=["GET", "POST"])
@login_required
def edit_portfolio(portfolio_id):
    try:
        portfolio = get_portfolio(session["user_id"], portfolio_id)
        if not portfolio:
            flash("Portfolio not found.", "error")
            return redirect(url_for("main.dashboard"))

        if request.method == "POST":
            name, status = _portfolio_form_data()
            update_portfolio(session["user_id"], portfolio_id, name, status)
            flash("Portfolio updated.", "success")
            return redirect(url_for("portfolios.edit_portfolio", portfolio_id=portfolio_id))
    except ValueError as exc:
        flash(str(exc), "error")
    except DatabaseError:
        current_app.logger.exception("Could not load or update portfolio")
        flash("That portfolio could not be loaded.", "error")
        return redirect(url_for("main.dashboard"))

    return render_template("portfolio_form.html", portfolio=portfolio)


@portfolios_bp.get("/<uuid:portfolio_id>/preview")
@login_required
def preview_portfolio(portfolio_id):
    try:
        builder_state = get_builder_data(session["user_id"], portfolio_id)
        if not builder_state:
            flash("Portfolio not found.", "error")
            return redirect(url_for("main.dashboard"))
    except DatabaseError:
        current_app.logger.exception("Could not load portfolio preview")
        flash("That portfolio could not be previewed.", "error")
        return redirect(url_for("main.dashboard"))
    return render_template("portfolio_preview.html", portfolio=builder_state["portfolio"])


@portfolios_bp.get("/<uuid:portfolio_id>/preview/content")
@login_required
def preview_content(portfolio_id):
    try:
        builder_state = get_builder_data(session["user_id"], portfolio_id)
        if not builder_state:
            flash("Portfolio not found.", "error")
            return redirect(url_for("main.dashboard"))
        rendered = render_portfolio(builder_state)
    except (DatabaseError, RendererError):
        current_app.logger.exception("Portfolio rendering failed")
        return "Portfolio rendering is temporarily unavailable.", 503
    response = make_response(rendered)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline' https: data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://unpkg.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com https://unpkg.com data:; "
        "img-src 'self' https: http: data:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://unpkg.com https://cdn.jsdelivr.net; "
        "frame-ancestors 'self'"
    )
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@portfolios_bp.get("/<uuid:portfolio_id>/download")
@login_required
def download_portfolio(portfolio_id):
    try:
        builder_state = get_builder_data(session["user_id"], portfolio_id)
        if not builder_state:
            flash("Portfolio not found.", "error")
            return redirect(url_for("main.dashboard"))
        archive_buffer, filename = create_portfolio_export(builder_state)
        return send_file(
            archive_buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/zip",
        )
    except ExportError as exc:
        current_app.logger.exception("Portfolio export failed")
        flash(f"Could not export portfolio: {str(exc)}", "error")
        return redirect(url_for("portfolios.preview_portfolio", portfolio_id=portfolio_id))
    except DatabaseError:
        current_app.logger.exception("Could not export portfolio")
        flash("Portfolio export is temporarily unavailable.", "error")
        return redirect(url_for("portfolios.preview_portfolio", portfolio_id=portfolio_id))


@portfolios_bp.post("/<uuid:portfolio_id>/duplicate")
@login_required
def duplicate(portfolio_id):
    try:
        new_id = duplicate_portfolio(session["user_id"], portfolio_id)
    except DatabaseError:
        current_app.logger.exception("Could not duplicate portfolio")
        flash("That portfolio could not be duplicated.", "error")
        return redirect(url_for("main.dashboard"))

    if not new_id:
        flash("Portfolio not found.", "error")
        return redirect(url_for("main.dashboard"))
    flash("Portfolio duplicated.", "success")
    return redirect(url_for("portfolios.builder", portfolio_id=new_id))


@portfolios_bp.post("/<uuid:portfolio_id>/delete")
@login_required
def remove(portfolio_id):
    try:
        deleted = delete_portfolio(session["user_id"], portfolio_id)
    except DatabaseError:
        current_app.logger.exception("Could not delete portfolio")
        flash("That portfolio could not be deleted.", "error")
        return redirect(url_for("main.dashboard"))

    flash("Portfolio deleted." if deleted else "Portfolio not found.", "success" if deleted else "error")
    return redirect(url_for("main.dashboard"))


def _portfolio_form_data():
    name = request.form.get("name", "").strip()
    status = request.form.get("status", "draft").strip().lower()
    if not name:
        raise ValueError("Portfolio name is required.")
    if len(name) > 150:
        raise ValueError("Portfolio name must be 150 characters or fewer.")
    if status not in STATUS_VALUES:
        raise ValueError("Choose a valid portfolio status.")
    return name, status
