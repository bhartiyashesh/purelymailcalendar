"""Admin endpoints — token-gated read-only stats for the project owner.

Auth model: a single shared bearer token from the `ADMIN_API_TOKEN` env var.
Anything else returns 401. The token is intended to be set once on Railway
and copy-pasted into the off-repo dashboard HTML's prompt.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import func, select

from .db import SessionLocal
from .models import Mailbox, ScheduledReminder, User


router = APIRouter(prefix="/api/admin", tags=["admin"])


def _check_token(authorization: Optional[str]) -> None:
    expected = os.getenv("ADMIN_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_API_TOKEN not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


@router.get("/stats")
def admin_stats(authorization: Optional[str] = Header(default=None)) -> dict:
    _check_token(authorization)
    with SessionLocal() as db:
        users_q = (
            db.query(
                User.id,
                User.email,
                User.display_name,
                User.created_at,
                User.last_login_at,
            )
            .order_by(User.last_login_at.desc().nullslast())
            .all()
        )
        # Build per-user mailbox + reminder counts.
        mb_user_ids = {row[0] for row in db.query(Mailbox.user_id).all()}
        reminder_counts = dict(
            db.query(ScheduledReminder.user_id, func.count(ScheduledReminder.id))
            .group_by(ScheduledReminder.user_id)
            .all()
        )
        users = []
        for uid, email, name, created, last_login in users_q:
            users.append({
                "email": email,
                "display_name": name or "",
                "created_at": created.isoformat() if created else None,
                "last_login_at": last_login.isoformat() if last_login else None,
                "has_mailbox": uid in mb_user_ids,
                "reminder_rows": int(reminder_counts.get(uid, 0)),
            })

        # Reminder rollup.
        reminders = db.execute(
            select(
                func.count(ScheduledReminder.id),
                func.count(ScheduledReminder.id).filter(ScheduledReminder.sent_at.isnot(None)),
                func.count(ScheduledReminder.id).filter(
                    ScheduledReminder.sent_at.is_(None),
                    ScheduledReminder.declined_at.is_(None),
                ),
                func.count(ScheduledReminder.id).filter(ScheduledReminder.declined_at.isnot(None)),
                func.count(ScheduledReminder.id).filter(ScheduledReminder.confirmed_at.isnot(None)),
            )
        ).one()
    return {
        "users": users,
        "totals": {
            "users": len(users),
            "with_mailbox": sum(1 for u in users if u["has_mailbox"]),
            "stalled": sum(1 for u in users if not u["has_mailbox"]),
        },
        "reminders": {
            "total_rows": int(reminders[0]),
            "sent": int(reminders[1]),
            "pending": int(reminders[2]),
            "declined": int(reminders[3]),
            "confirmed": int(reminders[4]),
        },
    }
