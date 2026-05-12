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
from calinvite import inbound_invites as invites_mod
from calinvite import mailer
from calinvite import rsvp as rsvp_mod
from calinvite.ics import Alarm, Attendee, EventSpec, Recurrence, build_cancel, build_request

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
    RecurrenceOut,
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


def _rrule_to_recurrence_out(rrule_val) -> Optional["RecurrenceOut"]:
    """Convert an icalendar vRecur into our RecurrenceOut, with a friendly text."""
    if rrule_val is None:
        return None
    try:
        # vRecur is a dict-like; each value is a list.
        def first(key):
            v = rrule_val.get(key)
            if v is None:
                return None
            return v[0] if isinstance(v, list) else v

        freq = str(first("FREQ") or "").upper()
        if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
            return None
        interval = int(first("INTERVAL") or 1)
        until_val = first("UNTIL")
        count_val = first("COUNT")
        from_date = None
        if isinstance(until_val, datetime):
            from_date = until_val.date()
        elif hasattr(until_val, "year"):  # date
            from_date = until_val
        count_int = int(count_val) if count_val is not None else None

        bits = {
            "DAILY": "Daily",
            "WEEKLY": "Weekly",
            "MONTHLY": "Monthly",
            "YEARLY": "Yearly",
        }
        text = bits[freq]
        if interval > 1:
            text = f"Every {interval} " + {"DAILY": "days", "WEEKLY": "weeks", "MONTHLY": "months", "YEARLY": "years"}[freq]
        if from_date is not None:
            text += f", ends {from_date.strftime('%b %-d, %Y')}"
        elif count_int is not None:
            text += f", {count_int} times"

        return RecurrenceOut(
            freq=freq,  # type: ignore[arg-type]
            interval=interval,
            until=from_date,
            count=count_int,
            text=text,
        )
    except Exception:
        return None


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

    uid = str(comp.get("uid") or "")
    recurrence_out = _rrule_to_recurrence_out(comp.get("rrule"))

    return EventOut(
        uid=uid,
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
        recurrence=recurrence_out,
        master_uid=uid,
        occurrence_id=uid,
    )


def list_calendars(creds: MailboxCreds) -> List[str]:
    def _do() -> List[str]:
        client = cdav.connect(creds.caldav_url, creds.email, creds.password)
        return cdav.list_calendars(client)
    return _with_retry(_do)


def list_events(
    creds: MailboxCreds,
    calendar_name: Optional[str],
    days: int,
    start_override: Optional[datetime] = None,
    end_override: Optional[datetime] = None,
) -> List[EventOut]:
    if start_override is not None and end_override is not None:
        window_start, window_end = start_override, end_override
    else:
        window_start = datetime.now(timezone.utc)
        window_end = window_start + timedelta(days=days)

    def _do_search():
        client = cdav.connect(creds.caldav_url, creds.email, creds.password)
        calendar = cdav.get_calendar(client, calendar_name)
        return list(
            calendar.search(
                start=window_start, end=window_end, event=True, expand=False
            )
        )

    search_results = _with_retry(_do_search)
    out: List[EventOut] = []
    for ev in search_results:
        try:
            cal = ICalendar.from_ical(ev.data)
        except Exception:
            continue
        for comp in cal.walk("VEVENT"):
            try:
                base = serialize_vevent(comp)
            except Exception:
                continue
            if comp.get("rrule") is None:
                out.append(base)
                continue
            # Recurring master: expand into individual occurrences inside the
            # visible window using the recurring-ical-events lib (already a
            # dependency). Each occurrence becomes its own EventOut with a
            # synthetic occurrence_id so the frontend can address it.
            try:
                import recurring_ical_events as rie

                expanded = rie.of(cal).between(window_start, window_end)
            except Exception:
                # If expansion fails, surface the master once so it isn't lost.
                out.append(base)
                continue
            for inst in expanded:
                inst_start = _to_aware(inst.get("dtstart").dt) if inst.get("dtstart") else base.start
                inst_end = _to_aware(inst.get("dtend").dt) if inst.get("dtend") else base.end
                out.append(
                    base.model_copy(
                        update={
                            "start": inst_start,
                            "end": inst_end,
                            "occurrence_id": f"{base.master_uid}#{inst_start.isoformat()}",
                        }
                    )
                )
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

    recurrence = None
    if inp.recurrence is not None:
        recurrence = Recurrence(
            freq=inp.recurrence.freq,
            interval=int(inp.recurrence.interval or 1),
            until=inp.recurrence.until,
            count=inp.recurrence.count,
        )

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
        recurrence=recurrence,
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


def cancel_occurrence(user_id: int, event_uid: str, occurrence_start: datetime) -> None:
    """Cancel a single occurrence of a recurring event.

    Steps:
      1. Look up the user and mailbox creds.
      2. Fetch the master VEVENT from CalDAV (across all calendars).
      3. Add an EXDATE for `occurrence_start`, bump SEQUENCE, PUT back.
      4. Build a per-occurrence iTIP CANCEL (same UID, RECURRENCE-ID, METHOD:CANCEL).
      5. Email the cancel notice to attendees.
      6. Delete the matching ScheduledReminder row (caller stamps declined_at).
    """
    from .db import SessionLocal as _SL
    from .models import User as _User
    from .reminders import cancel_for_occurrence

    with _SL() as db:
        user = db.query(_User).filter(_User.id == user_id).one_or_none()
        if user is None or user.mailbox is None:
            raise RuntimeError("user or mailbox missing")
        mb = user.mailbox
        creds = creds_for(mb)

    def _find():
        client = cdav.connect(creds.caldav_url, creds.email, creds.password)
        # We don't know which calendar holds the event — try them all.
        for cname in cdav.list_calendars(client):
            cal_obj = cdav.get_calendar(client, cname)
            found = cdav.find_event_by_uid(cal_obj, event_uid)
            if found is not None:
                return cal_obj, found
        return None, None

    cal_obj, ev = _with_retry(_find)
    if ev is None:
        raise RuntimeError(f"event {event_uid} not found on any calendar")

    # Parse master, add EXDATE, bump SEQUENCE, strip METHOD, PUT back.
    master_cal = ICalendar.from_ical(ev.data)
    master_vevent = None
    for comp in master_cal.walk("VEVENT"):
        if str(comp.get("uid")) == event_uid:
            master_vevent = comp
            break
    if master_vevent is None:
        raise RuntimeError("master VEVENT not found in event payload")

    # Make occurrence_start timezone-aware (use the master's DTSTART tz if possible)
    occ = occurrence_start
    if occ.tzinfo is None:
        try:
            tzparam = master_vevent.get("dtstart").params.get("TZID")
            if tzparam:
                occ = occ.replace(tzinfo=ZoneInfo(str(tzparam)))
            else:
                occ = occ.replace(tzinfo=timezone.utc)
        except Exception:
            occ = occ.replace(tzinfo=timezone.utc)

    master_vevent.add("exdate", occ)
    current_seq = int(master_vevent.get("sequence") or 0)
    if "sequence" in master_vevent:
        del master_vevent["sequence"]
    master_vevent.add("sequence", current_seq + 1)

    def _put_master():
        cdav.put_event(cal_obj, _strip_method(master_cal.to_ical()))
    _with_retry(_put_master)

    # Build per-occurrence CANCEL (RECURRENCE-ID = the cancelled instance).
    organizer = master_vevent.get("organizer")
    organizer_email = _strip_mailto(str(organizer)) if organizer is not None else creds.email
    organizer_name = creds.display_name
    try:
        if organizer is not None and organizer.params.get("CN"):
            organizer_name = str(organizer.params.get("CN"))
    except AttributeError:
        pass

    attendees_for_cancel: List[Attendee] = []
    raw_atts = master_vevent.get("attendee")
    if raw_atts is None:
        atts: List = []
    elif isinstance(raw_atts, list):
        atts = raw_atts
    else:
        atts = [raw_atts]
    for a in atts:
        email = _strip_mailto(str(a))
        if email.lower() == organizer_email.lower():
            continue
        name = None
        try:
            cn = a.params.get("CN")
            if cn:
                name = str(cn)
        except AttributeError:
            pass
        attendees_for_cancel.append(Attendee(email=email, name=name))

    summary = str(master_vevent.get("summary") or "")
    dtend_master = master_vevent.get("dtend")
    duration = timedelta(hours=1)
    if dtend_master is not None and master_vevent.get("dtstart") is not None:
        try:
            duration = _to_aware(dtend_master.dt) - _to_aware(master_vevent.get("dtstart").dt)
        except Exception:
            duration = timedelta(hours=1)
    occ_end = occ + duration
    tz_name = "UTC"
    try:
        tzparam = master_vevent.get("dtstart").params.get("TZID")
        if tzparam:
            tz_name = str(tzparam)
    except AttributeError:
        pass

    # Build a one-shot CANCEL ICS manually so we can include RECURRENCE-ID.
    cancel_cal = ICalendar()
    cancel_cal.add("prodid", "-//calinvite//pulseproof.app//EN")
    cancel_cal.add("version", "2.0")
    cancel_cal.add("calscale", "GREGORIAN")
    cancel_cal.add("method", "CANCEL")
    from icalendar import Event as _IEvent, vCalAddress, vText
    inst = _IEvent()
    inst.add("uid", event_uid)
    inst.add("dtstamp", datetime.utcnow())
    inst.add("dtstart", occ)
    inst.add("dtend", occ_end)
    inst.add("summary", summary)
    inst.add("sequence", current_seq + 1)
    inst.add("status", "CANCELLED")
    inst.add("recurrence-id", occ)
    org_addr = vCalAddress(f"mailto:{organizer_email}")
    org_addr.params["CN"] = vText(organizer_name)
    inst["organizer"] = org_addr
    for a in attendees_for_cancel:
        addr = vCalAddress(f"mailto:{a.email}")
        if a.name:
            addr.params["CN"] = vText(a.name)
        addr.params["ROLE"] = vText("REQ-PARTICIPANT")
        addr.params["PARTSTAT"] = vText("NEEDS-ACTION")
        addr.params["RSVP"] = vText("FALSE")
        addr.params["CUTYPE"] = vText("INDIVIDUAL")
        inst.add("attendee", addr, encode=0)
    cancel_cal.add_component(inst)
    ics_bytes = cancel_cal.to_ical()

    # Build a spec just for the email path.
    fake_spec = EventSpec(
        summary=summary,
        start=occ,
        end=occ_end,
        organizer_email=organizer_email,
        organizer_name=organizer_name,
        attendees=attendees_for_cancel,
        sequence=current_seq + 1,
        tz=tz_name,
        uid=event_uid,
    )
    body = _default_body(fake_spec, "This occurrence has been cancelled.")
    try:
        _send_invite(creds, fake_spec, body, ics_bytes, method="CANCEL")
    except Exception as e:
        # Email failure shouldn't roll back the EXDATE that's already persisted.
        print(f"[cancel_occurrence] email failed for {event_uid} @ {occ}: {e}")

    try:
        cancel_for_occurrence(user_id, event_uid, occ)
    except Exception as e:
        print(f"[cancel_occurrence] reminder delete failed: {e}")


def sync_invites(
    creds: MailboxCreds,
    calendar_name: Optional[str],
    *,
    mailbox: str = "INBOX",
    only_unseen: bool = False,
    mark_seen: bool = False,
    since_days: Optional[int] = 30,
) -> dict:
    """Pull METHOD:REQUEST / METHOD:CANCEL .ics attachments from IMAP and
    apply them to the user's CalDAV calendar.

    Defaults scan the last 30 days regardless of read state — UID + SEQUENCE
    dedup handles repeats, so re-running is a no-op for already-imported
    events. only_unseen=True is still available for callers that want it.
    """

    def _do_caldav():
        client = cdav.connect(creds.caldav_url, creds.email, creds.password)
        return cdav.get_calendar(client, calendar_name)

    calendar = _with_retry(_do_caldav)
    results = invites_mod.sync_inbox_invites(
        imap_host=creds.imap_host,
        imap_port=creds.imap_port,
        imap_user=creds.email,
        imap_pass=creds.password,
        caldav_calendar=calendar,
        mailbox=mailbox,
        only_unseen=only_unseen,
        mark_seen=mark_seen,
        since_days=since_days,
    )
    counts = {"created": 0, "updated": 0, "cancelled": 0, "skipped": 0, "error": 0}
    items = []
    for r in results:
        counts[r.action] = counts.get(r.action, 0) + 1
        items.append({
            "uid": r.uid,
            "summary": r.summary,
            "action": r.action,
            "success": r.success,
            "detail": r.detail,
        })
    return {"mailbox": mailbox, "counts": counts, "results": items}


def _pick_target_calendar(client, preferred: Optional[str]) -> Optional[str]:
    """Pick which calendar to PUT new invites onto for a user. If they have
    a saved preference (mailbox.selected_calendar) and it still exists, use
    it. Otherwise pick the calendar with the most events (heuristic that
    avoids dumping into an empty `Default` calendar)."""
    names = cdav.list_calendars(client)
    if not names:
        return None
    if preferred and preferred in names:
        return preferred
    # Heuristic: most events wins. Cheap PROPFIND-equivalent via the lib.
    best_name = names[0]
    best_count = -1
    for n in names:
        try:
            cal = cdav.get_calendar(client, n)
            count = len(list(cal.events()))
            if count > best_count:
                best_count = count
                best_name = n
        except Exception:
            continue
    return best_name


def auto_sync_all_users_invites() -> dict:
    """Run invite sync for every user with a configured mailbox. Used by the
    5-min Railway cron alongside the reminder tick so new invites land on
    the calendar without any user action."""
    from .db import SessionLocal as _SL
    from .models import Mailbox as _Mailbox, User as _User

    aggregate = {
        "users_synced": 0,
        "users_failed": 0,
        "totals": {"created": 0, "updated": 0, "cancelled": 0, "skipped": 0, "error": 0},
    }
    with _SL() as db:
        # Snapshot what we need into plain dicts so we don't hit the DB while
        # iterating (IMAP/CalDAV calls below take seconds).
        snapshot = []
        rows = (
            db.query(_Mailbox)
            .all()
        )
        for mb in rows:
            snapshot.append({
                "user_id": mb.user_id,
                "mailbox": mb,
            })
            # Force-load lazy fields by touching them.
            _ = (mb.email, mb.smtp_host, mb.imap_host, mb.account_id, mb.encrypted_password)

    for s in snapshot:
        mb = s["mailbox"]
        try:
            creds = creds_for(mb)
            def _pick():
                client = cdav.connect(creds.caldav_url, creds.email, creds.password)
                return _pick_target_calendar(client, getattr(mb, "selected_calendar", None))
            target = _with_retry(_pick)
            out = sync_invites(
                creds,
                target,
                only_unseen=False,
                mark_seen=False,
                since_days=30,
            )
            for k in aggregate["totals"]:
                aggregate["totals"][k] += out["counts"].get(k, 0)
            aggregate["users_synced"] += 1
        except Exception as e:
            aggregate["users_failed"] += 1
            print(f"[auto_sync_invites] user {s['user_id']} failed: {e}")
    return aggregate


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
