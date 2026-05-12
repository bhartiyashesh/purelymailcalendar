"""Server-side email-reminder scheduler.

When an event is created or updated with an EMAIL VALARM, services.py calls
`schedule_for_event(...)` to record the trigger time(s) in the
`scheduled_reminders` table. A periodic POST to /api/reminders/tick (Railway
cron, every minute) calls `tick_due()` which finds due rows and sends each
reminder via the owning user's Purelymail SMTP.
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from .crypto import decrypt
from .db import SessionLocal
from .models import Mailbox, ScheduledReminder, User
from .schemas import EventIn


router = APIRouter(prefix="/api/reminders", tags=["reminders"])


def _utcnow() -> datetime:
    return datetime.utcnow()


def replace_for_event(user_id: int, event_uid: str, event_summary: str, event_start: datetime, inp: EventIn) -> int:
    """Replace all pending reminders for this event/user with the current set.

    Returns count of rows written.
    """
    email_alarms = [r for r in (inp.reminders or []) if (r.action or "DISPLAY").upper() == "EMAIL"]
    written = 0
    with SessionLocal() as db:
        db.query(ScheduledReminder).filter(
            ScheduledReminder.user_id == user_id,
            ScheduledReminder.event_uid == event_uid,
            ScheduledReminder.sent_at.is_(None),
        ).delete(synchronize_session=False)
        for a in email_alarms:
            recipients = [r.strip() for r in (a.recipients or []) if r and r.strip()]
            if not recipients:
                continue
            fire_at = event_start - timedelta(minutes=int(a.minutes_before))
            if fire_at < _utcnow() - timedelta(minutes=1):
                # Don't schedule reminders in the past.
                continue
            db.add(ScheduledReminder(
                user_id=user_id,
                event_uid=event_uid,
                event_summary=event_summary,
                event_start=event_start.replace(tzinfo=None) if event_start.tzinfo else event_start,
                fire_at=fire_at.replace(tzinfo=None) if fire_at.tzinfo else fire_at,
                minutes_before=int(a.minutes_before),
                recipients_json=json.dumps(recipients),
                description=(a.description or "")[:5000],
            ))
            written += 1
        db.commit()
    return written


def cancel_for_event(user_id: int, event_uid: str) -> int:
    with SessionLocal() as db:
        n = db.query(ScheduledReminder).filter(
            ScheduledReminder.user_id == user_id,
            ScheduledReminder.event_uid == event_uid,
            ScheduledReminder.sent_at.is_(None),
        ).delete(synchronize_session=False)
        db.commit()
        return n


def _send_one(mailbox: Mailbox, r: ScheduledReminder) -> None:
    recipients: List[str] = json.loads(r.recipients_json or "[]")
    if not recipients:
        raise RuntimeError("no recipients")
    when_str = r.event_start.strftime("%a %b %d, %Y  %I:%M %p UTC")
    offset = (
        f"{r.minutes_before} min" if r.minutes_before < 60
        else f"{r.minutes_before // 60}h"
    )
    subject = f"Reminder: {r.event_summary}"
    body_text = (
        f"This is a reminder that '{r.event_summary}' starts in {offset}.\n\n"
        f"When: {when_str}\n\n"
        f"{r.description}\n\n"
        f"--\nSent by Purelymail Calendar."
    )
    body_html = (
        f"<p>This is a reminder that <strong>{r.event_summary}</strong> starts in {offset}.</p>"
        f"<p style='color:#475569'>When: {when_str}</p>"
        + (f"<p>{r.description}</p>" if r.description else "")
        + "<p style='color:#94a3b8;font-size:12px'>Sent by Purelymail Calendar.</p>"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((mailbox.display_name, mailbox.email))
    msg["To"] = ", ".join(recipients)
    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")

    password = decrypt(mailbox.encrypted_password)
    ctx = ssl.create_default_context()
    if mailbox.smtp_port == 465:
        with smtplib.SMTP_SSL(mailbox.smtp_host, mailbox.smtp_port, context=ctx) as s:
            s.login(mailbox.email, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(mailbox.smtp_host, mailbox.smtp_port) as s:
            s.ehlo(); s.starttls(context=ctx); s.ehlo()
            s.login(mailbox.email, password)
            s.send_message(msg)


def tick_due(limit: int = 50) -> dict:
    """Find due reminders and send them. Returns counts."""
    sent = 0
    failed = 0
    skipped = 0
    with SessionLocal() as db:
        rows = (
            db.query(ScheduledReminder)
            .filter(ScheduledReminder.sent_at.is_(None), ScheduledReminder.fire_at <= _utcnow())
            .order_by(ScheduledReminder.fire_at.asc())
            .limit(limit)
            .all()
        )
        for r in rows:
            user = db.query(User).filter(User.id == r.user_id).one_or_none()
            mb = user.mailbox if user else None
            if mb is None:
                r.last_error = "user or mailbox missing"
                r.attempts += 1
                skipped += 1
                continue
            try:
                _send_one(mb, r)
                r.sent_at = _utcnow()
                sent += 1
            except Exception as e:
                r.attempts += 1
                r.last_error = str(e)[:1000]
                failed += 1
                # Give up after 5 attempts to avoid hammering on bad creds.
                if r.attempts >= 5:
                    r.sent_at = _utcnow()
            db.commit()
    return {"sent": sent, "failed": failed, "skipped": skipped}


@router.post("/tick")
def tick_endpoint(authorization: Optional[str] = Header(default=None)):
    secret = os.getenv("CRON_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET not configured")
    expected = f"Bearer {secret}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")
    return tick_due()
