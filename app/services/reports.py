"""Read-only statistics: home, profile, performance, achievements, history, leaderboard."""
from sqlalchemy import case, func, select

from ..models import Bookmark, Category, QuizGame, QuizGameAnswer, User, UserDailyStreak
from ..utils import clock

RANGES = ("all", "month", "week", "today")
RANGE_LABELS = {"all": "All Time", "month": "This Month", "week": "This Week", "today": "Today"}


def quiz_label(game_type, category_name):
    return {"category": category_name, "all": "All Quiz", "daily": "Daily Quiz"}[game_type]


def _done(user_id, *extra):
    return (QuizGame.user_id == user_id, QuizGame.status == "completed", *extra)


def _answer_totals(session, user_id, *extra):
    """(answered, correct, hint_resolved) over saved games of this user."""
    row = session.execute(
        select(
            func.coalesce(func.sum(case((QuizGameAnswer.selected_option.is_not(None), 1), else_=0)), 0),
            func.coalesce(func.sum(case((QuizGameAnswer.is_correct.is_(True), 1), else_=0)), 0),
            func.coalesce(func.sum(case((QuizGameAnswer.hint_used.is_(True), 1), else_=0)), 0),
        ).select_from(QuizGameAnswer).join(QuizGame, QuizGame.id == QuizGameAnswer.game_id)
        .where(*_done(user_id, *extra))).one()
    return int(row[0]), int(row[1]), int(row[2])


def _game_totals(session, user_id, *extra):
    row = session.execute(select(
        func.count(QuizGame.id), func.coalesce(func.sum(QuizGame.score), 0),
        func.coalesce(func.max(QuizGame.score), 0), func.coalesce(func.sum(QuizGame.elapsed_seconds), 0),
    ).where(*_done(user_id, *extra))).one()
    return {"games": int(row[0]), "score": int(row[1]), "best": int(row[2]), "time": int(row[3])}


def home_stats(session, user_id):
    cat_game = QuizGame.quiz_type == "category"
    last = session.execute(select(Category.name).join(QuizGame, QuizGame.category_id == Category.id)
                           .where(*_done(user_id, cat_game))
                           .order_by(QuizGame.finished_at.desc(), QuizGame.id.desc()).limit(1)).scalar()
    most_time = session.execute(
        select(Category.name, func.sum(QuizGame.elapsed_seconds).label("t"))
        .join(QuizGame, QuizGame.category_id == Category.id).where(*_done(user_id, cat_game))
        .group_by(Category.id, Category.name).order_by(func.sum(QuizGame.elapsed_seconds).desc(),
                                                       Category.position).limit(1)).first()
    most_q = session.execute(
        select(Category.name, func.count(QuizGameAnswer.id).label("n"))
        .select_from(QuizGameAnswer).join(QuizGame, QuizGame.id == QuizGameAnswer.game_id)
        .join(Category, Category.id == QuizGame.category_id)
        .where(*_done(user_id, cat_game), QuizGameAnswer.selected_option.is_not(None))
        .group_by(Category.id, Category.name).order_by(func.count(QuizGameAnswer.id).desc(),
                                                       Category.position).limit(1)).first()
    answered, correct, hints = _answer_totals(session, user_id)
    totals = _game_totals(session, user_id)
    return {
        "last_category": last, "most_time_category": most_time[0] if most_time else None,
        "most_time_seconds": int(most_time[1]) if most_time else 0,
        "most_questions_category": most_q[0] if most_q else None,
        "most_questions_count": int(most_q[1]) if most_q else 0,
        "total_questions_answered": answered, "correct_answers": correct, "hints_used": hints,
        "accuracy": round(100 * correct / answered) if answered else 0,
        "games_played": totals["games"], "total_score": totals["score"],
        "best_score": totals["best"], "total_time": totals["time"],
    }


def profile_stats(session, user_id):
    """Quiz Type 1 (category quizzes) only; deliberately not broken down by category."""
    cat = QuizGame.quiz_type == "category"
    answered, correct, hints = _answer_totals(session, user_id, cat)
    t = _game_totals(session, user_id, cat)
    return {"games": t["games"], "answered": answered, "correct": correct, "hints": hints,
            "accuracy": round(100 * correct / answered) if answered else 0,
            "score": t["score"], "best": t["best"], "time": t["time"]}


def performance(session, user_id):
    breakdown = []
    for qt, label in (("category", "Category Quizzes"), ("all", "All Quiz"), ("daily", "Daily Quiz")):
        extra = QuizGame.quiz_type == qt
        answered, correct, _ = _answer_totals(session, user_id, extra)
        t = _game_totals(session, user_id, extra)
        breakdown.append({"label": label, **t, "answered": answered,
                          "accuracy": round(100 * correct / answered) if answered else 0})
    recent = session.execute(select(QuizGame.score, QuizGame.finished_at).where(*_done(user_id))
                             .order_by(QuizGame.finished_at.desc(), QuizGame.id.desc()).limit(10)).all()
    return {"overall": home_stats(session, user_id), "breakdown": breakdown,
            "recent_scores": [r[0] for r in reversed(recent)]}


def achievements(session, user_id):
    t = _game_totals(session, user_id)
    answered, correct, _ = _answer_totals(session, user_id)
    streak = session.get(UserDailyStreak, user_id)
    longest = streak.longest_streak if streak else 0
    cats = session.scalar(select(func.count(func.distinct(QuizGame.category_id))).where(
        *_done(user_id, QuizGame.quiz_type == "category"))) or 0
    daily = session.scalar(select(func.count(QuizGame.id)).where(*_done(user_id, QuizGame.quiz_type == "daily"))) or 0
    all_q = session.scalar(select(func.count(QuizGame.id)).where(*_done(user_id, QuizGame.quiz_type == "all"))) or 0
    perfect = session.scalar(select(func.count(QuizGame.id)).where(
        *_done(user_id, QuizGame.resolved_count >= 5, QuizGame.correct_count == QuizGame.resolved_count))) or 0
    defs = [
        ("First Steps", "Save your first quiz.", t["games"] >= 1),
        ("Quiz Enthusiast", "Save 10 quizzes.", t["games"] >= 10),
        ("Sharp Mind", "Answer 50 questions correctly.", correct >= 50),
        ("Century Club", "Answer 100 questions correctly.", correct >= 100),
        ("Perfect Round", "Answer every question correctly in a quiz of 5+ questions.", perfect >= 1),
        ("Explorer", "Play 10 different categories.", cats >= 10),
        ("All-Rounder", "Complete an All Quiz.", all_q >= 1),
        ("Daily Dedication", "Complete a Daily Challenge.", daily >= 1),
        ("On a Roll", "Reach a 3-day daily streak.", longest >= 3),
        ("Week Warrior", "Reach a 7-day daily streak.", longest >= 7),
        ("Monthly Master", "Reach a 30-day daily streak.", longest >= 30),
    ]
    return [{"name": n, "description": d, "earned": e} for n, d, e in defs]


def history_page(session, user_id, page, page_size, tzname):
    base = _done(user_id)
    total = session.scalar(select(func.count(QuizGame.id)).where(*base)) or 0
    pages = max(1, -(-total // page_size))
    page = min(max(page, 1), pages)
    rows = session.execute(
        select(QuizGame, Category.name).outerjoin(Category, Category.id == QuizGame.category_id)
        .where(*base).order_by(QuizGame.finished_at.desc(), QuizGame.id.desc())
        .limit(page_size).offset((page - 1) * page_size)).all()
    items = []
    for g, cname in rows:
        local = clock.to_local(g.finished_at, tzname)
        items.append({
            "date": local.strftime("%d %b %Y, %H:%M"),
            "game": {"category": "Category Quiz", "all": "All Quiz", "daily": "Daily Quiz"}[g.quiz_type],
            "category": quiz_label(g.quiz_type, cname), "difficulty": g.difficulty,
            "time": clock.format_duration(g.elapsed_seconds), "score": g.score})
    return {"items": items, "page": page, "pages": pages, "total": total}


def leaderboard_page(session, range_name, page, page_size, tzname):
    if range_name not in RANGES:
        raise ValueError("invalid range")
    start = clock.range_start_utc(range_name, tzname)
    where = [QuizGame.status == "completed"]
    if start is not None:
        where.append(QuizGame.finished_at >= start)
    grouped = (select(User.id.label("uid"), User.username.label("username"), QuizGame.quiz_type.label("qt"),
                      QuizGame.category_id.label("cid"), Category.name.label("cname"),
                      func.count(QuizGame.id).label("games"), func.sum(QuizGame.score).label("score"),
                      func.sum(QuizGame.elapsed_seconds).label("time"))
               .join(User, User.id == QuizGame.user_id)
               .outerjoin(Category, Category.id == QuizGame.category_id)
               .where(*where).group_by(User.id, User.username, QuizGame.quiz_type, QuizGame.category_id,
                                       Category.name))
    sub = grouped.subquery()
    total = session.scalar(select(func.count()).select_from(sub)) or 0
    pages = max(1, -(-total // page_size))
    page = min(max(page, 1), pages)
    # Ranking: total score DESC, then total time ASC, then username, then quiz label (deterministic).
    rows = session.execute(select(sub).order_by(sub.c.score.desc(), sub.c.time.asc(), sub.c.username.asc(),
                                                sub.c.qt.asc(), sub.c.cname.asc())
                           .limit(page_size).offset((page - 1) * page_size)).all()
    offset = (page - 1) * page_size
    items = [{"rank": offset + i + 1, "username": r.username, "uid": r.uid,
              "quiz": quiz_label(r.qt, r.cname), "games": int(r.games), "score": int(r.score or 0),
              "time": clock.format_duration(r.time)} for i, r in enumerate(rows)]
    return {"items": items, "page": page, "pages": pages, "total": total}


def bookmarked_questions(session, user_id):
    from ..models import Question
    rows = session.execute(
        select(Question, Category.name).join(Bookmark, Bookmark.question_id == Question.id)
        .join(Category, Category.id == Question.category_id)
        .where(Bookmark.user_id == user_id).order_by(Bookmark.created_at.desc(), Bookmark.id.desc())).all()
    return [{"id": q.id, "category": c, "text": q.question_text, "options": q.options(),
             "correct": q.correct_answer, "explanation": q.explanation} for q, c in rows]
