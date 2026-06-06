"""Database layer for the PulseGo orchestrator auth.

SQLAlchemy engine + session built from DATABASE_URL. Defaults to a local SQLite file so
the app/tests run with zero setup; in prod set DATABASE_URL to the Railway Postgres URL
(postgresql://… — psycopg driver). A single `users` table backs email+password login.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, String, Integer, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Mapped, mapped_column


def _normalize_url(url: str) -> str:
    # Railway/Heroku hand out postgres:// ; SQLAlchemy 2 wants postgresql:// (psycopg).
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL = _normalize_url(os.getenv("DATABASE_URL", "sqlite:///./pulsego.db"))

# SQLite needs check_same_thread off so the FastAPI threadpool can share the connection.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="dispatcher")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def init_db() -> None:
    """Create tables if they do not exist. Safe to call on every startup."""
    Base.metadata.create_all(bind=engine)


def get_session():
    """Return a new SQLAlchemy session (caller is responsible for closing)."""
    return SessionLocal()
