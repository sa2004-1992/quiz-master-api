"""Server-rendered pages: home, quizzes, all quiz, history, leaderboard, profile, etc."""
from datetime import date

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template,
                   request, url_for)
from sqlalchemy import select, text

from .. import limiter
from ..auth.security import login_required
from ..database import get_session
from ..models import (Bookmark, Category, DailyQuestionSet, Feedback, PlayAllProgress, QuizGame,
                      UserDailyStreak, UserPreference)
from ..services import daily_streak, quiz_engine, reports
from ..services.user_data import clear_all_quiz_data, clear_user_quiz_data
from ..utils import clock

bp = Blueprint("pages", __name__)


def _page_arg():
    try:
        return max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        return 1


@bp.route("/healthz")
def healthz():
    try:
        get_session().execute(text("SELECT 1"))
        return jsonify({"status": "ok"})
    except Exception:  # noqa: BLE001 - never leak internals
        current_app.logger.exception("Health check database failure")
        return jsonify({"status": "unavailable"}), 503


@bp.route("/")
@bp.route("/home")
@login_required
def home():
    db, uid, tz = get_session(), g.user.id, current_app.config["APP_TIMEZONE"]
    today = clock.local_today(tz)
    rec = quiz_engine.daily_status(db, uid, today)
    current, longest = daily_streak.display_streaks(db.get(UserDailyStreak, uid), today)
    ds = db.scalars(select(DailyQuestionSet).where(DailyQuestionSet.quiz_date == today)).first()
    daily = {"completed": bool(rec and rec.status == "completed"),
             "in_progress": bool(rec and rec.status == "in_progress"),
             "score": rec.score if rec and rec.status == "completed" else None,
             "questions": len(ds.question_ids) if ds else current_app.config["DAILY_QUESTION_COUNT"],
             "hints": current_app.config["DAILY_HINTS"], "current": current, "longest": longest}
    all_active = db.scalars(select(QuizGame.id).where(
        QuizGame.user_id == uid, QuizGame.active_key == "all")).first() is not None
    return render_template("home.html", stats=reports.home_stats(db, uid), daily=daily, all_active=all_active)


@bp.route("/quizzes")
@login_required
def quizzes():
    db = get_session()
    q = (request.args.get("q") or "").strip()[:60]
    stmt = select(Category).order_by(Category.position)
    if q:
        stmt = stmt.where(Category.name.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    active = set(db.scalars(select(QuizGame.category_id).where(
        QuizGame.user_id == g.user.id, QuizGame.active_key.like("cat:%"))))
    return render_template("quizzes.html", categories=list(db.scalars(stmt)), q=q, active=active)


@bp.route("/all-quiz")
@login_required
def all_quiz():
    db = get_session()
    cats = list(db.scalars(select(Category).order_by(Category.position)))
    prog = db.get(PlayAllProgress, g.user.id)
    pointer = prog.pointer if prog else 0
    active = db.scalars(select(QuizGame.id).where(
        QuizGame.user_id == g.user.id, QuizGame.active_key == "all")).first() is not None
    nxt = cats[pointer % len(cats)].name if cats else None
    return render_template("all_quiz.html", o=reports.all_quiz_overview(db, g.user.id), pointer=pointer, round_no=pointer // max(len(cats), 1) + 1,
                           next_category=nxt, active=active, saved=prog is not None,
                           total_categories=len(cats), per_game=current_app.config["ALL_QUIZ_QUESTIONS"])


@bp.route("/all-quiz/clear-data", methods=["POST"])
@login_required
def clear_all_quiz():
    if (request.form.get("confirm") or "").strip() != "DELETE":
        flash("Type DELETE to confirm clearing your All Quiz data.", "error")
        return redirect(url_for("pages.all_quiz"))
    clear_all_quiz_data(get_session(), g.user.id)
    flash("Your All Quiz data has been cleared.", "success")
    return redirect(url_for("pages.all_quiz"))


@bp.route("/history")
@login_required
def history():
    db = get_session()
    errors, filters = [], {}
    q = (request.args.get("q") or "").strip()[:60]
    if q:
        filters["q"] = q
    categories = list(db.scalars(select(Category).order_by(Category.position)))
    category_id = None
    raw_cat = (request.args.get("category") or "").strip()
    if raw_cat:
        if raw_cat.isdigit() and int(raw_cat) in {c.id for c in categories}:
            category_id = int(raw_cat)
            filters["category"] = category_id
        else:
            errors.append("Please choose a valid category.")
    dates = {}
    for key, label in (("start", "Start date"), ("end", "End date")):
        raw = (request.args.get(key) or "").strip()
        if raw:
            try:
                dates[key] = date.fromisoformat(raw)
            except ValueError:
                errors.append(f"{label} is not a valid date.")
    if dates.get("start") and dates.get("end") and dates["start"] > dates["end"]:
        errors.append("Start date must be on or before the end date.")
        dates = {}
    for key, value in dates.items():
        filters[key] = value.isoformat()
    data = reports.history_page(db, g.user.id, _page_arg(), current_app.config["PAGE_SIZE"],
                                current_app.config["APP_TIMEZONE"], q=q or None, category_id=category_id,
                                start=dates.get("start"), end=dates.get("end"))
    return render_template("history.html", data=data, categories=categories, filters=filters,
                           form=request.args, errors=errors)


@bp.route("/leaderboard")
@login_required
def leaderboard():
    range_name = request.args.get("range", "all")
    if range_name not in reports.RANGES:
        abort(400)
    data = reports.leaderboard_page(get_session(), range_name, _page_arg(), current_app.config["PAGE_SIZE"],
                                    current_app.config["APP_TIMEZONE"], current_user_id=g.user.id)
    return render_template("leaderboard.html", data=data, range_name=range_name,
                           ranges=reports.RANGE_LABELS)


@bp.route("/profile")
@login_required
def profile():
    overview = reports.profile_overview(get_session(), g.user.id, request.args.get("sort", "questions"))
    joined = clock.to_local(g.user.created_at, current_app.config["APP_TIMEZONE"]).strftime("%d %b %Y")
    return render_template("profile.html", o=overview, joined=joined)


@bp.route("/profile/clear-data", methods=["POST"])
@login_required
def clear_data():
    if (request.form.get("confirm") or "").strip() != "DELETE":
        flash("Type DELETE to confirm clearing your quiz data.", "error")
        return redirect(url_for("pages.profile"))
    clear_user_quiz_data(get_session(), g.user.id)
    flash("All your quiz data has been cleared.", "success")
    return redirect(url_for("pages.profile"))


@bp.route("/performance")
@login_required
def performance():
    return render_template("performance.html", data=reports.performance(get_session(), g.user.id))


@bp.route("/achievements")
@login_required
def achievements():
    return render_template("achievements.html", badges=reports.achievements(get_session(), g.user.id))


@bp.route("/bookmarks")
@login_required
def bookmarks():
    return render_template("bookmarks.html", items=reports.bookmarked_questions(get_session(), g.user.id))


@bp.route("/bookmarks/<int:question_id>/remove", methods=["POST"])
@login_required
def remove_bookmark(question_id):
    db = get_session()
    bm = db.scalars(select(Bookmark).where(Bookmark.user_id == g.user.id,
                                           Bookmark.question_id == question_id)).first()
    if bm:
        db.delete(bm)
        db.commit()
    return redirect(url_for("pages.bookmarks"))


@bp.route("/feedback", methods=["GET", "POST"])
@login_required
@limiter.limit(lambda: current_app.config["FEEDBACK_RATE_LIMIT"], methods=["POST"])
def feedback():
    errors, form = {}, request.form if request.method == "POST" else {}
    if request.method == "POST":
        message = (form.get("message") or "").strip()
        rating = form.get("rating") or ""
        if len(message) < 5 or len(message) > 2000:
            errors["message"] = "Please write between 5 and 2000 characters."
        if rating and rating not in {"1", "2", "3", "4", "5"}:
            errors["rating"] = "Choose a rating from 1 to 5."
        if not errors:
            db = get_session()
            db.add(Feedback(user_id=g.user.id, message=message, rating=int(rating) if rating else None))
            db.commit()
            flash("Thank you for your feedback!", "success")
            return redirect(url_for("pages.feedback"))
    return render_template("feedback.html", errors=errors, form=form), (400 if errors else 200)


@bp.route("/api/preferences/theme", methods=["POST"])
@login_required
def set_theme():
    payload = request.get_json(silent=True) or {}
    dark = payload.get("dark")
    if not isinstance(dark, bool):
        return jsonify({"ok": False, "error": "Invalid theme value."}), 400
    db = get_session()
    pref = db.get(UserPreference, g.user.id)
    if pref is None:
        pref = UserPreference(user_id=g.user.id)
        db.add(pref)
    pref.dark_mode = dark
    db.commit()
    return jsonify({"ok": True, "dark": dark})
