import pytest

from app.chat.adapters.memory_rate_limiter import MemoryRateLimiter
from app.chat.security.redaction import redact


def test_redacts_secrets_and_pii():
    text = "Bearer abcdefghijklmnop password=secret sk-abcdefghijklmnop 13800138000"
    safe = redact(text)
    assert "abcdefghijklmnop" not in safe
    assert "secret" not in safe
    assert "13800138000" not in safe


def test_redact_truncates():
    assert redact("x" * 20, max_length=10).endswith("...[TRUNCATED]")


def test_rate_limiter_is_per_key():
    limiter = MemoryRateLimiter(limit=1, window_seconds=60)
    assert limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")


def test_rate_limiter_rejects_invalid_config():
    with pytest.raises(ValueError):
        MemoryRateLimiter(limit=0)
