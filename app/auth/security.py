"""Authentication helpers: login_required, safe redirects, password hashing."""
from functools import wraps
from urllib.parse import urlparse

from flask import current_app, flash, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

_DUMMY_HASH = None


def hash_password(password: str) -> str:
    return generate_password_hash(password, method=current_app.config.get("PASSWORD_HASH_METHOD", "scrypt"))


def verify_password(stored_hash, password: str) -> bool:
    """Always performs a hash comparison, even for unknown users (no timing oracle)."""
    global _DUMMY_HASH
    if stored_hash is None:
        if _DUMMY_HASH is None:
            _DUMMY_HASH = hash_password("dummy-password-for-timing")
        check_password_hash(_DUMMY_HASH, password)
        return False
    return check_password_hash(stored_hash, password)


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.get("user") is None:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Please log in to continue."}), 401
            flash("Please log in to continue.", "info")
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapper


def safe_next(target):
    """Only allow same-site relative redirects."""
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


def start_session(user, remember):
    session.clear()  # renew the session on authentication (prevents fixation)
    session["uid"] = user.id
    session.permanent = bool(remember)
