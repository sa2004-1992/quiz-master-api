"""Quiz start routes (forms) and the gameplay JSON API."""
from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from ..auth.security import login_required
from ..database import get_session
from ..services import quiz_engine
from ..services.quiz_engine import QuizError

bp = Blueprint("quiz", __name__)
_BACK = {"home": "pages.home", "quizzes": "pages.quizzes", "all_quiz": "pages.all_quiz"}


@bp.errorhandler(QuizError)
def handle_quiz_error(err):
    get_session().rollback()
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": err.message, "code": err.code}), err.status
    if err.status == 404:
        return render_template("error.html", status=404, title="Page not found",
                               message="The page you were looking for does not exist."), 404
    flash(err.message, "error")
    return redirect(url_for(_BACK.get(request.form.get("back"), "pages.home")))


def _start(fn, *args):
    game = fn(get_session(), g.user.id, *args)
    return redirect(url_for("quiz.play", game_id=game.id))


@bp.route("/quiz/start/category/<int:category_id>", methods=["POST"])
@login_required
def start_category(category_id):
    return _start(quiz_engine.start_category_game, category_id)


@bp.route("/quiz/start/all", methods=["POST"])
@login_required
def start_all():
    return _start(quiz_engine.start_all_game)


@bp.route("/quiz/start/daily", methods=["POST"])
@login_required
def start_daily():
    return _start(quiz_engine.start_daily_game)


@bp.route("/quiz/<int:game_id>")
@login_required
def play(game_id):
    game = quiz_engine.get_game(get_session(), g.user.id, game_id)
    if game.status != "in_progress":
        flash("That game has already been saved. You can find it in your History.", "info")
        return redirect(url_for("pages.history"))
    return render_template("quiz_game.html", game=game)


def _state(game):
    return jsonify({"ok": True, "state": quiz_engine.game_state(get_session(), game)})


@bp.route("/api/games/<int:game_id>/state")
@login_required
def state(game_id):
    return _state(quiz_engine.get_game(get_session(), g.user.id, game_id))


@bp.route("/api/games/<int:game_id>/answer", methods=["POST"])
@login_required
def answer(game_id):
    body = request.get_json(silent=True) or {}
    try:
        qid = int(body.get("question_id"))
    except (TypeError, ValueError):
        raise QuizError("Invalid question.", 400, "bad_request")
    return _state(quiz_engine.submit_answer(get_session(), g.user.id, game_id, qid, body.get("option")))


@bp.route("/api/games/<int:game_id>/hint", methods=["POST"])
@login_required
def hint(game_id):
    body = request.get_json(silent=True) or {}
    try:
        qid = int(body.get("question_id"))
    except (TypeError, ValueError):
        raise QuizError("Invalid question.", 400, "bad_request")
    return _state(quiz_engine.use_hint(get_session(), g.user.id, game_id, qid))


@bp.route("/api/games/<int:game_id>/previous", methods=["POST"])
@login_required
def previous(game_id):
    return _state(quiz_engine.go_previous(get_session(), g.user.id, game_id))


@bp.route("/api/games/<int:game_id>/next", methods=["POST"])
@login_required
def next_question(game_id):
    return _state(quiz_engine.go_next(get_session(), g.user.id, game_id))


@bp.route("/api/games/<int:game_id>/pause", methods=["POST"])
@login_required
def pause(game_id):
    return _state(quiz_engine.pause(get_session(), g.user.id, game_id))


@bp.route("/api/games/<int:game_id>/resume", methods=["POST"])
@login_required
def resume(game_id):
    return _state(quiz_engine.resume(get_session(), g.user.id, game_id))


@bp.route("/api/games/<int:game_id>/exit", methods=["POST"])
@login_required
def exit_game(game_id):
    quiz_type = quiz_engine.exit_game(get_session(), g.user.id, game_id)
    target = {"category": "pages.quizzes", "all": "pages.all_quiz", "daily": "pages.home"}[quiz_type]
    return jsonify({"ok": True, "redirect": url_for(target)})


@bp.route("/api/games/<int:game_id>/finish", methods=["POST"])
@login_required
def finish(game_id):
    summary = quiz_engine.finish_game(get_session(), g.user.id, game_id)
    return jsonify({"ok": True, "summary": summary, "redirect": url_for("pages.history")})


@bp.route("/api/games/<int:game_id>/bookmark", methods=["POST"])
@login_required
def bookmark(game_id):
    body = request.get_json(silent=True) or {}
    try:
        qid = int(body.get("question_id"))
    except (TypeError, ValueError):
        raise QuizError("Invalid question.", 400, "bad_request")
    return jsonify({"ok": True, "bookmarked": quiz_engine.toggle_bookmark(get_session(), g.user.id, game_id, qid)})
