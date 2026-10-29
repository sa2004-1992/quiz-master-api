"""Quiz Master application factory."""
import logging
import os
from contextlib import closing

import click
from flask import Flask, g, jsonify, render_template, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config, finalize

from .database import create_schema, get_session, init_engine, new_session
from .models import User
from .utils import clock

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])
log = logging.getLogger(__name__)


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    finalize(app)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    init_engine(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from .services.ai_question_generator import GeminiGenerator
    app.extensions["question_generator"] = GeminiGenerator.from_config(app.config)

    from .auth.routes import bp as auth_bp
    from .routes.admin import bp as admin_bp
    from .routes.pages import bp as pages_bp
    from .routes.quiz import bp as quiz_bp
    for bp in (auth_bp, pages_bp, quiz_bp, admin_bp):
        app.register_blueprint(bp)

    register_hooks(app)
    register_cli(app)
    if app.config["AUTO_INIT_DB"]:
        init_database(app)
    return app


def init_database(app):
    """Create missing tables (never drops anything) and seed categories/starter questions."""
    from .services.seed import seed_categories, seed_questions
    create_schema(app)
    if app.config["SEED_ON_STARTUP"]:
        with closing(new_session(app)) as s:
            seed_categories(s)
            seed_questions(s)


def register_hooks(app):
    @app.before_request
    def load_user():
        g.user = None
        uid = session.get("uid")
        if uid:
            user = get_session().get(User, uid)
            if user is None:
                session.clear()
            g.user = user

    @app.context_processor
    def inject():
        user = getattr(g, "user", None)
        dark = bool(user and user.preferences and user.preferences.dark_mode)
        return {"current_user": user, "theme": "dark" if dark else "light"}

    @app.template_filter("duration")
    def duration(seconds):
        return clock.format_duration(seconds)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
        if app.config["IS_PRODUCTION"]:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.endpoint and request.endpoint != "static" and request.method == "GET":
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    def wants_json():
        return request.path.startswith("/api/")

    def error_response(status, title, message):
        if wants_json():
            return jsonify({"ok": False, "error": message}), status
        return render_template("error.html", status=status, title=title, message=message), status

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        log.warning("CSRF rejected: %s | path=%s host=%s session_cookie_sent=%s", e.description,
                    request.path, request.host, "session" in request.cookies)
        return error_response(400, "Request expired", "Your session expired or the request was invalid. "
                                                     "Please reload the page and try again.")

    @app.errorhandler(400)
    def bad_request(_e):
        return error_response(400, "Bad request", "The request could not be processed.")

    @app.errorhandler(403)
    def forbidden(_e):
        return error_response(403, "Forbidden", "You do not have access to this resource.")

    @app.errorhandler(404)
    def not_found(_e):
        return error_response(404, "Page not found", "The page you were looking for does not exist.")

    @app.errorhandler(405)
    def not_allowed(_e):
        return error_response(405, "Method not allowed", "This action is not allowed.")

    @app.errorhandler(413)
    def too_large(_e):
        return error_response(413, "Request too large", "The request was too large.")

    @app.errorhandler(429)
    def too_many(_e):
        return error_response(429, "Too many requests", "Too many attempts. Please wait a moment and try again.")

    @app.errorhandler(500)
    def server_error(_e):
        return error_response(500, "Something went wrong", "An unexpected error occurred. Please try again.")


def register_cli(app):
    @app.cli.command("init-db")
    def init_db_cmd():
        """Create missing tables and seed categories + starter questions (non-destructive)."""
        init_database(app)
        click.echo("Database ready.")

    @app.cli.command("import-questions")
    @click.option("--source", type=click.Choice(["opentdb", "trivia_api", "all"]), default="all", show_default=True)
    @click.option("--rounds", default=1, show_default=True, help="Repeat the import to collect more questions.")
    @click.option("--pool", type=click.Choice(["category", "daily"]), default="category", show_default=True)
    def import_cmd(source, rounds, pool):
        """Import ready-made questions (Open Trivia DB / The Trivia API) into the database."""
        from .services.question_sources import import_all
        sources = ("opentdb", "trivia_api") if source == "all" else (source,)
        with closing(new_session(app)) as s:
            totals = import_all(s, sources, rounds, pool, progress=click.echo)
        click.echo(f"Done: {totals['inserted']} new questions, {totals['rejected']} skipped.")

    @app.cli.command("generate-questions")
    @click.option("--category", "category_name", default=None, help="Category name (default: all).")
    @click.option("--batches", default=1, show_default=True)
    @click.option("--pool", type=click.Choice(["category", "daily"]), default="category")
    def generate_cmd(category_name, batches, pool):
        """Pre-generate and store questions with Gemini (uses GEMINI_API_KEY)."""
        from sqlalchemy import select

        from .models import Category
        from .services.ai_question_generator import generate_and_store, get_generator
        if not get_generator().enabled:
            raise click.ClickException("GEMINI_API_KEY is not configured.")
        with closing(new_session(app)) as s:
            stmt = select(Category).order_by(Category.position)
            if category_name:
                stmt = stmt.where(Category.name == category_name)
            cats = list(s.scalars(stmt))
            if not cats:
                raise click.ClickException("No matching category.")
            for cat in cats:
                for _ in range(batches):
                    n = generate_and_store(s, cat, pool)
                    click.echo(f"{cat.name}: +{n}")
