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


app.include_router(auth_router)
app.include_router(mailbox_router)


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
    user: User = Depends(current_user),
):
    creds = _creds(user)
    try:
        return services.list_events(creds, calendar, days)
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
        return services.create_event(creds, body)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


@app.put("/api/events/{uid}", response_model=CreateEventResponse)
def put_event(uid: str, body: EventIn, user: User = Depends(current_user)):
    creds = _creds(user)
    try:
        return services.update_event(creds, uid, body)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")


@app.post("/api/events/{uid}/cancel", response_model=CancelEventResponse)
def cancel_event(uid: str, body: EventIn, user: User = Depends(current_user)):
    creds = _creds(user)
    try:
        result = services.cancel_event(creds, uid, body)
        return CancelEventResponse(uid=result.uid, sent_to=result.sent_to)
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


_static_dir = Path(__file__).resolve().parent.parent / "web" / "dist"
if _static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=_static_dir / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(_static_dir / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        target = _static_dir / full_path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(_static_dir / "index.html")
