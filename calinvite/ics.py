"""Build iCalendar VEVENTs with proper iTIP semantics (REQUEST / CANCEL)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, List, Tuple
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event, Timezone, TimezoneStandard, TimezoneDaylight, vCalAddress, vText


@dataclass
class Attendee:
    email: str
    name: str | None = None
    role: str = "REQ-PARTICIPANT"
    partstat: str = "NEEDS-ACTION"
    rsvp: bool = True


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

    org = vCalAddress(f"mailto:{spec.organizer_email}")
    org.params["CN"] = vText(spec.organizer_name)
    ev["organizer"] = org

    _add_attendees(ev, spec.attendees)
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
