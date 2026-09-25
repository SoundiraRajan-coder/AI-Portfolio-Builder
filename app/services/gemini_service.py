import json
import re
import time
from typing import Any

from flask import current_app

from app.services.design_spec import ALLOWED_VALUES, COMPOSITION_SECTION_KEYS, COMPOSITION_VARIANTS, SECTION_KEYS


def _design_spec_json_schema():
    """Build the JSON schema for design-spec generation directly from
    design_spec.ALLOWED_VALUES, so Gemini is always constrained to the
    exact fields/enum values the rest of the app (validate_design_spec,
    design_studio.js) actually understands.
    """
    properties = {
        field: {"type": "string", "enum": sorted(values)}
        for field, values in ALLOWED_VALUES.items()
    }
    properties["animations"] = {"type": "boolean"}
    properties["section_order"] = {
        "type": "array",
        "items": {"type": "string", "enum": list(SECTION_KEYS)},
        "uniqueItems": True,
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(ALLOWED_VALUES.keys()) + ["animations", "section_order"],
    }


def _portfolio_spec_json_schema():
    """A deliberately non-executable response contract for the final build."""
    composition = {
        "type": "object",
        "properties": {
            **{field: {"type": "string", "enum": sorted(values)} for field, values in COMPOSITION_VARIANTS.items()},
            "section_order": {"type": "array", "items": {"type": "string", "enum": list(COMPOSITION_SECTION_KEYS)}, "uniqueItems": True},
        },
        "required": list(COMPOSITION_VARIANTS.keys()) + ["section_order"],
    }
    visual = _design_spec_json_schema()
    return {
        "type": "object",
        "properties": {
            "content": {"type": "object"},
            "composition": composition,
            "visual": visual,
            "responsive": {"type": "object"},
        },
        "required": ["content", "composition", "visual", "responsive"],
    }


TASK_LIMITS = {
    "bio": 2000,
    "project": 3000,
    "skills": 1200,
    "experience": 3000,
    "education": 2000,
}


class GeminiServiceError(Exception):
    """Base error for Gemini configuration and generation failures."""


class GeminiConfigurationError(GeminiServiceError):
    """Raised when Gemini is not configured or installed."""


class GeminiRateLimitError(GeminiServiceError):
    """Raised when Gemini rate-limits a request."""


class GeminiResponseError(GeminiServiceError):
    """Raised when Gemini returns an unusable response."""


def _get_gemini_config():
    api_key = current_app.config.get("GEMINI_API_KEY")
    model = current_app.config.get("GEMINI_MODEL", "gemini-3.6-flash")
    if not api_key:
        raise GeminiConfigurationError("GEMINI_API_KEY is not configured.")
    return api_key, model


def _low_thinking_config(types):
    """Set low thinking effort so Gemini Flash outputs HTML smoothly
    and accurately without consuming budget on excessive thinking.
    """
    try:
        return types.ThinkingConfig(thinking_budget=1024)
    except Exception:
        try:
            return types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
        except Exception:
            return None


def _get_gemini_client(api_key):
    try:
        from google import genai
    except ImportError as exc:
        raise GeminiConfigurationError("The google-genai package is not installed.") from exc
    return genai.Client(api_key=api_key)


def _is_rate_limit(exc):
    msg = str(exc).lower()
    return "429" in msg or "quota" in msg or "resource_exhausted" in msg


def _log_gemini_error(exc, model):
    message = str(exc)
    current_app.logger.error(
        "Gemini error: type=%s model=%s message=%s",
        exc.__class__.__name__,
        model,
        message if len(message) < 1000 else message[:1000],
    )


def _call_gemini_with_fallback(client, prompt, config, primary_model: str):
    """Call Gemini with immediate model fallback when encountering 503 high demand spikes or 429 free-tier quota limits."""
    candidate_models = [primary_model]
    for fallback in [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-flash-latest",
    ]:
        if fallback not in candidate_models:
            candidate_models.append(fallback)

    last_exc = None
    for m in candidate_models:
        try:
            return client.models.generate_content(
                model=m,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            last_exc = exc
            err_msg = str(exc).lower()
            if (
                "503" in err_msg
                or "unavailable" in err_msg
                or "high demand" in err_msg
                or "resource_exhausted" in err_msg
                or "rate" in err_msg
                or "quota" in err_msg
                or "429" in err_msg
                or "404" in err_msg
            ):
                current_app.logger.warning(
                    "Model %s temporarily unavailable: %s. Immediately trying next candidate model...",
                    m,
                    exc,
                )
                continue
            else:
                _log_gemini_error(exc, m)
                raise
    if last_exc:
        _log_gemini_error(last_exc, primary_model)
        if _is_rate_limit(last_exc):
            raise GeminiRateLimitError("AI request quota limit reached. Please try again shortly.") from last_exc
        raise GeminiServiceError("Gemini AI is currently experiencing high demand. Please try again in a moment.") from last_exc


def generate_content(task, raw_input):
    """Generate one structured content value without persisting it."""
    prompt = build_prompt(task, raw_input)
    api_key, model = _get_gemini_config()

    try:
        from google.genai import types
    except ImportError as exc:
        raise GeminiConfigurationError("The google-genai package is not installed.") from exc

    client = _get_gemini_client(api_key)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        },
        max_output_tokens=2048,
        thinking_config=_low_thinking_config(types),
    )
    response = _call_gemini_with_fallback(client, prompt, config, model)

    text = getattr(response, "text", "") or str(response)
    try:
        content = _extract_content_from_text(text)
    except GeminiResponseError:
        current_app.logger.debug("Gemini response (truncated): %s", (text or "")[:1000])
        raise

    if not content or len(content) > 6000:
        raise GeminiResponseError("Gemini returned empty or oversized content.")
    return {"content": content, "task": task}


def build_prompt(task, raw_input):
    if task not in TASK_LIMITS:
        raise ValueError("Unsupported AI task.")
    if not isinstance(raw_input, dict):
        raise ValueError("AI input must be an object.")
    cleaned = {}
    for key, value in raw_input.items():
        value = str(value or "").strip()
        if len(value) > TASK_LIMITS[task]:
            raise ValueError(f"{key} is too long for this AI task.")
        if value:
            cleaned[key] = value
    if not cleaned:
        raise ValueError("Add some source information before generating content.")

    instructions = {
        "bio": "Write a concise first-person professional portfolio bio from the provided basics.",
        "project": "Write a polished project description emphasizing problem, approach, technologies, and outcome.",
        "skills": "Write a concise professional skill summary grouped naturally by strengths.",
        "experience": "Rewrite the work or internship details into clear portfolio language with impact and responsibilities.",
        "education": "Write a concise education description highlighting study focus, relevant work, and growth.",
    }
    return (
        "You are a professional portfolio editor. Return JSON with exactly one string field named content. "
        "Do not include markdown fences, code, HTML, scripts, credentials, or invented facts. "
        f"{instructions[task]} Keep it specific and under 180 words. Source information: {json.dumps(cleaned)}"
    )


def _strip_code_and_tags(text: str) -> str:
    """Remove code fences, script/style tags and simple HTML tags."""
    if not isinstance(text, str):
        return ""
    # Remove triple-backtick code blocks
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # Remove inline backticks
    text = text.replace("`", "")
    # Remove script/style tags
    text = re.sub(r"<script.*?>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _extract_json_substring(text: str) -> Any:
    """Attempt to find a JSON object inside noisy text."""
    if not text or not isinstance(text, str):
        return None
    m = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _extract_content_from_text(text: str) -> str:
    """Robustly extract a content string from an LLM response text.

    Preference order:
    1. Parsed JSON with 'content' string field
    2. Parsed JSON dict with any string field
    3. Parsed JSON list with first string or dict->content
    4. JSON substring parsing
    5. Fallback to stripped plain text (sanitized)
    """
    # Try parse as full JSON
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = _extract_json_substring(text)

    if isinstance(payload, dict):
        # Prefer explicit 'content' field
        if isinstance(payload.get("content"), str) and payload.get("content").strip():
            candidate = payload.get("content").strip()
        else:
            # Pick the first string-like field
            candidate = None
            for v in payload.values():
                if isinstance(v, str) and v.strip():
                    candidate = v.strip()
                    break
        if candidate:
            candidate = _strip_code_and_tags(candidate)
            _reject_executable_snippets(candidate)
            return candidate
        raise GeminiResponseError("Gemini returned JSON without usable content.")

    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, str) and first.strip():
            candidate = _strip_code_and_tags(first)
            _reject_executable_snippets(candidate)
            return candidate
        if isinstance(first, dict) and isinstance(first.get("content"), str):
            candidate = _strip_code_and_tags(first.get("content"))
            _reject_executable_snippets(candidate)
            return candidate

    # Fallback: treat as plain text
    candidate = _strip_code_and_tags(text)
    _reject_executable_snippets(candidate)
    return candidate


def _reject_executable_snippets(text: str):
    """Reject responses that appear to contain executable code or HTML."""
    if not text:
        return
    lowered = text.lower()
    # Heuristic checks
    if "<script" in lowered or "<html" in lowered or "<body" in lowered:
        raise GeminiResponseError("Gemini returned unsafe content.")
    if re.search(r"\b(def |class |import |from |console\.log|<\/?script)", lowered):
        raise GeminiResponseError("Gemini returned code-like content.")


def generate_design_spec(prompt):
    """Generate controlled design JSON; never request executable output."""
    api_key, model = _get_gemini_config()
    try:
        from google.genai import types
    except ImportError as exc:
        raise GeminiConfigurationError("The google-genai package is not installed.") from exc

    client = _get_gemini_client(api_key)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=_design_spec_json_schema(),
        max_output_tokens=2048,
        thinking_config=_low_thinking_config(types),
    )
    response = _call_gemini_with_fallback(client, prompt, config, model)

    text = getattr(response, "text", "") or str(response)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = _extract_json_substring(text)

    if not isinstance(parsed, dict):
        current_app.logger.debug("Gemini design response (truncated): %s", (text or "")[:1000])
        raise GeminiResponseError("Gemini returned an invalid design specification.")
    return parsed


def _clean_data_dict(data: dict) -> dict:
    """Recursively clean dict/list structures to remove empty, null, or whitespace-only values."""
    if not isinstance(data, dict):
        return {}
    cleaned = {}
    for k, v in data.items():
        if isinstance(v, str):
            v_clean = v.strip()
            if v_clean:
                cleaned[k] = v_clean
        elif isinstance(v, list):
            cleaned_list = []
            for item in v:
                if isinstance(item, dict):
                    c_item = _clean_data_dict(item)
                    if c_item and any(c_item.values()):
                        cleaned_list.append(c_item)
                elif isinstance(item, str) and item.strip():
                    cleaned_list.append(item.strip())
            if cleaned_list:
                cleaned[k] = cleaned_list
        elif isinstance(v, dict):
            c_dict = _clean_data_dict(v)
            if c_dict:
                cleaned[k] = c_dict
        elif v is not None:
            cleaned[k] = v
    return cleaned


def _resolve_project_images(projects: list[dict]) -> list[dict]:
    """Inspect project items, categorize them based on keywords in title/description/technologies,
    and dynamically assign high-resolution, unique, domain-relevant Unsplash images so that no two projects
    share the same image and each project gets an authentically matching illustration."""
    if not isinstance(projects, list):
        return []

    domain_pools = {
        "vision_ai": [
            "https://images.unsplash.com/photo-1507146426996-ef05306b995a?w=900&auto=format&fit=crop&q=80",  # Neural network optical vision matrix
            "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=900&auto=format&fit=crop&q=80",  # Cyber visual stream
            "https://images.unsplash.com/photo-1535378917042-10a22c95931a?w=900&auto=format&fit=crop&q=80",  # AI optical sensor
            "https://images.unsplash.com/photo-1518770660439-4636190af475?w=900&auto=format&fit=crop&q=80",  # Microprocessor hardware
        ],
        "ml_data": [
            "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=900&auto=format&fit=crop&q=80",  # Data analytics & graph dashboard
            "https://images.unsplash.com/photo-1504868584819-f8e8b4b6d7e3?w=900&auto=format&fit=crop&q=80",  # Data charts & dashboard
            "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=900&auto=format&fit=crop&q=80",  # Neural glow flows
            "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=900&auto=format&fit=crop&q=80",  # AI glow core
        ],
        "web_saas": [
            "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=900&auto=format&fit=crop&q=80",  # Modern SaaS dashboard
            "https://images.unsplash.com/photo-1551836022-d5d88e9218df?w=900&auto=format&fit=crop&q=80",  # Web collaboration app
            "https://images.unsplash.com/photo-1507238691740-187a5b1d37b8?w=900&auto=format&fit=crop&q=80",  # Clean responsive web app
            "https://images.unsplash.com/photo-1522542550221-31fd19575a2d?w=900&auto=format&fit=crop&q=80",  # Web UI design
        ],
        "mobile": [
            "https://images.unsplash.com/photo-1512941937669-90a1b58e7e9c?w=900&auto=format&fit=crop&q=80",  # Mobile phone app in hand
            "https://images.unsplash.com/photo-1526470608268-f674ce90ebd4?w=900&auto=format&fit=crop&q=80",  # Mobile UX layout
            "https://images.unsplash.com/photo-1555774698-0b77e0d5fac6?w=900&auto=format&fit=crop&q=80",  # Mobile screen on desk
        ],
        "cloud_backend": [
            "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=900&auto=format&fit=crop&q=80",  # Server cloud racks
            "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=900&auto=format&fit=crop&q=80",  # Global cloud network
            "https://images.unsplash.com/photo-1544197150-b99a580bb7a8?w=900&auto=format&fit=crop&q=80",  # Network connection mesh
        ],
        "fintech_ecommerce": [
            "https://images.unsplash.com/photo-1559526324-4b87b5e36e44?w=900&auto=format&fit=crop&q=80",  # Financial analytics
            "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=900&auto=format&fit=crop&q=80",  # Digital shopping app
            "https://images.unsplash.com/photo-1621416894569-0f39ed31d247?w=900&auto=format&fit=crop&q=80",  # Crypto / decentralized UI
        ],
        "robotics_iot": [
            "https://images.unsplash.com/photo-1581091226825-a6a2a5aee158?w=900&auto=format&fit=crop&q=80",  # Robotics automation arm
            "https://images.unsplash.com/photo-1517077304055-6e89abbf09b0?w=900&auto=format&fit=crop&q=80",  # Hardware circuit board
            "https://images.unsplash.com/photo-1581092160607-ee22621dd758?w=900&auto=format&fit=crop&q=80",  # Smart testing hardware
        ],
        "cybersecurity": [
            "https://images.unsplash.com/photo-1563089145-599997674d42?w=900&auto=format&fit=crop&q=80",  # Cybersecurity cyber shield
            "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?w=900&auto=format&fit=crop&q=80",  # Security terminal matrix
        ],
        "creative_general": [
            "https://images.unsplash.com/photo-1498050108023-c5249f4df085?w=900&auto=format&fit=crop&q=80",  # Modern developer setup
            "https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=900&auto=format&fit=crop&q=80",  # Code syntax screen
            "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?w=900&auto=format&fit=crop&q=80",  # Workspace setup
        ],
    }

    used_images = set()
    enhanced_projects = []

    for proj in projects:
        p_copy = dict(proj)
        existing_img = p_copy.get("image_url") or p_copy.get("photo_url") or p_copy.get("image")
        if existing_img and isinstance(existing_img, str) and existing_img.strip():
            p_copy["image_url"] = existing_img.strip()
            used_images.add(existing_img.strip())
            enhanced_projects.append(p_copy)
            continue

        text_corpus = (
            f"{p_copy.get('name', '')} {p_copy.get('title', '')} "
            f"{p_copy.get('summary', '')} {p_copy.get('description', '')} "
            f"{p_copy.get('role', '')} {p_copy.get('technologies', '')}"
        ).lower()

        if any(w in text_corpus for w in ["vision", "opencv", "yolo", "detect", "camera", "object", "nano counter", "counter", "image processing", "video stream"]):
            pool_key = "vision_ai"
        elif any(w in text_corpus for w in ["machine learning", "deep learning", "neural", "nlp", "llm", "ai", "model", "analytics", "prediction", "data science"]):
            pool_key = "ml_data"
        elif any(w in text_corpus for w in ["mobile", "android", "ios", "flutter", "react native", "swift", "kotlin", "app"]):
            pool_key = "mobile"
        elif any(w in text_corpus for w in ["cloud", "devops", "docker", "kubernetes", "aws", "gcp", "azure", "backend", "api", "microservice", "server"]):
            pool_key = "cloud_backend"
        elif any(w in text_corpus for w in ["crypto", "fintech", "finance", "payment", "bank", "shop", "ecommerce", "store", "stripe", "cart"]):
            pool_key = "fintech_ecommerce"
        elif any(w in text_corpus for w in ["robot", "robotics", "iot", "arduino", "raspberry", "sensor", "hardware", "embedded"]):
            pool_key = "robotics_iot"
        elif any(w in text_corpus for w in ["security", "auth", "crypto", "cyber", "penetration", "shield", "firewall"]):
            pool_key = "cybersecurity"
        elif any(w in text_corpus for w in ["web", "dashboard", "portal", "react", "vue", "next", "full stack", "saas", "platform"]):
            pool_key = "web_saas"
        else:
            pool_key = "creative_general"

        candidates = domain_pools.get(pool_key, domain_pools["creative_general"])
        assigned_img = None
        for img in candidates:
            if img not in used_images:
                assigned_img = img
                break
        if not assigned_img:
            for any_pool in domain_pools.values():
                for img in any_pool:
                    if img not in used_images:
                        assigned_img = img
                        break
                if assigned_img:
                    break
        if not assigned_img:
            assigned_img = candidates[0]

        used_images.add(assigned_img)
        p_copy["image_url"] = assigned_img
        enhanced_projects.append(p_copy)

    return enhanced_projects


def generate_creative_portfolio_html(wizard_data: dict, design_prompt: str) -> str:
    """Generate a complete, standalone, creative HTML+CSS portfolio directly using Gemini Flash."""
    api_key, model = _get_gemini_config()
    try:
        from google.genai import types
    except ImportError as exc:
        raise GeminiConfigurationError("The google-genai package is not installed.") from exc

    raw_profile = wizard_data.get("profile", {}) or {}
    raw_professional = wizard_data.get("professional", {}) or {}
    raw_portfolio = wizard_data.get("portfolio", {}) or {}

    clean_profile = _clean_data_dict(raw_profile)
    clean_professional = _clean_data_dict(raw_professional)
    clean_portfolio = _clean_data_dict(raw_portfolio)

    social_links = {
        "github": clean_profile.get("github_url"),
        "linkedin": clean_profile.get("linkedin_url"),
        "website": clean_profile.get("website_url"),
        "other_links": clean_profile.get("other_links", []),
    }
    social_links = {k: v for k, v in social_links.items() if v}

    skills_list = clean_professional.get("skills", [])
    exp_list = clean_professional.get("experience", [])
    edu_list = clean_professional.get("education", [])
    proj_list = _resolve_project_images(clean_portfolio.get("projects", []))
    cert_list = clean_professional.get("certifications", [])
    achieve_list = clean_professional.get("achievements", [])
    serv_list = clean_portfolio.get("services", [])
    lang_list = clean_portfolio.get("languages", [])
    custom_list = clean_portfolio.get("custom_sections", [])

    inventory_checklist = (
        f"• Profile: Name='{clean_profile.get('name')}', Title='{clean_profile.get('professional_title')}', Location='{clean_profile.get('location')}', Photo='{clean_profile.get('photo_url')}', CV='{clean_profile.get('resume_url')}'\n"
        f"• Skills ({len(skills_list)} items): {json.dumps(skills_list)}\n"
        f"• Projects ({len(proj_list)} items with pre-assigned unique contextual images): {json.dumps(proj_list)}\n"
        f"• Work Experience ({len(exp_list)} items): {json.dumps(exp_list)}\n"
        f"• Education ({len(edu_list)} items): {json.dumps(edu_list)}\n"
        f"• Certifications ({len(cert_list)} items): {json.dumps(cert_list)}\n"
        f"• Achievements & Awards ({len(achieve_list)} items): {json.dumps(achieve_list)}\n"
        f"• Services Offered ({len(serv_list)} items): {json.dumps(serv_list)}\n"
        f"• Languages ({len(lang_list)} items): {json.dumps(lang_list)}\n"
        f"• Custom Sections ({len(custom_list)} items): {json.dumps(custom_list)}"
    )

    prefs = clean_portfolio.get("design_preferences", {}) if isinstance(clean_portfolio.get("design_preferences"), dict) else {}
    pref_theme = prefs.get("theme", "auto")
    pref_style = prefs.get("style", "auto")
    pref_animation = prefs.get("animation", "auto")

    theme_descriptions = {
        "milk_green": "Milk Green / Sage & Mint: Deep luxurious dark mint/sage background (#04150e / #061d14) or soft creamy mint (#f0fdf4), radiant mint/emerald glows, frosted jade glass cards (bg-[#0a2c20]/60 border border-emerald-400/25), and mint gradient texts.",
        "dark": "Obsidian Dark: Sleek midnight slate (#070a13 / #030712), obsidian glass cards, cyan and indigo glowing accents, high-contrast typography.",
        "light": "Clean Minimalist Light: Crisp porcelain light background (#f8fafc / #ffffff), subtle frosted glass borders, deep charcoal typography (#0f172a), refined slate accents.",
        "emerald": "Emerald Glow: Deep dark emerald matrix (#03140c), neon emerald glows, vibrant green accents, dark tinted glass cards.",
        "indigo": "Midnight Indigo & Slate: Rich deep indigo/navy background (#070a1e), purple-indigo gradient headings, luminous cobalt accents.",
        "cyan": "Cyber Cyan & Neon: High-contrast dark cyber theme with glowing neon cyan/teal highlights (#00f2fe, #4facfe) and tech grids.",
        "crimson": "Crimson & Velvet Red: Luxurious deep velvet charcoal background (#120608), rich crimson/ruby glow highlights, bold warm accents.",
        "violet": "Purple Galaxy & Violet: Cosmic deep violet/space background (#0c061a), luminous purple and magenta nebula glows.",
        "amber": "Sunset Amber & Warm Gold: Warm dark espresso background (#140c06), radiant golden amber buttons and honey glow accents.",
        "monochrome": "Monochrome High-Contrast: Jet black (#000000) and pure white (#ffffff) high-contrast brutalist elegance with ultra-sharp typography.",
        "nordic": "Nordic Frosted Glass: Cool icy slate (#0b1120), frosted glass blur effects, arctic blue gradients, and crisp clean layouts.",
        "auto": "AI Autonomous Choice (No Preference): Intelligently select the most aesthetically stunning and domain-appropriate color theme.",
    }

    style_descriptions = {
        "modern": "Modern Bento Grid: Asymmetric bento grid layout with varying card spans, rounded glass corners, and dynamic visual hierarchy.",
        "minimal": "Minimalist Clean: Ultra-clean typography, ample breathing room, subtle hairline borders, and elegant restraint.",
        "glassmorphism": "Glassmorphism & Frosted Glass: Heavy backdrop-blur effects, layered translucent glass cards, and soft ambient drop shadows.",
        "terminal": "Developer Terminal: Monospaced code aesthetics, IDE tab bars, terminal status indicators, and syntax-highlighted badges.",
        "creative": "Creative Showcase & Magazine: Editorial typography, bold oversized headings, artistic badge alignments, and expressive card layouts.",
        "professional": "Executive & Corporate Tech: Polished executive hierarchy, structured metric cards, clean enterprise aesthetics.",
        "futuristic": "Cyberpunk & Futuristic HUD: Angular accents, neon bordered panels, sci-fi HUD styling, and high-tech flair.",
        "auto": "AI Autonomous Choice (No Preference): Intelligently choose the optimal layout and architectural style for the user's skillset.",
    }

    animation_descriptions = {
        "smooth": "Silky Smooth & Floating: Gentle floating keyframe animations, staggered scroll-reveal entrances, and seamless hover transitions.",
        "subtle": "Silky Smooth & Floating: Gentle floating keyframe animations, staggered scroll-reveal entrances, and seamless hover transitions.",
        "moderate": "Subtle & Moderate: Tasteful fade-in on scroll and gentle hover lift elevations without excessive motion.",
        "dynamic": "Luminous Glowing & Dynamic: Radiant pulsing glows, active gradient shifts, and energetic micro-interactions.",
        "rich": "Luminous Glowing & Dynamic: Radiant pulsing glows, active gradient shifts, and energetic micro-interactions.",
        "interactive": "Interactive Micro-Interactions: Engaging button ripple effects, interactive card tilt/lift, and tactile hover feedback.",
        "none": "Static & Minimal (Reduced Motion): Crisp instant states without heavy animations, optimized for pure clarity.",
        "auto": "AI Autonomous Choice (No Preference): Apply balanced, modern smooth animations with scroll-reveal.",
    }

    selected_theme_guide = theme_descriptions.get(pref_theme, theme_descriptions["auto"])
    selected_style_guide = style_descriptions.get(pref_style, style_descriptions["auto"])
    selected_anim_guide = animation_descriptions.get(pref_animation, animation_descriptions["auto"])

    prompt = (
        "You are an award-winning Principal Web Designer & Frontend Architect known for creating awe-inspiring, high-performance portfolios that win Awwwards and FWA.\n"
        "Your task is to craft an extraordinary, 100% complete, production-ready, standalone single-file HTML portfolio.\n\n"
        "=== 🌟 USER CUSTOM DESIGN DIRECTIVE & PREFERENCES (SUPREME PRIORITY) ===\n"
        f"User's Explicit Design Directive: \"{design_prompt or 'None specified - tailor design to role and preferences'}\"\n"
        f"• Selected Color Theme: {pref_theme} -> {selected_theme_guide}\n"
        f"• Selected Portfolio Style: {pref_style} -> {selected_style_guide}\n"
        f"• Selected Animation: {pref_animation} -> {selected_anim_guide}\n\n"
        "MANDATORY COLOR THEME & PALETTE COMPLIANCE (CRITICAL):\n"
        "1. IF A SPECIFIC COLOR THEME IS SELECTED OR REQUESTED:\n"
        "   - You MUST tailor the entire visual design (page background, card fills, glass borders, gradient texts, button colors, and accent glows) to that exact color palette!\n"
        "2. IF NO PREFERENCE / AUTO IS SELECTED: Use sleek modern aesthetics tailored to the user's domain.\n\n"
        "=== MANDATORY 100% DATA PRESERVATION RULE (CRITICAL) ===\n"
        "You MUST render EVERY SINGLE ITEM from the provided data inventory below into its own dedicated HTML card, row, badge, or pill. "
        "NEVER truncate, summarize, merge, or omit any project, job experience, education entry, certification, achievement, service, language, or custom section. "
        f"Render ALL {len(skills_list)} skills, ALL {len(proj_list)} projects, ALL {len(exp_list)} experience entries, ALL {len(edu_list)} education entries, ALL {len(cert_list)} certifications, ALL {len(achieve_list)} achievements, ALL {len(serv_list)} services, ALL {len(lang_list)} languages.\n\n"
        "=== EXACT USER DATA INVENTORY ===\n"
        f"{inventory_checklist}\n"
        f"Introduction: {clean_profile.get('introduction', '')}\n"
        f"Overview / Bio: {clean_portfolio.get('overview', '')}\n"
        f"Email: {clean_profile.get('email', '')}\n"
        f"Phone: {clean_profile.get('phone', '')}\n"
        f"Social & Web Links: {json.dumps(social_links)}\n\n"
        "=== STRICT NO EMOJIS & OFFICIAL VECTOR BRAND LOGOS RULE (CRITICAL) ===\n"
        "1. NEVER USE CASUAL EMOJIS: Do NOT use emojis like 🐍, ☕, 🚀, 💻, ⚡ as icons in skill cards, badges, hero code snippets, or headers. A professional engineering portfolio uses official vector brand logos.\n"
        "2. For ALL skills and technologies, render crisp vector SVG logos (`<img>` tags with standard Devicon CDN or SkillIcons):\n"
        "   - Python: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/python/python-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"Python\">`\n"
        "   - OpenCV: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/opencv/opencv-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"OpenCV\">`\n"
        "   - Java: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/java/java-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"Java\">`\n"
        "   - JavaScript: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/javascript/javascript-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"JavaScript\">`\n"
        "   - TypeScript: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/typescript/typescript-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"TypeScript\">`\n"
        "   - HTML5: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/html5/html5-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"HTML5\">`\n"
        "   - CSS3: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/css3/css3-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"CSS3\">`\n"
        "   - React: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/react/react-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"React\">`\n"
        "   - Node.js: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/nodejs/nodejs-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"Node.js\">`\n"
        "   - Next.js: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/nextjs/nextjs-original.svg\" class=\"w-7 h-7 inline-block bg-white rounded-full p-0.5\" alt=\"Next.js\">`\n"
        "   - PostgreSQL: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/postgresql/postgresql-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"PostgreSQL\">`\n"
        "   - MySQL: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/mysql/mysql-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"MySQL\">`\n"
        "   - MongoDB: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/mongodb/mongodb-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"MongoDB\">`\n"
        "   - Tailwind CSS: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/tailwindcss/tailwindcss-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"Tailwind CSS\">`\n"
        "   - Git: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/git/git-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"Git\">`\n"
        "   - Docker: `<img src=\"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/docker/docker-original.svg\" class=\"w-7 h-7 inline-block\" alt=\"Docker\">`\n"
        "   - For any other technology: `<img src=\"https://skillicons.dev/icons?i=[tech]\" class=\"w-7 h-7 inline-block\" alt=\"[tech]\">` or official Devicon SVG.\n"
        "3. For Social & Contact links, render working FontAwesome icons (`<i class=\"fa-brands fa-github\"></i>`, `<i class=\"fa-brands fa-linkedin\"></i>`, `<i class=\"fa-solid fa-globe\"></i>`, `<i class=\"fa-solid fa-envelope\"></i>`, `<i class=\"fa-solid fa-phone\"></i>`).\n\n"
        "=== ELEVATED SECTION-BY-SECTION DESIGN ARCHITECTURE ===\n"
        "Every section MUST be visually striking with category pill badges, dynamic gradient headings, smooth animations, and tailored palette styling:\n\n"
        "1. NAVBAR (<nav class=\"fixed top-0 left-0 right-0 z-50 backdrop-blur-xl border-b border-white/10 bg-slate-950/80\">\n"
        "   - Layout: `<div class=\"max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 sm:h-20 flex items-center justify-between\">`\n"
        f"   - Brand (Left): `<a href=\"#hero\" class=\"flex items-center gap-3 font-bold text-lg sm:text-xl text-white\"><span class=\"w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-600 flex items-center justify-center text-white text-sm font-extrabold shadow-lg\">{''.join([p[0].upper() for p in clean_profile.get('name', 'Portfolio').split()[:2]])}</span><span class=\"tracking-tight font-display\">{clean_profile.get('name')}</span></a>`\n"
        "   - Nav Links (Center): `<div class=\"hidden md:flex items-center gap-6 lg:gap-8 text-sm font-medium text-slate-300\"><a href=\"#about\" class=\"hover:text-emerald-400 transition-colors\">About</a><a href=\"#skills\" class=\"hover:text-emerald-400 transition-colors\">Skills</a><a href=\"#projects\" class=\"hover:text-emerald-400 transition-colors\">Projects</a><a href=\"#experience\" class=\"hover:text-emerald-400 transition-colors\">Experience</a><a href=\"#education\" class=\"hover:text-emerald-400 transition-colors\">Education</a><a href=\"#contact\" class=\"hover:text-emerald-400 transition-colors\">Contact</a></div>`\n"
        "   - Action CTA (Right): 'Let's Talk' button and CV download if resume exists.\n"
        "   - Mobile Menu Button: `<button id=\"mobile-menu-btn\" class=\"md:hidden text-slate-300 hover:text-white p-2 text-xl\"><i class=\"fa-solid fa-bars\"></i></button>`\n\n"
        "2. HERO SECTION (<section id=\"hero\" class=\"relative pt-32 sm:pt-40 pb-20 sm:pb-28 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto min-h-[90vh] flex items-center overflow-hidden\">\n"
        "   - Ambient background glow orb matching the color theme.\n"
        "   - 2-Column Grid Layout: `<div class=\"grid grid-cols-1 lg:grid-cols-12 gap-12 items-center w-full relative z-10\">` (Text on lg:col-span-7, Photo on lg:col-span-5).\n"
        "   - Status indicator pill with animated pulse dot.\n"
        f"   - Headline: `<h1 class=\"text-4xl sm:text-5xl lg:text-6xl font-extrabold text-white tracking-tight leading-tight mb-4 font-display\">Hi, I'm <span class=\"bg-gradient-to-r from-emerald-300 via-teal-200 to-green-300 bg-clip-text text-transparent\">{clean_profile.get('name')}</span></h1>`\n"
        f"   - Professional Title: `<h2 class=\"text-xl sm:text-2xl font-semibold text-slate-300 mb-6\">{clean_profile.get('professional_title')}</h2>`\n"
        f"   - Bio Intro: `<p class=\"text-base sm:text-lg text-slate-300/90 max-w-2xl mb-8 leading-relaxed\">{clean_profile.get('introduction')}</p>`\n"
        "   - Action buttons: 'Explore Projects' (primary), 'Get In Touch' (secondary), and 'Download CV' (if resume_url exists).\n"
        f"   - HERO PROFILE PHOTO / AVATAR: If photo exists (`{clean_profile.get('photo_url')}`), render it inside:\n"
        f"     `<div class=\"relative mx-auto lg:mx-0 w-64 h-64 sm:w-80 sm:h-80 md:w-96 md:h-96 rounded-3xl overflow-hidden border-2 border-emerald-400/40 shadow-2xl shadow-emerald-500/20 bg-slate-900 flex items-center justify-center\"><img src=\"{clean_profile.get('photo_url')}\" alt=\"{clean_profile.get('name')}\" class=\"w-full h-full object-cover object-top\" style=\"object-fit: cover; object-position: center top;\"></div>`\n\n"
        "3. FEATURED PROJECTS SECTION (<section id=\"projects\" class=\"py-20 sm:py-28 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto relative\">\n"
        "   - Section Header: Category pill badge + gradient title + subtitle.\n"
        "   - PROJECT CARD DESIGN RULES:\n"
        "     * Each project MUST be rendered as a split-grid bento card: `<div class=\"group relative bg-gradient-to-b from-slate-900/90 to-slate-950/90 backdrop-blur-2xl border border-white/10 hover:border-emerald-500/40 rounded-3xl p-6 sm:p-8 lg:p-10 shadow-2xl hover:shadow-emerald-500/15 transition-all duration-500 mb-10 overflow-hidden\"><div class=\"grid grid-cols-1 lg:grid-cols-12 gap-8 items-center\">...</div></div>`\n"
        "     * Media Showcase Column (`lg:col-span-5`): Use the EXACT pre-assigned `image_url` from the project item. Wrap inside `<div class=\"relative aspect-video sm:aspect-[16/10] lg:aspect-[4/3] rounded-2xl overflow-hidden border border-white/10 shadow-inner\"><img src=\"[project_image_url]\" alt=\"[project_name]\" class=\"w-full h-full object-cover object-center group-hover:scale-105 transition-transform duration-700 ease-out\"><div class=\"absolute inset-0 bg-gradient-to-t from-slate-950/80 via-transparent to-transparent opacity-60\"></div><div class=\"absolute top-3 left-3 px-3 py-1 rounded-full bg-slate-950/80 backdrop-blur-md border border-white/15 text-emerald-400 text-xs font-semibold flex items-center gap-1.5 shadow-lg\"><span class=\"w-2 h-2 rounded-full bg-emerald-400 animate-pulse\"></span>Featured System</div></div>`\n"
        "     * Info & Feature Column (`lg:col-span-7`):\n"
        "       1. Category tag + Date header row.\n"
        "       2. Project Title with hover transition.\n"
        "       3. High-Impact Description.\n"
        "       4. Role & Impact Callout Box (`<div class=\"p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80 mb-4 flex items-start gap-3\"><i class=\"fa-solid fa-user-gear text-emerald-400 text-sm mt-1 shrink-0\"></i><p class=\"text-xs sm:text-sm text-slate-300\"><span class=\"font-bold text-white\">Role & Contribution:</span> [Role details]</p></div>`).\n"
        "       5. Structured Key Features Grid in 2-column chips with check icons (`<i class=\"fa-solid fa-circle-check text-emerald-400\"></i>`).\n"
        "       6. Tech Stack Badges with SVG Devicon logos.\n"
        "       7. Live Demo & GitHub Action buttons.\n\n"
        "4. TECHNICAL SKILLS SECTION (<section id=\"skills\" class=\"py-20 sm:py-28 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto\">\n"
        "   - Categorized Bento cards rendering ALL {len(skills_list)} skills with their official Devicon SVG logos and glowing hover cards.\n\n"
        "5. WORK EXPERIENCE SECTION (<section id=\"experience\" class=\"py-20 sm:py-28 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto\">\n"
        f"   - Illuminated vertical gradient timeline track showcasing ALL {len(exp_list)} work positions.\n\n"
        "6. EDUCATION SECTION (<section id=\"education\" class=\"py-20 sm:py-28 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto\">\n"
        f"   - Glassmorphic credential cards for ALL {len(edu_list)} education entries.\n\n"
        "7. CERTIFICATIONS & ACHIEVEMENTS SECTION (<section id=\"certifications\" class=\"py-20 sm:py-28 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto\">\n"
        f"   - Dedicated badge cards for ALL {len(cert_list)} certifications and ALL {len(achieve_list)} achievements.\n\n"
        "8. CONTACT SECTION (<section id=\"contact\" class=\"py-20 sm:py-28 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto\">\n"
        "   - Glassmorphic card with contact form, direct copy-email card, phone/WhatsApp card, and social links.\n\n"
        "9. FOOTER (<footer>): Minimalist footer with copyright and smooth back-to-top button.\n\n"
        "=== IMPLEMENTATION STANDARDS ===\n"
        "1. COMPLETE STANDALONE HTML: Output a valid, fully closed `<!DOCTYPE html><html lang=\"en\" class=\"scroll-smooth\"><head>...<style>...</style></head><body class=\"min-h-screen antialiased font-['DM_Sans',sans-serif]\">...</body></html>` document.\n"
        "2. ZERO DUMMY / EMPTY BUTTONS: Only render link buttons when actual URLs exist in user data.\n"
        "3. RESPONSIVENESS: Clean on mobile (375px), tablet (768px), and desktop (1280px+)."
    )

    client = _get_gemini_client(api_key)
    config = types.GenerateContentConfig(
        max_output_tokens=32768,
        thinking_config=_low_thinking_config(types),
    )
    response = _call_gemini_with_fallback(client, prompt, config, model)

    raw_text = getattr(response, "text", "") or str(response)
    html = _extract_and_sanitize_html(raw_text)
    if not html or len(html) < 200:
        raise GeminiResponseError("Gemini generated an empty or incomplete HTML portfolio.")
    return html


def edit_portfolio_html_with_ai(current_html: str, user_instruction: str) -> tuple[str, str]:
    """Modify an existing portfolio HTML directly based on a user's natural language edit prompt.
    Returns (updated_html, friendly_response_message)."""
    if not current_html or not current_html.strip():
        raise GeminiResponseError("No existing portfolio HTML found to edit.")
    if not user_instruction or not user_instruction.strip():
        return current_html, "No changes were requested."

    api_key, model = _get_gemini_config()
    try:
        from google.genai import types
    except ImportError as exc:
        raise GeminiConfigurationError("The google-genai package is not installed.") from exc

    prompt = (
        "You are an expert Principal Frontend Architect and AI UI/UX Copilot.\n"
        "The user wants you to modify their existing single-file HTML portfolio.\n\n"
        "=== USER EDIT REQUEST ===\n"
        f"{user_instruction.strip()}\n\n"
        "=== MANDATORY OUTPUT FORMAT (CRITICAL) ===\n"
        "1. Write 1-2 concise, professional sentences explaining what modifications you applied.\n"
        "2. IMMEDIATELY AFTER, you MUST output the COMPLETE, 100% STANDALONE updated HTML document wrapped inside a single ```html ... ``` code block:\n"
        "```html\n"
        "<!DOCTYPE html>\n"
        "<html lang=\"en\" class=\"scroll-smooth\">\n"
        "<head>...</head>\n"
        "<body ...>\n"
        "  ...\n"
        "</body>\n"
        "</html>\n"
        "```\n"
        "CRITICAL RULE: You MUST output the ENTIRE HTML document inside ```html ... ```. It is FORBIDDEN to output only an explanation or truncate any section.\n\n"
        "=== EDITING & DESIGN GUIDELINES ===\n"
        "1. COLOR PALETTES & THEMES (SUPREME PRIORITY): If the user requests a theme (e.g. 'milk green', 'mint', 'emerald', 'cyberpunk', 'light theme', 'dark theme', 'warm orange', etc.):\n"
        "   - Re-theme the ENTIRE page: body background, navbar, hero glow orbs, card backgrounds, borders, gradient titles, badges, and button styles to match that exact aesthetic.\n"
        "   - For 'milk green' / 'mint green': Use background `#04150e` / `#061d14`, card background `bg-[#0a2c20]/70 backdrop-blur-xl border border-emerald-400/30`, gradients `from-emerald-300 via-teal-200 to-green-300`, glow effects `shadow-emerald-500/20`.\n"
        "2. SMOOTH ANIMATIONS: Incorporate smooth hover transitions (`hover:-translate-y-2 hover:shadow-2xl transition-all duration-500`), image scale on hover (`group-hover:scale-105 duration-700`), and floating keyframe animation classes.\n"
        "3. PROJECT PHOTOS: Assign high-resolution, domain-matching Unsplash photography matching the project's real context.\n"
        "4. PRESERVE all existing data, sections, and links unless explicitly asked to modify them.\n"
        "5. STRICT NO EMOJIS in code.\n\n"
        "=== CURRENT HTML DOCUMENT TO MODIFY ===\n"
        f"{current_html}"
    )

    client = _get_gemini_client(api_key)
    edit_thinking = _low_thinking_config(types)

    config = types.GenerateContentConfig(
        max_output_tokens=32768,
        thinking_config=edit_thinking,
    )
    response = _call_gemini_with_fallback(client, prompt, config, model)

    raw_text = getattr(response, "text", "") or str(response)
    updated_html = _extract_and_sanitize_html(raw_text)
    if not updated_html or len(updated_html) < 400:
        raise GeminiResponseError("Gemini did not return the complete updated HTML document. Please try sending your edit request again.")

    explanation = re.sub(r"```(?:html)?[\s\S]*?```", "", raw_text).strip()
    explanation = re.sub(r"^#+\s*.*$", "", explanation, flags=re.MULTILINE).strip()
    explanation = re.sub(r"^\s*[-*•]\s*", "", explanation, flags=re.MULTILINE).strip()
    explanation = re.sub(r"[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]", "", explanation).strip()
    explanation = " ".join(line.strip() for line in explanation.splitlines() if line.strip())

    if not explanation or len(explanation) < 15:
        explanation = f"I updated the portfolio with your requested design enhancements ('{user_instruction.strip()}'). The live preview has been refreshed."

    return updated_html, explanation


def _extract_and_sanitize_html(text: str) -> str:
    """Extract HTML from LLM output, allow trusted CDNs (Tailwind, Fonts, Devicon, Lucide, FontAwesome), strip unsafe JS, and inject robust Tailwind config and theme styling."""
    if not text or not isinstance(text, str):
        return ""
    
    html = ""
    # 1. Match code blocks containing <!DOCTYPE html ... </html>
    match = re.search(r"```(?:html)?\s*(<!DOCTYPE[\s\S]*?</html>)\s*```", text, re.IGNORECASE)
    if match:
        html = match.group(1).strip()
    else:
        # 2. Match code blocks containing <html ... </html> or general html tags
        code_match = re.search(r"```(?:html)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if code_match and ("<html" in code_match.group(1).lower() or "<body" in code_match.group(1).lower() or "<section" in code_match.group(1).lower()):
            html = code_match.group(1).strip()
        else:
            # 3. Match raw <!DOCTYPE html or <html without code blocks
            doc_start = re.search(r"<!DOCTYPE\s+html|<html", text, re.IGNORECASE)
            if doc_start:
                html = text[doc_start.start():].strip()
                html = re.sub(r"```\s*$", "", html).strip()

    # Require minimum valid HTML structural landmarks
    if not html or ("<body" not in html.lower() and "<section" not in html.lower() and "<main" not in html.lower() and "<nav" not in html.lower()):
        return ""

    # Allowed script CDN domains
    allowed_script_cdns = (
        "cdn.tailwindcss.com",
        "cdnjs.cloudflare.com",
        "unpkg.com",
        "cdn.jsdelivr.net",
        "cdn.skypack.dev",
    )

    # Function to sanitize script tags: preserve trusted CDNs, strip inline/untrusted scripts
    def sanitize_script(match_obj):
        tag = match_obj.group(0)
        # Check if script has a trusted src
        src_match = re.search(r'src=["\'](https?://[^"\']+)["\']', tag, re.IGNORECASE)
        if src_match:
            src_url = src_match.group(1).lower()
            if any(cdn in src_url for cdn in allowed_script_cdns):
                return tag  # Preserve trusted CDN script
        return ""  # Remove untrusted script

    html = re.sub(r"<script\b[^>]*>[\s\S]*?<\/script>", sanitize_script, html, flags=re.IGNORECASE)
    html = re.sub(r"javascript:\s*", "", html, flags=re.IGNORECASE)
    html = re.sub(r"on\w+\s*=\s*[\"'][^\"']*[\"']", "", html, flags=re.IGNORECASE)

    # Clean malformed img tags with stray URLs inside tag definition
    html = re.sub(r'(<img\b[^>]*?)\s+https?://[^\s"\'>]+([\'"]?)', r'\1', html)

    # Ensure smooth scrolling on html tag without forcing dark mode over light themes
    if "<html" in html:
        if "scroll-smooth" not in html:
            html = re.sub(r'<html\b([^>]*)>', r'<html class="scroll-smooth"\1>', html, count=1, flags=re.IGNORECASE)

    # Fix broken or partial meta viewport tags
    if re.search(r'<meta\s+name=["\']viewport["\'][^>]*', html, re.IGNORECASE):
        html = re.sub(r'<meta\s+name=["\']viewport["\'][^>]*>', '<meta name="viewport" content="width=device-width, initial-scale=1.0">', html, flags=re.IGNORECASE)
    elif "<head>" in html:
        html = html.replace("<head>", '<head>\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">', 1)

    # Ensure Tailwind CSS is present
    if "cdn.tailwindcss.com" not in html and "<head>" in html:
        tailwind_script = '<script src="https://cdn.tailwindcss.com"></script>'
        html = html.replace("<head>", f"<head>\n  {tailwind_script}", 1)

    # Comprehensive Tailwind configuration defining custom palette colors, fonts, and glowing shadows
    full_tailwind_config = (
        '<script>\n'
        '  tailwind.config = {\n'
        '    darkMode: "class",\n'
        '    theme: {\n'
        '      extend: {\n'
        '        fontFamily: {\n'
        '          sans: ["Plus Jakarta Sans", "DM Sans", "sans-serif"],\n'
        '          display: ["Space Grotesk", "Outfit", "Plus Jakarta Sans", "sans-serif"],\n'
        '          heading: ["Space Grotesk", "Outfit", "Plus Jakarta Sans", "sans-serif"],\n'
        '          mono: ["JetBrains Mono", "monospace"],\n'
        '        },\n'
        '        boxShadow: {\n'
        '          "glow-emerald": "0 0 30px rgba(16, 185, 129, 0.35)",\n'
        '          "glow-cyan": "0 0 30px rgba(6, 182, 212, 0.35)",\n'
        '          "glow-indigo": "0 0 30px rgba(99, 102, 241, 0.35)",\n'
        '        }\n'
        '      }\n'
        '    }\n'
        '  };\n'
        '</script>'
    )
    if "<head>" in html:
        html = html.replace("<head>", f"<head>\n  {full_tailwind_config}", 1)

    # Ensure Google Fonts link is present in head if missing
    if "fonts.googleapis.com" not in html and "<head>" in html:
        google_fonts_link = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;600;700;800&family=Space+Grotesk:wght@400;600;700;800&family=Plus+Jakarta+Sans:wght@400;600;700;800&family=Outfit:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">'
        html = html.replace("<head>", f"<head>\n  {google_fonts_link}", 1)

    # Ensure FontAwesome is available for icon classes
    if "font-awesome" not in html and "<head>" in html:
        fa_link = '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">'
        html = html.replace("<head>", f"<head>\n  {fa_link}", 1)

    # Ensure Devicon is available for official programming & technology brand logos
    if "devicon" not in html and "<head>" in html:
        devicon_link = '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.16.0/devicon.min.css">'
        html = html.replace("<head>", f"<head>\n  {devicon_link}", 1)

    # Ensure Lucide Icons library is loaded and initialized so data-lucide icons render
    lucide_script = (
        '<script src="https://unpkg.com/lucide@latest"></script>\n'
        '<script>\n'
        '  document.addEventListener("DOMContentLoaded", function() {\n'
        '    if (window.lucide) { lucide.createIcons(); }\n'
        '  });\n'
        '</script>'
    )
    if "<head>" in html:
        html = html.replace("<head>", f"<head>\n  {lucide_script}", 1)

    # Smooth animations & fluid transitions styling without hardcoded background overrides
    theme_styles = (
        '<style>\n'
        '  html { scroll-behavior: smooth; }\n'
        '  h1, h2, h3 { text-wrap: balance; }\n'
        '  .glass-card, [class*="glass"] {\n'
        '    backdrop-filter: blur(16px);\n'
        '    -webkit-backdrop-filter: blur(16px);\n'
        '    transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);\n'
        '  }\n'
        '  .glass-card:hover, [class*="glass"]:hover {\n'
        '    transform: translateY(-6px);\n'
        '  }\n'
        '  [class^="devicon-"], [class*=" devicon-"] { font-family: "devicon" !important; font-style: normal !important; display: inline-block !important; line-height: 1 !important; }\n'
        '  @keyframes floatSlow {\n'
        '    0%, 100% { transform: translateY(0); }\n'
        '    50% { transform: translateY(-8px); }\n'
        '  }\n'
        '  @keyframes pulseGlow {\n'
        '    0%, 100% { opacity: 0.35; transform: scale(1); }\n'
        '    50% { opacity: 0.75; transform: scale(1.02); }\n'
        '  }\n'
        '  @keyframes shimmer {\n'
        '    0% { background-position: -200% 0; }\n'
        '    100% { background-position: 200% 0; }\n'
        '  }\n'
        '  .animate-float { animation: floatSlow 5s ease-in-out infinite; }\n'
        '  .animate-glow { animation: pulseGlow 4s ease-in-out infinite; }\n'
        '  .reveal-on-scroll {\n'
        '    opacity: 0;\n'
        '    transform: translateY(24px);\n'
        '    transition: opacity 0.7s cubic-bezier(0.16, 1, 0.3, 1), transform 0.7s cubic-bezier(0.16, 1, 0.3, 1);\n'
        '  }\n'
        '  .reveal-on-scroll.is-visible {\n'
        '    opacity: 1 !important;\n'
        '    transform: translateY(0) !important;\n'
        '  }\n'
        '</style>'
    )
    if "</head>" in html:
        html = html.replace("</head>", f"  {theme_styles}\n</head>", 1)

    # Universal Mobile Menu, Smooth Scroll, and Intersection Observer Scroll Reveal Script
    interactivity_script = (
        '<script>\n'
        '  (function() {\n'
        '    function setupInteractivity() {\n'
        '      var nav = document.querySelector("nav");\n'
        '      var menuBtn = document.getElementById("mobile-menu-btn") || document.querySelector("[aria-label*=\'menu\' i]") || (nav ? nav.querySelector("button") : null);\n'
        '      var menu = document.getElementById("mobile-menu") || document.querySelector("[data-mobile-menu]") || document.querySelector(".mobile-menu");\n'
        '\n'
        '      if (nav && !menu) {\n'
        '        var navLinks = nav.querySelectorAll("a[href^=\'#\']");\n'
        '        if (navLinks.length > 0) {\n'
        '          menu = document.createElement("div");\n'
        '          menu.id = "mobile-menu";\n'
        '          menu.className = "hidden md:hidden fixed inset-x-0 top-16 sm:top-20 bg-slate-950/95 backdrop-blur-2xl border-b border-white/10 px-6 py-6 space-y-4 shadow-2xl z-40";\n'
        '          navLinks.forEach(function(link) {\n'
        '            if (link.getAttribute("href") !== "#hero") {\n'
        '              var clone = link.cloneNode(true);\n'
        '              clone.className = "block text-base font-semibold text-slate-200 hover:text-emerald-400 py-1 transition-colors";\n'
        '              menu.appendChild(clone);\n'
        '            }\n'
        '          });\n'
        '          nav.appendChild(menu);\n'
        '        }\n'
        '      }\n'
        '\n'
        '      if (menuBtn && menu) {\n'
        '        menuBtn.setAttribute("type", "button");\n'
        '        menuBtn.addEventListener("click", function(e) {\n'
        '          e.stopPropagation();\n'
        '          var isHidden = menu.classList.contains("hidden") || menu.style.display === "none";\n'
        '          if (isHidden) {\n'
        '            menu.classList.remove("hidden");\n'
        '            menu.style.display = "block";\n'
        '            menuBtn.setAttribute("aria-expanded", "true");\n'
        '          } else {\n'
        '            menu.classList.add("hidden");\n'
        '            menu.style.display = "none";\n'
        '            menuBtn.setAttribute("aria-expanded", "false");\n'
        '          }\n'
        '        });\n'
        '\n'
        '        document.addEventListener("click", function(e) {\n'
        '          if (!menu.contains(e.target) && !menuBtn.contains(e.target)) {\n'
        '            menu.classList.add("hidden");\n'
        '            menu.style.display = "none";\n'
        '            menuBtn.setAttribute("aria-expanded", "false");\n'
        '          }\n'
        '        });\n'
        '\n'
        '        menu.querySelectorAll("a").forEach(function(link) {\n'
        '          link.addEventListener("click", function() {\n'
        '            menu.classList.add("hidden");\n'
        '            menu.style.display = "none";\n'
        '            menuBtn.setAttribute("aria-expanded", "false");\n'
        '          });\n'
        '        });\n'
        '      }\n'
        '\n'
        '      document.querySelectorAll("a[href^=\'#\']").forEach(function(anchor) {\n'
        '        anchor.addEventListener("click", function(e) {\n'
        '          var targetId = this.getAttribute("href");\n'
        '          if (targetId && targetId !== "#") {\n'
        '            var target = document.querySelector(targetId);\n'
        '            if (target) {\n'
        '              e.preventDefault();\n'
        '              target.scrollIntoView({ behavior: "smooth", block: "start" });\n'
        '            }\n'
        '          }\n'
        '        });\n'
        '      });\n'
        '\n'
        '      // Silky-Smooth Scroll Reveal Animation Runner\n'
        '      if ("IntersectionObserver" in window) {\n'
        '        var revealObserver = new IntersectionObserver(function(entries) {\n'
        '          entries.forEach(function(entry) {\n'
        '            if (entry.isIntersecting) {\n'
        '              entry.target.classList.add("is-visible");\n'
        '              revealObserver.unobserve(entry.target);\n'
        '            }\n'
        '          });\n'
        '        }, { threshold: 0.08, rootMargin: "0px 0px -30px 0px" });\n'
        '\n'
        '        document.querySelectorAll("section, article, .group, .bento-card").forEach(function(el) {\n'
        '          if (!el.classList.contains("reveal-on-scroll")) {\n'
        '            el.classList.add("reveal-on-scroll");\n'
        '            revealObserver.observe(el);\n'
        '          }\n'
        '        });\n'
        '      }\n'
        '    }\n'
        '\n'
        '    if (document.readyState === "loading") {\n'
        '      document.addEventListener("DOMContentLoaded", setupInteractivity);\n'
        '    } else {\n'
        '      setupInteractivity();\n'
        '    }\n'
        '  })();\n'
        '</script>'
    )
    if "</body>" in html:
        html = html.replace("</body>", f"  {interactivity_script}\n</body>", 1)
    else:
        html += f"\n{interactivity_script}"

    # Merge trailing single-character initials inside the name highlight span
    html = re.sub(r'(<span\b[^>]*class=["\'][^"\']*(?:gradient|text-)[^"\']*["\'][^>]*>[^<]+)</span>\s*([A-Za-z])\b', r'\1 \2</span>', html, flags=re.IGNORECASE)

    # Clean empty anchor tags that have no text and no children (e.g. <a href="#"></a> or <a href=""></a>)
    html = re.sub(r'<a\b[^>]*>\s*</a>', '', html, flags=re.IGNORECASE)

    # Auto-upgrade social icons to official FontAwesome 6 Brand classes
    html = re.sub(r'<i\b[^>]*class=["\'][^"\']*devicon-github[^"\']*["\'][^>]*>\s*</i>', '<i class="fa-brands fa-github text-xl"></i>', html, flags=re.IGNORECASE)
    html = re.sub(r'<i\b[^>]*class=["\'][^"\']*devicon-linkedin[^"\']*["\'][^>]*>\s*</i>', '<i class="fa-brands fa-linkedin text-xl"></i>', html, flags=re.IGNORECASE)
    html = re.sub(r'<i\b[^>]*class=["\'][^"\']*devicon-twitter[^"\']*["\'][^>]*>\s*</i>', '<i class="fa-brands fa-x-twitter text-xl"></i>', html, flags=re.IGNORECASE)

    # Technology SVG Map
    svg_icon_map = {
        "python": "python/python-original.svg",
        "java": "java/java-original.svg",
        "javascript": "javascript/javascript-original.svg",
        "typescript": "typescript/typescript-original.svg",
        "html5": "html5/html5-original.svg",
        "css3": "css3/css3-original.svg",
        "react": "react/react-original.svg",
        "nodejs": "nodejs/nodejs-original.svg",
        "nextjs": "nextjs/nextjs-original.svg",
        "postgresql": "postgresql/postgresql-original.svg",
        "mysql": "mysql/mysql-original.svg",
        "mongodb": "mongodb/mongodb-original.svg",
        "supabase": "supabase/supabase-original.svg",
        "firebase": "firebase/firebase-plain.svg",
        "photoshop": "photoshop/photoshop-original.svg",
        "illustrator": "illustrator/illustrator-plain.svg",
        "figma": "figma/figma-original.svg",
        "docker": "docker/docker-original.svg",
        "git": "git/git-original.svg",
        "tailwindcss": "tailwindcss/tailwindcss-original.svg",
        "bootstrap": "bootstrap/bootstrap-original.svg",
        "cplusplus": "cplusplus/cplusplus-original.svg",
        "csharp": "csharp/csharp-original.svg",
        "django": "django/django-plain.svg",
        "flask": "flask/flask-original.svg",
        "spring": "spring/spring-original.svg",
    }

    def _replace_devicon_with_svg(match_obj):
        tech = match_obj.group(1).lower()
        if tech in svg_icon_map:
            svg_url = f"https://cdn.jsdelivr.net/gh/devicons/devicon/icons/{svg_icon_map[tech]}"
            return f'<img src="{svg_url}" class="w-8 h-8 inline-block object-contain" alt="{tech}">'
        return match_obj.group(0)

    html = re.sub(r'<i\b[^>]*class=["\'][^"\']*devicon-([a-z0-9]+)-[^"\']*["\'][^>]*>\s*</i>', _replace_devicon_with_svg, html, flags=re.IGNORECASE)

    # Fix any invalid or 404 Unsplash URLs with verified 200 OK alternatives
    html = html.replace("photo-1677442136019-21780efad99a", "photo-1555255707-c07966088b7b")
    html = html.replace("photo-1556742049-0a67c5574f73", "photo-1559526324-4b87b5e36e44")

    # Remove stray emojis from code blocks
    html = html.replace("🚀", "").replace("☕", "").replace("🐍", "")

    # If document was cut off before closing tags, cleanly close it
    if "</html>" not in html:
        if "</main>" not in html and "<main" in html:
            html += "\n  </main>"
        if "</body>" not in html:
            html += "\n</body>"
        html += "\n</html>"

    return html


def _is_rate_limit(error):
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    return status == 429 or "429" in str(error) or "rate limit" in str(error).lower()


def get_gemini_diagnostic():
    try:
        api_key, model = _get_gemini_config()
    except GeminiConfigurationError:
        api_key = None
        model = current_app.config.get("GEMINI_MODEL", "gemini-3.6-flash")
    try:
        from google import genai
        sdk_installed = True
    except ImportError:
        sdk_installed = False
    return {
        "configured": bool(api_key),
        "model": model,
        "sdk_installed": sdk_installed,
    }


def ping_gemini():
    api_key, model = _get_gemini_config()
    try:
        from google.genai import types
    except ImportError as exc:
        raise GeminiConfigurationError("The google-genai package is not installed.") from exc
    try:
        client = _get_gemini_client(api_key)
        response = client.models.generate_content(
            model=model,
            contents="Reply with the word OK.",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=200,
                thinking_config=_low_thinking_config(types),
            ),
        )
    except Exception as exc:
        _log_gemini_error(exc, model)
        if _is_rate_limit(exc):
            raise GeminiRateLimitError from exc
        raise GeminiServiceError from exc
    text = getattr(response, "text", "") or str(response)
    return {"response": text.strip()}
