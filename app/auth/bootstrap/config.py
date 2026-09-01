"""Auth configuration; no adapter construction here."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthSettings:
    access_token_ttl_seconds: int = 900      # 15 分钟
    refresh_token_ttl_seconds: int = 604800  # 7 天
    token_length: int = 32


def read_auth_settings() -> AuthSettings:
    return AuthSettings(
        access_token_ttl_seconds=int(os.getenv("AUTH_ACCESS_TTL", "900")),
        refresh_token_ttl_seconds=int(os.getenv("AUTH_REFRESH_TTL", "604800")),
        token_length=int(os.getenv("AUTH_TOKEN_LENGTH", "32")),
    )