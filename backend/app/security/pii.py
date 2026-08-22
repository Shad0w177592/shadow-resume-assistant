from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PII_KEYS = {"name", "phone", "email", "id_number", "photo_file_id", "address"}
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ID_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\w)")


@dataclass(frozen=True)
class PiiEnvelope:
    redacted: dict[str, Any]
    mapping: dict[str, str]

    def restore_text(self, text: str) -> str:
        result = text
        for token, value in self.mapping.items():
            result = result.replace(token, value)
        return result


def redact_personal_info(personal_info: dict[str, Any]) -> PiiEnvelope:
    redacted = dict(personal_info)
    mapping: dict[str, str] = {}
    sequence = 1
    for key, value in personal_info.items():
        if key in PII_KEYS and value:
            token = f"[[PII_{sequence:03d}_{key.upper()}]]"
            mapping[token] = str(value)
            redacted[key] = token
            sequence += 1
    return PiiEnvelope(redacted=redacted, mapping=mapping)


def redact_text_for_ai(text: str) -> str:
    text = EMAIL_PATTERN.sub("[[EMAIL]]", text)
    text = PHONE_PATTERN.sub("[[PHONE]]", text)
    return ID_PATTERN.sub("[[ID_NUMBER]]", text)


def redact_payload_for_ai(value: Any, key: str | None = None) -> Any:
    if key in PII_KEYS and value:
        return f"[[{key.upper()}]]"
    if isinstance(value, dict):
        return {item_key: redact_payload_for_ai(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact_payload_for_ai(item) for item in value]
    if isinstance(value, str):
        return redact_text_for_ai(value)
    return value
