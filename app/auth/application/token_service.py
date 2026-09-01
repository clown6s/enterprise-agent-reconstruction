"""Revocable opaque token service.

The raw token is returned to the caller once; only its SHA-256 is persisted,
matching the `*_hash CHAR(64)` columns in the auth schema. A token can be
revoked by removing/marking the session row, so it is not a stateless JWT.
"""
import hashlib
import secrets


def generate_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()