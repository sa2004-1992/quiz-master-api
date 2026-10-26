"""Engine/session management. Services receive an explicit Session."""
import logging

from flask import g
from sqlalchemy import create_engine, event, text
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


def create_schema(app):
    """Idempotent, non-destructive schema creation (never drops tables)."""
    engine = app.extensions["db_engine"]
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(727001)"))  # serialize multi-worker startup
            Base.metadata.create_all(conn)
    else:
        Base.metadata.create_all(engine)
