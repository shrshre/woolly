"""One-time password-reset tokens. Store the hash; email the raw value."""

import hashlib
import secrets


def generate_reset_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hex). Store only the hash; email the raw token."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_reset_token(raw)


def hash_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
