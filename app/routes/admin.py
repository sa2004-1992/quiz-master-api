"""Token-protected administrative API for pre-generating questions (disabled unless configured)."""
import hmac

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import select

from .. import csrf
from ..database import get_session
from ..models import Category
from ..services.ai_question_generator import generate_and_store, get_generator

bp = Blueprint("admin", __name__)


@bp.route("/api/admin/generate-questions", methods=["POST"])
@csrf.exempt  # bearer-token authenticated, no cookies involved
def generate_questions():
    token = current_app.config.get("ADMIN_API_TOKEN")
    if not token:
        return jsonify({"ok": False, "error": "Not found."}), 404
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), token.encode()):
        return jsonify({"ok": False, "error": "Unauthorized."}), 401
    if not get_generator().enabled:
        return jsonify({"ok": False, "error": "AI generation is not configured."}), 503
    body = request.get_json(silent=True) or {}
    pool = body.get("pool", "category")
    if pool not in ("category", "daily"):
        return jsonify({"ok": False, "error": "Invalid pool."}), 400
    db = get_session()
    cat = db.scalars(select(Category).where(Category.name == body.get("category"))).first()
    if cat is None:
        return jsonify({"ok": False, "error": "Unknown category."}), 400
    inserted = generate_and_store(db, cat, pool)
    return jsonify({"ok": True, "inserted": inserted})
