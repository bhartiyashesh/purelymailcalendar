"""BCC invites: one private message per guest, full list kept on CalDAV."""
from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from icalendar import Calendar
from icalendar import Calendar as ICalendar
from icalendar import Event, vCalAddress, vText

from calinvite.ics import Alarm, Attendee, EventSpec, build_request, ics_for_recipient
from calinvite_web.schemas import AttendeeIn, EventIn, ReminderIn
from calinvite_web.services import MailboxCreds, _send_invite, create_event, serialize_vevent


def _creds() -> MailboxCreds:
    return MailboxCreds(
        email="host@example.com",
        password="secret",
        display_name="Host",
        caldav_url="https://caldav.example/cal",
        smtp_host="smtp.example",
        smtp_port=465,
        imap_host="imap.example",
        imap_port=993,
    )


def _event(*, bcc: bool) -> EventIn:
    return EventIn(
        summary="Town hall",
        start="2026-06-01T10:00",
        duration_minutes=60,
        tz="UTC",
        attendees=[
            AttendeeIn(email="ada@example.com", name="Ada"),
            AttendeeIn(email="grace@example.com", name="Grace"),
        ],
        reminders=[
            ReminderIn(
                action="EMAIL",
                minutes_before=15,
                recipients=["ada@example.com", "grace@example.com"],
            )
        ],
        bcc_invites=bcc,
    )


def _patch_transport(monkeypatch):
    stored: dict = {}
    sent: list = []

    class _Cal:
        name = "Default"

    monkeypatch.setattr("calinvite_web.services.cdav.connect", lambda *a, **k: object())
    monkeypatch.setattr("calinvite_web.services.cdav.get_calendar", lambda client, name: _Cal())
    monkeypatch.setattr(
        "calinvite_web.services.cdav.put_event",
        lambda calendar, ics: stored.__setitem__("ics", ics),
    )
    def _capture(**kwargs):
        for msg, addrs in kwargs["deliveries"]:
            sent.append({"msg": msg, "to_addrs": list(addrs)})
        return []

    monkeypatch.setattr("calinvite_web.services.mailer.send_all", _capture)
    return stored, sent


def _calendar_text(msg: EmailMessage) -> str:
    chunks = []
    for part in msg.walk():
        if part.get_content_type() in ("text/calendar", "application/ics"):
            payload = part.get_payload(decode=True)
            if payload:
                chunks.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def _attendee_emails(ics: bytes) -> set[str]:
    cal = ICalendar.from_ical(ics)
    found = set()
    for comp in cal.walk("VEVENT"):
        raw = comp.get("attendee")
        items = [] if raw is None else (raw if isinstance(raw, list) else [raw])
        for item in items:
            email = str(item)
            if email.lower().startswith("mailto:"):
                email = email[7:]
            found.add(email.lower())
    return found


def test_shared_invite_sends_one_message(monkeypatch):
    stored, sent = _patch_transport(monkeypatch)
    result = create_event(_creds(), _event(bcc=False))

    assert result.sent_to == ["ada@example.com", "grace@example.com"]
    assert len(sent) == 1
    msg = sent[0]["msg"]
    assert "ada@example.com" in msg["To"]
    assert "grace@example.com" in msg["To"]
    body = _calendar_text(msg)
    assert "ada@example.com" in body
    assert "grace@example.com" in body

    stored_ics = stored["ics"]
    assert _attendee_emails(stored_ics) >= {"ada@example.com", "grace@example.com", "host@example.com"}
    assert b"X-CALINVITE-BCC" not in stored_ics
    vevent = ICalendar.from_ical(stored_ics).walk("VEVENT")[0]
    assert serialize_vevent(vevent).bcc_invites is False


def test_bcc_invite_sends_one_private_message_per_guest(monkeypatch):
    stored, sent = _patch_transport(monkeypatch)
    result = create_event(_creds(), _event(bcc=True))

    assert result.sent_to == ["ada@example.com", "grace@example.com"]
    assert len(sent) == 2

    by_to = {item["msg"]["To"]: item for item in sent}
    assert set(by_to) == {"ada@example.com", "grace@example.com"}

    ada = _calendar_text(by_to["ada@example.com"]["msg"])
    grace = _calendar_text(by_to["grace@example.com"]["msg"])
    assert "ada@example.com" in ada
    assert "grace@example.com" not in ada
    assert "grace@example.com" in grace
    assert "ada@example.com" not in grace
    assert sent[0]["to_addrs"] == ["ada@example.com"]
    assert sent[1]["to_addrs"] == ["grace@example.com"]

    stored_ics = stored["ics"]
    assert _attendee_emails(stored_ics) >= {"ada@example.com", "grace@example.com", "host@example.com"}
    assert b"X-CALINVITE-BCC" in stored_ics
    vevent = ICalendar.from_ical(stored_ics).walk("VEVENT")[0]
    assert serialize_vevent(vevent).bcc_invites is True


def test_personal_cancel_keeps_recurrence_id(monkeypatch):
    sent: list = []
    def _capture(**kwargs):
        for msg, addrs in kwargs["deliveries"]:
            sent.append({"msg": msg, "to_addrs": list(addrs)})
        return []

    monkeypatch.setattr("calinvite_web.services.mailer.send_all", _capture)
    start = datetime(2026, 6, 1, 10, 0, tzinfo=ZoneInfo("UTC"))
    spec = EventSpec(
        summary="Town hall",
        start=start,
        end=datetime(2026, 6, 1, 11, 0, tzinfo=ZoneInfo("UTC")),
        organizer_email="host@example.com",
        organizer_name="Host",
        attendees=[
            Attendee(email="ada@example.com", name="Ada"),
            Attendee(email="grace@example.com", name="Grace"),
        ],
        tz="UTC",
        uid="series@calinvite",
        bcc_invites=True,
    )
    cal = Calendar()
    cal.add("prodid", "-//calinvite//test//EN")
    cal.add("version", "2.0")
    cal.add("method", "CANCEL")
    ev = Event()
    ev.add("uid", spec.uid)
    ev.add("dtstart", start)
    ev.add("dtend", spec.end)
    ev.add("summary", spec.summary)
    ev.add("recurrence-id", start)
    for email in ("ada@example.com", "grace@example.com"):
        addr = vCalAddress(f"mailto:{email}")
        addr.params["CN"] = vText(email)
        ev.add("attendee", addr, encode=0)
    cal.add_component(ev)

    sent_to, failed = _send_invite(
        _creds(),
        spec,
        "cancelled",
        cal.to_ical(),
        method="CANCEL",
        bcc_invites=True,
    )
    assert sent_to == ["ada@example.com", "grace@example.com"]
    assert failed == []
    assert len(sent) == 2
    for item in sent:
        text = _calendar_text(item["msg"])
        assert "RECURRENCE-ID" in text
        other = "grace@example.com" if item["to_addrs"] == ["ada@example.com"] else "ada@example.com"
        assert other not in text
        assert item["to_addrs"][0] in text


def test_ics_for_recipient_drops_other_email_alarm_recipients():
    start = datetime(2026, 6, 1, 10, 0, tzinfo=ZoneInfo("UTC"))
    spec = EventSpec(
        summary="Town hall",
        start=start,
        end=datetime(2026, 6, 1, 11, 0, tzinfo=ZoneInfo("UTC")),
        organizer_email="host@example.com",
        organizer_name="Host",
        attendees=[
            Attendee(email="host@example.com", name="Host", partstat="ACCEPTED", rsvp=False),
            Attendee(email="ada@example.com", name="Ada"),
            Attendee(email="grace@example.com", name="Grace"),
        ],
        alarms=[
            Alarm(action="DISPLAY", minutes_before=10, description="Popup"),
            Alarm(
                action="EMAIL",
                minutes_before=15,
                description="Email",
                recipients=["ada@example.com", "grace@example.com"],
            ),
            Alarm(
                action="EMAIL",
                minutes_before=30,
                description="Grace only",
                recipients=["grace@example.com"],
            ),
        ],
        tz="UTC",
        uid="town-hall@calinvite",
        bcc_invites=True,
    )
    full, _ = build_request(spec)
    personal = ics_for_recipient(full, "ada@example.com", "host@example.com")
    text = personal.decode("utf-8", errors="replace")
    assert "ada@example.com" in text
    assert "host@example.com" in text
    assert "grace@example.com" not in text
    assert "DISPLAY" in text
    assert b"X-CALINVITE-BCC" in full
    personal_cal = ICalendar.from_ical(personal)
    email_alarms = [
        alarm
        for alarm in personal_cal.walk("VALARM")
        if str(alarm.get("action") or "").upper() == "EMAIL"
    ]
    assert len(email_alarms) == 1
    assert email_alarms[0].get("attendee") is not None


def test_bcc_dedupes_addresses_ignoring_case(monkeypatch):
    sent: list = []

    def _capture(**kwargs):
        for _msg, addrs in kwargs["deliveries"]:
            sent.append(list(addrs))
        return []

    monkeypatch.setattr("calinvite_web.services.mailer.send_all", _capture)
    spec = EventSpec(
        summary="Town hall",
        start=datetime(2026, 6, 1, 10, 0, tzinfo=ZoneInfo("UTC")),
        end=datetime(2026, 6, 1, 11, 0, tzinfo=ZoneInfo("UTC")),
        organizer_email="host@example.com",
        organizer_name="Host",
        attendees=[
            Attendee(email="Ada@example.com", name="Ada"),
            Attendee(email="ada@example.com", name="Ada again"),
            Attendee(email="grace@example.com", name="Grace"),
        ],
        tz="UTC",
        uid="dedupe@calinvite",
        bcc_invites=True,
    )
    ics, _ = build_request(spec)
    sent_to, failed = _send_invite(_creds(), spec, "invited", ics, method="REQUEST", bcc_invites=True)
    assert sent == [["Ada@example.com"], ["grace@example.com"]]
    assert sent_to == ["Ada@example.com", "grace@example.com"]
    assert failed == []


def test_bcc_send_continues_when_one_guest_fails(monkeypatch):
    stored, sent = _patch_transport(monkeypatch)

    def _capture(**kwargs):
        failed = []
        for msg, addrs in kwargs["deliveries"]:
            if list(addrs) == ["grace@example.com"]:
                failed.append(("grace@example.com", RuntimeError("rejected")))
            else:
                sent.append({"msg": msg, "to_addrs": list(addrs)})
        return failed

    monkeypatch.setattr("calinvite_web.services.mailer.send_all", _capture)
    result = create_event(_creds(), _event(bcc=True))
    assert result.sent_to == ["ada@example.com"]
    assert result.failed_to == ["grace@example.com"]
    assert [item["to_addrs"] for item in sent] == [["ada@example.com"]]
    assert b"X-CALINVITE-BCC" in stored["ics"]


def test_send_all_uses_one_session_and_continues(monkeypatch):
    import calinvite.mailer as mailer_mod
    from calinvite import mailer

    class FakeSMTP:
        instances: list = []

        def __init__(self, *args, **kwargs):
            FakeSMTP.instances.append(self)
            self.sent: list = []

        def login(self, *args):
            return None

        def send_message(self, msg, from_addr=None, to_addrs=None):
            if to_addrs == ["bad@example.com"]:
                raise RuntimeError("rejected")
            self.sent.append(list(to_addrs))

        def quit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(mailer_mod.smtplib, "SMTP_SSL", FakeSMTP)
    msg = mailer.build_message(
        from_email="host@example.com",
        from_name="Host",
        to_addrs=["ada@example.com"],
        subject="Invitation: Town hall",
        body_text="You're invited.",
        ics_bytes=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
        method="REQUEST",
    )
    failed = mailer.send_all(
        smtp_host="smtp.example",
        smtp_port=465,
        smtp_user="host@example.com",
        smtp_pass="secret",
        deliveries=[
            (msg, ["ada@example.com"]),
            (msg, ["bad@example.com"]),
            (msg, ["grace@example.com"]),
        ],
    )
    assert len(FakeSMTP.instances) == 1
    assert FakeSMTP.instances[0].sent == [["ada@example.com"], ["grace@example.com"]]
    assert [addr for addr, _err in failed] == ["bad@example.com"]


def test_bcc_reminder_hides_guest_list_and_organizer_links(monkeypatch):
    from calinvite_web.models import Mailbox, ScheduledReminder
    from calinvite_web.reminders import _send_one

    captured: list = []

    def fake_send_all(**kwargs):
        captured.append(kwargs)
        return []

    monkeypatch.setattr("calinvite_web.reminders.mailer.send_all", fake_send_all)
    monkeypatch.setattr("calinvite_web.reminders.decrypt", lambda token: "pw")
    mailbox = Mailbox(
        user_id=1,
        email="host@example.com",
        display_name="Host",
        account_id="1",
        encrypted_password="x",
        smtp_host="smtp.example",
        smtp_port=465,
    )
    reminder = ScheduledReminder(
        user_id=1,
        event_uid="town-hall",
        event_summary="Town hall",
        event_start=datetime(2026, 6, 1, 10, 0),
        occurrence_start=datetime(2026, 6, 1, 10, 0),
        fire_at=datetime(2026, 6, 1, 9, 45),
        minutes_before=15,
        recipients_json='["ada@example.com", "Ada@example.com", "grace@example.com"]',
        confirm_token="tok",
        bcc_invites=True,
    )
    _send_one(mailbox, reminder)
    assert len(captured) == 1
    deliveries = captured[0]["deliveries"]
    tos = [list(addrs) for _msg, addrs in deliveries]
    assert tos == [["ada@example.com"], ["grace@example.com"], ["host@example.com"]]
    for msg, addrs in deliveries:
        body = msg.get_body(preferencelist=("plain",)).get_content()
        if list(addrs) == ["host@example.com"]:
            assert "Confirm:" in body
            assert "ada@example.com" not in body
            assert "grace@example.com" not in body
        else:
            assert "Cancel this occurrence" not in body
            other = "grace@example.com" if list(addrs) == ["ada@example.com"] else "ada@example.com"
            assert other not in body
            assert other not in msg["To"]
