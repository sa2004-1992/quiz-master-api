"""Read-only statistics: home, profile, performance, achievements, history, leaderboard."""
from datetime import timedelta

from flask import current_app

from sqlalchemy import case, func, or_, select

from ..models import Bookmark, Category, Question, QuizGame, QuizGameAnswer, User, UserDailyStreak
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
    """My Performance: combined stats over ALL saved games, per-mode rows kept separate, and the last 10
    saved games for the chart. Everything comes from this user's completed rows in quiz_games, so each
    game is counted once; paused time is already excluded from elapsed_seconds."""
    rows = session.execute(
        select(QuizGame.id, QuizGame.quiz_type, QuizGame.score, QuizGame.answered_count, QuizGame.correct_count,
               QuizGame.wrong_count, QuizGame.elapsed_seconds, QuizGame.finished_at, Category.name)
        .outerjoin(Category, Category.id == QuizGame.category_id).where(*_done(user_id))
        .order_by(QuizGame.finished_at.desc(), QuizGame.id.desc())).all()

    def block(subset):
        answered = sum(r.answered_count for r in subset)
        correct = sum(r.correct_count for r in subset)
        return {"games": len(subset), "answered": answered, "correct": correct,
                "wrong": sum(r.wrong_count for r in subset), "accuracy": _pct(correct, answered),
                "score": sum(r.score for r in subset), "time": sum(r.elapsed_seconds or 0 for r in subset)}

    overall = block(rows)
    overall["best_game"] = max((r.score for r in rows), default=0)
    overall["best_time"] = min((r.elapsed_seconds or 0 for r in rows), default=0)  # fastest single game
    by_type = [{"label": label, **block([r for r in rows if r.quiz_type == qt])}
               for qt, label in (("category", "Category Quizzes"), ("all", "All Quiz"), ("daily", "Daily Quiz"))]
    chart = []
    for r in reversed(rows[:10]):  # latest 10, shown oldest -> newest
        local = clock.to_local(r.finished_at, current_app.config["APP_TIMEZONE"])
        chart.append({"score": r.score, "date": local.strftime("%d %b %Y"),
                      "quiz": "Category Quiz \u2014 " + r.name if r.quiz_type == "category" and r.name
                      else {"all": "All Quiz", "daily": "Daily Quiz"}.get(r.quiz_type, "Category Quiz")})
    for i, item in enumerate(chart, start=1):
        item["n"] = i
    return {"overall": overall, "by_type": by_type, "chart": chart}


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


GAME_LABELS = {"category": "Category Quiz", "all": "All Quiz", "daily": "Daily Quiz"}


def _like_escape(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def history_page(session, user_id, page, page_size, tzname, q=None, category_id=None, start=None, end=None):
    """Saved games of ONE user, newest first. Optional filters combine with AND:
    q = text in the game label (Category Quiz / All Quiz / Daily Quiz) or the category name,
    category_id = Category Quiz games of that category, start/end = inclusive local dates."""
    base = list(_done(user_id))
    if q:
        needle = q.lower()
        types = [t for t, label in GAME_LABELS.items() if needle in label.lower()]
        pattern = f"%{_like_escape(q)}%"
        base.append(or_(Category.name.ilike(pattern, escape="\\"), QuizGame.quiz_type.in_(types)))
    if category_id:
        base += [QuizGame.quiz_type == "category", QuizGame.category_id == category_id]
    if start:
        base.append(QuizGame.finished_at >= clock.local_day_start_utc(start, tzname))
    if end:
        base.append(QuizGame.finished_at < clock.local_day_start_utc(end + timedelta(days=1), tzname))
    count_q = select(func.count(QuizGame.id)).outerjoin(Category, Category.id == QuizGame.category_id).where(*base)
    total = session.scalar(count_q) or 0
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


def leaderboard_page(session, range_name, page, page_size, tzname, current_user_id=None):
    """ONE combined, user-wise ranking over completed games of ALL quiz modes (Category, All, Daily).

    Each completed game is a single row in quiz_games, so grouping by user counts it exactly once.
    Ranking (documented tie-breaks): total score DESC, total correct answers DESC, total questions
    played DESC, total time ASC (faster is better), then username A-Z. Ranks are therefore unique.
    Only public data (username) is returned.
    """
    if range_name not in RANGES:
        raise ValueError("invalid range")
    start = clock.range_start_utc(range_name, tzname)
    where = [QuizGame.status == "completed"]
    if start is not None:
        where.append(QuizGame.finished_at >= start)
    agg = (select(User.id.label("uid"), User.username.label("username"), User.username_lower.label("ulower"),
                  func.coalesce(func.sum(QuizGame.score), 0).label("score"),
                  func.coalesce(func.sum(QuizGame.correct_count), 0).label("correct"),
                  func.coalesce(func.sum(QuizGame.answered_count), 0).label("answered"),
                  func.count(QuizGame.id).label("games"),
                  func.coalesce(func.sum(QuizGame.elapsed_seconds), 0).label("time"))
           .select_from(QuizGame).join(User, User.id == QuizGame.user_id).where(*where)
           .group_by(User.id, User.username, User.username_lower).subquery())
    ranked = select(agg, func.row_number().over(order_by=(
        agg.c.score.desc(), agg.c.correct.desc(), agg.c.answered.desc(), agg.c.time.asc(), agg.c.ulower.asc()
    )).label("rank")).subquery()
    total = session.scalar(select(func.count()).select_from(agg)) or 0
    pages = max(1, -(-total // page_size))
    page = min(max(page, 1), pages)
    offset = (page - 1) * page_size
    rows = session.execute(select(ranked).order_by(ranked.c.rank).limit(page_size).offset(offset)).all()
    items = [{"rank": int(r.rank), "uid": r.uid, "username": r.username, "score": int(r.score),
              "answered": int(r.answered), "games": int(r.games), "time": int(r.time)} for r in rows]
    me = None
    if current_user_id is not None:
        m = session.execute(select(ranked.c.rank).where(ranked.c.uid == current_user_id)).first()
        me = int(m[0]) if m else None
    first = offset + 1 if items else 0
    return {"items": items, "page": page, "pages": pages, "total": total, "first": first,
            "last": offset + len(items), "me_rank": me,
            "total_players": session.scalar(select(func.count(User.id))) or 0}


def bookmarked_questions(session, user_id):
    from ..models import Question
    rows = session.execute(
        select(Question, Category.name).join(Bookmark, Bookmark.question_id == Question.id)
        .join(Category, Category.id == Question.category_id)
        .where(Bookmark.user_id == user_id).order_by(Bookmark.created_at.desc(), Bookmark.id.desc())).all()
    return [{"id": q.id, "category": c, "text": q.question_text, "options": q.options(),
             "correct": q.correct_answer, "explanation": q.explanation} for q, c in rows]


CATEGORY_SORTS = ("questions", "name", "accuracy", "best")


def _pct(num, den):
    return round(100.0 * num / den, 1) if den else 0.0


def profile_overview(session, user_id, sort="questions", quiz_type="category"):
    """Profile statistics for ONE quiz mode (default: Category Quizzes / Quiz 1). Modes are never mixed:
    All Quiz statistics live on the All Quiz page (see all_quiz_overview) and Daily games are excluded here.

    Definitions: answered = correct + wrong; hint-resolved questions are neither correct nor wrong.
    Each answer is counted exactly once (rows come from quiz_game_answers of saved games).
    Category figures use each question's stored category, so All Quiz / Daily answers are attributed
    to their real categories. A category's Best Score is the highest single saved game score for a
    Category Quiz, or the points earned from that category inside one All/Daily game.
    """
    games = session.execute(
        select(QuizGame.id, QuizGame.quiz_type, QuizGame.score, QuizGame.elapsed_seconds,
               QuizGame.finished_at, Category.name)
        .outerjoin(Category, Category.id == QuizGame.category_id)
        .where(*_done(user_id, QuizGame.quiz_type == quiz_type))).all()
    per = session.execute(
        select(QuizGameAnswer.game_id, Question.category_id,
               func.sum(case((QuizGameAnswer.selected_option.is_not(None), 1), else_=0)),
               func.sum(case((QuizGameAnswer.is_correct.is_(True), 1), else_=0)),
               func.sum(QuizGameAnswer.points))
        .select_from(QuizGameAnswer).join(QuizGame, QuizGame.id == QuizGameAnswer.game_id)
        .join(Question, Question.id == QuizGameAnswer.question_id)
        .where(*_done(user_id, QuizGame.quiz_type == quiz_type))
        .group_by(QuizGameAnswer.game_id, Question.category_id)).all()

    gstats = {g.id: {"answered": 0, "correct": 0} for g in games}
    cats = {}
    for gid, cid, answered, correct, points in per:
        answered, correct, points = int(answered or 0), int(correct or 0), int(points or 0)
        gstats[gid]["answered"] += answered
        gstats[gid]["correct"] += correct
        c = cats.setdefault(cid, {"answered": 0, "correct": 0, "best": 0})
        c["answered"] += answered
        c["correct"] += correct
        game = next(g for g in games if g.id == gid)
        game_best = game.score if game.quiz_type == "category" else max(0, points)
        c["best"] = max(c["best"], game_best)

    total_games = len(games)
    answered = sum(v["answered"] for v in gstats.values())
    correct = sum(v["correct"] for v in gstats.values())
    wrong = answered - correct
    total_time = sum(g.elapsed_seconds or 0 for g in games)
    total_score = sum(g.score for g in games)
    stats = {"games": total_games, "correct": correct, "wrong": wrong, "score": total_score,
             "answered": answered, "time": total_time}
    accuracy = _pct(correct, answered)
    performance = {
        "accuracy": accuracy, "correct_rate": accuracy, "wrong_rate": _pct(wrong, answered),
        "avg_time": round(total_time / total_games) if total_games else 0,
        "avg_score": round(total_score / total_games, 1) if total_games else 0.0,
        "avg_questions": round(answered / total_games, 1) if total_games else 0.0,
    }

    def label(g):
        return {"all": "Play All Quiz \u2014 Mixed Categories",
                "daily": "Daily Quiz \u2014 Mixed Categories"}.get(g.quiz_type, g[5])

    records = None
    if games:
        def best(key):  # ties: most recent saved game wins (finished_at, then id)
            g = max(games, key=lambda g: (key(g), g.finished_at, g.id))
            return key(g), label(g)
        records = {
            "score": best(lambda g: g.score),
            "answered": best(lambda g: gstats[g.id]["answered"]),
            "correct": best(lambda g: gstats[g.id]["correct"]),
            "wrong": best(lambda g: gstats[g.id]["answered"] - gstats[g.id]["correct"]),
            "time": best(lambda g: g.elapsed_seconds or 0),
        }

    rows = []
    for c in session.scalars(select(Category).order_by(Category.position)):
        d = cats.get(c.id, {"answered": 0, "correct": 0, "best": 0})
        rows.append({"id": c.id, "name": c.name, "position": c.position, "questions": d["answered"],
                     "correct": d["correct"], "wrong": d["answered"] - d["correct"],
                     "accuracy": _pct(d["correct"], d["answered"]), "best": d["best"],
                     "played": d["answered"] > 0 or c.id in cats})
    sort = sort if sort in CATEGORY_SORTS else "questions"
    keys = {"questions": lambda r: (-r["questions"], r["position"]), "name": lambda r: r["name"].lower(),
            "accuracy": lambda r: (-r["accuracy"], -r["questions"], r["position"]),
            "best": lambda r: (-r["best"], r["position"])}
    rows.sort(key=keys[sort])
    return {"stats": stats, "performance": performance, "records": records, "sort": sort,
            "played": [r for r in rows if r["played"]], "unplayed": [r for r in rows if not r["played"]]}


def all_quiz_overview(session, user_id):
    """Quiz 2 (Play All Quiz) statistics: ONLY this user's completed games with quiz_type='all'
    (the play_all mode). Uses the per-game counts saved when each game was finished."""
    rows = session.execute(
        select(QuizGame.id, QuizGame.score, QuizGame.answered_count, QuizGame.correct_count,
               QuizGame.wrong_count, QuizGame.elapsed_seconds, QuizGame.finished_at)
        .where(*_done(user_id, QuizGame.quiz_type == "all"))).all()
    games = len(rows)
    answered = sum(r.answered_count for r in rows)
    correct = sum(r.correct_count for r in rows)
    wrong = sum(r.wrong_count for r in rows)
    score = sum(r.score for r in rows)
    time_total = sum(r.elapsed_seconds or 0 for r in rows)
    stats = {"games": games, "correct": correct, "wrong": wrong, "score": score,
             "answered": answered, "time": time_total}
    accuracy = _pct(correct, answered)
    performance = {
        "accuracy": accuracy, "correct_rate": accuracy, "wrong_rate": _pct(wrong, answered),
        "avg_time": round(time_total / games) if games else 0,
        "avg_score": round(score / games, 1) if games else 0.0,
        "avg_questions": round(answered / games, 1) if games else 0.0,
    }
    records = None
    if rows:  # every record comes from ONE game; ties go to the most recent game
        def best(key):
            return key(max(rows, key=lambda r: (key(r), r.finished_at, r.id)))
        records = {"score": best(lambda r: r.score), "answered": best(lambda r: r.answered_count),
                   "correct": best(lambda r: r.correct_count), "wrong": best(lambda r: r.wrong_count),
                   "time": best(lambda r: r.elapsed_seconds or 0)}
    return {"stats": stats, "performance": performance, "records": records}
