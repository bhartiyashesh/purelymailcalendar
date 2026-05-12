"""calinvite CLI."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from typing import List
from zoneinfo import ZoneInfo

from .config import Account, Settings, load_settings, resolve_account
from .ics import Attendee, EventSpec, build_cancel, build_request
from . import caldav_client as cdav
from . import mailer
from . import rsvp as rsvp_mod


def _parse_attendee(spec: str) -> Attendee:
    """Format: email or email:Display Name"""
    if ":" in spec:
        email, name = spec.split(":", 1)
    else:
        email, name = spec, None
    return Attendee(email=email.strip(), name=name.strip() if name else None)


def _parse_dt(s: str, tz_name: str) -> datetime:
    """Accept ISO with or without seconds: 2026-05-15T14:00 or 2026-05-15T14:00:00."""
    fmts = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M")
    for f in fmts:
        try:
            naive = datetime.strptime(s, f)
            return naive.replace(tzinfo=ZoneInfo(tz_name))
        except ValueError:
            continue
    raise SystemExit(f"Could not parse datetime: {s!r}")


def _build_spec(args, account: Account) -> EventSpec:
    start = _parse_dt(args.start, args.tz)
    if args.duration:
        end = start + timedelta(minutes=int(args.duration))
    elif args.end:
        end = _parse_dt(args.end, args.tz)
    else:
        end = start + timedelta(hours=1)

    return EventSpec(
        summary=args.summary,
        start=start,
        end=end,
        organizer_email=account.email,
        organizer_name=account.display_name,
        attendees=[_parse_attendee(a) for a in args.attendee or []],
        description=args.description or "",
        location=args.location or "",
        uid=args.uid or f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}-{abs(hash(args.summary))}@calinvite",
        sequence=int(args.sequence or 0),
        tz=args.tz,
    )


def _send_invite(settings: Settings, account: Account, spec: EventSpec, body: str, ics_bytes: bytes, method: str) -> None:
    to = [a.email for a in spec.attendees]
    if not to:
        return
    subject_prefix = {"REQUEST": "Invitation", "CANCEL": "Cancelled"}.get(method, "Update")
    msg = mailer.build_message(
        from_email=account.email,
        from_name=account.display_name,
        to_addrs=to,
        subject=f"{subject_prefix}: {spec.summary}",
        body_text=body,
        ics_bytes=ics_bytes,
        method=method,
    )
    mailer.send(
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_user=account.email,
        smtp_pass=account.password,
        msg=msg,
        to_addrs=to,
    )


def cmd_create(args) -> int:
    settings = load_settings()
    account = resolve_account(settings, args.account)
    spec = _build_spec(args, account)
    ics_bytes, uid = build_request(spec)

    client = cdav.connect(settings.caldav_url, settings.caldav_user, settings.caldav_pass)
    calendar = cdav.get_calendar(client, args.calendar)
    cdav.put_event(calendar, ics_bytes)

    if not args.dry_run:
        body = _default_body(spec, "You're invited.")
        _send_invite(settings, account, spec, body, ics_bytes, method="REQUEST")

    print(f"Created event")
    print(f"  UID:       {uid}")
    print(f"  Calendar:  {calendar.name}")
    print(f"  When:      {spec.start.isoformat()} → {spec.end.isoformat()} ({spec.tz})")
    print(f"  Attendees: {', '.join(a.email for a in spec.attendees) or '(none)'}")
    if args.dry_run:
        print("  (dry-run: no email sent)")
    return 0


def cmd_update(args) -> int:
    settings = load_settings()
    account = resolve_account(settings, args.account)
    if not args.uid:
        raise SystemExit("--uid is required for update")
    if int(args.sequence or 0) < 1:
        # Bumping rule: every update increments SEQUENCE.
        # If caller didn't pass one, assume 1.
        args.sequence = "1"
    spec = _build_spec(args, account)
    ics_bytes, uid = build_request(spec)

    client = cdav.connect(settings.caldav_url, settings.caldav_user, settings.caldav_pass)
    calendar = cdav.get_calendar(client, args.calendar)
    cdav.put_event(calendar, ics_bytes)

    if not args.dry_run:
        body = _default_body(spec, "This invitation has been updated.")
        _send_invite(settings, account, spec, body, ics_bytes, method="REQUEST")

    print(f"Updated event {uid} (SEQUENCE={spec.sequence})")
    return 0


def cmd_cancel(args) -> int:
    settings = load_settings()
    account = resolve_account(settings, args.account)
    if not args.uid:
        raise SystemExit("--uid is required for cancel")
    if int(args.sequence or 0) < 1:
        args.sequence = "1"
    spec = _build_spec(args, account)
    ics_bytes, uid = build_cancel(spec)

    client = cdav.connect(settings.caldav_url, settings.caldav_user, settings.caldav_pass)
    calendar = cdav.get_calendar(client, args.calendar)
    ev = cdav.find_event_by_uid(calendar, uid)
    if ev is not None:
        try:
            ev.delete()
        except Exception:
            pass

    if not args.dry_run:
        body = _default_body(spec, "This event has been cancelled.")
        _send_invite(settings, account, spec, body, ics_bytes, method="CANCEL")

    print(f"Cancelled event {uid}")
    return 0


def cmd_list(args) -> int:
    settings = load_settings()
    client = cdav.connect(settings.caldav_url, settings.caldav_user, settings.caldav_pass)
    calendar = cdav.get_calendar(client, args.calendar)
    rows = cdav.upcoming(calendar, days=args.days)
    if not rows:
        print("(no upcoming events)")
        return 0
    for uid, summary, start, end in rows:
        print(f"{start.isoformat()}  {summary}  [{uid}]")
    return 0


def cmd_calendars(args) -> int:
    settings = load_settings()
    client = cdav.connect(settings.caldav_url, settings.caldav_user, settings.caldav_pass)
    for name in cdav.list_calendars(client):
        print(name)
    return 0


def cmd_accounts(args) -> int:
    settings = load_settings()
    for key, acct in settings.accounts.items():
        marker = " (default)" if key == settings.default_account else ""
        print(f"{key}: {acct.display_name} <{acct.email}>{marker}")
    return 0


def cmd_rsvps(args) -> int:
    settings = load_settings()
    account = resolve_account(settings, args.account)
    client = cdav.connect(settings.caldav_url, settings.caldav_user, settings.caldav_pass)
    calendar = cdav.get_calendar(client, args.calendar)
    since = None
    if args.since:
        since = datetime.fromisoformat(args.since)
    results = rsvp_mod.process_inbox(
        imap_host=settings.imap_host,
        imap_port=settings.imap_port,
        imap_user=account.email,
        imap_pass=account.password,
        caldav_calendar=calendar,
        mailbox=args.mailbox,
        mark_seen=not args.no_mark_seen,
        only_unseen=not args.all,
        since=since,
    )
    if not results:
        print(f"(no RSVPs processed in {args.mailbox})")
        return 0
    for r in results:
        status = "OK " if r.success else "SKIP"
        print(f"{status}  {r.attendee:40}  {r.partstat:14}  {r.summary}  [{r.uid}]"
              + (f"  -- {r.detail}" if r.detail else ""))
    return 0


def cmd_sieve_install(args) -> int:
    from . import sieve_client
    settings = load_settings()
    account = resolve_account(settings, args.account)
    name, script = sieve_client.load_bundled_script()
    sieve_client.install(
        host=settings.sieve_host, port=settings.sieve_port,
        user=account.email, password=account.password,
        name=name, script_text=script, activate=not args.no_activate,
    )
    print(f"Installed sieve script '{name}' on {account.email}"
          + ("" if args.no_activate else " (activated)"))
    print("Replies will be filed into the 'RSVPs' mailbox.")
    print(f"Run: calinvite rsvps --account {account.key} --mailbox RSVPs")
    return 0


def cmd_sieve_list(args) -> int:
    from . import sieve_client
    settings = load_settings()
    account = resolve_account(settings, args.account)
    active, names = sieve_client.list_scripts(
        host=settings.sieve_host, port=settings.sieve_port,
        user=account.email, password=account.password,
    )
    if not names:
        print("(no sieve scripts)")
        return 0
    for n in names:
        print(f"{'*' if n == active else ' '} {n}")
    return 0


def cmd_sieve_show(args) -> int:
    from . import sieve_client
    settings = load_settings()
    account = resolve_account(settings, args.account)
    body = sieve_client.get_script(
        host=settings.sieve_host, port=settings.sieve_port,
        user=account.email, password=account.password,
        name=args.name,
    )
    print(body)
    return 0


def cmd_sieve_activate(args) -> int:
    from . import sieve_client
    settings = load_settings()
    account = resolve_account(settings, args.account)
    sieve_client.activate(
        host=settings.sieve_host, port=settings.sieve_port,
        user=account.email, password=account.password,
        name=args.name,
    )
    print(f"Activated sieve script '{args.name}'")
    return 0


def cmd_sieve_delete(args) -> int:
    from . import sieve_client
    settings = load_settings()
    account = resolve_account(settings, args.account)
    sieve_client.delete(
        host=settings.sieve_host, port=settings.sieve_port,
        user=account.email, password=account.password,
        name=args.name,
    )
    print(f"Deleted sieve script '{args.name}'")
    return 0


def _default_body(spec: EventSpec, lead: str) -> str:
    lines = [
        lead,
        "",
        f"What:  {spec.summary}",
        f"When:  {spec.start.strftime('%a %b %d, %Y  %I:%M %p')} – "
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


def _add_event_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--account", help="account key (e.g. YASHESH); defaults to DEFAULT_ACCOUNT")
    p.add_argument("--calendar", help="CalDAV calendar name (substring match); defaults to first")
    p.add_argument("--summary", required=True, help="event title")
    p.add_argument("--start", required=True, help="ISO datetime, e.g. 2026-05-15T14:00")
    p.add_argument("--end", help="ISO datetime")
    p.add_argument("--duration", help="minutes (alternative to --end)")
    p.add_argument("--tz", default="America/Chicago", help="IANA tz, default America/Chicago")
    p.add_argument("--location", help="location text or URL")
    p.add_argument("--description", help="description body")
    p.add_argument("--attendee", action="append", help="email or email:Name (repeatable)")
    p.add_argument("--uid", help="event UID (required for update/cancel)")
    p.add_argument("--sequence", help="iTIP SEQUENCE; bumped on update/cancel")
    p.add_argument("--dry-run", action="store_true", help="write to CalDAV but don't email")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="calinvite",
        description="CalDAV + SMTP/IMAP calendar invites with RSVP handling for Purelymail.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="create event + send invites")
    _add_event_args(p_create)
    p_create.set_defaults(func=cmd_create)

    p_update = sub.add_parser("update", help="update event (bumps SEQUENCE) + resend invites")
    _add_event_args(p_update)
    p_update.set_defaults(func=cmd_update)

    p_cancel = sub.add_parser("cancel", help="cancel event + send METHOD:CANCEL")
    _add_event_args(p_cancel)
    p_cancel.set_defaults(func=cmd_cancel)

    p_list = sub.add_parser("list", help="list upcoming events")
    p_list.add_argument("--calendar", help="calendar name")
    p_list.add_argument("--days", type=int, default=14)
    p_list.set_defaults(func=cmd_list)

    p_cals = sub.add_parser("calendars", help="list calendars")
    p_cals.set_defaults(func=cmd_calendars)

    p_acct = sub.add_parser("accounts", help="list configured SMTP accounts")
    p_acct.set_defaults(func=cmd_accounts)

    p_rsvp = sub.add_parser("rsvps", help="poll IMAP for replies and update CalDAV")
    p_rsvp.add_argument("--account", help="account key")
    p_rsvp.add_argument("--calendar", help="calendar name")
    p_rsvp.add_argument("--mailbox", default="INBOX",
                        help="IMAP mailbox to scan (use RSVPs after `sieve install`)")
    p_rsvp.add_argument("--all", action="store_true", help="scan all messages, not just unseen")
    p_rsvp.add_argument("--no-mark-seen", action="store_true", help="don't mark messages \\Seen")
    p_rsvp.add_argument("--since", help="ISO date, e.g. 2026-05-01")
    p_rsvp.set_defaults(func=cmd_rsvps)

    p_sieve = sub.add_parser("sieve", help="manage Sieve filters via ManageSieve")
    sieve_sub = p_sieve.add_subparsers(dest="sieve_cmd", required=True)

    s_install = sieve_sub.add_parser("install",
        help="upload+activate the bundled calinvite.sieve filter")
    s_install.add_argument("--account", help="account key")
    s_install.add_argument("--no-activate", action="store_true",
        help="upload but don't make it the active script")
    s_install.set_defaults(func=cmd_sieve_install)

    s_list = sieve_sub.add_parser("list", help="list installed sieve scripts")
    s_list.add_argument("--account", help="account key")
    s_list.set_defaults(func=cmd_sieve_list)

    s_show = sieve_sub.add_parser("show", help="print a sieve script")
    s_show.add_argument("--account", help="account key")
    s_show.add_argument("name")
    s_show.set_defaults(func=cmd_sieve_show)

    s_activate = sieve_sub.add_parser("activate", help="set the active sieve script")
    s_activate.add_argument("--account", help="account key")
    s_activate.add_argument("name")
    s_activate.set_defaults(func=cmd_sieve_activate)

    s_delete = sieve_sub.add_parser("delete", help="delete a sieve script")
    s_delete.add_argument("--account", help="account key")
    s_delete.add_argument("name")
    s_delete.set_defaults(func=cmd_sieve_delete)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
