"""Build iCalendar VEVENTs with proper iTIP semantics (REQUEST / CANCEL)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from icalendar import Alarm as ICalAlarm, Calendar, Event, Timezone, TimezoneStandard, TimezoneDaylight, vCalAddress, vText, vRecur


@dataclass
class Attendee:
    email: str
    name: str | None = None
    role: str = "REQ-PARTICIPANT"
    partstat: str = "NEEDS-ACTION"
    rsvp: bool = True


@dataclass
class Alarm:
    """A VALARM nested inside the VEVENT.

    action: DISPLAY (popup in client) or EMAIL (sent by a scheduler).
    minutes_before: positive offset; we emit `-PTNm` as TRIGGER.
    description: alarm body text. For DISPLAY this is the popup text;
                 for EMAIL this becomes the email body.
    recipients: empty for DISPLAY; list of email addresses for EMAIL.
    """
    action: str = "DISPLAY"
    minutes_before: int = 15
    description: str = ""
    recipients: List[str] = field(default_factory=list)


@dataclass
class Recurrence:
    """Simple RRULE-shaped recurrence. `until` and `count` are mutually
    exclusive; `until` is treated as end-of-day in the event's timezone."""
    freq: str  # DAILY | WEEKLY | MONTHLY | YEARLY
    interval: int = 1
    until: Optional[date] = None
    count: Optional[int] = None


@dataclass
class EventSpec:
    summary: str
    start: datetime
    end: datetime
    organizer_email: str
    organizer_name: str
    attendees: List[Attendee]
    description: str = ""
    location: str = ""
    uid: str = field(default_factory=lambda: f"{uuid.uuid4()}@calinvite")
    sequence: int = 0
    tz: str = "America/Chicago"
    prodid: str = "-//calinvite//pulseproof.app//EN"
    alarms: List[Alarm] = field(default_factory=list)
    recurrence: Optional[Recurrence] = None
    # EXDATEs (cancelled occurrences) — preserved when re-PUTting an existing
    # series so previously cancelled instances stay cancelled.
    exdates: List[datetime] = field(default_factory=list)


def _vtimezone(tz_name: str) -> Timezone:
    """Minimal VTIMEZONE component for the given zone."""
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    # Use the current UTC offset; for production, you'd compute STANDARD/DAYLIGHT
    # transitions from the IANA db. Most clients accept this minimal form because
    # they resolve the TZID against their own zoneinfo when present.
    vtz = Timezone()
    vtz.add("tzid", tz_name)

    std = TimezoneStandard()
    std.add("dtstart", datetime(1970, 1, 1, 2, 0))
    std.add("tzname", tz.tzname(now) or tz_name)
    std.add("tzoffsetfrom", now.utcoffset() or timedelta(0))
    std.add("tzoffsetto", now.utcoffset() or timedelta(0))
    vtz.add_component(std)
    return vtz


def _build_calendar(method: str, prodid: str) -> Calendar:
    cal = Calendar()
    cal.add("prodid", prodid)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", method)
    return cal


def _add_attendees(event: Event, attendees: Iterable[Attendee]) -> None:
    for a in attendees:
        addr = vCalAddress(f"mailto:{a.email}")
        if a.name:
            addr.params["CN"] = vText(a.name)
        addr.params["ROLE"] = vText(a.role)
        addr.params["PARTSTAT"] = vText(a.partstat)
        addr.params["RSVP"] = vText("TRUE" if a.rsvp else "FALSE")
        addr.params["CUTYPE"] = vText("INDIVIDUAL")
        event.add("attendee", addr, encode=0)


def _make_event(spec: EventSpec, status: str = "CONFIRMED") -> Tuple[Calendar, Event]:
    cal = _build_calendar("REQUEST", spec.prodid)
    cal.add_component(_vtimezone(spec.tz))

    ev = Event()
    ev.add("uid", spec.uid)
    ev.add("dtstamp", datetime.utcnow())
    ev.add("dtstart", spec.start)
    ev.add("dtend", spec.end)
    ev.add("summary", spec.summary)
    if spec.description:
        ev.add("description", spec.description)
    if spec.location:
        ev.add("location", spec.location)
    ev.add("sequence", spec.sequence)
    ev.add("status", status)
    ev.add("transp", "OPAQUE")

    if spec.recurrence is not None:
        rec = spec.recurrence
        rule: dict = {"FREQ": rec.freq.upper(), "INTERVAL": int(rec.interval or 1)}
        if rec.until is not None:
            # UNTIL must be UTC per RFC 5545 when DTSTART is tz-aware. We treat
            # the user-supplied date as end-of-day in the event timezone, then
            # convert to UTC.
            tz = ZoneInfo(spec.tz)
            until_local = datetime(rec.until.year, rec.until.month, rec.until.day, 23, 59, 59, tzinfo=tz)
            rule["UNTIL"] = until_local.astimezone(ZoneInfo("UTC"))
        elif rec.count is not None:
            rule["COUNT"] = int(rec.count)
        ev.add("rrule", vRecur(rule))

    for exd in spec.exdates:
        ev.add("exdate", exd)

    org = vCalAddress(f"mailto:{spec.organizer_email}")
    org.params["CN"] = vText(spec.organizer_name)
    ev["organizer"] = org

    _add_attendees(ev, spec.attendees)

    # VALARMs nested inside the VEVENT. DISPLAY alarms fire on each attendee's
    # calendar client; EMAIL alarms are written but actual sending is handled
    # by our own scheduler (Purelymail's CalDAV doesn't fire VALARM emails).
    for a in spec.alarms:
        va = ICalAlarm()
        va.add("action", a.action.upper())
        va.add("trigger", timedelta(minutes=-abs(int(a.minutes_before))))
        va.add("description", a.description or spec.summary)
        if a.action.upper() == "EMAIL":
            va.add("summary", spec.summary)
            for r in a.recipients:
                addr = vCalAddress(f"mailto:{r}")
                va.add("attendee", addr, encode=0)
        ev.add_component(va)

    cal.add_component(ev)
    return cal, ev


def build_request(spec: EventSpec) -> Tuple[bytes, str]:
    """Build an iTIP REQUEST. Returns (ics_bytes, uid)."""
    cal, _ = _make_event(spec, status="CONFIRMED")
    return cal.to_ical(), spec.uid


def build_cancel(spec: EventSpec) -> Tuple[bytes, str]:
    """Build an iTIP CANCEL for the same UID. Bumps SEQUENCE caller-side."""
    cal = _build_calendar("CANCEL", spec.prodid)
    cal.add_component(_vtimezone(spec.tz))

    ev = Event()
    ev.add("uid", spec.uid)
    ev.add("dtstamp", datetime.utcnow())
    ev.add("dtstart", spec.start)
    ev.add("dtend", spec.end)
    ev.add("summary", spec.summary)
    ev.add("sequence", spec.sequence)
    ev.add("status", "CANCELLED")

    org = vCalAddress(f"mailto:{spec.organizer_email}")
    org.params["CN"] = vText(spec.organizer_name)
    ev["organizer"] = org
    _add_attendees(ev, spec.attendees)

    cal.add_component(ev)
    return cal.to_ical(), spec.uid
