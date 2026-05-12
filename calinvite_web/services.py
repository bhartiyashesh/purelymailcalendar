"""Service layer: bridges FastAPI routes to the calinvite Python modules.

Per-user model: every function takes a `Mailbox` (the user's Purelymail
mailbox, encrypted password decrypted via `mailbox_password`) and uses
those credentials for CalDAV / SMTP / IMAP.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, TypeVar
from zoneinfo import ZoneInfo

from icalendar import Calendar as ICalendar

from calinvite import caldav_client as cdav
from calinvite import mailer
from calinvite import rsvp as rsvp_mod
from calinvite.ics import Alarm, Attendee, EventSpec, build_cancel, build_request

from .mailbox import mailbox_password
from .models import Mailbox


_T = TypeVar("_T")


def _is_transient_caldav_error(err: Exception) -> bool:
    """Return True if the exception looks like a transient upstream 5xx.

    Purelymail occasionally returns 500 on PROPFIND under load; one retry
    usually clears it.
    """
    msg = str(err)
    if "500 Internal Server Error" in msg or "502 Bad Gateway" in msg or "503 Service Unavailable" in msg or "504 Gateway Timeout" in msg:
        return True
    if "PropfindError" in err.__class__.__name__ and "500" in msg:
        return True
    return False


def _with_retry(fn: Callable[[], _T], attempts: int = 3, backoff: float = 0.4) -> _T:
    """Run a CalDAV-bound callable, retrying on transient upstream errors."""
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            if not _is_transient_caldav_error(e) or i == attempts - 1:
                raise
            time.sleep(backoff * (2**i))
    assert last is not None
    raise last
from .schemas import (
    AttendeeOut,
    CreateEventResponse,
    EventIn,
    EventOut,
    OrganizerOut,
    ReminderOut,
    RsvpPollIn,
    RsvpPollOut,
    RsvpResultOut,
)


_DT_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class MailboxCreds:
    email: str
    password: str
    display_name: str
    caldav_url: str
    smtp_host: str
    smtp_port: int
    imap_host: str
    imap_port: int


def creds_for(mb: Mailbox) -> MailboxCreds:
    return MailboxCreds(
        email=mb.email,
        password=mailbox_password(mb),
        display_name=mb.display_name,
        caldav_url=mb.caldav_url,
        smtp_host=mb.smtp_host,
        smtp_port=mb.smtp_port,
        imap_host=mb.imap_host,
        imap_port=mb.imap_port,
    )


def _strip_method(ics_bytes: bytes) -> bytes:
    """Strip METHOD before PUTting to CalDAV (RFC 4791 §4.1)."""
    cal = ICalendar.from_ical(ics_bytes)
    if cal.get("method"):
        del cal["method"]
    return cal.to_ical()


def parse_dt(s: str, tz_name: str) -> datetime:
    for f in _DT_FORMATS:
        try:
            naive = datetime.strptime(s, f)
            return naive.replace(tzinfo=ZoneInfo(tz_name))
        except ValueError:
            continue
    raise ValueError(f"Could not parse datetime: {s!r}")


def _strip_mailto(addr: str) -> str:
    s = (addr or "").strip()
    return s[7:] if s.lower().startswith("mailto:") else s


def _to_aware(dt) -> datetime:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def serialize_vevent(comp) -> EventOut:
    raw_org = comp.get("organizer")
    organizer: Optional[OrganizerOut] = None
    if raw_org is not None:
        org_email = _strip_mailto(str(raw_org))
        org_name = None
        try:
            org_name = str(raw_org.params.get("CN")) if raw_org.params.get("CN") else None
        except AttributeError:
            org_name = None
        organizer = OrganizerOut(email=org_email, name=org_name)

    raw_atts = comp.get("attendee")
    if raw_atts is None:
        atts: List = []
    elif isinstance(raw_atts, list):
        atts = raw_atts
    else:
        atts = [raw_atts]

    attendees_out: List[AttendeeOut] = []
    for a in atts:
        email = _strip_mailto(str(a))
        name = None
        partstat = "NEEDS-ACTION"
        try:
            cn = a.params.get("CN")
            if cn:
                name = str(cn)
            ps = a.params.get("PARTSTAT")
            if ps:
                partstat = str(ps).upper()
        except AttributeError:
            pass
        attendees_out.append(AttendeeOut(email=email, name=name, partstat=partstat))

    dtstart = _to_aware(comp.get("dtstart").dt) if comp.get("dtstart") else datetime.now(timezone.utc)
    dtend = _to_aware(comp.get("dtend").dt) if comp.get("dtend") else dtstart + timedelta(hours=1)
    tz = None
    try:
        tzparam = comp.get("dtstart").params.get("TZID") if comp.get("dtstart") else None
        if tzparam:
            tz = str(tzparam)
    except AttributeError:
        tz = None

    reminders_out: List[ReminderOut] = []
    try:
        for sub in comp.walk("VALARM"):
            trig = sub.get("trigger")
            mins = 15
            try:
                td = trig.dt if hasattr(trig, "dt") else trig
                if isinstance(td, timedelta):
                    mins = max(0, int(-td.total_seconds() / 60))
            except Exception:
                pass
            reminders_out.append(
                ReminderOut(
                    action=str(sub.get("action") or "DISPLAY").upper(),
                    minutes_before=mins,
                    description=str(sub.get("description") or ""),
                )
            )
    except Exception:
        pass

    return EventOut(
        uid=str(comp.get("uid") or ""),
        summary=str(comp.get("summary") or ""),
        start=dtstart,
        end=dtend,
        tz=tz,
        location=str(comp.get("location") or ""),
        description=str(comp.get("description") or ""),
        sequence=int(comp.get("sequence") or 0),
        reminders=reminders_out,
        organizer=organizer,
        attendees=attendees_out,
    )


def list_calendars(creds: MailboxCreds) -> List[str]:
    def _do() -> List[str]:
        client = cdav.connect(creds.caldav_url, creds.email, creds.password)
        return cdav.list_calendars(client)
    return _with_retry(_do)


def list_events(creds: MailboxCreds, calendar_name: Optional[str], days: int) -> List[EventOut]:
    def _do_search():
        client = cdav.connect(creds.caldav_url, creds.email, creds.password)
        calendar = cdav.get_calendar(client, calendar_name)
        start = datetime.now(timezone.utc)
        end = start + timedelta(days=days)
        return list(calendar.search(start=start, end=end, event=True, expand=False))
    search_results = _with_retry(_do_search)
    out: List[EventOut] = []
    for ev in search_results:
        try:
            cal = ICalendar.from_ical(ev.data)
        except Exception:
            continue
        for comp in cal.walk("VEVENT"):
            try:
                out.append(serialize_vevent(comp))
            except Exception:
                continue
    out.sort(key=lambda e: e.start)
    return out


def get_event(creds: MailboxCreds, calendar_name: Optional[str], uid: str) -> Optional[EventOut]:
    def _do():
        client = cdav.connect(creds.caldav_url, creds.email, creds.password)
        calendar = cdav.get_calendar(client, calendar_name)
        return cdav.find_event_by_uid(calendar, uid)
    ev = _with_retry(_do)
    if ev is None:
        return None
    try:
        cal = ICalendar.from_ical(ev.data)
    except Exception:
        return None
    for comp in cal.walk("VEVENT"):
        if str(comp.get("uid")) == uid:
            return serialize_vevent(comp)
    return None


def _spec_from_input(inp: EventIn, creds: MailboxCreds, sequence_override: Optional[int] = None) -> EventSpec:
    start = parse_dt(inp.start, inp.tz)
    if inp.end:
        end = parse_dt(inp.end, inp.tz)
    elif inp.duration_minutes:
        end = start + timedelta(minutes=int(inp.duration_minutes))
    else:
        end = start + timedelta(hours=1)

    seq = sequence_override if sequence_override is not None else (inp.sequence or 0)
    uid = inp.uid or f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}@calinvite"

    # Always include the organizer as a self-attendee so the event is
    # "scheduled" on their own calendar (Purelymail otherwise treats
    # organizer-only events oddly and they can fail to appear in listings).
    # RSVP=FALSE marks the self-row so they aren't emailed an invite to
    # themselves; PARTSTAT=ACCEPTED is the iTIP convention for the organizer.
    organizer_email = creds.email.lower().strip()
    attendees = [
        Attendee(
            email=organizer_email,
            name=creds.display_name,
            partstat="ACCEPTED",
            rsvp=False,
        )
    ]
    for a in inp.attendees:
        if a.email.lower().strip() == organizer_email:
            continue
        attendees.append(Attendee(email=a.email, name=a.name))

    alarms = [
        Alarm(
            action=r.action.upper() if r.action else "DISPLAY",
            minutes_before=int(r.minutes_before),
            description=r.description or inp.summary,
            recipients=list(r.recipients or []),
        )
        for r in (inp.reminders or [])
    ]

    return EventSpec(
        summary=inp.summary,
        start=start,
        end=end,
        organizer_email=creds.email,
        organizer_name=creds.display_name,
        attendees=attendees,
        description=inp.description or "",
        location=inp.location or "",
        uid=uid,
        alarms=alarms,
        sequence=int(seq),
        tz=inp.tz,
    )


def _default_body(spec: EventSpec, lead: str) -> str:
    lines = [
        lead,
        "",
        f"What:  {spec.summary}",
        f"When:  {spec.start.strftime('%a %b %d, %Y  %I:%M %p')} - "
              f"{spec.end.strftime('%I:%M %p')} ({spec.tz})",
    ]
    if spec.location:
        lines.append(f"Where: {spec.location}")
    if spec.description:
        lines.append("")
        lines.append(spec.description)
    lines.append("")
    lines.append(f"Organizer: {spec.organizer_name} <{spec.organizer_email}>")
    return "\n".join(lines)


def _send_invite(creds: MailboxCreds, spec: EventSpec, body: str, ics_bytes: bytes, method: str) -> List[str]:
    # Exclude the organizer themselves from the recipient list; they're listed
    # as an ATTENDEE on the event for CalDAV scheduling but shouldn't get
    # emailed an invite to their own event.
    organizer_email = creds.email.lower().strip()
    to = [a.email for a in spec.attendees if a.email.lower().strip() != organizer_email]
    if not to:
        return []
    subject_prefix = {"REQUEST": "Invitation", "CANCEL": "Cancelled"}.get(method, "Update")
    msg = mailer.build_message(
        from_email=creds.email,
        from_name=creds.display_name,
        to_addrs=to,
        subject=f"{subject_prefix}: {spec.summary}",
        body_text=body,
        ics_bytes=ics_bytes,
        method=method,
    )
    mailer.send(
        smtp_host=creds.smtp_host,
        smtp_port=creds.smtp_port,
        smtp_user=creds.email,
        smtp_pass=creds.password,
        msg=msg,
        to_addrs=to,
    )
    return to


def _schedule_email_reminders(user_id: Optional[int], uid: str, spec: EventSpec, inp: EventIn) -> None:
    if user_id is None:
        return
    try:
        from .reminders import replace_for_event
        replace_for_event(user_id, uid, spec.summary, spec.start, inp)
    except Exception as e:
        # Don't fail the request if scheduling fails; the event itself is saved.
        print(f"[reminders] schedule failed for {uid}: {e}")


def create_event(creds: MailboxCreds, inp: EventIn, user_id: Optional[int] = None) -> CreateEventResponse:
    spec = _spec_from_input(inp, creds, sequence_override=0)
    ics_bytes, uid = build_request(spec)

    def _do_put():
        client = cdav.connect(creds.caldav_url, creds.email, creds.password)
        calendar = cdav.get_calendar(client, inp.calendar)
        cdav.put_event(calendar, _strip_method(ics_bytes))
    _with_retry(_do_put)

    _schedule_email_reminders(user_id, uid, spec, inp)

    sent: List[str] = []
    if not inp.dry_run:
        body = _default_body(spec, "You're invited.")
        sent = _send_invite(creds, spec, body, ics_bytes, method="REQUEST")
    return CreateEventResponse(uid=uid, sent_to=sent, dry_run=inp.dry_run)


def update_event(creds: MailboxCreds, uid: str, inp: EventIn, user_id: Optional[int] = None) -> CreateEventResponse:
    if not uid:
        raise ValueError("uid is required for update")
    new_seq = int(inp.sequence) if inp.sequence is not None and int(inp.sequence) >= 1 else 1
    inp_with_uid = inp.model_copy(update={"uid": uid, "sequence": new_seq})
    spec = _spec_from_input(inp_with_uid, creds, sequence_override=new_seq)
    ics_bytes, uid_out = build_request(spec)

    def _do_put():
        client = cdav.connect(creds.caldav_url, creds.email, creds.password)
        calendar = cdav.get_calendar(client, inp.calendar)
        cdav.put_event(calendar, _strip_method(ics_bytes))
    _with_retry(_do_put)

    _schedule_email_reminders(user_id, uid_out, spec, inp)

    sent: List[str] = []
    if not inp.dry_run:
        body = _default_body(spec, "This invitation has been updated.")
        sent = _send_invite(creds, spec, body, ics_bytes, method="REQUEST")
    return CreateEventResponse(uid=uid_out, sent_to=sent, dry_run=inp.dry_run)


def cancel_event(creds: MailboxCreds, uid: str, inp: EventIn, user_id: Optional[int] = None) -> CreateEventResponse:
    if not uid:
        raise ValueError("uid is required for cancel")
    new_seq = int(inp.sequence) if inp.sequence is not None and int(inp.sequence) >= 1 else 1
    inp_with_uid = inp.model_copy(update={"uid": uid, "sequence": new_seq})
    spec = _spec_from_input(inp_with_uid, creds, sequence_override=new_seq)
    ics_bytes, uid_out = build_cancel(spec)

    def _do_lookup():
        client = cdav.connect(creds.caldav_url, creds.email, creds.password)
        calendar = cdav.get_calendar(client, inp.calendar)
        return cdav.find_event_by_uid(calendar, uid_out)
    ev = _with_retry(_do_lookup)
    if ev is not None:
        try:
            ev.delete()
        except Exception:
            pass

    if user_id is not None:
        try:
            from .reminders import cancel_for_event
            cancel_for_event(user_id, uid_out)
        except Exception as e:
            print(f"[reminders] cancel failed for {uid_out}: {e}")

    sent: List[str] = []
    if not inp.dry_run:
        body = _default_body(spec, "This event has been cancelled.")
        sent = _send_invite(creds, spec, body, ics_bytes, method="CANCEL")
    return CreateEventResponse(uid=uid_out, sent_to=sent, dry_run=inp.dry_run)


def poll_rsvps(creds: MailboxCreds, inp: RsvpPollIn) -> RsvpPollOut:
    def _do_caldav():
        client = cdav.connect(creds.caldav_url, creds.email, creds.password)
        return cdav.get_calendar(client, inp.calendar)
    calendar = _with_retry(_do_caldav)
    results = rsvp_mod.process_inbox(
        imap_host=creds.imap_host,
        imap_port=creds.imap_port,
        imap_user=creds.email,
        imap_pass=creds.password,
        caldav_calendar=calendar,
        mailbox=inp.mailbox,
        mark_seen=inp.mark_seen,
        only_unseen=inp.only_unseen,
        since=None,
    )
    return RsvpPollOut(
        mailbox=inp.mailbox,
        results=[
            RsvpResultOut(
                uid=r.uid,
                attendee=r.attendee,
                partstat=r.partstat,
                summary=r.summary,
                success=r.success,
                detail=r.detail,
            )
            for r in results
        ],
    )
