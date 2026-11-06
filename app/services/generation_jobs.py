"""Administrator-triggered Gemini generation for each quiz mode (results are saved before anything is reported)."""
import math

from sqlalchemy import func, select

from ..categories import KANNADA
from ..models import Category, Question
from .ai_question_generator import generate_batch, get_generator
from .question_bank import MODES

LANGUAGES = ("auto", "en", "kn")
ERRORS = {
    "disabled": "AI generation is not configured on this server (GEMINI_API_KEY is missing).",
    "quota": "The Gemini quota or rate limit was reached. Try again later.",
    "failed": "Gemini could not generate questions right now. Please try again later.",
    "busy": "Another generation is already running for this category. Please wait a moment.",
}


class RequestError(Exception):
    """Invalid administrator input (message is safe to show)."""


def _split(count, size):
    out = []
    while count > 0:
        out.append(min(size, count))
        count -= size
    return out


def plan(session, mode, category, count, language, batch_size):
    """Return [(Category, n_questions)] - at most ``batch_size`` questions per Gemini call."""
    if mode not in MODES:
        raise RequestError("Choose a valid quiz mode.")
    if language not in LANGUAGES:
        raise RequestError("Choose a valid language.")
    if mode == "category":
        if category is None:
            raise RequestError("Choose a category for Category Quiz generation.")
        if category.name == KANNADA and language == "en":
            raise RequestError("The Kannada category must be generated in Kannada (choose Auto or Kannada).")
        if category.name != KANNADA and language == "kn":
            raise RequestError("Kannada can only be generated for the Kannada category.")
        return [(category, n) for n in _split(count, batch_size)]
    cats = list(session.scalars(select(Category).order_by(Category.position)))
    if language == "kn":
        cats = [c for c in cats if c.name == KANNADA]
    elif language == "en" or mode == "daily":  # Auto for the Daily Quiz keeps its English-only pool
        cats = [c for c in cats if c.name != KANNADA]
    stored = dict(session.execute(select(Question.category_id, func.count(Question.id))
                                  .where(Question.pool == mode).group_by(Question.category_id)).all())
    cats.sort(key=lambda c: (stored.get(c.id, 0), c.position))  # fill the thinnest categories first
    if not cats:
        raise RequestError("No category matches that language.")
    return [(cats[i % len(cats)], n) for i, n in enumerate(_split(count, batch_size))]


def run(session, mode, category, count, language, batch_size=10):
    """Generate and store questions. Returns a result dict; ``ok`` is True only if something was saved."""
    if not get_generator().enabled:
        return {"ok": False, "error": ERRORS["disabled"], "requested": count, "generated": 0, "saved": 0,
                "duplicates": 0, "invalid": 0, "details": []}
    tasks = plan(session, mode, category, count, language, batch_size)
    total = {"generated": 0, "saved": 0, "duplicates": 0, "invalid": 0}
    details, error, failures = [], None, 0
    for cat, n in tasks:
        res = generate_batch(session, cat, mode, n)
        details.append({"category": cat.name, "requested": n, "generated": res["generated"], "saved": res["inserted"],
                        "duplicates": res["duplicates"], "invalid": res["invalid"], "error": res["error"]})
        total["generated"] += res["generated"]
        total["saved"] += res["inserted"]
        total["duplicates"] += res["duplicates"]
        total["invalid"] += res["invalid"]
        if res["error"] in ("quota", "disabled"):
            error = res["error"]
            break
        if res["error"]:
            error = res["error"]
            failures += 1
            if failures >= 2:
                break
        else:
            failures = 0
    message = ERRORS.get(error) if error else None
    if message and total["saved"]:
        message += f" {total['saved']} question(s) were saved before it stopped."
    return {"ok": total["saved"] > 0 or not error, "error": message, "requested": count, **total, "details": details}
