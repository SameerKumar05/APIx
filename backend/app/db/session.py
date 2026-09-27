"""Database Engine and Session Management for APIx.

Supports SQLite (development/testing) and PostgreSQL (production).
Enforces foreign key constraints for SQLite connections.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Database URL configuration
DEFAULT_SQLITE_URL = "sqlite:///./apix.db"
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_SQLITE_URL)

# Configure connection arguments based on database dialect
connect_args: dict[str, Any] = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# Create database engine
engine: Engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=os.environ.get("SQL_ECHO", "false").lower() in ("true", "1"),
    pool_pre_ping=True,
)


# Enforce foreign key constraints on SQLite
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    """Enable SQLite foreign key support on new connections."""
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base declarative class for all APIx SQLAlchemy models."""

    pass


def probe_database_readiness(db: Session) -> None:
    """Verify routes and the durable queue tables exist and are queryable.

    Rolls the session back when a probe statement fails so the caller can
    raise without leaving the transaction aborted.
    """
    try:
        for statement in (
            "SELECT 1 FROM routes LIMIT 1",
            "SELECT 1 FROM crawler_jobs LIMIT 1",
            "SELECT 1 FROM worker_heartbeats LIMIT 1",
        ):
            db.execute(text(statement))
    except SQLAlchemyError:
        db.rollback()
        raise


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for yielding database sessions.

    Ensures proper cleanup and rollback on uncaught exceptions.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(target_engine: Engine | None = None) -> None:
    """Create all tables registered with Base.metadata.

    Args:
        target_engine: Optional engine override (useful for testing).
    """
    import backend.app.models  # noqa: F401

    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)


def drop_db(target_engine: Engine | None = None) -> None:
    """Drop all tables registered with Base.metadata.

    Args:
        target_engine: Optional engine override (useful for testing).
    """
    eng = target_engine or engine
    Base.metadata.drop_all(bind=eng)
