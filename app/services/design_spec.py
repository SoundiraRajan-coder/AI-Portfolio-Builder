import json
from copy import deepcopy

from app.database import get_db_connection

SECTION_KEYS = ("about", "skills", "projects", "experience", "education", "certifications", "achievements", "services", "languages", "custom_sections", "contact")
COMPOSITION_SECTION_KEYS = ("hero",) + SECTION_KEYS

# Visual styling is intentionally separate from composition.
VISUAL_DEFAULTS = {
    "theme": "dark", "style": "modern", "layout": "centered", "section_arrangement": "vertical",
    "spacing": "normal", "border_radius": "rounded", "shadows": "medium", "background": "gradient",
    "density": "balanced", "effects": "hover", "primary_color": "blue", "secondary_color": "violet",
    "font_style": "modern", "animations": True,
}
SPEC_DEFAULTS = {**VISUAL_DEFAULTS, "navigation": "top", "hero": "left", "about": "editorial", "projects": "grid", "experience": "timeline", "skills": "grid", "education": "cards", "achievements": "cards", "contact": "statement", "section_order": list(SECTION_KEYS)}

ALLOWED_VALUES = {
    "theme": {"light", "dark", "milk_green", "emerald", "indigo", "cyan", "crimson", "violet", "amber", "monochrome", "nordic", "auto"},
    "style": {"minimal", "modern", "creative", "professional", "tech", "terminal", "futuristic", "cyberpunk", "glassmorphism", "editorial", "playful", "auto"},
    "layout": {"centered", "sidebar", "split", "asymmetric", "bento", "editorial", "two_column"},
    "section_arrangement": {"vertical", "two_column", "alternating", "asymmetric", "bento", "editorial", "sidebar"},
    "spacing": {"compact", "normal", "generous", "editorial"},
    "border_radius": {"none", "subtle", "rounded", "pill"},
    "shadows": {"none", "subtle", "medium", "dramatic", "glow", "soft"},
    "background": {"solid", "plain", "gradient", "radial_glow", "mesh", "dark_grid", "dots", "glow"},
    "density": {"compact", "balanced", "airy"},
    "effects": {"quiet", "borders", "hover", "glow", "elevated"},
    "primary_color": {"emerald", "violet", "coral", "blue", "gold", "monochrome", "cyberpunk", "slate", "crimson", "amber", "rose", "teal", "indigo", "dark_obsidian", "milk_green", "cyan", "nordic"},
    "secondary_color": {"emerald", "violet", "coral", "blue", "gold", "monochrome", "cyberpunk", "slate", "crimson", "amber", "rose", "teal", "indigo", "dark_obsidian", "milk_green", "cyan", "nordic"},
    "font_style": {"modern", "classic", "mono", "editorial", "futuristic", "tech", "geometric", "serif"},
}
COMPOSITION_VARIANTS = {
    "navigation": {"top", "sidebar", "floating", "minimal"},
    "hero": {"centered", "left", "split", "editorial", "profile", "compact"},
    "about": {"text", "editorial", "split", "highlight", "minimal"},
    "skills": {"pills", "grid", "grouped", "compact", "icon"},
    "projects": {"grid", "bento", "featured", "masonry", "horizontal", "image"},
    "experience": {"timeline", "cards", "compact", "milestones", "split"},
    "education": {"timeline", "cards", "compact"},
    "achievements": {"highlights", "statistics", "cards", "timeline", "compact"},
    "certifications": {"cards", "list", "badges", "compact"},
    "services": {"list", "grid", "compact"},
    "languages": {"list", "badges", "compact"},
    "contact": {"centered", "split", "statement", "card", "minimal"},
}
COMPOSITION_DEFAULTS = {
    "navigation": "top", "hero": "left", "about": "editorial", "skills": "grid", "projects": "bento",
    "experience": "timeline", "education": "cards", "achievements": "cards", "certifications": "badges",
    "services": "grid", "languages": "badges", "contact": "statement", "section_order": list(COMPOSITION_SECTION_KEYS)
}
LEGACY_COMPOSITION_ALIASES = {
    "navigation": {"transparent": "top", "glass": "floating"},
    "hero": {"fullscreen": "editorial", "image_focus": "profile", "large": "editorial"},
    "about": {"centered": "highlight", "statement": "highlight", "glass": "text"},
    "projects": {"image_focus": "image", "list": "horizontal"},
    "experience": {"list": "compact", "two_column": "split"},
    "skills": {"progress": "grid", "icon_grid": "icon"},
    "education": {"list": "compact"},
    "achievements": {"stats": "statistics", "grid": "cards"},
    "contact": {"footer": "minimal"},
}


def normalize_portfolio_spec(raw_spec):
    """Convert a legacy flat saved spec to the current non-executable shape."""
    source = deepcopy(raw_spec) if isinstance(raw_spec, dict) else {}
    if isinstance(source.get("composition"), dict):
        return source

    composition = {}
    for field, allowed in COMPOSITION_VARIANTS.items():
        value = source.get(field)
        value = LEGACY_COMPOSITION_ALIASES.get(field, {}).get(value, value)
        if value in allowed:
            composition[field] = value
    if isinstance(source.get("section_order"), list):
        composition["section_order"] = source["section_order"]
    if composition:
        source["composition"] = composition

    if not isinstance(source.get("visual"), dict):
        visual = {field: source[field] for field in ALLOWED_VALUES if field in source}
        if "animations" in source:
            visual["animations"] = source["animations"]
        source["visual"] = visual
    return source


def validate_design_spec(raw_spec):
    """Validate only visual design."""
    raw = raw_spec.get("visual", raw_spec.get("design", raw_spec)) if isinstance(raw_spec, dict) else {}
    result = dict(VISUAL_DEFAULTS)
    for field, allowed in ALLOWED_VALUES.items():
        if raw.get(field) in allowed:
            result[field] = raw[field]
    if isinstance(raw.get("animations"), bool):
        result["animations"] = raw["animations"]
    return result


def validate_composition(raw_spec):
    raw = raw_spec.get("composition", {}) if isinstance(raw_spec, dict) else {}
    legacy = raw_spec.get("design", raw_spec) if isinstance(raw_spec, dict) else {}
    result = dict(COMPOSITION_DEFAULTS)
    for field, allowed in COMPOSITION_VARIANTS.items():
        value = raw.get(field, legacy.get(field)) if isinstance(legacy, dict) else raw.get(field)
        if value in allowed:
            result[field] = value
    order = raw.get("section_order", legacy.get("section_order") if isinstance(legacy, dict) else None)
    if isinstance(order, list):
        validated = [item for item in order if item in COMPOSITION_SECTION_KEYS]
        if len(validated) == len(set(validated)) and validated:
            result["section_order"] = validated
    return result


def wizard_content(wizard):
    wizard = wizard if isinstance(wizard, dict) else {}
    profile = wizard.get("profile") if isinstance(wizard.get("profile"), dict) else {}
    professional = wizard.get("professional") if isinstance(wizard.get("professional"), dict) else {}
    portfolio = wizard.get("portfolio") if isinstance(wizard.get("portfolio"), dict) else {}
    return {
        "profile": _clean_object(profile, ("name", "professional_title", "introduction", "photo_url", "resume_url", "email", "phone", "location", "website_url", "github_url", "linkedin_url")),
        "other_links": _clean_records(profile.get("other_links"), ("label", "url")),
        "about": {"summary": _text(profile.get("introduction"), 2000), "overview": _text(portfolio.get("overview"), 2000)},
        "skills": [_text(value, 100) for value in professional.get("skills", []) if _text(value, 100)],
        "education": _clean_records(professional.get("education"), ("degree", "institution", "start_year", "end_year", "grade", "description")),
        "experience": _clean_records(professional.get("experience"), ("job_title", "company_name", "employment_type", "start_date", "end_date", "location", "description", "responsibilities")),
        "projects": _clean_records(portfolio.get("projects"), ("name", "short_description", "description", "technologies", "project_url", "repository_url", "demo_url", "start_date", "end_date", "key_features", "role")),
        "certifications": _clean_records(professional.get("certifications"), ("name", "issuing_organization")),
        "achievements": _clean_records(professional.get("achievements"), ("title", "description")),
        "services": _clean_records(portfolio.get("services"), ("name", "description")),
        "languages": _clean_records(portfolio.get("languages"), ("language", "level", "proficiency")),
        "custom_sections": _clean_records(portfolio.get("custom_sections"), ("title", "content")),
    }


def validate_portfolio_spec(raw_spec, wizard):
    raw_spec = _apply_explicit_design_brief(normalize_portfolio_spec(raw_spec), wizard)
    content = wizard_content(wizard)
    candidate = raw_spec.get("content", {}) if isinstance(raw_spec, dict) else {}
    if isinstance(candidate, dict):
        _merge_ai_wording(content, candidate)
    spec = {
        "content": content,
        "composition": validate_composition(raw_spec),
        "visual": validate_design_spec(raw_spec),
        "responsive": {"mobile_navigation": "top", "stack_complex_layouts": True},
    }
    if isinstance(raw_spec, dict) and raw_spec.get("custom_html"):
        spec["custom_html"] = raw_spec["custom_html"]
    return spec


def _apply_explicit_design_brief(raw_spec, wizard):
    source = deepcopy(raw_spec) if isinstance(raw_spec, dict) else {}
    portfolio = wizard.get("portfolio", {}) if isinstance(wizard, dict) else {}
    prefs = portfolio.get("design_preferences", {}) if isinstance(portfolio.get("design_preferences"), dict) else {}
    brief = _text(portfolio.get("design_prompt"), 4000).lower()

    composition = source.setdefault("composition", {})
    visual = source.setdefault("visual", {})

    def has(*terms):
        return any(term in brief for term in terms)

    def set_composition(field, value):
        if value in COMPOSITION_VARIANTS.get(field, set()):
            composition[field] = value

    def set_visual(field, value):
        if value in ALLOWED_VALUES.get(field, set()):
            visual[field] = value

    # Apply explicit user UI preferences first if present
    if prefs.get("theme") in {"light", "dark"}:
        set_visual("theme", prefs["theme"])
    if prefs.get("style") in ALLOWED_VALUES["style"]:
        set_visual("style", prefs["style"])
    if prefs.get("animation") == "none":
        visual["animations"] = False
    elif prefs.get("animation") in {"subtle", "moderate"}:
        visual["animations"] = True

    # Check brief for explicit layout cues
    if has("left sidebar", "sidebar navigation", "fixed sidebar"):
        set_composition("navigation", "sidebar")
        set_visual("layout", "sidebar")
    elif has("floating navigation", "floating nav", "floating pill"):
        set_composition("navigation", "floating")

    if has("split hero"):
        set_composition("hero", "split")
    elif has("compact hero"):
        set_composition("hero", "compact")
    elif has("editorial hero"):
        set_composition("hero", "editorial")
    elif has("profile hero", "photo hero"):
        set_composition("hero", "profile")

    if has("bento project", "bento layout", "bento grid"):
        set_composition("projects", "bento")
    elif has("image-focused project", "image focused", "large project imagery"):
        set_composition("projects", "image")
    elif has("featured project", "showcase project"):
        set_composition("projects", "featured")
    elif has("masonry project", "masonry"):
        set_composition("projects", "masonry")

    if has("experience timeline", "career timeline", "vertical timeline", "timeline"):
        set_composition("experience", "timeline")

    if has("cyberpunk", "neon"):
        set_visual("theme", "dark")
        set_visual("style", "futuristic")
        set_visual("primary_color", "cyberpunk")
        set_visual("secondary_color", "violet")
        set_visual("background", "radial_glow")
        set_visual("effects", "glow")
        set_visual("font_style", "futuristic")
    elif has("glassmorphism", "glass panel", "frosted"):
        set_visual("style", "glassmorphism")
        set_visual("background", "mesh")
        set_visual("effects", "glow")
    elif has("editorial", "magazine", "vogue", "minimalist luxury"):
        set_visual("style", "editorial")
        set_visual("layout", "editorial")
        set_visual("section_arrangement", "editorial")
        set_visual("font_style", "editorial")
    elif has("tech", "developer", "terminal", "hacker", "coder"):
        set_visual("style", "tech")
        set_visual("font_style", "mono")
        set_visual("background", "dark_grid")

    return source


def build_portfolio_generation_prompt(wizard):
    content = wizard_content(wizard)
    portfolio = wizard.get("portfolio") if isinstance(wizard.get("portfolio"), dict) else {}
    design_prompt = _text(portfolio.get("design_prompt"), 4000)
    if not design_prompt:
        raise ValueError("A design prompt is required to generate your portfolio.")

    return (
        "You are an award-winning digital design director & portfolio architect. Return JSON only: never HTML, CSS, JavaScript, Python, or markdown fences. "
        "Return an object with: content, composition, visual, responsive. "
        "YOUR GOAL: Create a visually unique, high-contrast, professional portfolio architecture that directly reflects the user's design prompt and personal brand. "
        "Make bold, creative choices with color palettes, layouts, section structures, and typography. "
        "Rules: "
        "1. For visual.layout choose from: 'bento', 'two_column', 'sidebar', 'editorial', 'asymmetric', 'centered'. (Do NOT always default to centered; use 'bento' or 'two_column' for modern tech portfolios!). "
        "2. For visual.section_arrangement choose from: 'bento', 'two_column', 'alternating', 'asymmetric', 'editorial'. "
        "3. For visual.style choose from: 'modern', 'creative', 'professional', 'tech', 'futuristic', 'cyberpunk', 'glassmorphism', 'editorial', 'playful', 'minimal'. "
        "4. For visual.primary_color & visual.secondary_color choose harmonious, striking colors: 'blue', 'indigo', 'violet', 'cyberpunk', 'emerald', 'teal', 'coral', 'crimson', 'amber', 'rose', 'slate', 'gold', 'monochrome'. "
        "5. For visual.background choose from: 'gradient', 'mesh', 'radial_glow', 'dark_grid', 'dots', 'solid'. "
        "6. For visual.shadows choose 'medium', 'dramatic', 'glow', or 'soft'. "
        "7. For visual.effects choose 'hover', 'glow', 'elevated', or 'borders'. "
        "8. For composition, choose rich, varied component layouts: "
        "   - hero: 'split', 'profile', 'left', 'editorial', or 'centered'. "
        "   - projects: 'bento', 'grid', 'featured', 'masonry', 'image', or 'horizontal'. "
        "   - experience: 'timeline', 'cards', 'milestones', or 'split'. "
        "   - education: 'cards' or 'timeline'. "
        "   - skills: 'grid', 'grouped', 'pills', or 'icon'. "
        "   - navigation: 'floating', 'sidebar', or 'top'. "
        "   - contact: 'card', 'statement', 'split', or 'centered'. "
        "   - section_order: reorder sections intelligently (e.g. put projects or skills early if relevant). "
        "9. Content: Elevate and polish the biography, summaries, and project descriptions into compelling, executive-quality language. Preserve all factual names, companies, institutions, skills, and links without inventing new ones. "
        f"Available Composition options: {json.dumps({key: sorted(value) for key, value in COMPOSITION_VARIANTS.items()})}. "
        f"Available Visual options: {json.dumps({key: sorted(value) for key, value in ALLOWED_VALUES.items()})}. "
        f"Design request: {design_prompt}\nPreferences: {json.dumps(portfolio.get('design_preferences', {}))}\nUser data: {json.dumps(content)}"
    )


def save_design_spec(user_id, portfolio_id, prompt, specification):
    prompt = _text(prompt, 4000)
    if not prompt:
        raise ValueError("Design prompt must contain 1 to 4000 characters.")
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM portfolios WHERE id = %s AND user_id = %s", (portfolio_id, user_id))
            if not cursor.fetchone():
                raise ValueError("Portfolio not found.")
            cursor.execute(
                """INSERT INTO portfolio_design_specs (portfolio_id, user_id, generation_prompt, specification, is_custom)
                   VALUES (%s, %s, %s, %s, TRUE)
                   ON CONFLICT (portfolio_id) DO UPDATE SET
                       generation_prompt = EXCLUDED.generation_prompt,
                       specification = EXCLUDED.specification,
                       is_custom = TRUE,
                       updated_at = timezone('utc', now())""",
                (portfolio_id, user_id, prompt, json.dumps(specification)),
            )
            cursor.execute("UPDATE portfolios SET updated_at = timezone('utc', now()) WHERE id = %s AND user_id = %s", (portfolio_id, user_id))
        connection.commit()
    return specification


def _merge_ai_wording(target, candidate):
    profile = candidate.get("profile")
    if isinstance(profile, dict) and profile.get("introduction"):
        target["profile"]["introduction"] = _safe_ai_text(profile["introduction"], 2000)
    about = candidate.get("about")
    if isinstance(about, dict):
        for field in ("summary", "overview"):
            if about.get(field):
                target["about"][field] = _safe_ai_text(about[field], 2000)
    for section in ("education", "experience", "projects", "services", "custom_sections"):
        updates = candidate.get(section)
        if isinstance(updates, list):
            for index, item in enumerate(updates):
                if index < len(target.get(section, [])) and isinstance(item, dict):
                    for field in ("description", "short_description", "responsibilities", "content"):
                        if item.get(field) and field in target[section][index]:
                            target[section][index][field] = _safe_ai_text(item[field], 3000)


def _safe_ai_text(value, limit):
    text = _text(value, limit)
    return "" if any(token in text.lower() for token in ("<script", "<html", "javascript:", "def ", "import ")) else text

def _clean_object(raw, fields):
    return {field: _text(raw.get(field), 2000) for field in fields}

def _clean_records(raw, fields):
    return [_clean_object(item, fields) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

def _text(value, limit):
    return str(value or "").strip()[:limit]
