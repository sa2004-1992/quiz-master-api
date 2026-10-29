"""Idempotent seeding of categories and the starter question bank."""
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..categories import CATEGORY_NAMES, language_for, slugify
from ..data.seed_questions import SEED
from ..models import Category
from .ai_question_generator import store_questions

log = logging.getLogger(__name__)


def seed_categories(session):
    existing = {c.name: c for c in session.scalars(select(Category))}
    changed = False
    for pos, name in enumerate(CATEGORY_NAMES, start=1):
        if name not in existing:
            session.add(Category(name=name, slug=slugify(name), position=pos, language=language_for(name)))
            changed = True
    if changed:
        try:
            session.commit()
        except IntegrityError:  # another worker seeded concurrently
            session.rollback()


def seed_questions(session):
    """Insert the starter bank into both pools (daily pool excludes Kannada). Safe to re-run."""
    cats = {c.name: c for c in session.scalars(select(Category))}
    total = 0
    for name, items in SEED.items():
        cat = cats[name]
        raw = [{"question": q, "option_a": o[0], "option_b": o[1], "option_c": o[2], "option_d": o[3],
                "correct_answer": ans, "explanation": expl, "difficulty": diff}
               for q, o, ans, expl, diff in items]
        ins, _ = store_questions(session, cat, "category", raw, source="seed")
        total += ins
        if name != "Kannada":
            ins, _ = store_questions(session, cat, "daily", raw, source="seed")
            total += ins
    if total:
        log.info("Seeded %s starter questions", total)
    return total
