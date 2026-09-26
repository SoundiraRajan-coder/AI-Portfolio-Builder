from datetime import date
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from app.database import DatabaseError
from app.routes.auth import login_required
from app.services.profile import (
    ITEM_DEFINITIONS,
    create_item,
    delete_item,
    get_profile_page_data,
    save_profile_details,
    update_item,
)

profile_bp = Blueprint("profile", __name__)

MAX_LENGTHS = {
    "display_name": 150,
    "avatar_url": 500,
    "headline": 180,
    "phone": 40,
    "bio": 2000,
    "location": 150,
    "github_url": 500,
    "linkedin_url": 500,
    "website_url": 500,
}


@profile_bp.get("/profile")
@login_required
def profile_page():
    try:
        data = get_profile_page_data(session["user_id"])
    except DatabaseError:
        current_app.logger.exception("Could not load profile data")
        flash("Your profile could not be loaded right now.", "error")
        return redirect(url_for("main.dashboard"))

    if not data:
        session.clear()
        flash("Please sign in again.", "info")
        return redirect(url_for("auth.login"))

    return render_template("profile.html", **data)


@profile_bp.post("/profile/details")
@login_required
def update_details():
    try:
        profile = _profile_form_data(request.form)
        save_profile_details(session["user_id"], profile)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("profile.profile_page"))
    except DatabaseError:
        current_app.logger.exception("Could not save profile details")
        flash("Your profile details could not be saved.", "error")
        return redirect(url_for("profile.profile_page"))

    flash("Profile details saved.", "success")
    return redirect(url_for("profile.profile_page"))


@profile_bp.post("/profile/<kind>/create")
@login_required
def create_profile_item(kind):
    if kind not in ITEM_DEFINITIONS:
        return redirect(url_for("profile.profile_page"))
    try:
        values = _item_form_data(kind, request.form)
        create_item(session["user_id"], kind, values)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("profile.profile_page"))
    except DatabaseError:
        current_app.logger.exception("Could not create profile item")
        flash("That profile item could not be saved.", "error")
        return redirect(url_for("profile.profile_page"))

    flash(f"{kind.title()} entry added.", "success")
    return redirect(url_for("profile.profile_page"))


@profile_bp.post("/profile/<kind>/<uuid:item_id>/edit")
@login_required
def edit_profile_item(kind, item_id):
    if kind not in ITEM_DEFINITIONS:
        return redirect(url_for("profile.profile_page"))
    try:
        values = _item_form_data(kind, request.form)
        updated = update_item(session["user_id"], kind, item_id, values)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("profile.profile_page"))
    except DatabaseError:
        current_app.logger.exception("Could not update profile item")
        flash("That profile item could not be updated.", "error")
        return redirect(url_for("profile.profile_page"))

    flash("Entry updated." if updated else "Entry not found.", "success" if updated else "error")
    return redirect(url_for("profile.profile_page"))


@profile_bp.post("/profile/<kind>/<uuid:item_id>/delete")
@login_required
def remove_profile_item(kind, item_id):
    if kind not in ITEM_DEFINITIONS:
        return redirect(url_for("profile.profile_page"))
    try:
        deleted = delete_item(session["user_id"], kind, item_id)
    except DatabaseError:
        current_app.logger.exception("Could not delete profile item")
        flash("That profile item could not be deleted.", "error")
        return redirect(url_for("profile.profile_page"))

    flash("Entry deleted." if deleted else "Entry not found.", "success" if deleted else "error")
    return redirect(url_for("profile.profile_page"))


def _profile_form_data(form):
    profile = {
        field: _text(form.get(field), field, MAX_LENGTHS[field])
        for field in MAX_LENGTHS
    }
    if not profile["display_name"]:
        raise ValueError("Full name is required.")
    for field in ("avatar_url", "github_url", "linkedin_url", "website_url"):
        _validate_url(profile[field], field)
    return profile


def _item_form_data(kind, form):
    if kind == "skills":
        name = _text(form.get("name"), "Skill name", 100)
        if not name:
            raise ValueError("Skill name is required.")
        proficiency = _integer(form.get("proficiency"), "Proficiency", 1, 5)
        return {"name": name, "category": _text(form.get("category"), "Category", 100), "proficiency": proficiency}

    if kind == "education":
        values = {
            "institution": _required(form, "institution", "Institution", 200),
            "degree": _text(form.get("degree"), "Degree", 150),
            "field_of_study": _text(form.get("field_of_study"), "Field of study", 150),
            "start_date": _date(form.get("start_date"), "Start date"),
            "end_date": _date(form.get("end_date"), "End date"),
            "is_current": "is_current" in form,
            "description": _text(form.get("description"), "Description", 2000),
        }
        _validate_date_range(values["start_date"], values["end_date"])
        return values

    if kind == "experience":
        values = {
            "company_name": _required(form, "company_name", "Company", 200),
            "job_title": _required(form, "job_title", "Job title", 180),
            "location": _text(form.get("location"), "Location", 150),
            "start_date": _date(form.get("start_date"), "Start date"),
            "end_date": _date(form.get("end_date"), "End date"),
            "is_current": "is_current" in form,
            "description": _text(form.get("description"), "Description", 2000),
        }
        _validate_date_range(values["start_date"], values["end_date"])
        return values

    if kind == "projects":
        values = {
            "name": _required(form, "name", "Project name", 200),
            "summary": _text(form.get("summary"), "Summary", 500),
            "description": _text(form.get("description"), "Description", 3000),
            "project_url": _text(form.get("project_url"), "Project URL", 500),
            "repository_url": _text(form.get("repository_url"), "Repository URL", 500),
            "start_date": _date(form.get("start_date"), "Start date"),
            "end_date": _date(form.get("end_date"), "End date"),
            "is_current": "is_current" in form,
        }
        _validate_url(values["project_url"], "Project URL")
        _validate_url(values["repository_url"], "Repository URL")
        _validate_date_range(values["start_date"], values["end_date"])
        return values

    values = {
        "name": _required(form, "name", "Certification name", 200),
        "issuing_organization": _text(form.get("issuing_organization"), "Issuing organization", 200),
        "issue_date": _date(form.get("issue_date"), "Issue date"),
        "expiration_date": _date(form.get("expiration_date"), "Expiration date"),
        "credential_id": _text(form.get("credential_id"), "Credential ID", 200),
        "credential_url": _text(form.get("credential_url"), "Credential URL", 500),
    }
    _validate_url(values["credential_url"], "Credential URL")
    _validate_date_range(values["issue_date"], values["expiration_date"])
    return values


def _required(form, field, label, limit):
    value = _text(form.get(field), label, limit)
    if not value:
        raise ValueError(f"{label} is required.")
    return value


def _text(value, label, limit):
    value = (value or "").strip()
    if len(value) > limit:
        raise ValueError(f"{label} must be {limit} characters or fewer.")
    return value or None


def _date(value, label):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid date.") from exc


def _integer(value, label, minimum, maximum):
    value = (value or "").strip()
    if not value:
        return None
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}.")
    return number


def _validate_url(value, label):
    if not value:
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} must be a valid http or https URL.")


def _validate_date_range(start, end):
    if start and end and end < start:
        raise ValueError("The end date cannot be earlier than the start date.")
