"""SQLAlchemy engine, session factory, and base class for all models.  Database: SQLite (one local file)."""
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

settings = get_settings()
IS_SQLITE = settings.database_url.startswith("sqlite")

# FastAPI runs requests in worker threads, and SQLite blocks cross-thread use by default; the flag is safe
# here because every request gets its own session (see get_db). `timeout` waits for a busy file instead of failing.
connect_args = {"check_same_thread": False, "timeout": 15} if IS_SQLITE else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):
    """SQLite ignores foreign keys unless asked. Turn them on so "ON DELETE SET NULL / CASCADE" really work
    (as they do in PostgreSQL), and use WAL so readers do not block the single writer."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        try:
            cur.execute("PRAGMA journal_mode=WAL")   # not available for in-memory databases; harmless if refused
        except Exception:
            pass
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """All ORM models inherit from this."""


def get_db():
    """FastAPI dependency: one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
