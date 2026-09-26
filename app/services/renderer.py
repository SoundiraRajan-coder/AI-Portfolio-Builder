from copy import deepcopy
from urllib.parse import urlparse

from flask import current_app, has_request_context, render_template
from jinja2 import TemplateNotFound

from app.services.design_engine import build_design_context
from app.services.design_spec import COMPOSITION_SECTION_KEYS, validate_portfolio_spec, wizard_content


class RendererError(ValueError):
    """Raised when safe portfolio output cannot be prepared."""


def build_render_context(portfolio_data):
    source = deepcopy(portfolio_data if isinstance(portfolio_data, dict) else {})
    wizard = source.get("wizard", {})
    saved_spec = source.get("design_spec", {})
    # Both legacy flat records and current records are normalized by the
    # shared validator before any composition reaches the template.
    spec = validate_portfolio_spec(saved_spec, wizard)
    content = _safe_content(spec["content"])
    design = build_design_context(spec["visual"])
    sections = {
        "about": content.get("about", {}).get("overview") or content.get("about", {}).get("summary"),
        "skills": content.get("skills"), "projects": content.get("projects"), "experience": content.get("experience"),
        "education": content.get("education"), "certifications": content.get("certifications"), "achievements": content.get("achievements"),
        "services": content.get("services"), "languages": content.get("languages"), "custom_sections": content.get("custom_sections"),
        "contact": content.get("other_links") or content.get("profile", {}).get("email"),
    }
    composition = spec["composition"]
    available = {"hero": bool(content.get("profile", {}).get("name")), **sections}
    requested_order = composition.get("section_order", [])
    section_order = [key for key in requested_order if key in COMPOSITION_SECTION_KEYS and available.get(key)]
    modules = [_module_context(key, composition) for key in section_order]
    return {
        "portfolio": source.get("portfolio", {}),
        "content": content,
        "design": design,
        "composition": composition,
        "modules": modules,
        "navigation_links": [item for item in modules if item["key"] not in {"hero", "contact", "custom_sections"}],
    }


def render_portfolio(portfolio_data):
    try:
        source = portfolio_data if isinstance(portfolio_data, dict) else {}
        saved_spec = source.get("design_spec", {})
        if isinstance(saved_spec, dict) and saved_spec.get("custom_html"):
            custom_html = saved_spec["custom_html"]
            if isinstance(custom_html, str) and len(custom_html) > 300 and ("<body" in custom_html.lower() or "<section" in custom_html.lower() or "<main" in custom_html.lower()):
                return custom_html

        context = build_render_context(portfolio_data)
        if not has_request_context() and current_app:
            with current_app.test_request_context("/"):
                return render_template("ai_portfolio.html", portfolio=context)
        return render_template("ai_portfolio.html", portfolio=context)
    except TemplateNotFound as exc:
        raise RendererError("The AI portfolio renderer is missing.") from exc
    except Exception as exc:
        raise RendererError("An error occurred while rendering the portfolio.") from exc


def _safe_content(content):
    content = deepcopy(content if isinstance(content, dict) else {})
    profile = content.setdefault("profile", {})
    for key in ("photo_url", "website_url", "github_url", "linkedin_url"):
        profile[key] = _safe_url(profile.get(key))
    profile["photo_css_url"] = _safe_css_url(profile.get("photo_url"))
    content["other_links"] = [item for item in content.get("other_links", []) if _safe_url(item.get("url"))]
    for item in content.get("other_links", []): item["url"] = _safe_url(item.get("url"))
    for project in content.get("projects", []):
        for key in ("project_url", "repository_url", "demo_url"): project[key] = _safe_url(project.get(key))
    return content


def _safe_url(value):
    parsed = urlparse(str(value or "").strip())
    return str(value).strip() if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _safe_css_url(value):
    """Allow a remote portrait as a CSS URL without permitting CSS injection."""
    value = _safe_url(value)
    if any(character in value for character in ("'", '"', "\\", "(", ")", "<", ">", "\r", "\n")):
        return ""
    return value


def _module_context(key, composition):
    """Map validated names to internal templates only; never trust model paths."""
    template_key = "custom" if key == "custom_sections" else ("supplemental" if key in {"services", "languages"} else key)
    variant = composition.get(key, "")
    return {"key": key, "variant": variant, "template": f"components/{template_key}.html"}
