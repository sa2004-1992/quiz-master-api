"""Achievements & Badges.

Source of truth = this user's completed (saved) games and their answers. Awards are inserted once per
(user, achievement) under a unique constraint and are never removed. Status is always decided here on the
server; nothing the browser sends can change it.
"""
import logging
from collections import Counter
from datetime import timedelta

from flask import current_app

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..models import (DailyGameRecord, Question, QuizGame, QuizGameAnswer, UserAchievement,
                      UserAchievementState, UserDailyStreak)
from ..utils import clock

log = logging.getLogger(__name__)

G = "Play {} quiz games (overall across all quiz modes)."
# (id, name, description, metric, threshold) - in the exact display order required.
ACHIEVEMENTS = [
    ("first_steps", "First Steps", "Complete your first quiz game.", "games", 1),
    ("games_10", "Quiz Enthusiast", G.format(10), "games", 10),
    ("games_20", "Dedicated Player", G.format(20), "games", 20),
    ("games_50", "Quiz Regular", G.format(50), "games", 50),
    ("games_100", "Quiz Veteran", G.format(100), "games", 100),
    ("games_200", "Quiz Champion", G.format(200), "games", 200),
    ("games_300", "Quiz Master", G.format(300), "games", 300),
    ("games_500", "Quiz Legend", G.format(500), "games", 500),
    ("correct_10", "Sharp Mind", "Answer 10 questions correctly.", "correct", 10),
    ("correct_20", "Quick Thinker", "Answer 20 questions correctly.", "correct", 20),
    ("correct_50", "Bright Mind", "Answer 50 questions correctly.", "correct", 50),
    ("correct_100", "Century Club", "Answer 100 questions correctly.", "correct", 100),
    ("correct_500", "Knowledge Champion", "Answer 500 questions correctly.", "correct", 500),
    ("streak_10", "Winning Streak", "Answer 10 questions correctly in a row.", "streak", 10),
    ("streak_20", "Unstoppable Mind", "Answer 20 questions correctly in a row.", "streak", 20),
    ("streak_30", "Brain Power", "Answer 30 questions correctly in a row.", "streak", 30),
    ("streak_40", "Master Thinker", "Answer 40 questions correctly in a row.", "streak", 40),
    ("streak_50", "Perfect Streak", "Answer 50 questions correctly in a row.", "streak", 50),
    ("streak_100", "Perfect Streak", "Answer 100 questions correctly in a row.", "streak", 100),
    ("perfect_round", "Perfect Round",
     "Answer every question correctly in a completed quiz containing at least 5 questions.", "perfect_rounds", 1),
    ("cats_10", "Curious Explorer", "Play 10 different categories.", "categories", 10),
    ("cats_20", "Knowledge Explorer", "Play 20 different categories.", "categories", 20),
    ("cats_30", "Adventure Seeker", "Play 30 different categories.", "categories", 30),
    ("cats_40", "Master Explorer", "Play 40 different categories.", "categories", 40),
    ("cats_50", "Ultimate Explorer", "Play 50 different categories.", "categories", 50),
    ("all_rounder", "All-Rounder", "Complete one All Quiz (Quiz 2 / Play All Quiz).", "all_games", 1),
    ("daily_1", "Daily Dedication", "Complete your first Daily Challenge.", "daily_games", 1),
    ("daily_3", "On a Roll", "Reach a 3-day daily streak.", "daily_streak", 3),
    ("daily_7", "Week Warrior", "Reach a 7-day daily streak.", "daily_streak", 7),
    ("daily_15", "Fortnight Champion", "Reach a 15-day daily streak.", "daily_streak", 15),
    ("daily_30", "Monthly Master", "Reach a 30-day daily streak.", "daily_streak", 30),
    ("hint_free_hero", "Hint-Free Hero", "Complete 5 quiz games without using any hints.", "hint_free_games", 5),
    ("speed_solver", "Speed Solver", "Complete a quiz game in under 2 minutes.", "fast_games", 1),
    ("accuracy_expert", "Accuracy Expert",
     "Achieve at least 90% accuracy in one completed quiz containing at least 20 questions.", "accuracy_games", 1),
    ("no_mistakes", "No Mistakes", "Complete a quiz game with zero wrong answers and at least 20 questions.",
     "no_mistake_games", 1),
    ("marathon_player", "Marathon Player", "Answer 100 questions in a single completed quiz game.", "marathon_games", 1),
    ("knowledge_collector", "Knowledge Collector", "Answer 1,000 questions across all quiz modes.", "total_answered", 1000),
    ("perfect_ten", "Perfect Ten", "Answer 10 consecutive questions correctly within a single quiz game.",
     "best_game_run", 10),
    ("hint_saver", "Hint Saver", "Complete 10 quiz games using no more than one hint per game.", "hint_saver_games", 10),
    ("category_expert", "Category Expert", "Answer 100 questions correctly in the same category.",
     "category_correct_max", 100),
    ("daily_perfectionist", "Daily Perfectionist", "Complete a Daily Challenge with all answers correct.",
     "daily_perfect_games", 1),
    ("comeback_champion", "Comeback Champion",
     "Complete a quiz game with at least 5 correct answers after answering a question incorrectly.",
     "comeback_games", 1),
    ("quiz_marathon", "Quiz Marathon", "Complete 10 quiz games in a single day.", "max_games_in_day", 10),
]
assert len({a[0] for a in ACHIEVEMENTS}) == len(ACHIEVEMENTS) == 43


def longest_run_of_days(dates):
    """Longest run of consecutive calendar days in an iterable of dates (duplicates count once)."""
    best = run = 0
    prev = None
    for d in sorted(set(dates)):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return best


def scan_answers(rows):
    """Walk answers in play order. Rows are (game_id, is_correct, selected_option).

    * current/best: correct streak that continues ACROSS games and quiz modes.
    * best_game_run: longest run of correct answers inside ONE game.
    * comeback_games: games where >= 5 correct answers came after a wrong answer in that same game.
    Correct = +1, wrong = reset; a hint-revealed question (selected_option is None) is neither."""
    cur = best = game_run = best_game_run = after = 0
    current_game, wrong_seen, comebacks = None, False, set()
    for game_id, is_correct, selected in rows:
        if game_id != current_game:
            current_game, game_run, wrong_seen, after = game_id, 0, False, 0
        if selected is None:
            continue
        if is_correct:
            cur += 1
            game_run += 1
            if wrong_seen:
                after += 1
                if after >= 5:
                    comebacks.add(game_id)
        else:
            cur = game_run = 0
            wrong_seen = True
        best = max(best, cur)
        best_game_run = max(best_game_run, game_run)
    return {"current": cur, "best": best, "best_game_run": best_game_run, "comeback_games": len(comebacks)}


def correct_streaks(rows):
    """(current, best) cross-mode streak for rows of (is_correct, selected_option)."""
    r = scan_answers((0, ok, sel) for ok, sel in rows)
    return r["current"], r["best"]


def _tzname():
    try:
        return current_app.config["APP_TIMEZONE"]
    except RuntimeError:  # no app context (background/test use)
        return "Asia/Kolkata"


def compute_metrics(session, user_id):
    done = (QuizGame.user_id == user_id, QuizGame.status == "completed")
    ans_rows = session.execute(
        select(QuizGameAnswer.game_id, QuizGameAnswer.is_correct, QuizGameAnswer.selected_option)
        .join(QuizGame, QuizGame.id == QuizGameAnswer.game_id).where(*done)
        .order_by(QuizGame.finished_at, QuizGame.id, QuizGameAnswer.position)).all()
    scan = scan_answers(ans_rows)
    state = session.get(UserAchievementState, user_id)
    stored_best = state.best_correct_streak if state else 0
    cats = session.scalar(
        select(func.count(func.distinct(Question.category_id)))
        .select_from(QuizGameAnswer).join(QuizGame, QuizGame.id == QuizGameAnswer.game_id)
        .join(Question, Question.id == QuizGameAnswer.question_id)
        .where(*done, QuizGameAnswer.selected_option.is_not(None))) or 0
    per_cat_correct = session.execute(
        select(func.count(QuizGameAnswer.id))
        .select_from(QuizGameAnswer).join(QuizGame, QuizGame.id == QuizGameAnswer.game_id)
        .join(Question, Question.id == QuizGameAnswer.question_id)
        .where(*done, QuizGameAnswer.is_correct.is_(True)).group_by(Question.category_id)).scalars().all()
    count = lambda *extra: session.scalar(select(func.count(QuizGame.id)).where(*done, *extra)) or 0
    daily_dates = list(session.scalars(select(DailyGameRecord.quiz_date).where(
        DailyGameRecord.user_id == user_id, DailyGameRecord.status == "completed")))
    streak_row = session.get(UserDailyStreak, user_id)
    tz = _tzname()
    per_day = Counter(clock.to_local(f, tz).date() for f in session.scalars(
        select(QuizGame.finished_at).where(*done)) if f is not None)
    return {
        "games": count(), "correct": sum(1 for r in ans_rows if r[1]), "streak": max(scan["best"], stored_best),
        "_current_streak": scan["current"], "categories": cats,
        "perfect_rounds": count(QuizGame.answered_count >= 5, QuizGame.wrong_count == 0),
        "all_games": count(QuizGame.quiz_type == "all"), "daily_games": count(QuizGame.quiz_type == "daily"),
        "daily_streak": max(longest_run_of_days(daily_dates), streak_row.longest_streak if streak_row else 0),
        # newer achievements
        "hint_free_games": count(QuizGame.hints_used == 0),
        "fast_games": count(QuizGame.elapsed_seconds < 120),
        "accuracy_games": count(QuizGame.answered_count >= 20, QuizGame.correct_count * 10 >= QuizGame.answered_count * 9),
        "no_mistake_games": count(QuizGame.answered_count >= 20, QuizGame.wrong_count == 0),
        "marathon_games": count(QuizGame.answered_count >= 100),
        "total_answered": session.scalar(select(func.coalesce(func.sum(QuizGame.answered_count), 0)).where(*done)) or 0,
        "best_game_run": scan["best_game_run"], "hint_saver_games": count(QuizGame.hints_used <= 1),
        "category_correct_max": max(per_cat_correct, default=0),
        "daily_perfect_games": count(QuizGame.quiz_type == "daily", QuizGame.wrong_count == 0, QuizGame.answered_count >= 1),
        "comeback_games": scan["comeback_games"], "max_games_in_day": max(per_day.values(), default=0),
    }


def earned_ids(session, user_id):
    return set(session.scalars(select(UserAchievement.achievement_id).where(UserAchievement.user_id == user_id)))


def evaluate(session, user_id, game_id=None):
    """Award every achievement whose requirement is now met. Idempotent: safe to run any number of times
    (after each saved game, on page view, concurrently); returns the ids newly awarded by this call."""
    for attempt in (1, 2):
        try:
            return _evaluate_once(session, user_id, game_id)
        except IntegrityError:  # lost a race with a concurrent evaluation (unique constraint): retry once
            session.rollback()
            if attempt == 2:
                return []
    return []


def _evaluate_once(session, user_id, game_id):
    metrics = compute_metrics(session, user_id)
    state = session.get(UserAchievementState, user_id)
    if state is None:
        session.add(UserAchievementState(user_id=user_id, current_correct_streak=metrics["_current_streak"],
                                         best_correct_streak=metrics["streak"]))
    else:
        state.current_correct_streak = metrics["_current_streak"]
        state.best_correct_streak = max(state.best_correct_streak, metrics["streak"])
    have = earned_ids(session, user_id)
    new = [a[0] for a in ACHIEVEMENTS if a[0] not in have and metrics[a[3]] >= a[4]]
    now = clock.now_utc()
    for aid in new:
        session.add(UserAchievement(user_id=user_id, achievement_id=aid, earned_at=now, game_id=game_id))
    session.commit()
    return new


def evaluate_safely(session, user_id, game_id=None):
    """Used right after a game is saved: an achievement problem must never undo or block the saved game."""
    try:
        return evaluate(session, user_id, game_id)
    except Exception:  # noqa: BLE001
        session.rollback()
        log.exception("Achievement evaluation failed for user %s (will be retried on the next save / page view)", user_id)
        return []


def statuses(session, user_id):
    """Every achievement, in the required order, with status 'Locked' or 'Earned'."""
    have = earned_ids(session, user_id)
    return [{"id": a[0], "name": a[1], "description": a[2], "status": "Earned" if a[0] in have else "Locked"}
            for a in ACHIEVEMENTS]
