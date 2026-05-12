"""SQLAlchemy models: users, mailboxes, sessions, magic-link tokens."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    # Naive UTC: SQLite drops tzinfo, so we avoid the naive/aware comparison trap.
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)

    mailbox: Mapped[Optional["Mailbox"]] = relationship("Mailbox", back_populates="user", uselist=False, cascade="all, delete-orphan")
    sessions: Mapped[list["UserSession"]] = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")


class Mailbox(Base):
    """A user's Purelymail mailbox: CalDAV + SMTP + IMAP creds."""
    __tablename__ = "mailboxes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False)
    smtp_host: Mapped[str] = mapped_column(String(120), default="smtp.purelymail.com", nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, default=465, nullable=False)
    imap_host: Mapped[str] = mapped_column(String(120), default="imap.purelymail.com", nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, default=993, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow, onupdate=_utcnow, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="mailbox")

    @property
    def caldav_url(self) -> str:
        return f"https://purelymail.com/webdav/{self.account_id}/caldav/"


class MagicToken(Base):
    """One-time login tokens for magic-link auth."""
    __tablename__ = "magic_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow, nullable=False)


class UserSession(Base):
    """Long-lived session, keyed by random id stored in HttpOnly cookie."""
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="sessions")
