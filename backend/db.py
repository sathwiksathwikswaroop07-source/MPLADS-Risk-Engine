"""Engine, session factory and schema creation.

Kept separate from models.py so the models stay importable by a test harness
without opening a connection, and so this module does not grow into a
thousand-line file by step 06.

Run `python -m backend.db` to build an empty backend/mplads.db from scratch.
This module inserts no rows -- all data, including the demo users, comes
from step 02 (generate_data.py).
"""

from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from backend.config import DATABASE_URL
from backend.models import Base

__all__ = [
    "engine",
    "SessionLocal",
    "get_session",
    "get_db",
    "init_db",
    "table_names",
    "index_names",
    "foreign_keys_enabled",
]


engine = create_engine(DATABASE_URL)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    """Enable SQLite foreign key enforcement on every connection.

    SQLite has foreign keys off by default, SQLAlchemy does not turn them on,
    and create_engine has no option for it. Without this listener every
    ForeignKey in models.py is decorative: a work could reference a vendor
    that does not exist and nothing would complain.

    Note this fires only for genuinely NEW connections, never for a pooled
    one being handed back out. Anything that turns the pragma off on a live
    connection must call engine.dispose() afterwards, or the pool will serve
    that connection again with foreign keys still disabled.

    WAL journalling lets a reader (the API) and a writer (the nightly checks
    run) work at the same time instead of locking each other out.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def get_session():
    """Session context manager for scripts: generate_data, checks, evaluate.

    Commits on success, rolls back on error, always closes.

        with get_session() as session:
            session.add(work)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """FastAPI dependency, used from step 04 onward.

        @router.get("/alerts")
        def list_alerts(db: Session = Depends(get_db)):
            ...

    Deliberately does not commit. Read routes should not, and write routes
    commit explicitly so the intent is visible at the call site.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db():
    """Drop and recreate every table. Safe to re-run at any time.

    SQLAlchemy sorts the drop order by dependency itself, so this handles the
    foreign keys without a hand-maintained ordering.

    Inserts no rows. All data, including the demo users, comes from step 02.
    """
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def table_names() -> list[str]:
    """Real tables present in the database file, sorted. Excludes sqlite_*.

    Reads the file, not Base.metadata -- so it reports what was actually
    created rather than what Python knows about.
    """
    return sorted(
        name
        for name in inspect(engine).get_table_names()
        if not name.startswith("sqlite_")
    )


def index_names() -> list[str]:
    """Named indexes across all tables, sorted. Excludes auto-indexes."""
    inspector = inspect(engine)
    names = []
    for table in inspector.get_table_names():
        for index in inspector.get_indexes(table):
            name = index.get("name")
            if name and not name.startswith("sqlite_autoindex"):
                names.append(name)
    return sorted(names)


def foreign_keys_enabled() -> bool:
    """Whether foreign key enforcement is live on a fresh session.

    The spec calls this the check most likely to fail, so it is a function
    rather than a one-off: checks.py, evaluate.py and any test can assert it
    without repeating the query.
    """
    with SessionLocal() as session:
        return bool(session.execute(text("PRAGMA foreign_keys")).scalar())


if __name__ == "__main__":
    init_db()

    tables = table_names()
    indexes = index_names()
    fk_on = foreign_keys_enabled()

    print(f"Initialised {DATABASE_URL}")
    print(f"  {len(tables)} tables: {', '.join(tables)}")
    print(f"  {len(indexes)} indexes")
    print(f"  foreign_keys: {'ON' if fk_on else 'OFF -- BROKEN, check the listener'}")

    if not fk_on:
        raise SystemExit(1)