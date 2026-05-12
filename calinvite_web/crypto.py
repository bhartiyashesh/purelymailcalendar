"""Symmetric encryption for sensitive at-rest values (mailbox passwords).

Uses Fernet (AES-128-CBC + HMAC) with a key from the FERNET_KEY env var. In
dev we auto-generate a key file at .fernet.key so the app boots without a
manual step. In production set FERNET_KEY explicitly.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet


_KEY_FILE = Path(__file__).resolve().parent.parent / ".fernet.key"


def _load_or_create_key() -> bytes:
    env = os.getenv("FERNET_KEY")
    if env:
        return env.strip().encode()
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    try:
        os.chmod(_KEY_FILE, 0o600)
    except OSError:
        pass
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt(plaintext: str) -> str:
    if plaintext is None:
        raise ValueError("encrypt() received None")
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode("utf-8")).decode("utf-8")
