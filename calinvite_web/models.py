"""SQLAlchemy models: users, mailboxes, sessions, magic-link tokens."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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

    mailboxes: Mapped[list["Mailbox"]] = relationship(
        "Mailbox",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="Mailbox.id",
    )
    sessions: Mapped[list["UserSession"]] = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")

    @property
    def mailbox(self) -> Optional["Mailbox"]:
        """First mailbox (the user's primary). Kept for back-compat with the
        original single-mailbox model. New code should iterate `mailboxes`
        or use the X-Mailbox-Id-resolved object from `current_mailbox`."""
        return self.mailboxes[0] if self.mailboxes else None


class Mailbox(Base):
    """A user's Purelymail mailbox: CalDAV + SMTP + IMAP creds.

    A user can have multiple mailboxes (personal + work + ...). The active
    one for a given request is selected by the X-Mailbox-Id header on the
    client side; the server resolves it via `current_mailbox` and defaults
    to the first mailbox when the header is absent.
    """
    __tablename__ = "mailboxes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False)
    smtp_host: Mapped[str] = mapped_column(String(120), default="smtp.purelymail.com", nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, default=465, nullable=False)
    imap_host: Mapped[str] = mapped_column(String(120), default="imap.purelymail.com", nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, default=993, nullable=False)
    # The CalDAV calendar this mailbox prefers (used by auto-sync and seeded
    # into the UI dropdown when the user switches to this mailbox).
    selected_calendar: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Hex color used to tint this mailbox's events in the All-accounts overlay
    # view. Nullable so the UI can fall back to a palette index derived from
    # `id` when the user hasn't picked one.
    color: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # Last time we ran an AI-tasks inbox scan against this mailbox. Drives
    # the "since last scan" incremental fetch so we don't reprocess the
    # same emails on every Fetch click.
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
    # Last time we walked CardDAV and synced this mailbox's contact cache.
    # Used by the autocomplete debouncer to decide whether the cache is
    # fresh enough to skip a refetch (5-min TTL).
    last_contacts_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow, onupdate=_utcnow, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="mailboxes")

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


class ScheduledReminder(Base):
    """One scheduled email reminder for a single event occurrence.

    Rows are inserted by services.create_event/update_event when an event has
    an EMAIL VALARM. For recurring events one row is written per occurrence
    (within a forward-looking expansion window). A periodic
    /api/reminders/tick endpoint scans for rows whose fire_at has passed and
    sent_at is null, then sends the email via the owning user's mailbox SMTP.

    Each row carries a `confirm_token` that gives access to a public
    /api/reminders/confirm endpoint where the organizer can confirm or
    cancel just this occurrence.
    """
    __tablename__ = "scheduled_reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    # Which mailbox the reminder was scheduled from. Nullable for back-compat
    # with rows written before multi-mailbox; tick falls back to the user's
    # first mailbox in that case.
    mailbox_id: Mapped[Optional[int]] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), index=True, nullable=True)
    event_uid: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    event_summary: Mapped[str] = mapped_column(String(500), nullable=False)
    event_start: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    # For recurring events, this is the specific occurrence's start time.
    # For one-off events it equals `event_start`. Stored as naive UTC.
    occurrence_start: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
    fire_at: Mapped[datetime] = mapped_column(DateTime(), index=True, nullable=False)
    minutes_before: Mapped[int] = mapped_column(Integer, nullable=False)
    recipients_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # When set, the reminder is emailed once per recipient so the guest list
    # is not in a shared To header. Confirm/cancel links stay on the
    # organizer's copy only.
    bcc_invites: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirm_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True, nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
    declined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
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


class TaskItem(Base):
    """An action item extracted from an inbox email by a browser-side LLM.

    The browser pulls recent emails via /api/inbox/recent, runs Gemini Nano
    locally to extract tasks, and POSTs the structured results back to
    /api/tasks/bulk. Email bodies never round-trip through the server.

    The unique key on (user_id, mailbox_id, message_uid, task_index) makes
    re-scanning idempotent: a second extraction of the same email overwrites
    the row in place, while user-managed state (done_at, snoozed_until,
    as_event_uid) lives only here and is carried forward by the upsert path.
    """
    __tablename__ = "task_items"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "mailbox_id", "message_uid", "task_index",
            name="ux_task_items_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    mailbox_id: Mapped[int] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), index=True, nullable=False)
    message_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    task_index: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)

    source_subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    source_from: Mapped[str] = mapped_column(String(254), nullable=False, default="")
    source_date: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)

    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
    snoozed_until: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
    # When the user converts a task into a calendar event, we stamp the
    # resulting event UID here so the row stops nagging.
    as_event_uid: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow, nullable=False)


class Contact(Base):
    """A vCard cached from the user's Purelymail CardDAV address book.

    Source of truth is CardDAV (Purelymail's /webdav/{account}/carddav/);
    this table is a read-through cache so the attendee autocomplete can
    answer in sub-100ms without walking PROPFIND on every keystroke.
    `source_book` records which address book on the server the row came
    from ('default' or 'automaticallyCollected'). `etag` is the server-
    side validator for incremental sync; when CardDAV doesn't expose one
    we fall back to a hash of the vCard bytes.
    """
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("mailbox_id", "vcard_uid", name="ux_contacts_mailbox_uid"),
        Index("ix_contacts_user_email", "user_id", "primary_email"),
        Index("ix_contacts_mailbox_id", "mailbox_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    mailbox_id: Mapped[int] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False)
    vcard_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    etag: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    href: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    primary_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    emails_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    org: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_book: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    raw_vcard: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow, nullable=False)
