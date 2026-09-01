import pytest

from app.chat.adapters.health_checkers import CompositeHealthChecker, configured
from app.chat.adapters.memory_usage_meter import MemoryUsageMeter


def test_usage_meter_aggregates_per_key():
    meter = MemoryUsageMeter()
    meter.record("t:u", input_chars=10, output_chars=5, duration_ms=20)
    meter.record("t:u", input_chars=3, output_chars=2, duration_ms=30)
    snap = meter.snapshot()
    assert snap["t:u"]["requests"] == 2
    assert snap["t:u"]["input_chars"] == 13
    assert snap["t:u"]["output_chars"] == 7
    assert snap["t:u"]["duration_ms"] == 50


def test_usage_meter_rejects_empty_key():
    with pytest.raises(ValueError):
        MemoryUsageMeter().record("", input_chars=1, output_chars=1, duration_ms=1)


def test_health_checker_all_ok():
    checker = CompositeHealthChecker({"mysql": lambda: True, "redis": lambda: True})
    assert checker.statuses() == {"mysql": "ok", "redis": "ok"}
    assert checker.check() is True


def test_health_checker_partial_failure_and_redaction():
    def boom():
        raise RuntimeError("secret dsn and password exposed")
    checker = CompositeHealthChecker({"mysql": boom, "redis": lambda: True})
    statuses = checker.statuses()
    assert statuses["mysql"] == "unavailable"
    assert statuses["redis"] == "ok"
    assert "secret" not in str(statuses)
    assert "password" not in str(statuses)
    assert checker.check() is False


def test_configured_check():
    assert configured("abc")() == "ok"
    assert configured("")() == "not_configured"
    assert configured(None)() == "not_configured"
