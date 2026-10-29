"""Password records compatible with legacy operator hashes; no public serializer."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import unicodedata

ALGORITHM = "pbkdf2-sha256"
ITERATIONS = 600_000
MIN_PASSWORD = 12
MAX_PASSWORD = 200
_USERNAME = re.compile(r"\w[\w.-]*\w", re.UNICODE)


def username_identity(value: str) -> tuple[str, str]:
    """Display spelling and a unique, Unicode-normalized login identity."""
    display = unicodedata.normalize("NFKC", value.strip())
    identity = display.casefold()
    if not 2 <= len(display) <= 64 or not _USERNAME.fullmatch(display) or len(identity) > 128:
        raise ValueError("Use 2–64 letters, numbers, underscores, dots or hyphens for the username")
    return display, identity


def make_password_record(password: str) -> dict:
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise ValueError("Use a password between 12 and 200 characters")
    salt = secrets.token_bytes(16)
    return {
        "algorithm": ALGORITHM,
        "salt": salt.hex(),
        "iterations": ITERATIONS,
        "hash": hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS).hex(),
    }


def password_matches(record: object, password: str) -> bool:
    if not isinstance(record, dict) or record.get("algorithm") != ALGORITHM or len(password) > MAX_PASSWORD:
        return False
    try:
        salt = bytes.fromhex(record["salt"])
        expected = bytes.fromhex(record["hash"])
        iterations = int(record.get("iterations", ITERATIONS))
        if len(salt) != 16 or len(expected) != 32 or not 100_000 <= iterations <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return hmac.compare_digest(expected, actual)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
