from app.services.design_spec import SPEC_DEFAULTS, validate_design_spec

# Palette format: (light_bg, dark_bg, primary_accent, accent_strong, secondary_accent, muted_light, muted_dark)
PALETTES = {
    "blue": (
        "#f0f7ff", "#070e1e", "#2563eb", "#1d4ed8", "#38bdf8", "#475569", "#94a3b8"
    ),
    "indigo": (
        "#f5f3ff", "#0b0c1e", "#6366f1", "#4f46e5", "#818cf8", "#4b5563", "#a5b4fc"
    ),
    "violet": (
        "#faf5ff", "#0f0821", "#9333ea", "#7e22ce", "#c084fc", "#581c87", "#c4b5fd"
    ),
    "cyberpunk": (
        "#fdf4ff", "#050711", "#00f0ff", "#00c4d4", "#ff007f", "#475569", "#7dd3fc"
    ),
    "emerald": (
        "#f0fdf4", "#04150f", "#059669", "#047857", "#34d399", "#374151", "#6ee7b7"
    ),
    "teal": (
        "#f0fdfa", "#041416", "#0d9488", "#0f766e", "#2dd4bf", "#334155", "#5eead4"
    ),
    "coral": (
        "#fff5f2", "#180d09", "#ea580c", "#c2410c", "#fb923c", "#57534e", "#fdba74"
    ),
    "crimson": (
        "#fff1f2", "#18060a", "#e11d48", "#be123c", "#fb7185", "#4c0519", "#fda4af"
    ),
    "amber": (
        "#fffbeb", "#161003", "#d97706", "#b45309", "#fcd34d", "#78350f", "#fde68a"
    ),
    "rose": (
        "#fff1f5", "#180810", "#e11d48", "#db2777", "#f472b6", "#500724", "#fbcfe8"
    ),
    "gold": (
        "#fffdf0", "#141005", "#ca8a04", "#a16207", "#facc15", "#713f12", "#fef08a"
    ),
    "slate": (
        "#f8fafc", "#0f172a", "#3b82f6", "#1d4ed8", "#64748b", "#475569", "#94a3b8"
    ),
    "dark_obsidian": (
        "#f4f4f5", "#09090b", "#a1a1aa", "#71717a", "#e4e4e7", "#52525b", "#a1a1aa"
    ),
    "monochrome": (
        "#ffffff", "#000000", "#18181b", "#09090b", "#71717a", "#52525b", "#a1a1aa"
    ),
}

FONT_STYLES = {
    "modern": ("'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif", "'Space Grotesk', sans-serif"),
    "classic": ("Georgia, 'Times New Roman', serif", "Georgia, serif"),
    "mono": ("'SF Mono', 'Fira Code', 'Courier New', monospace", "'SF Mono', 'Fira Code', monospace"),
    "editorial": ("'Newsreader', Georgia, serif", "'Playfair Display', Georgia, serif"),
    "futuristic": ("'DM Sans', sans-serif", "'Space Grotesk', 'Arial Black', sans-serif"),
    "tech": ("'JetBrains Mono', 'Fira Code', monospace", "'Space Grotesk', sans-serif"),
    "geometric": ("'Plus Jakarta Sans', sans-serif", "'Outfit', sans-serif"),
    "serif": ("'Lora', Georgia, serif", "'Playfair Display', serif"),
}

SPACING = {
    "compact": ("18px", "32px", "36px"),
    "normal": ("32px", "56px", "64px"),
    "generous": ("48px", "88px", "100px"),
    "editorial": ("40px", "72px", "84px"),
}

RADII = {
    "none": "0px",
    "subtle": "6px",
    "rounded": "16px",
    "pill": "28px",
}

SHADOWS = {
    "none": "none",
    "subtle": "0 2px 8px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.06)",
    "soft": "0 4px 20px -2px rgba(0, 0, 0, 0.08), 0 2px 6px -1px rgba(0, 0, 0, 0.04)",
    "medium": "0 12px 32px -4px rgba(0, 0, 0, 0.12), 0 4px 12px -2px rgba(0, 0, 0, 0.08)",
    "dramatic": "0 24px 60px -8px rgba(0, 0, 0, 0.28), 0 8px 24px -4px rgba(0, 0, 0, 0.16)",
    "glow": "0 0 32px -4px color-mix(in srgb, var(--pf-accent) 45%, transparent), 0 8px 24px -4px rgba(0, 0, 0, 0.2)",
}


def build_design_context(raw_spec=None):
    spec = validate_design_spec(raw_spec if raw_spec is not None else {})
    is_dark = spec["theme"] == "dark"

    p_palette = PALETTES.get(spec["primary_color"], PALETTES["blue"])
    s_palette = PALETTES.get(spec["secondary_color"], PALETTES["violet"])

    p_light_bg, p_dark_bg, p_accent, p_accent_strong, p_secondary_alt, p_muted_light, p_muted_dark = p_palette
    _, _, s_accent, s_accent_strong, _, _, _ = s_palette

    body_bg = p_dark_bg if is_dark else p_light_bg
    text_color = "#f8fafc" if is_dark else "#0f172a"
    muted_color = p_muted_dark if is_dark else p_muted_light
    accent = p_accent
    accent_strong = p_accent_strong
    secondary = s_accent

    # Surface & Card colors
    is_glass = spec["style"] == "glassmorphism"
    if is_glass:
        card_bg = "rgba(255, 255, 255, 0.06)" if is_dark else "rgba(255, 255, 255, 0.65)"
        surface = "rgba(255, 255, 255, 0.08)" if is_dark else "rgba(255, 255, 255, 0.8)"
        border_color = "rgba(255, 255, 255, 0.15)" if is_dark else "rgba(0, 0, 0, 0.08)"
    elif is_dark:
        card_bg = "color-mix(in srgb, var(--pf-body-bg) 82%, white 18%)"
        surface = "color-mix(in srgb, var(--pf-body-bg) 88%, white 12%)"
        border_color = "color-mix(in srgb, var(--pf-body-bg) 75%, white 25%)"
    else:
        card_bg = "#ffffff"
        surface = "#ffffff"
        border_color = "rgba(15, 23, 42, 0.09)"

    font_body, font_heading = FONT_STYLES.get(spec["font_style"], FONT_STYLES["modern"])
    section_gap, section_padding, page_padding = SPACING.get(spec["spacing"], SPACING["normal"])
    radius = RADII.get(spec["border_radius"], RADII["rounded"])
    shadow = SHADOWS.get(spec["shadows"], SHADOWS["medium"])

    # Badge styling
    badge_bg = "color-mix(in srgb, var(--pf-accent) 14%, transparent)" if is_dark else "color-mix(in srgb, var(--pf-accent) 10%, #ffffff)"
    badge_text = p_secondary_alt if is_dark else p_accent_strong

    css_vars = {
        "--pf-body-bg": body_bg,
        "--pf-text": text_color,
        "--pf-muted": muted_color,
        "--pf-accent": accent,
        "--pf-accent-strong": accent_strong,
        "--pf-secondary": secondary,
        "--pf-surface": surface,
        "--pf-card-bg": card_bg,
        "--pf-border": border_color,
        "--pf-radius": radius,
        "--pf-shadow": shadow,
        "--pf-font-body": font_body,
        "--pf-font-heading": font_heading,
        "--pf-section-gap": section_gap,
        "--pf-section-padding": section_padding,
        "--pf-page-padding": page_padding,
        "--pf-page-max-width": "1420px" if spec["layout"] in {"editorial", "asymmetric"} else ("1080px" if spec["density"] == "compact" else "1220px"),
        "--pf-animation-duration": ".25s" if spec["animations"] else "0s",
        "--pf-badge-bg": badge_bg,
        "--pf-badge-text": badge_text,
    }

    classes = [
        f"theme-{spec['theme']}",
        f"style-{spec['style']}",
        f"layout-{spec['layout']}",
        f"arrangement-{spec['section_arrangement']}",
        f"background-{spec['background']}",
        f"density-{spec['density']}",
        f"effects-{spec['effects']}",
        "glass-enabled" if is_glass else "",
    ]

    return {
        "spec": spec,
        "classes": [c for c in classes if c],
        "css_vars": css_vars,
    }
