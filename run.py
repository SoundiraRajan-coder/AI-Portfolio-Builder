from app import create_app

app = create_app()


# Trigger reload: 2026-09-09 AI Portfolio Builder v2.4.0 Nested Dict String Fix
if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"])
