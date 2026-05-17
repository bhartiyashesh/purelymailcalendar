"""Server-side email-reminder scheduler with per-occurrence confirm/cancel flow.

When an event is created or updated with an EMAIL VALARM, services.py calls
`replace_for_event(...)` to record the trigger time(s) in the
`scheduled_reminders` table. For recurring events one row is written per
occurrence within a forward-looking expansion window. A periodic POST to
/api/reminders/tick (Railway cron, every 5 min) calls `tick_due()` which
finds due rows and sends each reminder via the owning user's Purelymail SMTP.

Each row carries a `confirm_token`. The reminder email includes confirm /
cancel links pointing at /api/reminders/confirm/{token}. Confirm just stamps
the row; cancel adds an EXDATE for that occurrence on the master CalDAV
event, bumps SEQUENCE, PUTs back, and emails a per-occurrence CANCEL.
"""
from __future__ import annotations

import json
import os
import secrets
import smtplib
import ssl
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from .crypto import decrypt
from .db import SessionLocal
from .models import Mailbox, ScheduledReminder, User
from .schemas import EventIn


router = APIRouter(prefix="/api/reminders", tags=["reminders"])


# How far ahead we materialize occurrences for a recurring event. The tick
# endpoint top-ups this window for series that are about to fall out of it.
RECURRENCE_HORIZON_DAYS = 90


def _utcnow() -> datetime:
    return datetime.utcnow()


def _public_base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://purelymailcalendar.com").rstrip("/")


def _enumerate_occurrences(
    series_start: datetime,
    freq: str,
    interval: int,
    until: Optional[date],
    count: Optional[int],
    window_end: datetime,
) -> List[datetime]:
    """Return occurrence start times from series_start up to min(until, window_end),
    capped by `count` if set. Naive year/month math is good enough for v1 simple
    rules (no BYDAY/BYMONTHDAY)."""
    out: List[datetime] = []
    cur = series_start
    interval = max(1, int(interval or 1))
    count_limit = int(count) if count is not None else None
    until_dt = (
        datetime(until.year, until.month, until.day, 23, 59, 59, tzinfo=series_start.tzinfo)
        if until is not None
        else None
    )

    def too_far(d: datetime) -> bool:
        if until_dt is not None and d > until_dt:
            return True
        if d > window_end:
            return True
        return False

    def step(d: datetime) -> datetime:
        f = freq.upper()
        if f == "DAILY":
            return d + timedelta(days=interval)
        if f == "WEEKLY":
            return d + timedelta(weeks=interval)
        if f == "MONTHLY":
            year = d.year
            month = d.month + interval
            while month > 12:
                year += 1
                month -= 12
            day = min(d.day, _days_in_month(year, month))
            return d.replace(year=year, month=month, day=day)
        if f == "YEARLY":
            try:
                return d.replace(year=d.year + interval)
            except ValueError:
                # Feb 29 → Feb 28 in non-leap years
                return d.replace(year=d.year + interval, day=28)
        return d + timedelta(days=interval)

    n = 0
    while not too_far(cur):
        out.append(cur)
        n += 1
        if count_limit is not None and n >= count_limit:
            break
        cur = step(cur)
    return out


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    return (next_month - timedelta(days=1)).day


def _new_token() -> str:
    return secrets.token_urlsafe(32)[:48]


def replace_for_event(
    user_id: int,
    event_uid: str,
    event_summary: str,
    event_start: datetime,
    inp: EventIn,
) -> int:
    """Replace all pending reminders for this event/user with the current set.

    For one-off events: one row per email alarm.
    For recurring events: one row per (occurrence, email alarm) within the
    next RECURRENCE_HORIZON_DAYS.

    Returns count of rows written.
    """
    email_alarms = [r for r in (inp.reminders or []) if (r.action or "DISPLAY").upper() == "EMAIL"]
    written = 0
    now = _utcnow()  # naive UTC
    # Horizon as an aware datetime in the same zone as event_start, so the
    # comparison inside _enumerate_occurrences is apples-to-apples.
    if event_start.tzinfo is not None:
        horizon = datetime.now(event_start.tzinfo) + timedelta(days=RECURRENCE_HORIZON_DAYS)
    else:
        horizon = datetime.utcnow() + timedelta(days=RECURRENCE_HORIZON_DAYS)

    if inp.recurrence is not None:
        occurrences = _enumerate_occurrences(
            series_start=event_start,
            freq=inp.recurrence.freq,
            interval=int(inp.recurrence.interval or 1),
            until=inp.recurrence.until,
            count=inp.recurrence.count,
            window_end=horizon,
        )
    else:
        occurrences = [event_start]

    with SessionLocal() as db:
        db.query(ScheduledReminder).filter(
            ScheduledReminder.user_id == user_id,
            ScheduledReminder.event_uid == event_uid,
            ScheduledReminder.sent_at.is_(None),
        ).delete(synchronize_session=False)

        for occ_start in occurrences:
            for a in email_alarms:
                recipients = [r.strip() for r in (a.recipients or []) if r and r.strip()]
                if not recipients:
                    continue
                fire_at = occ_start - timedelta(minutes=int(a.minutes_before))
                if fire_at < now - timedelta(minutes=1):
                    continue  # Don't schedule reminders in the past.
                db.add(ScheduledReminder(
                    user_id=user_id,
                    event_uid=event_uid,
                    event_summary=event_summary,
                    event_start=event_start.replace(tzinfo=None) if event_start.tzinfo else event_start,
                    occurrence_start=occ_start.replace(tzinfo=None) if occ_start.tzinfo else occ_start,
                    fire_at=fire_at.replace(tzinfo=None) if fire_at.tzinfo else fire_at,
                    minutes_before=int(a.minutes_before),
                    recipients_json=json.dumps(recipients),
                    description=(a.description or "")[:5000],
                    confirm_token=_new_token(),
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


def cancel_for_occurrence(user_id: int, event_uid: str, occurrence_start: datetime) -> int:
    """Delete a single pending reminder row for one occurrence."""
    occ_naive = occurrence_start.replace(tzinfo=None) if occurrence_start.tzinfo else occurrence_start
    with SessionLocal() as db:
        n = db.query(ScheduledReminder).filter(
            ScheduledReminder.user_id == user_id,
            ScheduledReminder.event_uid == event_uid,
            ScheduledReminder.occurrence_start == occ_naive,
            ScheduledReminder.sent_at.is_(None),
        ).delete(synchronize_session=False)
        db.commit()
        return n


def _format_when(occ_start: datetime) -> str:
    return occ_start.strftime("%a %b %d, %Y  %I:%M %p UTC")


def _send_one(mailbox: Mailbox, r: ScheduledReminder) -> None:
    recipients: List[str] = json.loads(r.recipients_json or "[]")
    if not recipients:
        raise RuntimeError("no recipients")
    occ = r.occurrence_start or r.event_start
    when_str = _format_when(occ)
    offset = (
        f"{r.minutes_before} min" if r.minutes_before < 60
        else f"{r.minutes_before // 60}h"
    )
    base = _public_base_url()
    confirm_link = f"{base}/api/reminders/confirm/{r.confirm_token}?action=yes" if r.confirm_token else None
    cancel_link = f"{base}/api/reminders/confirm/{r.confirm_token}?action=cancel" if r.confirm_token else None

    subject = f"Reminder: {r.event_summary}"
    body_text_lines = [
        f"This is a reminder that '{r.event_summary}' starts in {offset}.",
        "",
        f"When: {when_str}",
    ]
    if r.description:
        body_text_lines += ["", r.description]
    if confirm_link and cancel_link:
        body_text_lines += [
            "",
            "Will this happen?",
            f"Confirm: {confirm_link}",
            f"Cancel this occurrence: {cancel_link}",
        ]
    body_text_lines += ["", "--", "Sent by Purelymail Calendar."]
    body_text = "\n".join(body_text_lines)

    confirm_html = ""
    if confirm_link and cancel_link:
        confirm_html = (
            "<p style='margin-top:18px;font-weight:600;color:#1e293b'>Will this happen?</p>"
            f"<p><a href='{confirm_link}' style='display:inline-block;padding:8px 14px;background:#16a34a;color:#fff;text-decoration:none;border-radius:6px;margin-right:8px'>Yes, confirm</a>"
            f"<a href='{cancel_link}' style='display:inline-block;padding:8px 14px;background:#dc2626;color:#fff;text-decoration:none;border-radius:6px'>Cancel this one</a></p>"
        )
    body_html = (
        f"<p>This is a reminder that <strong>{r.event_summary}</strong> starts in {offset}.</p>"
        f"<p style='color:#475569'>When: {when_str}</p>"
        + (f"<p>{r.description}</p>" if r.description else "")
        + confirm_html
        + "<p style='color:#94a3b8;font-size:12px;margin-top:24px'>Sent by Purelymail Calendar.</p>"
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
            .filter(
                ScheduledReminder.sent_at.is_(None),
                ScheduledReminder.declined_at.is_(None),
                ScheduledReminder.fire_at <= _utcnow(),
            )
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
            # Backfill confirm_token for rows created before this column existed.
            if not r.confirm_token:
                r.confirm_token = _new_token()
                db.flush()
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


def _run_invite_autosync_safely() -> None:
    """Wrapper so a stray exception in the background thread doesn't crash."""
    try:
        from . import services  # local import to avoid import-time cycle
        result = services.auto_sync_all_users_invites()
        print(f"[tick/bg] invite auto-sync done: {result}")
    except Exception as e:
        print(f"[tick/bg] invite auto-sync failed: {e}")


@router.post("/tick")
def tick_endpoint(
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(default=None),
):
    """Fire due email reminders synchronously (fast) and kick off the
    per-user invite auto-sync in a background task so the HTTP response
    returns immediately. Iterating IMAP+CalDAV serially across every
    mailbox was overrunning Railway's request timeout once the user
    count grew past a handful."""
    secret = os.getenv("CRON_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET not configured")
    expected = f"Bearer {secret}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")
    reminders = tick_due()
    background_tasks.add_task(_run_invite_autosync_safely)
    return {
        "reminders": reminders,
        "invites": {"status": "queued"},
    }


# ---- Confirmation pages -----------------------------------------------------


def _html_page(title: str, body_html: str, status: int = 200) -> HTMLResponse:
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f8fafc;margin:0;padding:0;color:#0f172a}}
  .wrap{{max-width:520px;margin:48px auto;padding:24px;background:#fff;border:1px solid #e2e8f0;border-radius:12px;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
  h1{{font-size:20px;margin:0 0 12px 0}}
  p{{color:#334155;line-height:1.55}}
  .ok{{color:#16a34a}} .warn{{color:#b45309}} .err{{color:#dc2626}}
  .muted{{color:#64748b;font-size:13px;margin-top:24px}}
  a{{color:#7c3aed}}
</style></head>
<body><div class="wrap">{body_html}<p class="muted">Purelymail Calendar</p></div></body></html>
"""
    return HTMLResponse(doc, status_code=status)


@router.get("/confirm/{token}", response_class=HTMLResponse)
def confirm_endpoint(token: str, action: str = Query("yes", pattern="^(yes|cancel)$")):
    """Public, token-gated. Confirm an occurrence (informational) or cancel
    just that occurrence (adds EXDATE on the master CalDAV event)."""
    from . import services  # local import to avoid cycles

    with SessionLocal() as db:
        r = db.query(ScheduledReminder).filter(ScheduledReminder.confirm_token == token).one_or_none()
        if r is None:
            return _html_page(
                "Link expired",
                "<h1>Link expired or invalid</h1><p>This confirmation link is no longer valid. If you needed to cancel a meeting, please open the calendar directly.</p>",
                status=404,
            )

        when_str = _format_when(r.occurrence_start or r.event_start)

        if action == "yes":
            if r.declined_at is not None:
                return _html_page(
                    "Already cancelled",
                    f"<h1 class='warn'>This occurrence was already cancelled</h1><p>{r.event_summary} on {when_str} was cancelled previously.</p>",
                )
            if r.confirmed_at is None:
                r.confirmed_at = _utcnow()
                db.commit()
            return _html_page(
                "Confirmed",
                f"<h1 class='ok'>Confirmed</h1><p>{r.event_summary} on {when_str} is on. Attendees will not get any extra emails.</p>",
            )

        # action == "cancel"
        if r.declined_at is not None:
            return _html_page(
                "Already cancelled",
                f"<h1 class='warn'>Already cancelled</h1><p>{r.event_summary} on {when_str} was cancelled previously.</p>",
            )

        user = db.query(User).filter(User.id == r.user_id).one_or_none()
        mb = user.mailbox if user else None
        if mb is None:
            return _html_page(
                "Account missing",
                "<h1 class='err'>Account missing</h1><p>The mailbox tied to this reminder was removed; nothing to cancel.</p>",
                status=410,
            )

        try:
            services.cancel_occurrence(
                user_id=user.id,
                event_uid=r.event_uid,
                occurrence_start=r.occurrence_start or r.event_start,
            )
        except Exception as e:
            return _html_page(
                "Couldn't cancel",
                f"<h1 class='err'>Couldn't cancel</h1><p>Something went wrong contacting the calendar server. Please try again, or cancel from the app directly.</p><p class='muted'>{e}</p>",
                status=502,
            )

        r.declined_at = _utcnow()
        db.commit()
        return _html_page(
            "Cancelled",
            f"<h1 class='ok'>Cancelled</h1><p>{r.event_summary} on {when_str} has been removed from the series. Attendees have been notified.</p>",
        )
