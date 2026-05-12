"""Database engine and session factory.

Defaults to SQLite at `./calinvite.db` for local dev. Override with
DATABASE_URL env var (e.g. postgresql+psycopg://user:pass@host/db) when
deploying.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


_DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent.parent / "calinvite.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_DEFAULT_SQLITE_PATH}")

# Railway's Postgres injects `postgresql://...`. SQLAlchemy maps that to the
# psycopg2 dialect by default, but we install psycopg3 (`psycopg[binary]`).
# Rewrite to `postgresql+psycopg://` so the right driver is used.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
