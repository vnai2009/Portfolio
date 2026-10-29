"""Database engine, session factory and the declarative base."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


class Base(DeclarativeBase):
    """Declarative base for every ORM model in this project."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session and always closing it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
