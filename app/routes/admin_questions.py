"""Administrator tools: CSV import and Gemini generation for the three quiz modes (Category / All / Daily)."""
from flask import Blueprint, Response, current_app, jsonify, render_template, request
from sqlalchemy import select

from .. import limiter
from ..auth.security import admin_required
from ..database import get_session
from ..models import Category
from ..services import generation_jobs, question_bank
from ..services.question_bank import MODE_LABELS, MODES, CsvError

bp = Blueprint("qadmin", __name__)


def _err(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _mode_and_category(db, source):
    """Validate the quiz mode / category supplied by the browser (never trusted as-is)."""
    mode = (source.get("mode") or "").strip()
    if mode not in MODES:
        raise ValueError("Choose a valid quiz mode.")
    raw = source.get("category")
    category = None
    if raw not in (None, "", "any"):
        if not str(raw).isdigit() or db.get(Category, int(raw)) is None:
            raise ValueError("Choose a valid category.")
        category = db.get(Category, int(raw))
    return mode, category


@bp.route("/admin/questions")
@admin_required
def page():
    db = get_session()
    categories = list(db.scalars(select(Category).order_by(Category.position)))
    return render_template("admin_questions.html", categories=categories, modes=[(m, MODE_LABELS[m]) for m in MODES],
                           max_generate=current_app.config["ADMIN_MAX_GENERATE"],
                           gemini_ready=bool(current_app.config.get("GEMINI_API_KEY")),
                           csv_columns=question_bank.CSV_COLUMNS, max_mb=current_app.config["CSV_MAX_BYTES"] // (1024 * 1024))


@bp.route("/api/admin/questions/counts")
@admin_required
def counts():
    db = get_session()
    by = question_bank.counts_by_mode(db)
    cats = list(db.scalars(select(Category).order_by(Category.position)))
    rows = [{"name": c.name, **by[c.id]} for c in cats]
    totals = {m: sum(r[m] for r in rows) for m in MODES}
    return jsonify({"ok": True, "rows": rows, "totals": totals})


@bp.route("/api/admin/questions/list")
@admin_required
def list_questions():
    db = get_session()
    try:
        mode, category = _mode_and_category(db, request.args)
        page = max(1, int(request.args.get("page", 1)))
    except ValueError as exc:
        return _err(str(exc) if "Choose" in str(exc) else "Invalid page.")
    data = question_bank.questions_for(db, mode, category.id if category else None, page)
    return jsonify({"ok": True, **data})


@bp.route("/api/admin/questions/csv/template")
@admin_required
def csv_template():
    return Response(question_bank.CSV_TEMPLATE, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=questions_template.csv"})


def _read_csv_request():
    db = get_session()
    mode, category = _mode_and_category(db, request.form)
    if mode != "category" and category is not None:
        category = None  # All Quiz / Daily Quiz take each row's own category_name
    if mode == "category" and request.form.get("category") in (None, ""):
        raise ValueError("Choose a category (or 'Use category_name from each row').")
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ValueError("Choose a CSV file to upload.")
    cfg = current_app.config
    data = upload.read(cfg["CSV_MAX_BYTES"] + 1)
    report = question_bank.analyze_csv(db, data, upload.filename, mode, category, cfg["CSV_MAX_BYTES"], cfg["CSV_MAX_ROWS"])
    return db, mode, report


@bp.route("/api/admin/questions/csv/preview", methods=["POST"])
@admin_required
@limiter.limit(lambda: current_app.config["ADMIN_CSV_RATE_LIMIT"], methods=["POST"])
def csv_preview():
    try:
        _, _, report = _read_csv_request()
    except (CsvError, ValueError) as exc:
        return _err(str(exc))
    return jsonify({"ok": True, **question_bank.public_report(report)})


@bp.route("/api/admin/questions/csv/import", methods=["POST"])
@admin_required
@limiter.limit(lambda: current_app.config["ADMIN_CSV_RATE_LIMIT"], methods=["POST"])
def csv_import():
    """Everything is validated again here (the preview is never trusted); only valid rows are saved."""
    try:
        db, mode, report = _read_csv_request()
    except (CsvError, ValueError) as exc:
        return _err(str(exc))
    try:
        ids, race = question_bank.insert_valid(db, mode, report["results"], source="csv")
    except Exception:  # noqa: BLE001 - nothing is reported as saved unless the database confirmed it
        db.rollback()
        current_app.logger.exception("CSV import failed")
        return _err("The import could not be saved. Nothing was imported. Please try again.", 500)
    pub = question_bank.public_report(report)
    return jsonify({"ok": True, "mode": mode, "mode_label": MODE_LABELS[mode], "imported": len(ids),
                    "invalid": pub["invalid"], "duplicates": pub["duplicates"] + race, "total": pub["total"],
                    "problems": pub["problems"], "problems_truncated": pub["problems_truncated"],
                    "first_id": min(ids) if ids else None, "last_id": max(ids) if ids else None})


@bp.route("/api/admin/questions/generate", methods=["POST"])
@admin_required
@limiter.limit(lambda: current_app.config["ADMIN_GENERATE_RATE_LIMIT"], methods=["POST"])
def generate():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _err("Invalid request.")
    db = get_session()
    try:
        mode, category = _mode_and_category(db, body)
        count = body.get("count")
        if isinstance(count, bool) or not str(count).strip().isdigit():
            raise ValueError("Enter how many questions to generate.")
        count = int(str(count).strip())
        cap = current_app.config["ADMIN_MAX_GENERATE"]
        if not 1 <= count <= cap:
            raise ValueError(f"Enter a number of questions between 1 and {cap}.")
        language = str(body.get("language") or "auto").strip().lower()
        result = generation_jobs.run(db, mode, category, count, language, current_app.config["GEMINI_BATCH_SIZE"])
    except (ValueError, generation_jobs.RequestError) as exc:
        return _err(str(exc))
    result["mode"], result["mode_label"] = mode, MODE_LABELS[mode]
    return jsonify(result), (200 if result["ok"] else 502)
