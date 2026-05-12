"""CalDAV operations: list calendars, PUT events, fetch event by UID, list upcoming."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Tuple

import caldav
from caldav import Calendar as DavCalendar, Event as DavEvent
from icalendar import Calendar as ICalendar


def connect(url: str, username: str, password: str) -> caldav.DAVClient:
    return caldav.DAVClient(url=url, username=username, password=password)


def get_calendar(client: caldav.DAVClient, name: Optional[str]) -> DavCalendar:
    principal = client.principal()
    cals = principal.calendars()
    if not cals:
        raise RuntimeError("No calendars found on server.")
    if not name:
        return cals[0]
    name_lower = name.lower()
    for c in cals:
        cname = (c.name or "").lower()
        if cname == name_lower or name_lower in cname:
            return c
    available = ", ".join(c.name or "?" for c in cals)
    raise RuntimeError(f"Calendar '{name}' not found. Available: {available}")


def list_calendars(client: caldav.DAVClient) -> List[str]:
    return [c.name or "?" for c in client.principal().calendars()]


def put_event(calendar: DavCalendar, ics_bytes: bytes) -> DavEvent:
    """Save (create or update) an event by its UID."""
    return calendar.save_event(ics_bytes.decode("utf-8"))


def find_event_by_uid(calendar: DavCalendar, uid: str) -> Optional[DavEvent]:
    try:
        return calendar.event_by_uid(uid)
    except caldav.lib.error.NotFoundError:
        return None
    except Exception:
        # Fallback: scan
        for ev in calendar.events():
            try:
                cal = ICalendar.from_ical(ev.data)
                for comp in cal.walk("VEVENT"):
                    if str(comp.get("uid")) == uid:
                        return ev
            except Exception:
                continue
        return None


def upcoming(calendar: DavCalendar, days: int = 14) -> List[Tuple[str, str, datetime, datetime]]:
    """Return upcoming events as (uid, summary, start, end)."""
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    out: List[Tuple[str, str, datetime, datetime]] = []
    for ev in calendar.search(start=start, end=end, event=True, expand=False):
        try:
            cal = ICalendar.from_ical(ev.data)
            for comp in cal.walk("VEVENT"):
                out.append((
                    str(comp.get("uid", "")),
                    str(comp.get("summary", "")),
                    comp.get("dtstart").dt if comp.get("dtstart") else start,
                    comp.get("dtend").dt if comp.get("dtend") else end,
                ))
        except Exception:
            continue
    out.sort(key=lambda r: r[2])
    return out
