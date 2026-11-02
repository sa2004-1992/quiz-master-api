"""Feedback: validation, storage and listing (always scoped to one user)."""
from sqlalchemy import select

from ..models import Feedback
from ..utils import clock

MAX_LEN = 2000


def validate(rating, message):
    """Return (clean_rating, clean_message, errors). Both fields are required."""
    errors = {}
    value = None
    if rating is None or str(rating).strip() == "":
        errors["rating"] = "Please select a rating."
    else:
        try:
            value = int(str(rating).strip())
        except (TypeError, ValueError):
            value = None
        if value is None or str(rating).strip() != str(value) or not 1 <= value <= 5:
            errors["rating"] = "Please choose a rating from 1 to 5."
            value = None
    text = message.strip() if isinstance(message, str) else ""
    if not text:
        errors["message"] = "Please write your feedback."
    elif len(text) > MAX_LEN:
        errors["message"] = f"Feedback must be {MAX_LEN} characters or fewer."
    return value, text, errors


def stars(rating):
    return "\u2605" * rating + f" ({rating}/5)" if rating else "No rating"


def create(session, user_id, rating, message):
    row = Feedback(user_id=user_id, rating=rating, message=message, created_at=clock.now_utc())
    session.add(row)
    session.commit()
    return row


def list_for_user(session, user_id, tzname):
    """All feedback of ONE user, newest first, formatted for display."""
    rows = session.scalars(select(Feedback).where(Feedback.user_id == user_id)
                           .order_by(Feedback.created_at.desc(), Feedback.id.desc())).all()
    return [{"id": r.id, "when": clock.to_local(r.created_at, tzname).strftime("%d %b %Y, %I:%M %p"),
             "rating": r.rating, "stars": stars(r.rating), "message": r.message} for r in rows]
