"""Magic-link authentication.

Flow:
1. POST /api/auth/request-link { email }
   - create MagicToken with sha256(token) stored, expire in 15min
   - email the user a link: BASE_URL/auth/verify?token=<raw>
2. GET /api/auth/verify?token=<raw>
   - look up by sha256, validate not expired/used
   - mark used, get-or-create User, create UserSession, set HttpOnly cookie
3. POST /api/auth/logout
   - revoke the session
4. GET /api/me
   - returns the current user + mailbox (if connected)
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from . import mailer_transactional
from .db import SessionLocal, get_db
from .models import MagicToken, User, UserSession


SESSION_COOKIE_NAME = "calinvite_session"
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "30"))
TOKEN_TTL_MINUTES = int(os.getenv("MAGIC_LINK_TTL_MIN", "15"))
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5173")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    # Naive UTC so it compares cleanly against values round-tripped through SQLite,
    # which strips tzinfo on read regardless of DateTime(timezone=True).
    return datetime.utcnow()


class RequestLinkIn(BaseModel):
    email: EmailStr


class RequestLinkOut(BaseModel):
    ok: bool = True


class MeOut(BaseModel):
    id: int
    email: str
    display_name: Optional[str] = None
    has_mailbox: bool


@router.post("/request-link", response_model=RequestLinkOut)
def request_link(body: RequestLinkIn, db: Session = Depends(get_db)):
    email = body.email.lower().strip()
    raw = secrets.token_urlsafe(32)
    token = MagicToken(
        token_hash=_hash(raw),
        email=email,
        expires_at=_utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES),
    )
    db.add(token)
    db.commit()

    link = f"{BASE_URL.rstrip('/')}/auth/verify?token={raw}"
    try:
        mailer_transactional.send_magic_link(email, link, ttl_minutes=TOKEN_TTL_MINUTES)
    except Exception as e:
        # In dev, surface the error but also log the link so the user can still proceed.
        print(f"[auth] failed to send magic link to {email}: {e}")
        print(f"[auth] DEV LINK (use this if no email arrives): {link}")
    return RequestLinkOut()


@router.get("/verify")
def verify(token: str, response: Response, db: Session = Depends(get_db)):
    if not token:
        raise HTTPException(status_code=400, detail="missing token")
    record = (
        db.query(MagicToken)
        .filter(MagicToken.token_hash == _hash(token))
        .one_or_none()
    )
    if record is None:
        raise HTTPException(status_code=400, detail="invalid or expired link")
    if record.used_at is not None:
        raise HTTPException(status_code=400, detail="this link was already used")
    if record.expires_at < _utcnow():
        raise HTTPException(status_code=400, detail="link has expired")

    user = db.query(User).filter(User.email == record.email).one_or_none()
    if user is None:
        user = User(email=record.email)
        db.add(user)
        db.flush()
    user.last_login_at = _utcnow()
    record.used_at = _utcnow()

    session_id = secrets.token_urlsafe(32)
    session = UserSession(
        id=session_id,
        user_id=user.id,
        expires_at=_utcnow() + timedelta(days=SESSION_TTL_DAYS),
    )
    db.add(session)
    db.commit()

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )
    return {"ok": True, "email": user.email}


@router.post("/logout")
def logout(
    response: Response,
    session_cookie: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    if session_cookie:
        db.query(UserSession).filter(UserSession.id == session_cookie).update({"revoked": True})
        db.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


def current_user(
    request: Request,
    session_cookie: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    if not session_cookie:
        raise HTTPException(status_code=401, detail="not authenticated")
    session = (
        db.query(UserSession)
        .filter(UserSession.id == session_cookie, UserSession.revoked.is_(False))
        .one_or_none()
    )
    if session is None or session.expires_at < _utcnow():
        raise HTTPException(status_code=401, detail="session expired")
    user = db.query(User).filter(User.id == session.user_id).one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")
    request.state.user = user
    return user


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)):
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        has_mailbox=user.mailbox is not None,
    )
