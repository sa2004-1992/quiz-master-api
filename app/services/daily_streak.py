"""Daily streak rules (applied only when a Daily Quiz is saved as completed)."""
from datetime import timedelta

from ..models import UserDailyStreak


def record_completion(session, user_id, quiz_date):
    """Update the streak for a completed daily challenge dated ``quiz_date``. Returns the row.

    Caller guarantees this runs at most once per (user, date) because it happens inside the
    transaction that atomically flips the daily record to completed.
    """
    row = session.get(UserDailyStreak, user_id, with_for_update=True)
    if row is None:
        row = UserDailyStreak(user_id=user_id, current_streak=0, longest_streak=0)
        session.add(row)
    last = row.last_completed_date
    if last == quiz_date:
        return row  # same day again: never increase twice
    if last is not None and quiz_date < last:
        return row  # out-of-order record; ignore
    if last is not None and quiz_date - last == timedelta(days=1):
        row.current_streak += 1
    else:
        row.current_streak = 1  # first ever, or a day was missed
    row.longest_streak = max(row.longest_streak, row.current_streak)
    row.last_completed_date = quiz_date
    return row


def display_streaks(row, today):
    """(current, longest) for display: a streak that was not continued yesterday/today shows 0."""
    if row is None:
        return 0, 0
    current = row.current_streak
    if row.last_completed_date is None or (today - row.last_completed_date).days > 1:
        current = 0
    return current, row.longest_streak
