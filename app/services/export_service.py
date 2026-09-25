import io
import os
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from app.services.renderer import render_portfolio, RendererError

EXPORT_MAX_BYTES = 25 * 1024 * 1024
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
SAFE_NAME_RE = re.compile(r"[^a-z0-9_.-]+")
IMAGE_MAX_BYTES = 5 * 1024 * 1024


class ExportError(ValueError):
    """Raised when a portfolio export cannot be created."""


def _sanitize_portfolio_name(name: str) -> str:
    if not isinstance(name, str):
        return "portfolio"
    safe = SAFE_NAME_RE.sub("-", name.strip().lower())
    safe = safe.strip("-")[:120]
    return safe or "portfolio"


def _clean_archive_name(path: str) -> str:
    normalized = os.path.normpath(path).replace("\\", "/")
    if normalized.startswith("../") or normalized.startswith("/"):
        raise ExportError("Invalid archive entry name.")
    return normalized


def _rewrite_static_urls(html: str) -> str:
    return re.sub(r'(?P<attr>href|src)="[^"]*/static/(?P<path>[^"]+)"', r'\g<attr>="\g<path>"', html)


def _find_local_static_paths(html: str) -> set:
    """Find non-http src/href attributes that reference local static files after rewrite."""
    matches = re.findall(r'(?:href|src)="(?!https?:|data:)([^"]+)"', html)
    paths = {m.split('#')[0].split('?')[0].strip() for m in matches}
    return {p for p in paths if p and not p.startswith(('mailto:', 'tel:', 'javascript:', '#'))}


def _is_external_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and parsed.netloc
    except Exception:
        return False


def _download_image(url: str, max_bytes: int = IMAGE_MAX_BYTES) -> bytes:
    try:
        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "image/*,*/*;q=0.8",
            },
        )
        with urlopen(req, timeout=12) as resp:
            info = resp.info()
            content_type = info.get_content_type()
            # Allow image/* or octet-stream for images
            if not (content_type.startswith("image/") or content_type == "application/octet-stream"):
                raise ExportError("Referenced image is not a valid image file.")
            total = 0
            chunks = []
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ExportError("Referenced image is too large to include in the export.")
                chunks.append(chunk)
            return b"".join(chunks)
    except Exception as exc:
        raise ExportError(f"Could not download image {url}: {exc}") from exc


def _read_static_file(relative_path: str) -> bytes:
    candidate = STATIC_DIR / Path(relative_path)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ExportError(f"Required static file is missing: {relative_path}") from exc
    if not str(resolved).startswith(str(STATIC_DIR.resolve())) or not resolved.is_file():
        raise ExportError(f"Invalid static file path: {relative_path}")
    return resolved.read_bytes()


def _build_readme(portfolio_name: str) -> str:
    return (
        f"Portfolio Forge Export\n"
        f"======================\n\n"
        f"This folder contains a standalone export of '{portfolio_name}'.\n"
        f"Open index.html in a web browser to view the portfolio.\n\n"
        f"If you want to host it on a web server or GitHub Pages, upload all extracted files and folders.\n"
        f"Google Fonts are loaded automatically when an internet connection is available.\n"
    )


def create_portfolio_export(builder_state: dict) -> tuple[io.BytesIO, str]:
    if not isinstance(builder_state, dict):
        raise ExportError("Invalid portfolio data for export.")

    portfolio_name = builder_state.get("portfolio", {}).get("name") or "portfolio"
    filename = f"{_sanitize_portfolio_name(portfolio_name)}.zip"
    try:
        rendered_html = render_portfolio(builder_state)
    except RendererError as exc:
        raise ExportError("The portfolio could not be rendered for export.") from exc

    exported_html = _rewrite_static_urls(rendered_html)

    # Collect static paths referenced in the rendered html (after rewrite)
    local_static_paths = _find_local_static_paths(exported_html)

    stylesheet_paths = set()
    js_paths = set()
    other_static = set()

    for p in local_static_paths:
        if p.startswith("css/"):
            stylesheet_paths.add(p)
        elif p.startswith("js/"):
            js_paths.add(p)
        elif not p.startswith("uploads/"):
            other_static.add(p)

    # Ensure core portfolio stylesheets are included
    stylesheet_paths.add("css/portfolio.css")
    stylesheet_paths.add("css/templates/portfolio_design_tokens.css")
    stylesheet_paths.add("css/ai_renderer_variants.css")
    stylesheet_paths.add("css/portfolio_composition.css")

    # Assets collected from builder_data (profile image, wizard photo, project images)
    external_images = []
    
    # 1. Profile / Avatar / Photo (ONLY use portfolio wizard photo, exclude Google account avatar)
    wizard_profile = builder_state.get("wizard", {}).get("profile", {}) or {}
    spec_profile = builder_state.get("design_spec", {}).get("content", {}).get("profile", {}) or {}
    
    candidate_avatars = [
        wizard_profile.get("photo_url"),
        spec_profile.get("photo_url"),
    ]
    for av in candidate_avatars:
        if av and _is_external_url(av) and (av, "assets/profile") not in external_images:
            external_images.append((av, "assets/profile"))

    # 2. Project images
    records = builder_state.get("records", {}) or {}
    wizard_projects = builder_state.get("wizard", {}).get("portfolio", {}).get("projects", []) or []
    spec_projects = builder_state.get("design_spec", {}).get("content", {}).get("projects", []) or []
    
    all_projects = list(records.get("projects", [])) + list(wizard_projects) + list(spec_projects)
    for proj in all_projects:
        if isinstance(proj, dict):
            img = proj.get("image_url") or proj.get("image")
            if img and _is_external_url(img) and (img, "assets/projects") not in external_images:
                external_images.append((img, "assets/projects"))

    # 3. Any additional external images inside the rendered HTML
    html_img_urls = re.findall(r'src=["\'](https?://[^"\']+)["\']', exported_html)
    for img_url in html_img_urls:
        if "fonts.googleapis" not in img_url and "gstatic.com" not in img_url:
            if not any(img_url == item[0] for item in external_images):
                external_images.append((img_url, "assets/images"))

    with tempfile.TemporaryDirectory() as staging_dir:
        staging_root = Path(staging_dir)
        (staging_root / "index.html").write_text(exported_html, encoding="utf-8")
        (staging_root / "README.txt").write_text(_build_readme(portfolio_name), encoding="utf-8")
        (staging_root / "assets").mkdir(parents=True, exist_ok=True)
        (staging_root / "assets" / "profile").mkdir(parents=True, exist_ok=True)
        (staging_root / "assets" / "projects").mkdir(parents=True, exist_ok=True)
        (staging_root / "assets" / "images").mkdir(parents=True, exist_ok=True)

        # Copy and bundle local uploads (photo, resume PDF) referenced in the portfolio
        local_upload_matches = re.findall(r'(?:href|src)=["\'](?:\/static\/)?(uploads\/[^"\']+)["\']', rendered_html)
        for upload_rel_path in set(local_upload_matches):
            clean_rel = upload_rel_path.lstrip("/").replace("\\", "/")
            candidate_file = STATIC_DIR / clean_rel
            if candidate_file.is_file():
                target_name = candidate_file.name
                dest_asset_path = staging_root / "assets" / target_name
                dest_asset_path.parent.mkdir(parents=True, exist_ok=True)
                dest_asset_path.write_bytes(candidate_file.read_bytes())
                
                # Rewrite both /static/uploads/... and uploads/... in exported_html
                exported_html = re.sub(
                    r'(href|src)=["\'](?:\/static\/)?' + re.escape(clean_rel) + r'["\']',
                    rf'\1="assets/{target_name}"',
                    exported_html
                )

        # Copy referenced stylesheets
        for stylesheet in stylesheet_paths:
            try:
                css_content = _read_static_file(stylesheet)
                css_destination = staging_root / _clean_archive_name(stylesheet)
                css_destination.parent.mkdir(parents=True, exist_ok=True)
                css_destination.write_bytes(css_content)
            except Exception:
                # If optional stylesheet missing, continue without breaking entire export
                continue

        # Copy referenced JS files if any
        for js in js_paths:
            try:
                js_content = _read_static_file(js)
                js_destination = staging_root / _clean_archive_name(js)
                js_destination.parent.mkdir(parents=True, exist_ok=True)
                js_destination.write_bytes(js_content)
            except Exception:
                continue

        # Copy other static files referenced directly (images/icons)
        for other in other_static:
            try:
                data = _read_static_file(other)
                dst = staging_root / _clean_archive_name(other)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
            except Exception:
                continue

        # Download and include external images referenced in builder data
        for url, dest_dir in external_images:
            try:
                img_bytes = _download_image(url)
                parsed = urlparse(url)
                name = Path(parsed.path).name or "image.jpg"
                if "." not in name:
                    name = f"{name}.jpg"
                safe_name = SAFE_NAME_RE.sub("-", name).strip("-")[:120] or "image.jpg"
                destination = staging_root / dest_dir / safe_name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(img_bytes)
                # Replace occurrences of the original URL in exported_html with new relative path
                exported_html = exported_html.replace(url, f"{dest_dir}/{safe_name}")
            except Exception:
                # Keep original external URL if download fails rather than blocking entire export
                continue

        # Update index.html with any replacements we made
        (staging_root / "index.html").write_text(exported_html, encoding="utf-8")

        archive_path = staging_root / "portfolio_export.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for file_path in staging_root.rglob("*"):
                if file_path == archive_path or file_path.is_dir():
                    continue
                archive.write(file_path, file_path.relative_to(staging_root))

        archive_bytes = archive_path.read_bytes()
        if len(archive_bytes) > EXPORT_MAX_BYTES:
            raise ExportError("The generated portfolio export is too large.")

        buffer = io.BytesIO(archive_bytes)
        buffer.seek(0)
        return buffer, filename
