"""Engine, session factory and schema creation.

Kept separate from models.py so the models stay importable by a test harness
without opening a connection, and so this module does not grow into a
thousand-line file by step 06.

Run `python -m backend.db` to build an empty backend/mplads.db from scratch.
"""

from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.config import DATABASE_URL
from backend.models import Base

engine = create_engine(DATABASE_URL)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    """Enable SQLite foreign key enforcement on every connection.

    SQLite has foreign keys off by default, SQLAlchemy does not turn them on,
    and create_engine has no option for it. Without this listener every
    ForeignKey in models.py is decorative: a work could reference a vendor
    that does not exist and nothing would complain.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def get_session():
    """Session context manager: commits on success, rolls back on error."""
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
    """FastAPI dependency, used from step 04 onward."""
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


if __name__ == "__main__":
    init_db()
    print(f"Initialised {len(Base.metadata.tables)} tables at {DATABASE_URL}")
