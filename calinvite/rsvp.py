"""Poll IMAP for METHOD:REPLY iTIP messages and apply RSVPs back to CalDAV events.

Strategy:
1. Connect over IMAPS, search INBOX for messages with text/calendar parts.
2. Parse each candidate; keep only METHOD:REPLY.
3. For each VEVENT in the reply, look up the matching event by UID on CalDAV.
4. Locate the matching ATTENDEE in the original event by mailto address and
   update PARTSTAT (and optionally DELEGATED-TO) to match the reply.
5. Bump SEQUENCE? No — replies don't bump SEQUENCE; only organizer changes do.
6. PUT the updated event back. Mark the email \\Seen and (optionally) move to a
   processed mailbox.
"""
from __future__ import annotations

import email
import imaplib
import ssl
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, List, Optional, Tuple

from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent

from .caldav_client import find_event_by_uid


@dataclass
class RsvpResult:
    uid: str
    attendee: str
    partstat: str
    summary: str
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
            if not payload:
                continue
            # Heuristic: must contain BEGIN:VCALENDAR
            if b"BEGIN:VCALENDAR" in payload:
                yield payload


def _parse_reply(ics_bytes: bytes) -> Optional[ICalendar]:
    try:
        cal = ICalendar.from_ical(ics_bytes)
    except Exception:
        return None
    method = str(cal.get("method") or "").upper()
    if method != "REPLY":
        return None
    return cal


def _apply_reply(server_event_data: str, reply_cal: ICalendar) -> Tuple[Optional[str], List[Tuple[str, str]]]:
    """
    Merge a REPLY into the server's stored VEVENT. Returns (new_ics_or_None, applied_changes).

    applied_changes is a list of (attendee_email, new_partstat).
    """
    server_cal = ICalendar.from_ical(server_event_data)

    # Index server VEVENTs by UID
    server_vevents = {str(c.get("uid")): c for c in server_cal.walk("VEVENT")}
    if not server_vevents:
        return None, []

    changes: List[Tuple[str, str]] = []
    changed = False

    for reply_event in reply_cal.walk("VEVENT"):
        uid = str(reply_event.get("uid") or "")
        target = server_vevents.get(uid)
        if target is None:
            continue
        # Reply should contain a single ATTENDEE: the responder
        reply_attendees = reply_event.get("attendee")
        if reply_attendees is None:
            continue
        if not isinstance(reply_attendees, list):
            reply_attendees = [reply_attendees]

        for ra in reply_attendees:
            ra_addr = _normalize_mailto(str(ra))
            ra_partstat = (ra.params.get("PARTSTAT") or "NEEDS-ACTION").upper()

            # Find matching ATTENDEE in target
            target_attendees = target.get("attendee")
            if target_attendees is None:
                continue
            if not isinstance(target_attendees, list):
                target_attendees = [target_attendees]

            for ta in target_attendees:
                ta_addr = _normalize_mailto(str(ta))
                if ta_addr.lower() == ra_addr.lower():
                    current = (ta.params.get("PARTSTAT") or "").upper()
                    if current != ra_partstat:
                        ta.params["PARTSTAT"] = ra_partstat
                        ta.params["RSVP"] = "FALSE"
                        changes.append((ra_addr, ra_partstat))
                        changed = True

    if not changed:
        return None, []
    return server_cal.to_ical().decode("utf-8"), changes


def _normalize_mailto(addr: str) -> str:
    s = addr.strip()
    if s.lower().startswith("mailto:"):
        s = s[7:]
    return s


def process_inbox(
    *,
    imap_host: str,
    imap_port: int,
    imap_user: str,
    imap_pass: str,
    caldav_calendar,
    mailbox: str = "INBOX",
    mark_seen: bool = True,
    only_unseen: bool = True,
    since: Optional[datetime] = None,
) -> List[RsvpResult]:
    results: List[RsvpResult] = []
    m = _imap_connect(imap_host, imap_port, imap_user, imap_pass)
    try:
        typ, _ = m.select(mailbox)
        if typ != "OK":
            # Try to create + select if the Sieve folder doesn't exist yet
            m.create(mailbox)
            typ, _ = m.select(mailbox)
            if typ != "OK":
                raise RuntimeError(f"cannot select mailbox '{mailbox}'")
        criteria_parts = []
        if only_unseen:
            criteria_parts.append("UNSEEN")
        if since is not None:
            criteria_parts.append(f'SINCE {since.strftime("%d-%b-%Y")}')
        criteria = " ".join(criteria_parts) or "ALL"
        typ, data = m.search(None, criteria)
        if typ != "OK":
            return results
        ids = data[0].split()
        for num in ids:
            typ, msg_data = m.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            handled_any = False
            for ics_bytes in _iter_calendar_parts(msg):
                reply = _parse_reply(ics_bytes)
                if reply is None:
                    continue
                handled_any = True
                for vevent in reply.walk("VEVENT"):
                    uid = str(vevent.get("uid") or "")
                    summary = str(vevent.get("summary") or "")
                    if not uid:
                        continue
                    server_ev = find_event_by_uid(caldav_calendar, uid)
                    if server_ev is None:
                        results.append(RsvpResult(uid, "?", "?", summary, False, "event not found on server"))
                        continue
                    new_ics, changes = _apply_reply(server_ev.data, reply)
                    if not changes:
                        results.append(RsvpResult(uid, "?", "?", summary, False, "no changes / already applied"))
                        continue
                    try:
                        server_ev.data = new_ics
                        server_ev.save()
                        for addr, partstat in changes:
                            results.append(RsvpResult(uid, addr, partstat, summary, True))
                    except Exception as e:
                        results.append(RsvpResult(uid, "?", "?", summary, False, f"save failed: {e}"))
            if mark_seen and handled_any:
                m.store(num, "+FLAGS", "\\Seen")
    finally:
        try:
            m.close()
        except Exception:
            pass
        m.logout()
    return results
