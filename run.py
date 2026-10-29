"""Entry point. Gunicorn target is ``run:app``."""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # `python run.py` is the local HTTP dev server: Secure cookies would never be stored over
    # http://localhost, which breaks login/CSRF. Gunicorn on Render (HTTPS) keeps Secure cookies.
    app.config["SESSION_COOKIE_SECURE"] = False
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
