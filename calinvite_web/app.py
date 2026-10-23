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
from .mailbox import current_mailbox, router as mailbox_router
from .reminders import router as reminders_router
from .models import Mailbox, User
from .schemas import (
    CalendarOut,
    CancelEventResponse,
    CreateEventResponse,
    EventIn,
    EventOut,
    MailboxCalendarOut,
    MailboxCalendarsAllOut,
    MailboxEventOut,
    MailboxEventsAllOut,
    MailboxFailureOut,
    RsvpPollIn,
    RsvpPollOut,
)


app = FastAPI(title="calinvite web", version="0.2.0")

# `null` is the Origin a browser sends for file:// pages (used by the
# off-repo admin dashboard HTML). Safe to allow because the admin
# endpoint is gated on a bearer token, not a cookie.
_dev_origins = os.getenv("CALINVITE_WEB_CORS", "http://localhost:5173,http://127.0.0.1:5173,null").split(",")
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

    # Idempotent migrations for tables that already exist. SQLAlchemy's
    # create_all only creates missing tables; it never alters existing
    # ones, so columns added in later commits have to be ALTERed in.
    #
    # We use the SQLAlchemy inspector to read each table's current
    # columns and only run ADD COLUMN when the column is missing. That
    # works on both Postgres (live deployments) and SQLite (local dev
    # DBs that pre-date a model change), so the dev DB no longer has to
    # be wiped every time we add a column.
    from sqlalchemy import inspect, text

    dialect = engine.dialect.name
    inspector = inspect(engine)

    # (table, column_name, column_type_for_alter)
    column_additions = [
        ("scheduled_reminders", "occurrence_start", "TIMESTAMP"),
        ("scheduled_reminders", "confirm_token", "VARCHAR(64)"),
        ("scheduled_reminders", "confirmed_at", "TIMESTAMP"),
        ("scheduled_reminders", "declined_at", "TIMESTAMP"),
        ("scheduled_reminders", "mailbox_id", "INTEGER"),
        ("scheduled_reminders", "bcc_invites", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("mailboxes", "selected_calendar", "VARCHAR(255)"),
        ("mailboxes", "color", "VARCHAR(16)"),
        ("mailboxes", "last_scanned_at", "TIMESTAMP"),
        ("mailboxes", "last_contacts_synced_at", "TIMESTAMP"),
    ]

    def _table_columns(table: str) -> set[str]:
        try:
            return {c["name"] for c in inspector.get_columns(table)}
        except Exception:
            return set()

    with engine.begin() as conn:
        for table, column, coltype in column_additions:
            cols = _table_columns(table)
            if not cols:
                continue  # table doesn't exist yet (handled by create_all on first run)
            if column in cols:
                continue
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
            except Exception as e:  # pragma: no cover - best-effort
                print(f"[startup] could not add {table}.{column}: {e}", flush=True)

        # Postgres-only constraint/index ops. SQLite either created these
        # via create_all already, or doesn't support the syntax.
        if dialect == "postgresql":
            pg_stmts = [
                "ALTER TABLE mailboxes DROP CONSTRAINT IF EXISTS mailboxes_user_id_key",
                "CREATE INDEX IF NOT EXISTS ix_mailboxes_user_id ON mailboxes (user_id)",
                "CREATE INDEX IF NOT EXISTS ix_scheduled_reminders_mailbox_id ON scheduled_reminders (mailbox_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_scheduled_reminders_confirm_token ON scheduled_reminders (confirm_token)",
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_task_items_source ON task_items (user_id, mailbox_id, message_uid, task_index)",
                "CREATE INDEX IF NOT EXISTS ix_task_items_user_id ON task_items (user_id)",
                "CREATE INDEX IF NOT EXISTS ix_task_items_mailbox_id ON task_items (mailbox_id)",
                "CREATE INDEX IF NOT EXISTS ix_task_items_done_at ON task_items (done_at)",
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_mailbox_uid ON contacts (mailbox_id, vcard_uid)",
                "CREATE INDEX IF NOT EXISTS ix_contacts_user_email ON contacts (user_id, primary_email)",
                "CREATE INDEX IF NOT EXISTS ix_contacts_mailbox_id ON contacts (mailbox_id)",
                "CREATE INDEX IF NOT EXISTS ix_contacts_user_id ON contacts (user_id)",
            ]
            for s in pg_stmts:
                try:
                    conn.execute(text(s))
                except Exception as e:  # pragma: no cover
                    print(f"[startup] migration step skipped: {s} -> {e}", flush=True)


app.include_router(auth_router)
app.include_router(mailbox_router)
app.include_router(reminders_router)
from .admin import router as admin_router  # noqa: E402  (intentional late import)
app.include_router(admin_router)
from .tasks import router as tasks_router  # noqa: E402  (intentional late import)
app.include_router(tasks_router)
from .contacts import router as contacts_router  # noqa: E402  (intentional late import)
app.include_router(contacts_router)


def _creds(mb: Mailbox) -> services.MailboxCreds:
    return services.creds_for(mb)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/version")
def version():
    """Build provenance for the running container. Baked into the Docker
    image at build time via --build-arg COMMIT_SHA + BUILD_TIME (CI sets
    these from github.sha and the workflow timestamp). Public on purpose
    so anyone can compare the running SHA to the public commit history."""
    sha = os.getenv("COMMIT_SHA", "unknown")
    short = sha[:7] if sha and sha != "unknown" else "unknown"
    return {
        "commit": sha,
        "short": short,
        "built_at": os.getenv("BUILD_TIME", "unknown"),
        "source": "https://github.com/bhartiyashesh/purelymailcalendar",
        "commit_url": (
            f"https://github.com/bhartiyashesh/purelymailcalendar/commit/{sha}"
            if sha and sha != "unknown"
            else None
        ),
    }


@app.get("/api/calendars", response_model=List[CalendarOut])
def get_calendars(mailbox: Mailbox = Depends(current_mailbox)):
    creds = _creds(mailbox)
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
    mailbox: Mailbox = Depends(current_mailbox),
):
    from datetime import datetime, timezone

    creds = _creds(mailbox)
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


# ---------------------------------------------------------------------------
# All-accounts overlay (phase 2a)
# Registered above /api/events/{uid} so FastAPI matches the literal `all`
# path before falling through to the {uid} parameterized route.
# ---------------------------------------------------------------------------


def _mailbox_failure(mb, exc: Exception) -> MailboxFailureOut:
    return MailboxFailureOut(
        mailbox_id=mb.id,
        mailbox_email=mb.email,
        error=str(exc)[:500],
    )


@app.get("/api/calendars/all", response_model=MailboxCalendarsAllOut)
def get_calendars_all(user: User = Depends(current_user)):
    import concurrent.futures as _futures

    mailboxes = list(user.mailboxes)
    if not mailboxes:
        return MailboxCalendarsAllOut(calendars=[], partial_failures=[])

    def _one(mb: Mailbox):
        creds = services.creds_for(mb)
        return services.list_calendar_names(creds)

    rows: list[MailboxCalendarOut] = []
    fails: list[MailboxFailureOut] = []
    workers = min(len(mailboxes), 4)
    with _futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_one, mb): mb for mb in mailboxes}
        for fut in _futures.as_completed(futures):
            mb = futures[fut]
            try:
                for name in fut.result(timeout=20):
                    rows.append(MailboxCalendarOut(
                        mailbox_id=mb.id,
                        mailbox_email=mb.email,
                        mailbox_display_name=mb.display_name,
                        mailbox_color=mb.color,
                        name=name,
                    ))
            except Exception as e:
                fails.append(_mailbox_failure(mb, e))
    rows.sort(key=lambda r: (r.mailbox_id, r.name.lower()))
    return MailboxCalendarsAllOut(calendars=rows, partial_failures=fails)


@app.get("/api/events/all", response_model=MailboxEventsAllOut)
def get_events_all(
    days: int = Query(60, ge=1, le=365),
    start: Optional[str] = Query(None, description="ISO-8601 start of fetch window. If set with `end`, overrides `days`."),
    end: Optional[str] = Query(None, description="ISO-8601 end of fetch window. If set with `start`, overrides `days`."),
    user: User = Depends(current_user),
):
    import concurrent.futures as _futures
    from datetime import datetime, timezone

    mailboxes = list(user.mailboxes)
    if not mailboxes:
        return MailboxEventsAllOut(events=[], partial_failures=[])

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

    def _one(mb: Mailbox):
        creds = services.creds_for(mb)
        return services.list_events_all_calendars(creds, days, start_override, end_override)

    events: list[MailboxEventOut] = []
    fails: list[MailboxFailureOut] = []
    workers = min(len(mailboxes), 4)
    with _futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_one, mb): mb for mb in mailboxes}
        for fut in _futures.as_completed(futures):
            mb = futures[fut]
            try:
                pairs = fut.result(timeout=25)
            except Exception as e:
                fails.append(_mailbox_failure(mb, e))
                continue
            for cname, ev in pairs:
                events.append(MailboxEventOut(
                    **ev.model_dump(),
                    mailbox_id=mb.id,
                    mailbox_email=mb.email,
                    mailbox_display_name=mb.display_name,
                    mailbox_color=mb.color,
                    calendar_name=cname,
                ))
    events.sort(key=lambda e: e.start)
    return MailboxEventsAllOut(events=events, partial_failures=fails)


@app.get("/api/events/{uid}", response_model=EventOut)
def get_event(uid: str, calendar: Optional[str] = None, mailbox: Mailbox = Depends(current_mailbox)):
    creds = _creds(mailbox)
    ev = services.get_event(creds, calendar, uid)
    if ev is None:
        raise HTTPException(status_code=404, detail="event not found")
    return ev


@app.post("/api/events", response_model=CreateEventResponse)
def post_event(body: EventIn, user: User = Depends(current_user), mailbox: Mailbox = Depends(current_mailbox)):
    creds = _creds(mailbox)
    try:
        return services.create_event(creds, body, user_id=user.id, mailbox_id=mailbox.id)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


@app.put("/api/events/{uid}", response_model=CreateEventResponse)
def put_event(uid: str, body: EventIn, user: User = Depends(current_user), mailbox: Mailbox = Depends(current_mailbox)):
    creds = _creds(mailbox)
    try:
        return services.update_event(creds, uid, body, user_id=user.id, mailbox_id=mailbox.id)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


@app.post("/api/events/{uid}/cancel", response_model=CancelEventResponse)
def cancel_event(uid: str, body: EventIn, user: User = Depends(current_user), mailbox: Mailbox = Depends(current_mailbox)):
    creds = _creds(mailbox)
    try:
        result = services.cancel_event(creds, uid, body, user_id=user.id, mailbox_id=mailbox.id)
        return CancelEventResponse(uid=result.uid, sent_to=result.sent_to, failed_to=result.failed_to)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


@app.post("/api/events/{uid}/cancel-occurrence")
def cancel_event_occurrence(
    uid: str,
    body: dict,
    user: User = Depends(current_user),
    mailbox: Mailbox = Depends(current_mailbox),
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
        services.cancel_occurrence(
            user_id=user.id,
            mailbox_id=mailbox.id,
            event_uid=uid,
            occurrence_start=occ,
        )
        return {"ok": True}
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


@app.post("/api/rsvps/poll", response_model=RsvpPollOut)
def post_rsvps(body: RsvpPollIn, mailbox: Mailbox = Depends(current_mailbox)):
    creds = _creds(mailbox)
    try:
        return services.poll_rsvps(creds, body)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


@app.post("/api/invites/sync")
def sync_invites_endpoint(
    body: dict | None = None,
    mailbox: Mailbox = Depends(current_mailbox),
):
    """Scan the inbox for incoming iTIP REQUEST / CANCEL .ics attachments
    and write them to the user's CalDAV calendar. Body (all optional):
    {"calendar": str, "mailbox": str = "INBOX", "only_unseen": bool = true,
     "mark_seen": bool = true}.
    """
    creds = _creds(mailbox)
    body = body or {}
    raw_since = body.get("since_days", 30)
    try:
        since_days = int(raw_since) if raw_since is not None else None
    except (TypeError, ValueError):
        since_days = 30
    try:
        return services.sync_invites(
            creds,
            body.get("calendar"),
            mailbox=body.get("mailbox") or "INBOX",
            only_unseen=bool(body.get("only_unseen", False)),
            mark_seen=bool(body.get("mark_seen", False)),
            since_days=since_days,
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


_static_dir = Path(__file__).resolve().parent.parent / "web" / "dist"
# In dev we don't have a `dist/` build but the source still has the
# about page at `web/public/about.html`. Mount a dedicated /about route
# that reads from whichever location is present, so navigating to
# /about works both in dev (Vite proxies to us) and in prod.
# Public is preferred so dev edits show up without a rebuild; in prod
# only `dist/` exists in the container (see Dockerfile) so the
# fallback path wins on its own.
_about_candidates = [
    Path(__file__).resolve().parent.parent / "web" / "public" / "about.html",
    Path(__file__).resolve().parent.parent / "web" / "dist" / "about.html",
]


def _find_about() -> Optional[Path]:
    for p in _about_candidates:
        if p.is_file():
            return p
    return None


_about_path = _find_about()
if _about_path is not None:
    @app.get("/about")
    @app.get("/about/")
    def about_page_dev():
        path = _find_about() or _about_path
        return FileResponse(path)


# Static content pages. Same dev-vs-prod resolution trick as /about above:
# in prod they live under web/dist/ after `npm run build`; in dev we read
# straight from web/public/. The reference page for on-device AI lives on
# the GitHub wiki rather than here; the blog post stays in-app because it
# carries the brand voice.
_content_pages = [
    (
        "/blog/private-by-design-ai",
        Path(__file__).resolve().parent.parent / "web" / "dist" / "blog" / "private-by-design-ai.html",
        Path(__file__).resolve().parent.parent / "web" / "public" / "blog" / "private-by-design-ai.html",
    ),
    (
        "/purelymail-calendar-feature",
        Path(__file__).resolve().parent.parent / "web" / "dist" / "purelymail-calendar-feature.html",
        Path(__file__).resolve().parent.parent / "web" / "public" / "purelymail-calendar-feature.html",
    ),
    (
        "/docs/send-meeting-invites-with-purelymail",
        Path(__file__).resolve().parent.parent / "web" / "dist" / "docs" / "send-meeting-invites-with-purelymail.html",
        Path(__file__).resolve().parent.parent / "web" / "public" / "docs" / "send-meeting-invites-with-purelymail.html",
    ),
    (
        "/docs/connect-purelymail-caldav-to-apple-calendar",
        Path(__file__).resolve().parent.parent / "web" / "dist" / "docs" / "connect-purelymail-caldav-to-apple-calendar.html",
        Path(__file__).resolve().parent.parent / "web" / "public" / "docs" / "connect-purelymail-caldav-to-apple-calendar.html",
    ),
    (
        "/docs/purelymail-caldav-rsvp-tracking",
        Path(__file__).resolve().parent.parent / "web" / "dist" / "docs" / "purelymail-caldav-rsvp-tracking.html",
        Path(__file__).resolve().parent.parent / "web" / "public" / "docs" / "purelymail-caldav-rsvp-tracking.html",
    ),
    (
        "/compare/purelymail-calendar-vs-fastmail-calendar",
        Path(__file__).resolve().parent.parent / "web" / "dist" / "compare" / "purelymail-calendar-vs-fastmail-calendar.html",
        Path(__file__).resolve().parent.parent / "web" / "public" / "compare" / "purelymail-calendar-vs-fastmail-calendar.html",
    ),
]


def _make_content_route(dist_path: Path, public_path: Path):
    def _serve():
        # Public first so dev edits show up without a rebuild; in prod
        # only `dist/` is shipped (see Dockerfile) so the fallback path
        # wins on its own.
        for p in (public_path, dist_path):
            if p.is_file():
                return FileResponse(p)
        raise HTTPException(status_code=404, detail="page not found")
    return _serve


for _route, _dist, _public in _content_pages:
    if _dist.is_file() or _public.is_file():
        handler = _make_content_route(_dist, _public)
        app.get(_route)(handler)
        app.get(_route + "/")(handler)


# The on-device-AI reference page used to live at /wiki/on-device-ai before
# it moved to the GitHub Wiki. Redirect cached or shared links there so they
# land on the canonical page instead of falling through to the SPA shell.
from fastapi.responses import RedirectResponse  # noqa: E402

_WIKI_ON_DEVICE_AI = (
    "https://github.com/bhartiyashesh/purelymailcalendar/wiki/"
    "On%E2%80%90device-AI-in-Purelymail-Calendar"
)


@app.get("/wiki/on-device-ai")
@app.get("/wiki/on-device-ai/")
def _redirect_wiki_on_device_ai():
    return RedirectResponse(_WIKI_ON_DEVICE_AI, status_code=301)


if _static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=_static_dir / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(_static_dir / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        # Normalize so /foo/ still resolves to /foo.html / dist/foo.html
        # before falling through to the SPA shell. Without this, a stray
        # trailing slash on a static URL like /about/ returns index.html
        # and looks like the page failed to load.
        candidate = full_path.rstrip("/")
        target = _static_dir / full_path
        if target.is_file():
            return FileResponse(target)
        if candidate and candidate != full_path:
            for ext in ("", ".html"):
                alt = _static_dir / (candidate + ext)
                if alt.is_file():
                    return FileResponse(alt)
        return FileResponse(_static_dir / "index.html")
