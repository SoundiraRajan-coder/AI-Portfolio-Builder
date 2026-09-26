from app import create_app

app = create_app()


# Trigger reload: 2026-09-09 Portfolio Forge v2.4.0 Nested Dict String Fix
if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"])
