"""SQLAlchemy models (PostgreSQL in production, SQLite only for local tests)."""
from datetime import date, datetime, timezone

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey,
                        Index, Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

QUIZ_TYPES = ("category", "all", "daily")
GENDERS = ("Male", "Female", "Other")


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)  # stored lowercase
    username: Mapped[str] = mapped_column(String(30), nullable=False)
    username_lower: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    gender: Mapped[str] = mapped_column(String(10), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    preferences = relationship("UserPreference", uselist=False, back_populates="user",
                               cascade="all, delete-orphan")
    __table_args__ = (CheckConstraint("gender IN ('Male','Female','Other')", name="ck_users_gender"),)


class UserPreference(Base):
    __tablename__ = "user_preferences"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    dark_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    user = relationship("User", back_populates="preferences")


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="en")


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool: Mapped[str] = mapped_column(String(10), nullable=False, default="category")  # category | daily
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    option_a: Mapped[str] = mapped_column(Text, nullable=False)
    option_b: Mapped[str] = mapped_column(Text, nullable=False)
    option_c: Mapped[str] = mapped_column(Text, nullable=False)
    option_d: Mapped[str] = mapped_column(Text, nullable=False)
    correct_answer: Mapped[str] = mapped_column(String(1), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(10), nullable=False, default="medium")
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="ai")
    daily_date: Mapped[date] = mapped_column(Date, nullable=True)  # last daily set that used it
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    category = relationship("Category")
    __table_args__ = (
        UniqueConstraint("pool", "question_hash", name="uq_questions_pool_hash"),
        CheckConstraint("correct_answer IN ('A','B','C','D')", name="ck_questions_correct"),
        CheckConstraint("pool IN ('category','daily')", name="ck_questions_pool"),
        CheckConstraint("difficulty IN ('easy','medium','hard')", name="ck_questions_difficulty"),
        Index("ix_questions_pool_cat_id", "pool", "category_id", "id"),
    )

    def options(self):
        return {"A": self.option_a, "B": self.option_b, "C": self.option_c, "D": self.option_d}


class UserCategoryProgress(Base):
    """Quiz Type 1 pointer: one row per user/category."""
    __tablename__ = "user_category_progress"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), primary_key=True)
    pointer: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (CheckConstraint("pointer >= 0", name="ck_ucp_pointer"),)


class PlayAllProgress(Base):
    """Quiz Type 2 pointer: a single row per user."""
    __tablename__ = "play_all_progress"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    pointer: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (CheckConstraint("pointer >= 0", name="ck_pap_pointer"),)


class DailyQuestionSet(Base):
    """Quiz Type 3: the dedicated question set for one calendar day (shared by all users)."""
    __tablename__ = "daily_question_sets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quiz_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    question_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class QuizGame(Base):
    __tablename__ = "quiz_games"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    quiz_type: Mapped[str] = mapped_column(String(10), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="in_progress")
    # 'cat:<id>' | 'all' | 'daily' while in progress, NULL once saved -> one active game per slot
    active_key: Mapped[str] = mapped_column(String(20), nullable=True)
    question_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    seq_positions: Mapped[list] = mapped_column(JSON, nullable=False)
    start_pointer: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    hints_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hints_max: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    difficulty: Mapped[str] = mapped_column(String(10), nullable=False, default="Mixed")
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    paused_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    paused_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, nullable=True)
    category = relationship("Category")
    __table_args__ = (
        UniqueConstraint("user_id", "active_key", name="uq_games_user_active"),
        CheckConstraint("quiz_type IN ('category','all','daily')", name="ck_games_type"),
        CheckConstraint("status IN ('in_progress','completed')", name="ck_games_status"),
        Index("ix_games_user_status_finished", "user_id", "status", "finished_at"),
        Index("ix_games_status_finished", "status", "finished_at"),
    )


class QuizGameAnswer(Base):
    __tablename__ = "quiz_game_answers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("quiz_games.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_option: Mapped[str] = mapped_column(String(1), nullable=True)  # NULL when resolved by hint
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hint_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("game_id", "question_id", name="uq_answers_game_question"),
        UniqueConstraint("game_id", "position", name="uq_answers_game_position"),
        Index("ix_answers_question", "question_id"),
    )


class DailyGameRecord(Base):
    """One row per user per calendar day: enforces the one-daily-challenge-per-day rule."""
    __tablename__ = "daily_game_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    quiz_date: Mapped[date] = mapped_column(Date, nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("quiz_games.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="in_progress")
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("user_id", "quiz_date", name="uq_daily_user_date"),
        CheckConstraint("status IN ('in_progress','completed')", name="ck_daily_status"),
    )


class UserDailyStreak(Base):
    __tablename__ = "user_daily_streaks"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    current_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_completed_date: Mapped[date] = mapped_column(Date, nullable=True)


class Bookmark(Base):
    __tablename__ = "bookmarks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "question_id", name="uq_bookmarks_user_question"),)


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
