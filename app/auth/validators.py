"""Server-side validation for registration (mirrors the frontend checks)."""
import re

from sqlalchemy import select

from ..models import GENDERS, User

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{3,30}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def validate_registration(form, session):
    """Return (clean_data, errors). Field order matches the registration form."""
    errors = {}
    full_name = re.sub(r"\s+", " ", (form.get("full_name") or "")).strip()
    email = (form.get("email") or "").strip().lower()
    username = (form.get("username") or "").strip()
    gender = (form.get("gender") or "").strip()
    password = form.get("password") or ""
    confirm = form.get("confirm_password") or ""

    if not full_name:
        errors["full_name"] = "Full name is required."
    elif len(full_name) < 2 or len(full_name) > 100:
        errors["full_name"] = "Full name must be between 2 and 100 characters."
    if not email:
        errors["email"] = "Email address is required."
    elif len(email) > 254 or not EMAIL_RE.match(email):
        errors["email"] = "Enter a valid email address."
    if not username:
        errors["username"] = "Username is required."
    elif not USERNAME_RE.match(username):
        errors["username"] = "Username must be 3-30 characters: letters, numbers, underscore or dot."
    if not gender:
        errors["gender"] = "Please select a gender."
    elif gender not in GENDERS:
        errors["gender"] = "Please select Male, Female or Other."
    if not password:
        errors["password"] = "Password is required."
    elif len(password) < 6:
        errors["password"] = "Password must be at least 6 characters."
    elif len(password) > 128:
        errors["password"] = "Password must be at most 128 characters."
    if not confirm:
        errors["confirm_password"] = "Please confirm your password."
    elif confirm != password:
        errors["confirm_password"] = "Passwords do not match."

    if "email" not in errors and session.scalar(select(User.id).where(User.email == email)):
        errors["email"] = "An account with this email already exists."
    if "username" not in errors and session.scalar(
            select(User.id).where(User.username_lower == username.lower())):
        errors["username"] = "This username is already taken."
    clean = {"full_name": full_name, "email": email, "username": username, "gender": gender}
    return clean, errors
