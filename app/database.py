"""Engine/session management. Services receive an explicit Session."""
import logging

from flask import g
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.orm import sessionmaker

from .models import Base, Question

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


def upgrade_questions_pg(conn):
    """PostgreSQL: allow the 'all' quiz mode and make duplicate detection per (mode, category).
    Existing rows are untouched; every statement is idempotent."""
    insp = inspect(conn)
    if "questions" not in insp.get_table_names():
        return
    ck = conn.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                           "WHERE conname = 'ck_questions_pool' AND conrelid = 'questions'::regclass")).scalar()
    if ck is None or "'all'" not in ck:
        conn.execute(text("ALTER TABLE questions DROP CONSTRAINT IF EXISTS ck_questions_pool"))
        conn.execute(text("ALTER TABLE questions ADD CONSTRAINT ck_questions_pool "
                          "CHECK (pool IN ('category','all','daily'))"))
    have = {r[0] for r in conn.execute(text("SELECT conname FROM pg_constraint WHERE conrelid = 'questions'::regclass"))}
    if "uq_questions_pool_cat_hash" not in have:
        conn.execute(text("ALTER TABLE questions ADD CONSTRAINT uq_questions_pool_cat_hash "
                          "UNIQUE (pool, category_id, question_hash)"))
    if "uq_questions_pool_hash" in have:  # superseded by the per-category constraint above
        conn.execute(text("ALTER TABLE questions DROP CONSTRAINT uq_questions_pool_hash"))


def upgrade_questions_sqlite(engine):
    """SQLite cannot alter constraints, so an old questions table is rebuilt (all rows and ids are copied,
    foreign keys from answers/bookmarks keep pointing at it). Runs once, only if the old schema is detected."""
    with engine.connect() as c:
        ddl = c.exec_driver_sql("SELECT sql FROM sqlite_master WHERE type='table' AND name='questions'").scalar()
    if not ddl or ("'all'" in ddl and "uq_questions_pool_cat_hash" in ddl):
        return
    raw = engine.raw_connection()
    try:
        raw.isolation_level = None  # autocommit: we issue BEGIN/COMMIT ourselves (PRAGMAs need this)
        cur = raw.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute("PRAGMA legacy_alter_table=ON")
        cols = ", ".join(c.name for c in Question.__table__.columns)
        try:
            cur.execute("BEGIN")
            cur.execute("ALTER TABLE questions RENAME TO questions_old")
            cur.execute("DROP INDEX IF EXISTS ix_questions_pool_cat_id")
            cur.execute(str(CreateTable(Question.__table__).compile(dialect=engine.dialect)))
            for idx in Question.__table__.indexes:
                cur.execute(str(CreateIndex(idx).compile(dialect=engine.dialect)))
            cur.execute(f"INSERT INTO questions ({cols}) SELECT {cols} FROM questions_old")
            cur.execute("DROP TABLE questions_old")
            cur.execute("COMMIT")
            log.info("Upgraded the SQLite questions table (quiz modes + per-category duplicate rule)")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA legacy_alter_table=OFF")
            cur.execute("PRAGMA foreign_keys=ON")
    finally:
        raw.close()


def create_schema(app):
    """Idempotent, non-destructive schema creation (never drops tables)."""
    engine = app.extensions["db_engine"]
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(727001)"))  # serialize multi-worker startup
            Base.metadata.create_all(conn)
            upgrade_columns(conn)
            upgrade_questions_pg(conn)
    else:
        upgrade_questions_sqlite(engine)
        with engine.begin() as conn:
            Base.metadata.create_all(conn)
            upgrade_columns(conn)
