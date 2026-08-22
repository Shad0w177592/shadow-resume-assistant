from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(api[_ -]?key\s*[:=]\s*)[^\s,;]+"),
]


def redact_text(value: str) -> str:
    result = value
    for pattern in SECRET_PATTERNS:
        result = pattern.sub(
            lambda match: (
                "[REDACTED]"
                if match.lastindex is None
                else f"{match.group(1)}[REDACTED]"
            ),
            result,
        )
    return result


def redact_object(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if key.lower() in {"api_key", "apikey", "authorization"}
                else redact_object(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_object(item) for item in value]
    return value
