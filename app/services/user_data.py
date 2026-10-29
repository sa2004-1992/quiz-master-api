"""Clear All Data: deletes ONLY the given user's quiz data, in one transaction."""
from sqlalchemy import delete, select

from ..models import (Bookmark, DailyGameRecord, PlayAllProgress, QuizGame, QuizGameAnswer,
                      UserCategoryProgress, UserDailyStreak)


def clear_user_quiz_data(session, user_id):
    """Keeps the account (identity, email, gender, password hash) and preferences. Shared data
    (categories, questions, daily question sets) and other users' data are untouched."""
    game_ids = select(QuizGame.id).where(QuizGame.user_id == user_id)
    try:
        session.execute(delete(QuizGameAnswer).where(QuizGameAnswer.game_id.in_(game_ids)))
        session.execute(delete(DailyGameRecord).where(DailyGameRecord.user_id == user_id))
        session.execute(delete(QuizGame).where(QuizGame.user_id == user_id))
        session.execute(delete(UserCategoryProgress).where(UserCategoryProgress.user_id == user_id))
        session.execute(delete(PlayAllProgress).where(PlayAllProgress.user_id == user_id))
        session.execute(delete(UserDailyStreak).where(UserDailyStreak.user_id == user_id))
        session.execute(delete(Bookmark).where(Bookmark.user_id == user_id))
        session.commit()
    except Exception:
        session.rollback()
        raise
