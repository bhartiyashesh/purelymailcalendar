"""SMTP mailer that sends iTIP invites with the correct MIME structure.

Layout that survives Apple Mail / Gmail / Outlook:

    multipart/mixed
    ├── multipart/alternative
    │   ├── text/plain
    │   └── text/calendar; method=REQUEST; charset=UTF-8   (inline iTIP body, 7bit/QP)
    └── application/ics; name=invite.ics                   (attachment fallback)

The `text/calendar` part deliberately avoids base64 — older Outlook clients reject
base64-encoded inline calendar parts. We use 8bit (or quoted-printable for non-ASCII).
"""
from __future__ import annotations

import smtplib
import ssl
from email import encoders
from email.charset import QP, Charset
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from typing import Iterable


_QP_UTF8 = Charset("utf-8")
_QP_UTF8.body_encoding = QP


def _calendar_part(ics_bytes: bytes, method: str) -> MIMEBase:
    """Build a `text/calendar; method=...` part with quoted-printable encoding."""
    part = MIMEBase("text", "calendar", method=method, charset="UTF-8")
    # MIMEBase sets a base64 default; override before set_payload.
    if "Content-Transfer-Encoding" in part:
        del part["Content-Transfer-Encoding"]
    part.set_payload(ics_bytes.decode("utf-8"), charset=_QP_UTF8)
    return part


def build_message(
    *,
    from_email: str,
    from_name: str,
    to_addrs: Iterable[str],
    subject: str,
    body_text: str,
    ics_bytes: bytes,
    method: str = "REQUEST",
) -> MIMEMultipart:
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = ", ".join(to_addrs)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_email.split("@")[-1])

    alt = MIMEMultipart("alternative")
    plain = MIMEText("", "plain", _charset=None)
    plain.set_payload(body_text or " ", charset=_QP_UTF8)
    alt.attach(plain)
    alt.attach(_calendar_part(ics_bytes, method))
    msg.attach(alt)

    attach = MIMEBase("application", "ics")
    attach.set_payload(ics_bytes)
    encoders.encode_base64(attach)
    attach.add_header("Content-Disposition", 'attachment; filename="invite.ics"')
    msg.attach(attach)

    return msg


def send(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    msg: MIMEMultipart,
    to_addrs: Iterable[str],
) -> None:
    ctx = ssl.create_default_context()
    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as s:
            s.login(smtp_user, smtp_pass)
            s.send_message(msg, from_addr=smtp_user, to_addrs=list(to_addrs))
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(smtp_user, smtp_pass)
            s.send_message(msg, from_addr=smtp_user, to_addrs=list(to_addrs))
