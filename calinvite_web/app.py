"""FastAPI application exposing calinvite over HTTP."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import services
from .auth import current_user, router as auth_router
from .db import Base, engine
from .mailbox import router as mailbox_router
from .reminders import router as reminders_router
from .models import User
from .schemas import (
    CalendarOut,
    CancelEventResponse,
    CreateEventResponse,
    EventIn,
    EventOut,
    RsvpPollIn,
    RsvpPollOut,
)


app = FastAPI(title="calinvite web", version="0.2.0")

_dev_origins = os.getenv("CALINVITE_WEB_CORS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _dev_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    Base.metadata.create_all(bind=engine)
    # Idempotent column additions for ScheduledReminder. Postgres-flavored
    # SQL; on SQLite (dev) we skip silently because IF NOT EXISTS isn't
    # supported and the dev DB is normally fresh.
    from sqlalchemy import text

    dialect = engine.dialect.name
    if dialect != "postgresql":
        return
    stmts = [
        "ALTER TABLE scheduled_reminders ADD COLUMN IF NOT EXISTS occurrence_start TIMESTAMP",
        "ALTER TABLE scheduled_reminders ADD COLUMN IF NOT EXISTS confirm_token VARCHAR(64)",
        "ALTER TABLE scheduled_reminders ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMP",
        "ALTER TABLE scheduled_reminders ADD COLUMN IF NOT EXISTS declined_at TIMESTAMP",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_scheduled_reminders_confirm_token ON scheduled_reminders (confirm_token)",
    ]
    with engine.begin() as conn:
        for s in stmts:
            try:
                conn.execute(text(s))
            except Exception as e:  # pragma: no cover - best-effort migration
                print(f"[startup] migration step skipped: {s} -> {e}")


app.include_router(auth_router)
app.include_router(mailbox_router)
app.include_router(reminders_router)


def _creds(user: User) -> services.MailboxCreds:
    if user.mailbox is None:
        raise HTTPException(status_code=412, detail="No mailbox connected. POST /api/me/mailbox first.")
    return services.creds_for(user.mailbox)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/calendars", response_model=List[CalendarOut])
def get_calendars(user: User = Depends(current_user)):
    creds = _creds(user)
    try:
        return [{"name": n} for n in services.list_calendars(creds)]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"CalDAV error: {e}")


@app.get("/api/events", response_model=List[EventOut])
def get_events(
    days: int = Query(60, ge=1, le=365),
    calendar: Optional[str] = None,
    start: Optional[str] = Query(None, description="ISO-8601 start of fetch window. If set with `end`, overrides `days`."),
    end: Optional[str] = Query(None, description="ISO-8601 end of fetch window. If set with `start`, overrides `days`."),
    user: User = Depends(current_user),
):
    from datetime import datetime, timezone

    creds = _creds(user)
    start_override = None
    end_override = None
    if start and end:
        try:
            sd = datetime.fromisoformat(start.replace("Z", "+00:00"))
            ed = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if sd.tzinfo is None:
                sd = sd.replace(tzinfo=timezone.utc)
            if ed.tzinfo is None:
                ed = ed.replace(tzinfo=timezone.utc)
            if ed <= sd:
                raise HTTPException(status_code=400, detail="`end` must be after `start`")
            start_override = sd
            end_override = ed
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid start/end: {e}")
    try:
        return services.list_events(creds, calendar, days, start_override, end_override)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"CalDAV error: {e}")


@app.get("/api/events/{uid}", response_model=EventOut)
def get_event(uid: str, calendar: Optional[str] = None, user: User = Depends(current_user)):
    creds = _creds(user)
    ev = services.get_event(creds, calendar, uid)
    if ev is None:
        raise HTTPException(status_code=404, detail="event not found")
    return ev


@app.post("/api/events", response_model=CreateEventResponse)
def post_event(body: EventIn, user: User = Depends(current_user)):
    creds = _creds(user)
    try:
        return services.create_event(creds, body, user_id=user.id)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


@app.put("/api/events/{uid}", response_model=CreateEventResponse)
def put_event(uid: str, body: EventIn, user: User = Depends(current_user)):
    creds = _creds(user)
    try:
        return services.update_event(creds, uid, body, user_id=user.id)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


@app.post("/api/events/{uid}/cancel", response_model=CancelEventResponse)
def cancel_event(uid: str, body: EventIn, user: User = Depends(current_user)):
    creds = _creds(user)
    try:
        result = services.cancel_event(creds, uid, body, user_id=user.id)
        return CancelEventResponse(uid=result.uid, sent_to=result.sent_to)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


@app.post("/api/events/{uid}/cancel-occurrence")
def cancel_event_occurrence(
    uid: str,
    body: dict,
    user: User = Depends(current_user),
):
    """Cancel a single occurrence of a recurring event (adds EXDATE on master,
    sends iTIP CANCEL with RECURRENCE-ID). Body: {"occurrence_start": ISO-8601}."""
    from datetime import datetime, timezone

    raw = (body or {}).get("occurrence_start")
    if not raw:
        raise HTTPException(status_code=400, detail="occurrence_start is required")
    try:
        occ = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if occ.tzinfo is None:
            occ = occ.replace(tzinfo=timezone.utc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid occurrence_start: {e}")
    try:
        services.cancel_occurrence(user_id=user.id, event_uid=uid, occurrence_start=occ)
        return {"ok": True}
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


@app.post("/api/rsvps/poll", response_model=RsvpPollOut)
def post_rsvps(body: RsvpPollIn, user: User = Depends(current_user)):
    creds = _creds(user)
    try:
        return services.poll_rsvps(creds, body)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


@app.post("/api/invites/sync")
def sync_invites_endpoint(
    body: dict | None = None,
    user: User = Depends(current_user),
):
    """Scan the inbox for incoming iTIP REQUEST / CANCEL .ics attachments
    and write them to the user's CalDAV calendar. Body (all optional):
    {"calendar": str, "mailbox": str = "INBOX", "only_unseen": bool = true,
     "mark_seen": bool = true}.
    """
    creds = _creds(user)
    body = body or {}
    try:
        return services.sync_invites(
            creds,
            body.get("calendar"),
            mailbox=body.get("mailbox") or "INBOX",
            only_unseen=bool(body.get("only_unseen", True)),
            mark_seen=bool(body.get("mark_seen", True)),
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


_static_dir = Path(__file__).resolve().parent.parent / "web" / "dist"
if _static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=_static_dir / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(_static_dir / "index.html")

    @app.get("/about")
    def about_page():
        about_html = _static_dir / "about.html"
        if about_html.is_file():
            return FileResponse(about_html)
        return FileResponse(_static_dir / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        target = _static_dir / full_path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(_static_dir / "index.html")
