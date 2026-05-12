"""ManageSieve client: install / list / activate Sieve scripts on Purelymail."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from sievelib.managesieve import Client


@dataclass
class SieveSettings:
    host: str = "mailserver.purelymail.com"
    port: int = 4190


def _connect(host: str, port: int, user: str, password: str) -> Client:
    c = Client(host, port)
    ok = c.connect(user, password, starttls=True)
    if not ok:
        raise RuntimeError(f"ManageSieve auth failed: {c.errmsg or 'unknown error'}")
    return c


def install(*, host: str, port: int, user: str, password: str,
            name: str, script_text: str, activate: bool = True) -> None:
    c = _connect(host, port, user, password)
    try:
        ok = c.putscript(name, script_text)
        if not ok:
            raise RuntimeError(f"putscript failed: {c.errmsg or 'unknown error'}")
        if activate:
            ok = c.setactive(name)
            if not ok:
                raise RuntimeError(f"setactive failed: {c.errmsg or 'unknown error'}")
    finally:
        c.logout()


def list_scripts(*, host: str, port: int, user: str, password: str) -> Tuple[str, List[str]]:
    """Returns (active_script_name, all_script_names)."""
    c = _connect(host, port, user, password)
    try:
        active, names = c.listscripts()
        return active or "", names or []
    finally:
        c.logout()


def get_script(*, host: str, port: int, user: str, password: str, name: str) -> str:
    c = _connect(host, port, user, password)
    try:
        body = c.getscript(name)
        if body is None:
            raise RuntimeError(f"Script '{name}' not found")
        return body
    finally:
        c.logout()


def activate(*, host: str, port: int, user: str, password: str, name: str) -> None:
    c = _connect(host, port, user, password)
    try:
        ok = c.setactive(name)
        if not ok:
            raise RuntimeError(f"setactive failed: {c.errmsg or 'unknown error'}")
    finally:
        c.logout()


def delete(*, host: str, port: int, user: str, password: str, name: str) -> None:
    c = _connect(host, port, user, password)
    try:
        ok = c.deletescript(name)
        if not ok:
            raise RuntimeError(f"deletescript failed: {c.errmsg or 'unknown error'}")
    finally:
        c.logout()


def load_bundled_script() -> Tuple[str, str]:
    """Return (script_name, script_text) for the bundled calinvite.sieve."""
    path = Path(__file__).resolve().parent.parent / "sieve" / "calinvite.sieve"
    if not path.exists():
        raise RuntimeError(f"Bundled sieve script not found at {path}")
    return "calinvite", path.read_text(encoding="utf-8")
