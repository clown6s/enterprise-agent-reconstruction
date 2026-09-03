"""面向日志、审计载荷和错误响应的确定性脱敏。"""
import re

_PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)"), "[REDACTED_PHONE]"),
    (re.compile(r"(?<!\d)(\d{17}[0-9Xx])(?!\d)"), "[REDACTED_ID]"),
    (re.compile(r"(?<!\d)(\d{16,19})(?!\d)"), "[REDACTED_NUMBER]"),
    (re.compile(r"(?i)(password\s*[:=]\s*)[^\s,;]+"), r"\1[REDACTED]"),
)


def redact(value: str, *, max_length: int | None = None) -> str:
    """对常见密钥 / 个人身份信息脱敏，并可按需限制输出长度。"""
    if not isinstance(value, str):
        value = str(value)
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    if max_length is not None and len(value) > max_length:
        value = value[:max_length] + "...[TRUNCATED]"
    return value
