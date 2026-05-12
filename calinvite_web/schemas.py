"""Pydantic request and response models for the web API."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class AccountOut(BaseModel):
    key: str
    email: str
    display_name: str
    is_default: bool


class CalendarOut(BaseModel):
    name: str


class AttendeeIn(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class AttendeeOut(BaseModel):
    email: str
    name: Optional[str] = None
    partstat: str = "NEEDS-ACTION"


class OrganizerOut(BaseModel):
    email: str
    name: Optional[str] = None


class EventIn(BaseModel):
    account: Optional[str] = None
    calendar: Optional[str] = None
    summary: str = Field(min_length=1)
    start: str = Field(description="ISO datetime e.g. 2026-05-15T14:00")
    duration_minutes: Optional[int] = Field(default=60, ge=1, le=24 * 60 * 14)
    end: Optional[str] = None
    tz: str = "America/Chicago"
    location: Optional[str] = ""
    description: Optional[str] = ""
    attendees: List[AttendeeIn] = []
    dry_run: bool = False
    uid: Optional[str] = None
    sequence: Optional[int] = None


class EventOut(BaseModel):
    uid: str
    summary: str
    start: datetime
    end: datetime
    tz: Optional[str] = None
    location: str = ""
    description: str = ""
    sequence: int = 0
    organizer: Optional[OrganizerOut] = None
    attendees: List[AttendeeOut] = []


class CreateEventResponse(BaseModel):
    uid: str
    sent_to: List[str]
    dry_run: bool


class CancelEventResponse(BaseModel):
    uid: str
    sent_to: List[str]


class RsvpResultOut(BaseModel):
    uid: str
    attendee: str
    partstat: str
    summary: str
    success: bool
    detail: str = ""


class RsvpPollIn(BaseModel):
    account: Optional[str] = None
    calendar: Optional[str] = None
    mailbox: str = "INBOX"
    only_unseen: bool = True
    mark_seen: bool = True


class RsvpPollOut(BaseModel):
    mailbox: str
    results: List[RsvpResultOut]
