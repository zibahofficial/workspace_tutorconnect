"""
Database engine, session factory and declarative base.

Uses SQLAlchemy 2.x with parameterised queries everywhere (no string-built SQL),
which removes SQL-injection risk.  Works with SQLite out of the box and with
PostgreSQL when DATABASE_URL is configured.
"""
from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from config import settings


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


def _build_engine():
    url = settings.database_url
    connect_args = {}

    if url.startswith("sqlite"):
        # SQLite needs `check_same_thread=False` for FastAPI's threadpool.
        connect_args["check_same_thread"] = False
        if ":memory:" in url:
            return create_engine(
                url,
                connect_args=connect_args,
                poolclass=StaticPool,
                echo=settings.db_echo,
                future=True,
            )
        return create_engine(url, connect_args=connect_args, echo=settings.db_echo, future=True)

    return create_engine(
        url,
        echo=settings.db_echo,
        future=True,
        pool_pre_ping=True,
        pool_size=int(10),
        max_overflow=int(20),
    )


engine = _build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


if settings.using_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):  # pragma: no cover
        """Enable foreign keys + WAL journaling for SQLite."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (idempotent)."""
    import models  # noqa: F401  (registers mappers on Base.metadata)

    Base.metadata.create_all(bind=engine)


def reset_db() -> None:
    """Drop + recreate every table. Used by the test-suite and `--recreate`."""
    import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
