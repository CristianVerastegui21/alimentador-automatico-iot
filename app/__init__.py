import os
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "1") == "1",
        MAX_CONTENT_LENGTH=16384,
        DEBUG=os.getenv("FLASK_DEBUG", "0") == "1",
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"] or app.config["SECRET_KEY"] == "dev-only-change-me":
        if not app.config.get("TESTING"):
            raise RuntimeError("Configura SECRET_KEY aleatoria en .env / Render")
    if not app.config.get("TESTING"):
        if not os.getenv("ADMIN_EMAIL") or not os.getenv("ADMIN_PASSWORD"):
            raise RuntimeError("Configura ADMIN_EMAIL y ADMIN_PASSWORD")
        if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_KEY"):
            raise RuntimeError("Configura SUPABASE_URL y SUPABASE_KEY")
        if not os.getenv("DEVICE_TOKEN") or len(os.getenv("DEVICE_TOKEN")) < 32:
            raise RuntimeError("DEVICE_TOKEN debe tener al menos 32 caracteres")
    from .routes import bp
    app.register_blueprint(bp)
    return app
