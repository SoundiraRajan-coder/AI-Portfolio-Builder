import mimetypes

from flask import Flask

from app.config import Config
from app.database import init_pool
from app.extensions import init_oauth


def create_app(config_class=Config):
    mimetypes.add_type("application/javascript", ".js")
    app = Flask(__name__)
    app.config.from_object(config_class)
    init_oauth(app)
    init_pool(app)


    from app.csrf import ensure_csrf_token, validate_csrf
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.portfolios import portfolios_bp
    from app.routes.profile import profile_bp
    from app.routes.gemini_diagnostic import gemini_diag_bp

    app.before_request(validate_csrf)

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": ensure_csrf_token()}

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if app.config.get("SESSION_COOKIE_SECURE") and not app.debug:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
        return response

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(portfolios_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(gemini_diag_bp)
    return app
