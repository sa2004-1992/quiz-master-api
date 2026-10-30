"""Quiz gameplay engine for all three (independent) quiz types.

Every mutating function: locks the game row (PostgreSQL FOR UPDATE), validates on the server,
writes, and commits in one transaction. Scores, hints, timing and progress are never taken
from the browser.
"""
import logging
import random
from collections import Counter

from flask import current_app
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from ..models import (Bookmark, Category, DailyGameRecord, DailyQuestionSet, PlayAllProgress,
                      Question, QuizGame, QuizGameAnswer, UserCategoryProgress)
from ..utils import clock
from . import daily_streak, progress, scoring
from .ai_question_generator import generate_and_store

log = logging.getLogger(__name__)


class QuizError(Exception):
    def __init__(self, message, status=400, code="error"):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


# --------------------------------------------------------------------------- helpers
def _cfg(key):
    return current_app.config[key]


def _tz():
    return current_app.config["APP_TIMEZONE"]


def get_game(session, user_id, game_id, lock=False):
    stmt = select(QuizGame).where(QuizGame.id == game_id, QuizGame.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    game = session.scalars(stmt).first()
    if game is None:
        raise QuizError("Game not found.", 404, "not_found")
    return game


def _require_active(game):
    if game.status != "in_progress":
        raise QuizError("This game has already been saved.", 409, "already_saved")


def _require_running(game):
    _require_active(game)
    if game.paused_at is not None:
        raise QuizError("The quiz is paused. Resume to continue.", 409, "paused")


def elapsed_seconds(game, now=None):
    """Server-calculated elapsed play time, excluding paused time."""
    if game.status == "completed" and game.elapsed_seconds is not None:
        return game.elapsed_seconds
    now = now or clock.now_utc()
    end = game.paused_at or now
    total = (end - game.started_at).total_seconds() - (game.paused_seconds or 0.0)
    return max(0, int(round(total)))


def _difficulty_label(questions):
    levels = {q.difficulty for q in questions}
    return levels.pop().capitalize() if len(levels) == 1 else "Mixed"


def _ordered_ids(session, pool, category_id):
    return list(session.scalars(select(Question.id).where(
        Question.pool == pool, Question.category_id == category_id).order_by(Question.id)))


def _active_game(session, user_id, key):
    return session.scalars(select(QuizGame).where(
        QuizGame.user_id == user_id, QuizGame.active_key == key)).first()


def _new_game(session, user_id, quiz_type, key, category_id, qids, positions, start_pointer,
              hints_max, questions):
    game = QuizGame(user_id=user_id, quiz_type=quiz_type, category_id=category_id,
                    status="in_progress", active_key=key, question_ids=list(qids),
                    seq_positions=list(positions), start_pointer=start_pointer, current_index=0,
                    hints_max=hints_max, difficulty=_difficulty_label(questions),
                    started_at=clock.now_utc(), paused_seconds=0.0)
    session.add(game)
    return game


def _load_questions(session, ids):
    rows = {q.id: q for q in session.scalars(select(Question).where(Question.id.in_(ids)))}
    return [rows[i] for i in ids if i in rows]


# --------------------------------------------------------------------------- start / resume
def start_category_game(session, user_id, category_id):
    """Quiz Type 1."""
    category = session.get(Category, category_id)
    if category is None:
        raise QuizError("Category not found.", 404, "not_found")
    key = f"cat:{category.id}"
    existing = _active_game(session, user_id, key)
    if existing:
        return existing
    ids = _ordered_ids(session, "category", category.id)
    prog = session.get(UserCategoryProgress, (user_id, category.id))
    pointer = prog.pointer if prog else 0
    needed = _cfg("QUESTIONS_PER_GAME")
    if pointer + needed > len(ids):  # near the end of the stored sequence: top up before wrapping
        session.rollback()
        if generate_and_store(session, category, "category"):
            ids = _ordered_ids(session, "category", category.id)
    if not ids:
        raise QuizError("No questions are available for this category yet. Please try again later.",
                        503, "no_questions")
    if pointer >= len(ids):
        pointer %= len(ids)
    qids, positions = progress.category_slice(ids, pointer, needed)
    questions = _load_questions(session, qids)
    game = _new_game(session, user_id, "category", key, category.id, qids, positions, pointer,
                     _cfg("HINTS_PER_GAME"), questions)
    try:
        session.commit()
    except IntegrityError:  # concurrent start of the same slot
        session.rollback()
        existing = _active_game(session, user_id, key)
        if existing:
            return existing
        raise
    return game


def start_all_game(session, user_id):
    """Quiz Type 2: one sequence across all categories in the required order."""
    existing = _active_game(session, user_id, "all")
    if existing:
        return existing
    cats = list(session.scalars(select(Category).order_by(Category.position)))
    order = [c.id for c in cats]
    prog = session.get(PlayAllProgress, user_id)
    pointer = prog.pointer if prog else 0
    count = _cfg("ALL_QUIZ_QUESTIONS")

    def build():
        by_cat = {cid: _ordered_ids(session, "category", cid) for cid in order}
        return progress.all_quiz_slice(order, by_cat, pointer, count)

    qids, positions, needs = build()
    if needs:
        session.rollback()
        by_id = {c.id: c for c in cats}
        for cid in needs[:_cfg("MAX_GENERATIONS_PER_REQUEST")]:
            generate_and_store(session, by_id[cid], "category")
        qids, positions, needs = build()
    if not qids:
        raise QuizError("No questions are available yet. Please try again later.", 503, "no_questions")
    questions = _load_questions(session, qids)
    game = _new_game(session, user_id, "all", "all", None, qids, positions, pointer,
                     _cfg("HINTS_PER_GAME"), questions)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = _active_game(session, user_id, "all")
        if existing:
            return existing
        raise
    return game


def _build_daily_set(session, quiz_date):
    """Get or create the dedicated question set for a date (shared by all users)."""
    ds = session.scalars(select(DailyQuestionSet).where(DailyQuestionSet.quiz_date == quiz_date)).first()
    if ds:
        return ds
    want = _cfg("DAILY_QUESTION_COUNT")
    unused = list(session.scalars(select(Question.id).where(
        Question.pool == "daily", Question.daily_date.is_(None)).order_by(Question.id)))
    if len(unused) < want:  # try to top up (rotating through English categories, by date)
        session.rollback()
        cats = list(session.scalars(select(Category).where(Category.language == "en").order_by(Category.position)))
        start = quiz_date.toordinal() % max(len(cats), 1)
        for i in range(_cfg("MAX_GENERATIONS_PER_REQUEST")):
            if cats:
                generate_and_store(session, cats[(start + i) % len(cats)], "daily")
        unused = list(session.scalars(select(Question.id).where(
            Question.pool == "daily", Question.daily_date.is_(None)).order_by(Question.id)))
    chosen = unused[:want]
    if len(chosen) < want:  # fall back to the least recently used daily questions
        used = list(session.scalars(select(Question.id).where(
            Question.pool == "daily", Question.daily_date.is_not(None))
            .order_by(Question.daily_date, Question.id).limit(want - len(chosen))))
        chosen += used
    if not chosen:
        raise QuizError("The daily challenge is not available yet. Please try again later.", 503, "no_questions")
    random.Random(quiz_date.toordinal()).shuffle(chosen)
    ds = DailyQuestionSet(quiz_date=quiz_date, question_ids=chosen)
    session.add(ds)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return session.scalars(select(DailyQuestionSet).where(DailyQuestionSet.quiz_date == quiz_date)).one()
    session.execute(update(Question).where(Question.id.in_(chosen)).values(daily_date=quiz_date))
    session.commit()
    return ds


def daily_status(session, user_id, today=None):
    today = today or clock.local_today(_tz())
    return session.scalars(select(DailyGameRecord).where(
        DailyGameRecord.user_id == user_id, DailyGameRecord.quiz_date == today)).first()


def start_daily_game(session, user_id):
    """Quiz Type 3: at most one completed challenge per user per calendar day (DB-enforced)."""
    today = clock.local_today(_tz())
    # Discard stale unsaved attempts from earlier days.
    stale = session.scalars(select(DailyGameRecord).where(
        DailyGameRecord.user_id == user_id, DailyGameRecord.status == "in_progress",
        DailyGameRecord.quiz_date < today)).all()
    for rec in stale:
        _discard(session, rec.game_id, user_id)
        session.delete(rec)
    if stale:
        session.commit()
    rec = daily_status(session, user_id, today)
    if rec and rec.status == "completed":
        raise QuizError("You have already completed today's Daily Challenge. Come back tomorrow!",
                        409, "daily_completed")
    if rec and rec.game_id:
        game = session.get(QuizGame, rec.game_id)
        if game and game.status == "in_progress":
            return game
    ds = _build_daily_set(session, today)
    qids = list(ds.question_ids)
    questions = _load_questions(session, qids)
    game = _new_game(session, user_id, "daily", "daily", None, qids, list(range(len(qids))), 0,
                     _cfg("DAILY_HINTS"), questions)
    try:
        session.flush()
        session.add(DailyGameRecord(user_id=user_id, quiz_date=today, game_id=game.id, status="in_progress"))
        session.commit()
    except IntegrityError:
        session.rollback()
        rec = daily_status(session, user_id, today)
        if rec and rec.status == "completed":
            raise QuizError("You have already completed today's Daily Challenge. Come back tomorrow!",
                            409, "daily_completed")
        game = _active_game(session, user_id, "daily")
        if game:
            return game
        raise
    return game


# --------------------------------------------------------------------------- state
def _answers(session, game):
    return list(session.scalars(select(QuizGameAnswer).where(
        QuizGameAnswer.game_id == game.id).order_by(QuizGameAnswer.position)))


def game_state(session, game):
    answers = _answers(session, game)
    by_q = {a.question_id: a for a in answers}
    qids = list(game.question_ids)
    idx = game.current_index
    q = session.get(Question, qids[idx])
    cat = session.get(Category, q.category_id)
    ans = by_q.get(q.id)
    score = scoring.final_score([a.points for a in answers])
    question = {"id": q.id, "number": idx + 1, "text": q.question_text, "options": q.options(),
                "category": cat.name, "difficulty": q.difficulty.capitalize(), "resolved": ans is not None}
    if ans is not None:  # the answer is only revealed once the question is resolved
        question.update({
            "selected": ans.selected_option, "correct_answer": q.correct_answer,
            "is_correct": ans.is_correct, "hint_used": ans.hint_used, "explanation": q.explanation,
            "bookmarked": session.scalars(select(Bookmark.id).where(
                Bookmark.user_id == game.user_id, Bookmark.question_id == q.id)).first() is not None,
        })
    label = {"category": cat.name if game.quiz_type == "category" else None,
             "all": "All Quiz", "daily": "Daily Quiz"}[game.quiz_type]
    return {
        "game_id": game.id, "quiz_type": game.quiz_type,
        "quiz_label": ("Category Quiz" if game.quiz_type == "category" else label),
        "category": game.category.name if game.category else None,
        "status": game.status, "total": len(qids), "current_index": idx,
        "resolved_count": game.resolved_count, "score": score,
        "hints_used": game.hints_used, "hints_max": game.hints_max,
        "hints_left": max(0, game.hints_max - game.hints_used),
        "elapsed_seconds": elapsed_seconds(game), "paused": game.paused_at is not None,
        "can_previous": idx > 0,
        "can_next": ans is not None and (game.quiz_type != "daily" or idx + 1 < len(qids)),
        "can_finish": game.resolved_count > 0,
        "all_resolved": game.resolved_count == len(qids), "question": question,
    }


# --------------------------------------------------------------------------- gameplay actions
def _current_question(session, game, question_id):
    qid = game.question_ids[game.current_index]
    if question_id is not None and int(question_id) != qid:
        raise QuizError("This question is out of date. Please reload the page.", 409, "out_of_sync")
    return session.get(Question, qid)


def _already_answered(session, game, qid):
    return session.scalars(select(QuizGameAnswer.id).where(
        QuizGameAnswer.game_id == game.id, QuizGameAnswer.question_id == qid)).first() is not None


def submit_answer(session, user_id, game_id, question_id, option):
    game = get_game(session, user_id, game_id, lock=True)
    _require_running(game)
    option = (option or "").strip().upper()
    if option not in ("A", "B", "C", "D"):
        raise QuizError("Choose one of the options A, B, C or D.", 400, "bad_option")
    q = _current_question(session, game, question_id)
    if _already_answered(session, game, q.id):
        raise QuizError("This question has already been answered.", 409, "duplicate_answer")
    correct = option == q.correct_answer
    session.add(QuizGameAnswer(game_id=game.id, question_id=q.id, position=game.current_index,
                               selected_option=option, is_correct=correct, hint_used=False,
                               points=scoring.points_for(correct, False), answered_at=clock.now_utc()))
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise QuizError("This question has already been answered.", 409, "duplicate_answer")
    game.resolved_count += 1
    if correct:
        game.correct_count += 1
    session.commit()
    return game


def use_hint(session, user_id, game_id, question_id):
    game = get_game(session, user_id, game_id, lock=True)
    _require_running(game)
    q = _current_question(session, game, question_id)
    if _already_answered(session, game, q.id):
        raise QuizError("This question has already been resolved.", 409, "duplicate_answer")
    if game.hints_used >= game.hints_max:
        raise QuizError("You have no hints left for this quiz.", 403, "no_hints")
    session.add(QuizGameAnswer(game_id=game.id, question_id=q.id, position=game.current_index,
                               selected_option=None, is_correct=False, hint_used=True, points=0,
                               answered_at=clock.now_utc()))
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise QuizError("This question has already been resolved.", 409, "duplicate_answer")
    game.hints_used += 1
    game.resolved_count += 1
    session.commit()
    return game


def go_previous(session, user_id, game_id):
    game = get_game(session, user_id, game_id, lock=True)
    _require_running(game)
    if game.current_index == 0:
        raise QuizError("There is no previous question.", 400, "no_previous")
    game.current_index -= 1  # every earlier question is resolved (skipping is impossible)
    session.commit()
    return game


def _at_open_end(session, user_id, game_id):
    g = session.scalars(select(QuizGame).where(QuizGame.id == game_id, QuizGame.user_id == user_id)).first()
    return bool(g and g.status == "in_progress" and g.quiz_type != "daily" and g.paused_at is None
                and g.current_index + 1 >= len(g.question_ids) and g.current_index < g.resolved_count)


def _extend_game(session, game):
    """Endless play for Quiz Types 1 and 2: append the next questions of the user's sequence.

    Never repeats a question inside the same game. Returns True if questions were added."""
    existing = set(game.question_ids)
    count = _cfg("QUESTIONS_PER_GAME") if game.quiz_type == "category" else _cfg("ALL_QUIZ_QUESTIONS")
    last = game.seq_positions[-1]
    if game.quiz_type == "category":
        ids = _ordered_ids(session, "category", game.category_id)
        n = len(ids)
        qids, positions = [], []
        for p in range(last + 1, last + 1 + n):
            qid = ids[p % n]
            if qid not in existing:
                qids.append(qid)
                positions.append(p)
            if len(qids) >= count:
                break
    else:
        cats = list(session.scalars(select(Category).order_by(Category.position)))
        order = [c.id for c in cats]
        by_cat = {cid: _ordered_ids(session, "category", cid) for cid in order}
        qs, ps, _ = progress.all_quiz_slice(order, by_cat, last + 1, count + len(existing))
        qids = [q for q in qs if q not in existing][:count]
        positions = [p for q, p in zip(qs, ps) if q not in existing][:count]
    if not qids:
        return False
    game.question_ids = list(game.question_ids) + qids
    game.seq_positions = list(game.seq_positions) + positions
    return True


def go_next(session, user_id, game_id):
    if _at_open_end(session, user_id, game_id):  # top up from Gemini BEFORE taking the row lock
        g = session.get(QuizGame, game_id)
        if g.quiz_type == "category":
            total = session.scalar(select(func.count(Question.id)).where(
                Question.pool == "category", Question.category_id == g.category_id))
            if total - len(g.question_ids) < _cfg("QUESTIONS_PER_GAME"):  # running low: ask Gemini for more
                generate_and_store(session, session.get(Category, g.category_id), "category")
        session.rollback()
    game = get_game(session, user_id, game_id, lock=True)
    _require_running(game)
    if game.current_index >= game.resolved_count:
        raise QuizError("Answer this question (or use a hint) before moving on.", 409, "unresolved")
    if game.current_index + 1 >= len(game.question_ids):
        if game.quiz_type == "daily" or not _extend_game(session, game):
            raise QuizError("No more new questions right now. Use Finish & Save.", 400, "last_question")
    game.current_index += 1
    session.commit()
    return game


def pause(session, user_id, game_id):
    game = get_game(session, user_id, game_id, lock=True)
    _require_active(game)
    if game.paused_at is None:
        game.paused_at = clock.now_utc()
        session.commit()
    return game


def resume(session, user_id, game_id):
    game = get_game(session, user_id, game_id, lock=True)
    _require_active(game)
    if game.paused_at is not None:
        now = clock.now_utc()
        game.paused_seconds = (game.paused_seconds or 0.0) + max(0.0, (now - game.paused_at).total_seconds())
        game.paused_at = None
        session.commit()
    return game


def _discard(session, game_id, user_id):
    if not game_id:
        return
    game = session.scalars(select(QuizGame).where(
        QuizGame.id == game_id, QuizGame.user_id == user_id, QuizGame.status == "in_progress")).first()
    if game:
        session.query(DailyGameRecord).filter(DailyGameRecord.game_id == game.id).update(
            {DailyGameRecord.game_id: None})
        session.query(QuizGameAnswer).filter(QuizGameAnswer.game_id == game.id).delete()
        session.delete(game)


def exit_game(session, user_id, game_id):
    """Discard an unsaved game: no history, no score, no pointer or streak changes."""
    game = get_game(session, user_id, game_id, lock=True)
    _require_active(game)
    if game.quiz_type == "daily":
        session.query(DailyGameRecord).filter(
            DailyGameRecord.game_id == game.id, DailyGameRecord.status == "in_progress").delete()
    _discard(session, game.id, user_id)
    session.commit()
    return game.quiz_type


def finish_game(session, user_id, game_id):
    """Finish & Save. Idempotent: a retry returns the same saved result and never double-counts."""
    game = get_game(session, user_id, game_id, lock=True)
    if game.status == "completed":
        return summarize(session, game, already_saved=True)
    if game.resolved_count == 0:
        raise QuizError("Answer at least one question before saving.", 400, "nothing_to_save")
    if game.quiz_type == "daily" and game.resolved_count < len(game.question_ids):
        raise QuizError("Complete all questions of the Daily Challenge to save it, or exit to discard it.",
                        400, "daily_incomplete")
    now = clock.now_utc()
    answers = _answers(session, game)
    score = scoring.final_score([a.points for a in answers])
    elapsed = elapsed_seconds(game, now)  # excludes pauses; a paused game ends at the pause instant
    positions = list(game.seq_positions)
    answered = sum(1 for a in answers if a.selected_option is not None)
    correct = sum(1 for a in answers if a.is_correct)
    # Atomic claim: only one request can flip in_progress -> completed.
    claimed = session.execute(update(QuizGame).where(
        QuizGame.id == game.id, QuizGame.status == "in_progress").values(
        status="completed", active_key=None, finished_at=now, elapsed_seconds=elapsed, score=score,
        paused_at=None, answered_count=answered, correct_count=correct, wrong_count=answered - correct)).rowcount
    if claimed != 1:
        session.rollback()
        game = get_game(session, user_id, game_id)
        return summarize(session, game, already_saved=True)
    last_pos = positions[game.resolved_count - 1]
    if game.quiz_type == "category":
        n = session.scalar(select(func.count(Question.id)).where(
            Question.pool == "category", Question.category_id == game.category_id))
        row = session.get(UserCategoryProgress, (user_id, game.category_id), with_for_update=True)
        new_ptr = progress.next_category_pointer(last_pos, n)
        if row is None:
            session.add(UserCategoryProgress(user_id=user_id, category_id=game.category_id, pointer=new_ptr))
        else:
            row.pointer = new_ptr
    elif game.quiz_type == "all":
        row = session.get(PlayAllProgress, user_id, with_for_update=True)
        if row is None:
            session.add(PlayAllProgress(user_id=user_id, pointer=last_pos + 1))
        else:
            row.pointer = last_pos + 1
    else:
        rec = session.scalars(select(DailyGameRecord).where(
            DailyGameRecord.game_id == game.id).with_for_update()).first()
        if rec is not None:
            rec.status, rec.score, rec.completed_at = "completed", score, now
            daily_streak.record_completion(session, user_id, rec.quiz_date)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        game = get_game(session, user_id, game_id)
        if game.status == "completed":
            return summarize(session, game, already_saved=True)
        raise QuizError("Could not save the game. Please try again.", 500, "save_failed")
    session.expire_all()
    return summarize(session, get_game(session, user_id, game_id), already_saved=False)


def summarize(session, game, already_saved=False):
    return {"game_id": game.id, "quiz_type": game.quiz_type, "score": game.score,
            "elapsed_seconds": game.elapsed_seconds, "resolved": game.resolved_count,
            "correct": game.correct_count, "hints_used": game.hints_used,
            "total": len(game.question_ids), "already_saved": already_saved}


def toggle_bookmark(session, user_id, game_id, question_id):
    """Bookmarks are allowed only for questions this user has already resolved in this game."""
    game = get_game(session, user_id, game_id)
    resolved = session.scalars(select(QuizGameAnswer.id).where(
        QuizGameAnswer.game_id == game.id, QuizGameAnswer.question_id == question_id)).first()
    if resolved is None:
        raise QuizError("Resolve the question before bookmarking it.", 409, "unresolved")
    bm = session.scalars(select(Bookmark).where(
        Bookmark.user_id == user_id, Bookmark.question_id == question_id)).first()
    if bm:
        session.delete(bm)
        state = False
    else:
        session.add(Bookmark(user_id=user_id, question_id=question_id))
        state = True
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        state = True
    return state
