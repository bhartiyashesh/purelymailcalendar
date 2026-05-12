"""Poll IMAP for METHOD:REQUEST / METHOD:CANCEL iTIP messages and write the
events to the user's CalDAV calendar.

Strategy:
1. Connect over IMAPS, scan INBOX for messages with text/calendar parts.
2. Parse each candidate; keep METHOD:REQUEST and METHOD:CANCEL.
3. For each VEVENT in the message:
   - REQUEST + UID not on CalDAV → PUT (create).
   - REQUEST + UID on CalDAV with older SEQUENCE → PUT (update).
   - REQUEST + UID on CalDAV with same/higher SEQUENCE → skip.
   - CANCEL + UID on CalDAV → delete.
4. METHOD:REQUEST .ics from public mail clients carries METHOD; Purelymail
   rejects PUTs that include METHOD, so we strip it before writing.
5. Mark each processed email \\Seen so we don't reprocess it.
"""
from __future__ import annotations

import email
import imaplib
import ssl
from dataclasses import dataclass
from typing import Iterator, List, Optional

from icalendar import Calendar as ICalendar

from .caldav_client import find_event_by_uid, put_event


@dataclass
class InviteResult:
    uid: str
    summary: str
    action: str          # "created" | "updated" | "cancelled" | "skipped" | "error"
    success: bool
    detail: str = ""


def _imap_connect(host: str, port: int, user: str, password: str) -> imaplib.IMAP4_SSL:
    ctx = ssl.create_default_context()
    m = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    m.login(user, password)
    return m


def _iter_calendar_parts(msg: email.message.Message) -> Iterator[bytes]:
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype in ("text/calendar", "application/ics", "application/octet-stream"):
            payload = part.get_payload(decode=True)
            if payload and b"BEGIN:VCALENDAR" in payload:
                yield payload


def _strip_method(cal: ICalendar) -> bytes:
    if cal.get("method"):
        del cal["method"]
    return cal.to_ical()


def _seq(comp) -> int:
    try:
        return int(comp.get("sequence") or 0)
    except (TypeError, ValueError):
        return 0


def sync_inbox_invites(
    *,
    imap_host: str,
    imap_port: int,
    imap_user: str,
    imap_pass: str,
    caldav_calendar,
    mailbox: str = "INBOX",
    only_unseen: bool = True,
    mark_seen: bool = True,
    limit: int = 200,
) -> List[InviteResult]:
    results: List[InviteResult] = []
    m = _imap_connect(imap_host, imap_port, imap_user, imap_pass)
    try:
        typ, _ = m.select(mailbox)
        if typ != "OK":
            raise RuntimeError(f"cannot select mailbox '{mailbox}'")
        criteria = "UNSEEN" if only_unseen else "ALL"
        typ, data = m.search(None, criteria)
        if typ != "OK":
            return results
        ids = data[0].split()[:limit]
        for num in ids:
            typ, msg_data = m.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            handled_any = False
            for ics_bytes in _iter_calendar_parts(msg):
                try:
                    cal = ICalendar.from_ical(ics_bytes)
                except Exception:
                    continue
                method = str(cal.get("method") or "").upper()
                if method not in ("REQUEST", "CANCEL"):
                    continue
                handled_any = True
                for vevent in cal.walk("VEVENT"):
                    uid = str(vevent.get("uid") or "")
                    summary = str(vevent.get("summary") or "")
                    if not uid:
                        continue
                    try:
                        existing = find_event_by_uid(caldav_calendar, uid)
                    except Exception as e:
                        results.append(InviteResult(uid, summary, "error", False, f"lookup failed: {e}"))
                        continue

                    if method == "CANCEL":
                        if existing is None:
                            results.append(InviteResult(uid, summary, "skipped", True, "cancel for unknown UID"))
                            continue
                        try:
                            existing.delete()
                            results.append(InviteResult(uid, summary, "cancelled", True))
                        except Exception as e:
                            results.append(InviteResult(uid, summary, "error", False, f"delete failed: {e}"))
                        continue

                    # method == "REQUEST"
                    new_seq = _seq(vevent)
                    if existing is not None:
                        try:
                            existing_cal = ICalendar.from_ical(existing.data)
                            existing_seq = 0
                            for c in existing_cal.walk("VEVENT"):
                                if str(c.get("uid")) == uid:
                                    existing_seq = _seq(c)
                                    break
                            if new_seq <= existing_seq:
                                results.append(InviteResult(uid, summary, "skipped", True, "already current"))
                                continue
                        except Exception:
                            pass  # Best-effort; fall through to overwrite.

                    # Build a single-VEVENT VCALENDAR to PUT. Strip METHOD per
                    # RFC 4791 §4.1 (Purelymail enforces this).
                    one = ICalendar()
                    one.add("prodid", "-//calinvite-inbound//pulseproof.app//EN")
                    one.add("version", "2.0")
                    one.add("calscale", "GREGORIAN")
                    # Copy VTIMEZONE components if any (improves client compat).
                    for tz in cal.walk("VTIMEZONE"):
                        one.add_component(tz)
                    one.add_component(vevent)
                    payload = _strip_method(one)
                    try:
                        put_event(caldav_calendar, payload)
                        action = "updated" if existing is not None else "created"
                        results.append(InviteResult(uid, summary, action, True))
                    except Exception as e:
                        results.append(InviteResult(uid, summary, "error", False, f"put failed: {e}"))
            if mark_seen and handled_any:
                try:
                    m.store(num, "+FLAGS", "\\Seen")
                except Exception:
                    pass
    finally:
        try:
            m.close()
        except Exception:
            pass
        m.logout()
    return results
