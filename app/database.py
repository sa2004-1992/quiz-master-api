"""Engine/session management. Services receive an explicit Session."""
import logging

from flask import g
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from .models import Base

log = logging.getLogger(__name__)


def make_engine(url: str, pool_size=5, max_overflow=5):
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"timeout": 30, "check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # enforce FKs in SQLite tests
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=pool_size,
                         max_overflow=max_overflow, pool_recycle=300)


def init_engine(app):
    cfg = app.config
    engine = make_engine(cfg["DATABASE_URL"], cfg["DB_POOL_SIZE"], cfg["DB_MAX_OVERFLOW"])
    app.extensions["db_engine"] = engine
    app.extensions["db_sessionmaker"] = sessionmaker(bind=engine, expire_on_commit=False)

    @app.teardown_appcontext
    def _close_session(_exc):
        session = g.pop("db_session", None)
        if session is not None:
            if _exc is not None:
                session.rollback()
            session.close()  # returns the connection to the pool


def get_session():
    from flask import current_app
    if "db_session" not in g:
        g.db_session = current_app.extensions["db_sessionmaker"]()
    return g.db_session


def new_session(app):
    """A standalone session (CLI, startup tasks, tests)."""
    return app.extensions["db_sessionmaker"]()


_BACKFILL = """
UPDATE quiz_games SET
  answered_count = (SELECT COUNT(*) FROM quiz_game_answers a
                    WHERE a.game_id = quiz_games.id AND a.selected_option IS NOT NULL),
  wrong_count = (SELECT COUNT(*) FROM quiz_game_answers a
                 WHERE a.game_id = quiz_games.id AND a.selected_option IS NOT NULL AND a.is_correct = :no)
WHERE status = 'completed'
"""


def upgrade_columns(conn):
    """Additive upgrade for databases created by an earlier version: add the per-game answered/wrong
    counts and backfill them from the stored answers. Safe to run repeatedly; nothing is dropped."""
    insp = inspect(conn)
    if "quiz_games" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("quiz_games")}
    added = False
    for name in ("answered_count", "wrong_count"):
        if name not in cols:
            conn.execute(text(f"ALTER TABLE quiz_games ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0"))
            added = True
    if added:
        conn.execute(text(_BACKFILL), {"no": False})
        log.info("Added quiz_games.answered_count / wrong_count and backfilled saved games")


def create_schema(app):
    """Idempotent, non-destructive schema creation (never drops tables)."""
    engine = app.extensions["db_engine"]
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(727001)"))  # serialize multi-worker startup
            Base.metadata.create_all(conn)
            upgrade_columns(conn)
    else:
        with engine.begin() as conn:
            Base.metadata.create_all(conn)
            upgrade_columns(conn)
