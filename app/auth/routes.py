from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from .. import limiter
from ..database import get_session
from ..models import User, UserPreference
from .security import hash_password, safe_next, start_session, verify_password
from .validators import validate_registration

bp = Blueprint("auth", __name__)
INVALID = "Invalid username/email or password."


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["REGISTER_RATE_LIMIT"], methods=["POST"])
def register():
    if g.user:
        return redirect(url_for("pages.home"))
    form = request.form if request.method == "POST" else {}
    errors = {}
    if request.method == "POST":
        db = get_session()
        clean, errors = validate_registration(form, db)
        if not errors:
            user = User(full_name=clean["full_name"], email=clean["email"], username=clean["username"],
                        username_lower=clean["username"].lower(), gender=clean["gender"],
                        password_hash=hash_password(form["password"]))
            user.preferences = UserPreference(dark_mode=False)
            db.add(user)
            try:
                db.commit()
            except IntegrityError:  # lost a race on the unique constraints
                db.rollback()
                errors = {"username": "This username or email is already registered."}
            else:
                flash("Account created successfully. Please log in.", "success")
                return redirect(url_for("auth.login"))
    return render_template("register.html", errors=errors, form=form), (400 if errors else 200)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["LOGIN_RATE_LIMIT"], methods=["POST"])
def login():
    if g.user:
        return redirect(url_for("pages.home"))
    error = None
    identifier = ""
    if request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip()
        password = request.form.get("password") or ""
        user = None
        if identifier and password and len(identifier) <= 254:
            ident = identifier.lower()
            user = get_session().scalars(select(User).where(
                or_(User.username_lower == ident, User.email == ident))).first()
        ok = verify_password(user.password_hash if user else None, password)
        if user and ok:
            start_session(user, request.form.get("remember") == "on")
            return redirect(safe_next(request.args.get("next")) or url_for("pages.home"))
        error = INVALID
    return render_template("login.html", error=error, identifier=identifier), (401 if error else 200)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
