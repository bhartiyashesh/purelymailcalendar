"""Per-user Purelymail mailbox: connect, fetch, delete.

On connect we PROPFIND `https://purelymail.com/webdav/` with the supplied
credentials and parse the response to discover the account ID, so users
don't have to find it themselves.
"""
from __future__ import annotations

import base64
import re
import ssl
import urllib.error
import urllib.request
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from .auth import current_user
from .crypto import decrypt, encrypt
from .db import get_db
from .models import Mailbox, User


router = APIRouter(prefix="/api/me/mailbox", tags=["mailbox"])


class MailboxConnectIn(BaseModel):
    email: EmailStr
    password: str
    display_name: Optional[str] = None


class MailboxOut(BaseModel):
    email: str
    display_name: str
    account_id: str
    caldav_url: str


def _discover_account_id(email: str, password: str) -> str:
    """PROPFIND /webdav/ to find the account directory the user can access."""
    auth = base64.b64encode(f"{email}:{password}".encode()).decode()
    req = urllib.request.Request("https://purelymail.com/webdav/", method="PROPFIND")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Depth", "1")
    req.add_header("Content-Type", "application/xml")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            text = r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise HTTPException(status_code=400, detail="Purelymail rejected those credentials")
        raise HTTPException(status_code=502, detail=f"Purelymail error: HTTP {e.code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"could not reach Purelymail: {e}")

    hrefs = re.findall(r"<href>([^<]+)</href>", text)
    for h in hrefs:
        m = re.search(r"/webdav/(\d+)/", h)
        if m:
            return m.group(1)
    raise HTTPException(status_code=400, detail="Could not discover Purelymail account ID. The credentials may be wrong or the account has no WebDAV space.")


def _to_out(mb: Mailbox) -> MailboxOut:
    return MailboxOut(
        email=mb.email,
        display_name=mb.display_name,
        account_id=mb.account_id,
        caldav_url=mb.caldav_url,
    )


@router.get("", response_model=Optional[MailboxOut])
def get_mailbox(user: User = Depends(current_user)):
    if user.mailbox is None:
        return None
    return _to_out(user.mailbox)


@router.post("", response_model=MailboxOut)
def connect_mailbox(
    body: MailboxConnectIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    email = body.email.lower().strip()
    password = body.password
    if not password:
        raise HTTPException(status_code=400, detail="password is required")

    account_id = _discover_account_id(email, password)
    display = (body.display_name or "").strip() or email.split("@")[0]

    if user.mailbox is None:
        mb = Mailbox(
            user_id=user.id,
            email=email,
            display_name=display,
            account_id=account_id,
            encrypted_password=encrypt(password),
        )
        db.add(mb)
    else:
        mb = user.mailbox
        mb.email = email
        mb.display_name = display
        mb.account_id = account_id
        mb.encrypted_password = encrypt(password)
    if user.display_name is None:
        user.display_name = display
    db.commit()
    db.refresh(mb)
    return _to_out(mb)


@router.delete("")
def delete_mailbox(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.mailbox is None:
        return {"ok": True}
    db.delete(user.mailbox)
    db.commit()
    return {"ok": True}


def mailbox_password(mb: Mailbox) -> str:
    """Decrypt a stored mailbox password (used by services)."""
    return decrypt(mb.encrypted_password)
