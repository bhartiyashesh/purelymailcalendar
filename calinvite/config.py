"""Configuration: load Purelymail accounts and CalDAV/SMTP/IMAP settings from env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class Account:
    key: str          # short id e.g. "YASHESH"
    email: str
    password: str
    display_name: str


@dataclass(frozen=True)
class Settings:
    caldav_url: str
    caldav_user: str
    caldav_pass: str
    smtp_host: str
    smtp_port: int
    imap_host: str
    imap_port: int
    sieve_host: str
    sieve_port: int
    accounts: Dict[str, Account]
    default_account: str


def load_settings() -> Settings:
    caldav_url = _require("PURELYMAIL_CALDAV_URL")
    caldav_user = _require("PURELYMAIL_CALDAV_USER")
    caldav_pass = _require("PURELYMAIL_CALDAV_PASS")

    smtp_host = os.getenv("SMTP_HOST", "smtp.purelymail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    imap_host = os.getenv("IMAP_HOST", "imap.purelymail.com")
    imap_port = int(os.getenv("IMAP_PORT", "993"))
    sieve_host = os.getenv("SIEVE_HOST", "mailserver.purelymail.com")
    sieve_port = int(os.getenv("SIEVE_PORT", "4190"))

    accounts: Dict[str, Account] = {}
    prefix = "ACCT_"
    suffix_email = "_EMAIL"
    for var in os.environ:
        if var.startswith(prefix) and var.endswith(suffix_email):
            key = var[len(prefix):-len(suffix_email)]
            email = os.environ[var]
            pw = os.getenv(f"{prefix}{key}_PASS")
            name = os.getenv(f"{prefix}{key}_NAME", email)
            if not pw:
                continue
            accounts[key] = Account(key=key, email=email, password=pw, display_name=name)

    if not accounts:
        raise RuntimeError(
            "No accounts configured. Define ACCT_<KEY>_EMAIL / ACCT_<KEY>_PASS / ACCT_<KEY>_NAME."
        )

    default_account = os.getenv("DEFAULT_ACCOUNT") or next(iter(accounts))
    if default_account not in accounts:
        raise RuntimeError(f"DEFAULT_ACCOUNT={default_account} not found in configured accounts.")

    return Settings(
        caldav_url=caldav_url,
        caldav_user=caldav_user,
        caldav_pass=caldav_pass,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        imap_host=imap_host,
        imap_port=imap_port,
        sieve_host=sieve_host,
        sieve_port=sieve_port,
        accounts=accounts,
        default_account=default_account,
    )


def resolve_account(settings: Settings, key: str | None) -> Account:
    chosen = key or settings.default_account
    chosen = chosen.upper()
    if chosen not in settings.accounts:
        raise RuntimeError(
            f"Unknown account '{chosen}'. Available: {', '.join(settings.accounts)}"
        )
    return settings.accounts[chosen]


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val
