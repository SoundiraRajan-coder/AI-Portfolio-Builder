import json
from datetime import date
from uuid import UUID
from urllib.parse import urlparse

from app.database import get_db_connection
from app.services.design_spec import validate_portfolio_spec
from app.services.portfolios import STATUS_VALUES

SECTION_ORDER = ["about", "skills", "education", "experience", "projects", "certifications", "social"]

RECORDS = {
    "skills": {
        "table": "skills",
        "join_table": "portfolio_skills",
        "join_id": "skill_id",
        "columns": "id, name, category, proficiency",
    },
    "education": {
        "table": "education",
        "join_table": "portfolio_education",
        "join_id": "education_id",
        "columns": "id, institution, degree, field_of_study, start_date, end_date, is_current, description",
    },
    "experience": {
        "table": "work_experiences",
        "join_table": "portfolio_experiences",
        "join_id": "experience_id",
        "columns": "id, company_name, job_title, location, start_date, end_date, is_current, description",
    },
    "projects": {
        "table": "projects",
        "join_table": "portfolio_projects",
        "join_id": "project_id",
        "columns": "id, name, summary, description, project_url, repository_url, start_date, end_date, is_current",
    },
    "certifications": {
        "table": "certifications",
        "join_table": "portfolio_certifications",
        "join_id": "certification_id",
        "columns": "id, name, issuing_organization, issue_date, expiration_date, credential_id, credential_url",
    },
}


class PortfolioNotFoundError(ValueError):
    """Raised when a portfolio is not owned by the authenticated user."""


def get_builder_data(user_id, portfolio_id):
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                  SELECT p.id, p.name, p.status,
                       COALESCE(pm.metadata, '{}'::jsonb),
                       COALESCE(ds.specification, '{}'::jsonb)
                FROM portfolios AS p
                LEFT JOIN portfolio_metadata AS pm
                    ON pm.portfolio_id = p.id AND pm.user_id = p.user_id
                LEFT JOIN portfolio_design_specs AS ds
                    ON ds.portfolio_id = p.id AND ds.user_id = p.user_id
                WHERE p.id = %s AND p.user_id = %s
                """,
                (portfolio_id, user_id),
            )
            portfolio_row = cursor.fetchone()
            if not portfolio_row:
                return None

            cursor.execute(
                """
                SELECT u.display_name, u.email, u.avatar_url, p.headline, p.phone,
                       p.bio, p.location, p.github_url, p.linkedin_url, p.website_url
                FROM users AS u
                LEFT JOIN user_profiles AS p ON p.user_id = u.id
                WHERE u.id = %s
                """,
                (user_id,),
            )
            profile_row = cursor.fetchone()
            if not profile_row:
                return None
            metadata = _metadata_dict(portfolio_row[3])
            records = {}
            selected = {}
            for kind, definition in RECORDS.items():
                cursor.execute(
                    f"SELECT {definition['columns']} FROM {definition['table']} WHERE user_id = %s ORDER BY display_order, created_at DESC",
                    (user_id,),
                )
                records[kind] = [_serialize_record(kind, row) for row in cursor.fetchall()]
                cursor.execute(
                    f"SELECT {definition['join_id']} FROM {definition['join_table']} WHERE portfolio_id = %s AND user_id = %s ORDER BY display_order",
                    (portfolio_id, user_id),
                )
                selected[kind] = [str(row[0]) for row in cursor.fetchall()]

    custom_items = _normalize_custom_items(metadata.get("custom_items", {}))
    for kind, items in custom_items.items():
        records.setdefault(kind, []).extend(items)

    if not metadata.get("builder_initialized"):
        selected = {kind: [item["id"] for item in items] for kind, items in records.items()}
    else:
        custom_selection = {kind: list(dict.fromkeys(metadata.get("custom_item_selection", {}).get(kind, []))) for kind in RECORDS}
        for kind, ids in custom_selection.items():
            selected.setdefault(kind, []).extend([item_id for item_id in ids if item_id not in selected.get(kind, [])])

    content_overrides = metadata.get("content_overrides", {})
    overrides = content_overrides
    wizard_metadata = metadata.get("wizard", {})
    if not isinstance(wizard_metadata, dict):
        wizard_metadata = {}

    # Check if essential sections (profile, skills, education, experience, projects) are missing
    prof_info = wizard_metadata.get("profile", {})
    prof_sec = wizard_metadata.get("professional", {})
    port_sec = wizard_metadata.get("portfolio", {})
    
    needs_recovery = (
        not prof_info.get("name")
        or not prof_info.get("photo_url")
        or not prof_sec.get("skills")
        or not prof_sec.get("education")
        or not port_sec.get("projects")
    )

    if needs_recovery:
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT pm.metadata->'wizard'
                    FROM portfolio_metadata AS pm
                    JOIN portfolios AS p ON p.id = pm.portfolio_id AND p.user_id = pm.user_id
                    WHERE pm.user_id = %s AND pm.portfolio_id != %s AND pm.metadata ? 'wizard'
                    ORDER BY p.updated_at DESC
                    LIMIT 5
                    """,
                    (user_id, portfolio_id),
                )
                for prev_row in cursor.fetchall():
                    if prev_row and prev_row[0]:
                        prev_wizard = _metadata_dict(prev_row[0])
                        if isinstance(prev_wizard, dict):
                            # Merge profile
                            prev_profile = prev_wizard.get("profile", {})
                            if isinstance(prev_profile, dict):
                                if "profile" not in wizard_metadata or not isinstance(wizard_metadata["profile"], dict):
                                    wizard_metadata["profile"] = {}
                                for k, v in prev_profile.items():
                                    if not wizard_metadata["profile"].get(k) and v:
                                        wizard_metadata["profile"][k] = v

                            # Merge professional
                            prev_prof = prev_wizard.get("professional", {})
                            if isinstance(prev_prof, dict):
                                if "professional" not in wizard_metadata or not isinstance(wizard_metadata["professional"], dict):
                                    wizard_metadata["professional"] = {}
                                cur_p = wizard_metadata["professional"]
                                if not cur_p.get("skills") and prev_prof.get("skills"):
                                    cur_p["skills"] = list(prev_prof["skills"])
                                if not cur_p.get("education") and prev_prof.get("education"):
                                    cur_p["education"] = list(prev_prof["education"])
                                if not cur_p.get("experience") and prev_prof.get("experience"):
                                    cur_p["experience"] = list(prev_prof["experience"])
                                if not cur_p.get("certifications") and prev_prof.get("certifications"):
                                    cur_p["certifications"] = list(prev_prof["certifications"])
                                if not cur_p.get("achievements") and prev_prof.get("achievements"):
                                    cur_p["achievements"] = list(prev_prof["achievements"])

                            # Merge portfolio
                            prev_port = prev_wizard.get("portfolio", {})
                            if isinstance(prev_port, dict):
                                if "portfolio" not in wizard_metadata or not isinstance(wizard_metadata["portfolio"], dict):
                                    wizard_metadata["portfolio"] = {}
                                cur_port = wizard_metadata["portfolio"]
                                if not cur_port.get("projects") and prev_port.get("projects"):
                                    cur_port["projects"] = list(prev_port["projects"])
                                if not cur_port.get("design_prompt") and prev_port.get("design_prompt"):
                                    cur_port["design_prompt"] = prev_port["design_prompt"]
                                if not cur_port.get("design_preferences") and prev_port.get("design_preferences"):
                                    cur_port["design_preferences"] = prev_port["design_preferences"]

    wizard = _normalize_wizard_data(wizard_metadata, profile_row, records)
    # Normalize legacy flat records at runtime; no stored specification is changed.
    design_spec = validate_portfolio_spec(portfolio_row[4], wizard)
    return {
        "portfolio": {
            "id": str(portfolio_row[0]),
            "name": portfolio_row[1],
            "status": portfolio_row[2],
        },
        "profile": {
            "name": profile_row[0] or "",
            "email": profile_row[1] or "",
            "avatar_url": profile_row[2] or "",
            "headline": profile_row[3] or "",
            "phone": profile_row[4] or "",
            "bio": profile_row[5] or "",
            "location": profile_row[6] or "",
            "github_url": profile_row[7] or "",
            "linkedin_url": profile_row[8] or "",
            "website_url": profile_row[9] or "",
        },
        "records": records,
        "selected": selected,
        "overrides": overrides,
        "content_overrides": content_overrides,
        "custom_items": custom_items,
        "wizard": wizard,
        "ai_overrides": metadata.get("ai_overrides", {}),
        "design_spec": design_spec,
        "section_order": _section_order(metadata.get("section_order")),
        "hidden_sections": _hidden_sections(metadata.get("hidden_sections")),
    }


def save_builder_data(user_id, portfolio_id, payload):
    name = _text(payload.get("portfolio_name"), "Portfolio name", 150, required=True)
    status = payload.get("status", "draft")
    if status not in STATUS_VALUES:
        raise ValueError("Choose a valid portfolio status.")
    overrides = _validate_overrides(payload.get("overrides", {}))
    content_overrides = _validate_content_overrides(payload.get("content_overrides", {}))
    custom_items = _validate_custom_items(payload.get("custom_items", {}))
    ai_overrides = _validate_ai_overrides(payload.get("ai_overrides", {}))
    wizard = _validate_wizard(payload.get("wizard", {}))
    section_order = _section_order(payload.get("section_order"))
    hidden_sections = _hidden_sections(payload.get("hidden_sections"))
    selected, custom_selected = _validate_selected(user_id, payload.get("selected", {}), custom_items)
    metadata = {
        "builder_initialized": True,
        "content_overrides": content_overrides,
        "custom_items": custom_items,
        "custom_item_selection": custom_selected,
        "ai_overrides": ai_overrides,
        "wizard": wizard,
        "section_order": section_order,
        "hidden_sections": hidden_sections,
    }

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE portfolios
                SET name = %s, status = %s, updated_at = timezone('utc', now())
                WHERE id = %s AND user_id = %s
                """,
                (name, status, portfolio_id, user_id),
            )
            if cursor.rowcount == 0:
                raise PortfolioNotFoundError("Portfolio not found.")
            cursor.execute(
                """
                INSERT INTO portfolio_metadata (portfolio_id, user_id, metadata)
                VALUES (%s, %s, %s)
                ON CONFLICT (portfolio_id) DO UPDATE SET
                    metadata = EXCLUDED.metadata,
                    updated_at = timezone('utc', now())
                """,
                (portfolio_id, user_id, json.dumps(metadata)),
            )
            for kind, definition in RECORDS.items():
                cursor.execute(
                    f"DELETE FROM {definition['join_table']} WHERE portfolio_id = %s AND user_id = %s",
                    (portfolio_id, user_id),
                )
                custom_ids = set(custom_selected.get(kind, []))
                existing_selected = [item_id for item_id in selected[kind] if item_id not in custom_ids]
                for display_order, item_id in enumerate(existing_selected):
                    cursor.execute(
                        f"INSERT INTO {definition['join_table']} (portfolio_id, user_id, {definition['join_id']}, display_order) VALUES (%s, %s, %s, %s)",
                        (portfolio_id, user_id, item_id, display_order),
                    )
        connection.commit()

    return {"name": name, "status": status, "section_order": section_order, "hidden_sections": hidden_sections}


def _validate_selected(user_id, selected, custom_items=None):
    if not isinstance(selected, dict):
        return {}, {}
    custom_items = custom_items or {}
    validated = {}
    custom_selection = {}
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            for kind, definition in RECORDS.items():
                values = selected.get(kind, [])
                if not isinstance(values, list):
                    values = []
                cursor.execute(
                    f"SELECT id FROM {definition['table']} WHERE user_id = %s",
                    (user_id,),
                )
                owned_ids_str = {str(row[0]) for row in cursor.fetchall()}
                custom_ids_str = {str(item['id']) for item in custom_items.get(kind, []) if isinstance(item, dict) and item.get('id')}
                
                validated[kind] = [str(val) for val in values if str(val) in owned_ids_str]
                custom_selection[kind] = [str(val) for val in values if str(val) in custom_ids_str]
    return validated, custom_selection


def _validate_overrides(overrides):
    if not isinstance(overrides, dict):
        raise ValueError("Portfolio-specific content must be an object.")
    allowed = {"name": 150, "headline": 180, "location": 150, "bio": 2000, "github_url": 500, "linkedin_url": 500, "website_url": 500}
    result = {}
    for field, limit in allowed.items():
        value = _text(overrides.get(field), field, limit)
        if field.endswith("_url") and value:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"{field} must be a valid http or https URL.")
        result[field] = value or ""
    return result


def _validate_content_overrides(content_overrides):
    if not isinstance(content_overrides, dict):
        raise ValueError("Content overrides must be an object.")
    result = {}
    for kind, items in content_overrides.items():
        if kind not in RECORDS:
            raise ValueError("Unsupported content override section.")
        if not isinstance(items, dict):
            raise ValueError("Content overrides must map item IDs to override fields.")
        result[kind] = {}
        for item_id, overrides in items.items():
            if not isinstance(overrides, dict):
                raise ValueError("Each content override must be an object.")
            safe_fields = {
                "skills": {"name"},
                "education": {"description"},
                "experience": {"description"},
                "projects": {"summary", "description"},
                "certifications": {"name"},
            }
            allowed_fields = safe_fields.get(kind, set())
            item_override = {}
            for field, value in overrides.items():
                if field not in allowed_fields:
                    continue
                if not isinstance(value, str):
                    raise ValueError("Override values must be strings.")
                item_override[field] = _text(value, field, 6000)
            if item_override:
                result[kind][str(item_id)] = item_override
    return result


def _normalize_custom_items(value):
    if not isinstance(value, dict):
        return {}
    normalized = {}
    for kind, items in value.items():
        if kind not in RECORDS or not isinstance(items, list):
            continue
        valid_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if not item_id or not isinstance(item_id, str) or len(item_id) > 80:
                continue
            normalized_item = {"id": item_id}
            for field, field_value in item.items():
                if field == "id":
                    continue
                normalized_item[field] = field_value
            valid_items.append(normalized_item)
        if valid_items:
            normalized[kind] = valid_items
    return normalized


def _validate_custom_items(custom_items):
    if not isinstance(custom_items, dict):
        raise ValueError("Custom portfolio items must be an object.")
    result = {}
    allowed_fields = {
        "skills": {"id", "name", "category", "proficiency"},
        "education": {"id", "institution", "degree", "field_of_study", "start_date", "end_date", "is_current", "description"},
        "experience": {"id", "company_name", "job_title", "location", "start_date", "end_date", "is_current", "description"},
        "projects": {"id", "name", "summary", "description", "project_url", "repository_url", "start_date", "end_date", "is_current"},
        "certifications": {"id", "name", "issuing_organization", "issue_date", "expiration_date", "credential_id", "credential_url"},
    }
    for kind, items in custom_items.items():
        if kind not in RECORDS:
            raise ValueError("Unsupported custom item section.")
        if not isinstance(items, list):
            raise ValueError("Custom items must be a list.")
        validated_items = []
        existing_ids = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Each custom item must be an object.")
            item_id = item.get("id")
            if not item_id or not isinstance(item_id, str) or len(item_id) > 80:
                raise ValueError("Each custom item must have a valid string id.")
            if item_id in existing_ids:
                raise ValueError("Custom item IDs must be unique per section.")
            existing_ids.add(item_id)
            validated_item = {"id": item_id}
            for field, value in item.items():
                if field == "id":
                    continue
                if field not in allowed_fields.get(kind, set()):
                    continue
                if isinstance(value, bool) and field == "is_current":
                    validated_item[field] = value
                    continue
                if not isinstance(value, str):
                    raise ValueError("Custom item values must be strings for text fields.")
                limit = 6000 if field in {"summary", "description"} else 500
                validated_item[field] = _text(value, field, limit)
            validated_items.append(validated_item)
        result[kind] = validated_items
    return result


def _validate_ai_overrides(overrides):
    if not isinstance(overrides, dict):
        raise ValueError("AI overrides must be an object.")
    result = {}
    for task in ("bio", "project", "skills", "experience", "education"):
        value = overrides.get(task)
        if value is None:
            continue
        if task == "bio":
            if not isinstance(value, str) or len(value) > 6000:
                raise ValueError("AI bio content is invalid.")
            result[task] = value
            continue
        if not isinstance(value, dict) or any(len(str(key)) > 80 or not isinstance(content, str) or len(content) > 6000 for key, content in value.items()):
            raise ValueError(f"AI {task} content is invalid.")
        result[task] = {str(key): content for key, content in value.items()}
    return result


def _validate_wizard(wizard):
    if wizard is None:
        return {}
    if not isinstance(wizard, dict):
        raise ValueError("Wizard data must be an object.")
    return {
        "profile": _validate_wizard_profile(wizard.get("profile", {})),
        "professional": _validate_wizard_professional(wizard.get("professional", {})),
        "portfolio": _validate_wizard_portfolio(wizard.get("portfolio", {})),
    }


def _normalize_wizard_data(wizard_metadata, profile_row, records=None):
    if not isinstance(wizard_metadata, dict):
        wizard_metadata = {}
    profile = wizard_metadata.get("profile", {}) if isinstance(wizard_metadata.get("profile", {}), dict) else {}
    professional = wizard_metadata.get("professional", {}) if isinstance(wizard_metadata.get("professional", {}), dict) else {}
    portfolio = wizard_metadata.get("portfolio", {}) if isinstance(wizard_metadata.get("portfolio", {}), dict) else {}
    records = records or {}

    # Recover skills
    skills_list = professional.get("skills")
    if not skills_list and records.get("skills"):
        skills_list = [item["name"] for item in records["skills"] if isinstance(item, dict) and item.get("name")]
    if not isinstance(skills_list, list):
        skills_list = []

    # Recover education
    edu_list = professional.get("education")
    if not edu_list and records.get("education"):
        edu_list = []
        for item in records["education"]:
            if isinstance(item, dict) and (item.get("institution") or item.get("degree")):
                start_year = str(item.get("start_date", ""))[:4] if item.get("start_date") else ""
                end_year = str(item.get("end_date", ""))[:4] if item.get("end_date") else ""
                edu_list.append({
                    "id": str(item.get("id") or ""),
                    "degree": item.get("degree") or item.get("field_of_study") or "",
                    "institution": item.get("institution") or "",
                    "start_year": start_year,
                    "end_year": end_year,
                    "grade": item.get("grade") or "",
                    "description": item.get("description") or "",
                })
    if not isinstance(edu_list, list):
        edu_list = []

    # Recover experience
    exp_list = professional.get("experience")
    if not exp_list and records.get("experience"):
        exp_list = []
        for item in records["experience"]:
            if isinstance(item, dict) and (item.get("job_title") or item.get("company_name")):
                exp_list.append({
                    "id": str(item.get("id") or ""),
                    "job_title": item.get("job_title") or "",
                    "company_name": item.get("company_name") or "",
                    "employment_type": item.get("employment_type") or "",
                    "location": item.get("location") or "",
                    "start_date": str(item.get("start_date") or ""),
                    "end_date": str(item.get("end_date") or ""),
                    "currently_working": bool(item.get("is_current")),
                    "description": item.get("description") or "",
                    "responsibilities": item.get("responsibilities") or "",
                })
    if not isinstance(exp_list, list):
        exp_list = []

    # Recover projects
    proj_list = portfolio.get("projects")
    if not proj_list and records.get("projects"):
        proj_list = []
        for item in records["projects"]:
            if isinstance(item, dict) and (item.get("name") or item.get("summary")):
                proj_list.append({
                    "id": str(item.get("id") or ""),
                    "name": item.get("name") or "",
                    "short_description": item.get("summary") or "",
                    "description": item.get("description") or "",
                    "technologies": item.get("technologies") or "",
                    "project_url": item.get("project_url") or "",
                    "repository_url": item.get("repository_url") or "",
                    "demo_url": item.get("demo_url") or "",
                    "start_date": str(item.get("start_date") or ""),
                    "end_date": str(item.get("end_date") or ""),
                    "key_features": item.get("key_features") or "",
                    "role": item.get("role") or "",
                })
    if not isinstance(proj_list, list):
        proj_list = []

    # Recover certifications
    cert_list = professional.get("certifications")
    if not cert_list and records.get("certifications"):
        cert_list = [{"name": item["name"]} for item in records["certifications"] if isinstance(item, dict) and item.get("name")]
    if not isinstance(cert_list, list):
        cert_list = []

    normalized_profile = {
        "name": profile.get("name") or profile_row[0] or "",
        "professional_title": profile.get("professional_title") or profile_row[3] or "",
        "introduction": profile.get("introduction") or profile_row[5] or "",
        # A Google/profile avatar is the safe default when the wizard has not
        # been given a dedicated portfolio photo.
        "photo_url": profile.get("photo_url") or profile_row[2] or "",
        "email": profile.get("email") or profile_row[1] or "",
        "phone": profile.get("phone") or profile_row[4] or "",
        "location": profile.get("location") or profile_row[6] or "",
        "date_of_birth": profile.get("date_of_birth", ""),
        "website_url": profile.get("website_url") or profile_row[9] or "",
        "github_url": profile.get("github_url") or profile_row[7] or "",
        "linkedin_url": profile.get("linkedin_url") or profile_row[8] or "",
        "resume_url": profile.get("resume_url", ""),
        "other_links": profile.get("other_links", []),
    }
    return {
        "profile": normalized_profile,
        "professional": {
            "skills": skills_list,
            "education": edu_list,
            "experience": exp_list,
            "certifications": cert_list,
            "achievements": professional.get("achievements", []),
        },
        "portfolio": {
            "projects": proj_list,
            "services": portfolio.get("services", []),
            "interests": portfolio.get("interests", []),
            "languages": portfolio.get("languages", []),
            "custom_sections": portfolio.get("custom_sections", []),
            "overview": portfolio.get("overview", ""),
            "design_prompt": portfolio.get("design_prompt", ""),
            "design_preferences": portfolio.get("design_preferences", {}),
        },
    }


def _validate_wizard_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError("Personal information must be an object.")
    result = {
        "name": _text(profile.get("name"), "Full name", 150),
        "professional_title": _text(profile.get("professional_title"), "Professional title", 180),
        "introduction": _text(profile.get("introduction"), "Short introduction", 2000),
        "photo_url": _text(profile.get("photo_url"), "Profile photo URL", 500),
        "email": _text(profile.get("email"), "Email", 320),
        "phone": _text(profile.get("phone"), "Phone", 40),
        "location": _text(profile.get("location"), "Location", 150),
        "date_of_birth": _text(profile.get("date_of_birth"), "Date of birth", 20),
        "website_url": _text(profile.get("website_url"), "Website URL", 500),
        "github_url": _text(profile.get("github_url"), "GitHub URL", 500),
        "linkedin_url": _text(profile.get("linkedin_url"), "LinkedIn URL", 500),
        "resume_url": _text(profile.get("resume_url"), "Resume URL", 500),
        "other_links": profile.get("other_links", []),
    }
    if result["photo_url"]:
        _validate_url(result["photo_url"], "Profile photo URL")
    if result["resume_url"]:
        _validate_url(result["resume_url"], "Resume URL")
    for field in ("website_url", "github_url", "linkedin_url"):
        if result[field]:
            _validate_url(result[field], field.replace("_", " ").title())
    if result["date_of_birth"]:
        _validate_date(result["date_of_birth"], "Date of birth")
    result["other_links"] = _validate_link_list(result["other_links"])
    return result


def _validate_wizard_professional(professional):
    if not isinstance(professional, dict):
        raise ValueError("Professional information must be an object.")
    return {
        "skills": _validate_string_list(professional.get("skills", []), "skills", 100),
        "education": _validate_education_list(professional.get("education", [])),
        "experience": _validate_experience_list(professional.get("experience", [])),
        "certifications": _validate_certification_list(professional.get("certifications", [])),
        "achievements": _validate_achievement_list(professional.get("achievements", [])),
    }


def _validate_wizard_portfolio(portfolio):
    if not isinstance(portfolio, dict):
        raise ValueError("Portfolio information must be an object.")
    return {
        "projects": _validate_project_list(portfolio.get("projects", [])),
        "services": _validate_service_list(portfolio.get("services", [])),
        "interests": _validate_string_list(portfolio.get("interests", []), "interests", 100),
        "languages": _validate_language_list(portfolio.get("languages", [])),
        "custom_sections": _validate_custom_section_list(portfolio.get("custom_sections", [])),
        "overview": _text(portfolio.get("overview"), "Portfolio overview", 2000),
        "design_prompt": _text(portfolio.get("design_prompt"), "Design prompt", 4000),
        "design_preferences": _validate_design_preferences(portfolio.get("design_preferences", {})),
    }


def _validate_string_list(value, label, limit):
    if not isinstance(value, list):
        raise ValueError(f"{label.title()} must be a list.")
    validated = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"Each {label} entry must be text.")
        item = item.strip()
        if item:
            if len(item) > limit:
                raise ValueError(f"Each {label} entry must be {limit} characters or fewer.")
            validated.append(item)
    return validated


def _validate_link_list(links):
    if not isinstance(links, list):
        raise ValueError("Other links must be a list.")
    validated = []
    for item in links:
        if not isinstance(item, dict):
            raise ValueError("Each link must be an object with label and URL.")
        label = _text(item.get("label"), "Link label", 80)
        url = _text(item.get("url"), "Link URL", 500)
        if label and url:
            _validate_url(url, "Link URL")
            validated.append({"label": label, "url": url})
    return validated


def _validate_education_list(entries):
    if not isinstance(entries, list):
        return []
    validated = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        record = {
            "id": _text(entry.get("id"), "ID", 100),
            "degree": _text(entry.get("degree"), "Degree", 150),
            "institution": _text(entry.get("institution"), "Institution", 200),
            "start_year": _text(entry.get("start_year"), "Start year", 10),
            "end_year": _text(entry.get("end_year"), "End year", 10),
            "grade": _text(entry.get("grade"), "Grade / CGPA", 50),
            "description": _text(entry.get("description"), "Education description", 1200),
        }
        validated.append(record)
    return validated


def _validate_experience_list(entries):
    if not isinstance(entries, list):
        return []
    valid_types = {"Internship", "Full-time", "Part-time", "Freelance", "Contract", ""}
    validated = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        record = {
            "id": _text(entry.get("id"), "ID", 100),
            "job_title": _text(entry.get("job_title"), "Job title", 180),
            "company_name": _text(entry.get("company_name"), "Company", 200),
            "employment_type": _text(entry.get("employment_type"), "Employment type", 50),
            "start_date": _text(entry.get("start_date"), "Start date", 20),
            "end_date": _text(entry.get("end_date"), "End date", 20),
            "currently_working": bool(entry.get("currently_working")),
            "location": _text(entry.get("location"), "Location", 150),
            "description": _text(entry.get("description"), "Experience description", 1500),
            "responsibilities": _text(entry.get("responsibilities"), "Responsibilities", 1500),
        }
        if record["employment_type"] and record["employment_type"] not in valid_types:
            record["employment_type"] = ""
        if record["currently_working"]:
            record["end_date"] = ""
        validated.append(record)
    return validated


def _validate_certification_list(entries):
    if not isinstance(entries, list):
        return []
    validated = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        record = {
            "id": _text(entry.get("id"), "ID", 100),
            "name": _text(entry.get("name"), "Certification name", 200),
            "issuing_organization": _text(entry.get("issuing_organization"), "Issuing organization", 200),
            "issue_date": _text(entry.get("issue_date"), "Issue date", 20),
            "expiration_date": _text(entry.get("expiration_date"), "Expiration date", 20),
            "credential_id": _text(entry.get("credential_id"), "Credential ID", 200),
            "credential_url": _text(entry.get("credential_url"), "Credential URL", 500),
        }
        if record["name"] or record["issuing_organization"] or record["credential_id"]:
            validated.append(record)
    return validated


def _validate_achievement_list(entries):
    if not isinstance(entries, list):
        return []
    validated = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        record = {
            "id": _text(entry.get("id"), "ID", 100),
            "title": _text(entry.get("title"), "Achievement title", 200),
            "organization": _text(entry.get("organization"), "Organization", 200),
            "date": _text(entry.get("date"), "Date", 20),
            "description": _text(entry.get("description"), "Description", 1200),
        }
        if record["title"] or record["organization"] or record["description"]:
            validated.append(record)
    return validated


def _validate_project_list(entries):
    if not isinstance(entries, list):
        return []
    validated = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        record = {
            "id": _text(entry.get("id"), "ID", 100),
            "name": _text(entry.get("name"), "Project name", 200),
            "short_description": _text(entry.get("short_description"), "Short description", 500),
            "description": _text(entry.get("description"), "Detailed description", 2000),
            "technologies": _text(entry.get("technologies"), "Technologies", 400),
            "category": _text(entry.get("category"), "Category", 150),
            "project_url": _text(entry.get("project_url"), "Project URL", 500),
            "repository_url": _text(entry.get("repository_url"), "Repository URL", 500),
            "demo_url": _text(entry.get("demo_url"), "Demo URL", 500),
            "start_date": _text(entry.get("start_date"), "Start date", 20),
            "end_date": _text(entry.get("end_date"), "End date", 20),
            "key_features": _text(entry.get("key_features"), "Key features", 1200),
            "role": _text(entry.get("role"), "Role / contribution", 200),
        }
        validated.append(record)
    return validated


def _validate_service_list(entries):
    if not isinstance(entries, list):
        return []
    validated = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        record = {
            "name": _text(entry.get("name"), "Service name", 150),
            "description": _text(entry.get("description"), "Service description", 500),
        }
        if record["name"] or record["description"]:
            validated.append(record)
    return validated


def _validate_language_list(entries):
    if not isinstance(entries, list):
        return []
    validated = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        record = {
            "language": _text(entry.get("language"), "Language", 100),
            "level": _text(entry.get("level"), "Proficiency", 100),
        }
        if record["language"]:
            validated.append(record)
    return validated


def _validate_custom_section_list(entries):
    if not isinstance(entries, list):
        return []
    validated = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        record = {
            "id": _text(entry.get("id"), "ID", 100),
            "title": _text(entry.get("title"), "Section title", 150),
            "content": _text(entry.get("content"), "Section content", 2000),
        }
        validated.append(record)
    return validated


def _validate_design_preferences(preferences):
    if not isinstance(preferences, dict):
        raise ValueError("Design preferences must be an object.")
    themes = {
        "auto", "none", "", "dark", "light", "milk_green", "emerald", "indigo",
        "cyan", "crimson", "violet", "amber", "monochrome", "nordic"
    }
    styles = {
        "auto", "none", "", "modern", "minimal", "glassmorphism", "terminal",
        "creative", "professional", "futuristic"
    }
    animations = {
        "auto", "none", "", "smooth", "moderate", "dynamic", "interactive", "subtle", "rich"
    }
    theme = preferences.get("theme") if preferences.get("theme") in themes else "auto"
    style = preferences.get("style") if preferences.get("style") in styles else "auto"
    animation = preferences.get("animation") if preferences.get("animation") in animations else "auto"
    return {"theme": theme, "style": style, "animation": animation}


def _validate_date(value, label):
    if not value:
        return ""
    val_str = str(value).strip()
    try:
        return date.fromisoformat(val_str).isoformat()
    except ValueError:
        import re
        # Allow YYYY, YYYY-MM, MM/YYYY, DD/MM/YYYY, or short valid date strings
        if re.match(r"^(\d{4}(-\d{2}(-\d{2})?)?|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}/\d{4}|\d{4})$", val_str):
            return val_str
        if len(val_str) <= 20:
            return val_str
        raise ValueError(f"{label} must be a valid date.")


def _validate_url(value, label):
    if not value:
        return
    if value.startswith("/static/") or value.startswith("data:"):
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} must be a valid http or https URL.")


def _section_order(value):
    if value is None:
        return SECTION_ORDER.copy()
    if not isinstance(value, list) or len(value) != len(SECTION_ORDER) or set(value) != set(SECTION_ORDER):
        raise ValueError("Sections must contain each builder section exactly once.")
    return value


def _hidden_sections(value):
    if value is None:
        return []
    if not isinstance(value, list) or any(section not in SECTION_ORDER for section in value):
        raise ValueError("Hidden sections contain an invalid section.")
    return list(dict.fromkeys(value))


def _clean_field_text(value):
    """Safely unwraps nested dictionary or stringified dictionary structures and extracts clean string content."""
    if value is None:
        return ""
    if isinstance(value, dict):
        for candidate_key in ("name", "language", "title", "content", "value", "text", "description"):
            if candidate_key in value and value[candidate_key]:
                return _clean_field_text(value[candidate_key])
        for v in value.values():
            if v:
                return _clean_field_text(v)
        return ""
    val_str = str(value).strip()
    if val_str.startswith("{") and val_str.endswith("}"):
        import ast
        try:
            parsed = ast.literal_eval(val_str)
            if isinstance(parsed, dict):
                return _clean_field_text(parsed)
        except Exception:
            pass
    return val_str


def _text(value, label, limit, required=False):
    value = _clean_field_text(value)
    if required and not value:
        raise ValueError(f"{label} is required.")
    if len(value) > limit:
        value = value[:limit].strip()
    return value


def _metadata_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _serialize_record(kind, row):
    fields = {
        "skills": ["id", "name", "category", "proficiency"],
        "education": ["id", "institution", "degree", "field_of_study", "start_date", "end_date", "is_current", "description"],
        "experience": ["id", "company_name", "job_title", "location", "start_date", "end_date", "is_current", "description"],
        "projects": ["id", "name", "summary", "description", "project_url", "repository_url", "start_date", "end_date", "is_current"],
        "certifications": ["id", "name", "issuing_organization", "issue_date", "expiration_date", "credential_id", "credential_url"],
    }[kind]
    result = {}
    for field, value in zip(fields, row):
        result[field] = value.isoformat() if hasattr(value, "isoformat") else (str(value) if field == "id" and value else value)
    return result
