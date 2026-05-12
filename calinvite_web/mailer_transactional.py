"""Transactional email sender for app-owned mail (magic links, etc).

Provider preference:
1. Resend, if RESEND_API_KEY is set.
2. Purelymail SMTP using MAGIC_LINK_SMTP_USER / MAGIC_LINK_SMTP_PASS env vars.
3. Fallback: the first ACCT_*_PASS pair so local dev works without extra setup.
"""
from __future__ import annotations

import html as html_lib
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr


def _build_html(link: str, ttl_minutes: int) -> str:
    safe = html_lib.escape(link)
    base = os.getenv("BASE_URL", "https://purelymailcalendar.com").rstrip("/")
    logo = f"{base}/logo.png"
    return (
        f'<table cellpadding="0" cellspacing="0" border="0" style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#0f172a;max-width:480px">'
        f'<tr><td style="padding-bottom:16px"><img src="{logo}" alt="Purelymail Calendar" width="40" height="40" style="display:block;border:0;border-radius:8px"/></td></tr>'
        f'<tr><td><p style="margin:0 0 8px;font-size:16px;font-weight:600">Sign in to Purelymail Calendar</p>'
        f'<p style="margin:0 0 16px;color:#475569;font-size:14px">Click the button below to sign in. The link expires in {ttl_minutes} minutes.</p></td></tr>'
        f'<tr><td><a href="{safe}" style="background:#4f46e5;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block">Sign in</a></td></tr>'
        f'<tr><td style="padding-top:16px"><p style="margin:0;color:#94a3b8;font-size:12px">Or paste this URL into your browser:<br><code style="color:#475569">{safe}</code></p></td></tr>'
        f'<tr><td style="padding-top:24px;border-top:1px solid #e2e8f0"><p style="margin:16px 0 0;color:#94a3b8;font-size:11px;line-height:1.5">'
        f"Purelymail Calendar is an unofficial, community-built tool. It is not affiliated with, endorsed by, or sponsored by Purelymail. "
        f'Made by <a href="https://yasheshbharti.com" style="color:#475569;text-decoration:underline">Yashesh Bharti</a>. '
        f'<a href="https://github.com/bhartiyashesh/purelymailcalendar" style="color:#475569;text-decoration:underline">Source on GitHub</a>.'
        f"</p></td></tr>"
        f"</table>"
    )


def _build_text(link: str, ttl_minutes: int) -> str:
    return (
        f"Sign in to Purelymail Calendar:\n\n"
        f"{link}\n\n"
        f"This link expires in {ttl_minutes} minutes. "
        f"If you didn't request it, you can ignore this email.\n\n"
        f"--\n"
        f"Purelymail Calendar is an unofficial, community-built tool. "
        f"Not affiliated with, endorsed by, or sponsored by Purelymail.\n"
        f"Made by Yashesh Bharti  https://yasheshbharti.com\n"
        f"Source on GitHub  https://github.com/bhartiyashesh/purelymailcalendar"
    )


def _send_via_resend(to_email: str, link: str, ttl_minutes: int) -> bool:
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        return False
    import resend  # imported lazily so SMTP-only setups don't need the package
    resend.api_key = api_key
    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    from_name = os.getenv("RESEND_FROM_NAME", "Purelymail Calendar")
    from_field = f"{from_name} <{from_email}>" if from_name else from_email

    resend.Emails.send({
        "from": from_field,
        "to": [to_email],
        "subject": "Your Purelymail Calendar sign-in link",
        "text": _build_text(link, ttl_minutes),
        "html": _build_html(link, ttl_minutes),
    })
    return True


def _smtp_config() -> tuple[str, int, str, str, str, str]:
    host = os.getenv("MAGIC_LINK_SMTP_HOST") or os.getenv("SMTP_HOST", "smtp.purelymail.com")
    port = int(os.getenv("MAGIC_LINK_SMTP_PORT") or os.getenv("SMTP_PORT", "465"))
    user = os.getenv("MAGIC_LINK_SMTP_USER")
    password = os.getenv("MAGIC_LINK_SMTP_PASS")
    from_email = os.getenv("MAGIC_LINK_FROM_EMAIL") or user
    from_name = os.getenv("MAGIC_LINK_FROM_NAME", "Purelymail Calendar")

    if not user or not password:
        for var in os.environ:
            if var.startswith("ACCT_") and var.endswith("_EMAIL"):
                key = var[len("ACCT_"):-len("_EMAIL")]
                em = os.environ[var]
                pw = os.getenv(f"ACCT_{key}_PASS")
                if pw and pw != "replace":
                    user = em
                    password = pw
                    from_email = from_email or em
                    break
    if not user or not password:
        raise RuntimeError(
            "No transactional email provider configured. Set RESEND_API_KEY, "
            "or MAGIC_LINK_SMTP_USER / MAGIC_LINK_SMTP_PASS."
        )
    return host, port, user, password, from_email, from_name


def _send_via_smtp(to_email: str, link: str, ttl_minutes: int) -> None:
    host, port, user, password, from_email, from_name = _smtp_config()

    msg = EmailMessage()
    msg["Subject"] = "Your Purelymail Calendar sign-in link"
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to_email
    msg.set_content(_build_text(link, ttl_minutes))
    msg.add_alternative(_build_html(link, ttl_minutes), subtype="html")

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(user, password)
            s.send_message(msg)


def send_magic_link(to_email: str, link: str, ttl_minutes: int) -> None:
    if _send_via_resend(to_email, link, ttl_minutes):
        return
    _send_via_smtp(to_email, link, ttl_minutes)
