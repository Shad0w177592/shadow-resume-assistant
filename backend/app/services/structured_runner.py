from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import ValidationError, validate


class StructuredOutputError(RuntimeError):
    pass


class TaskCancelled(RuntimeError):
    pass


@dataclass
class CancellationToken:
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


ProviderCall = Callable[[int], Awaitable[str]]


async def run_structured(
    provider_call: ProviderCall,
    schema: dict[str, Any],
    cancellation: CancellationToken | None = None,
    retries: int = 1,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        if cancellation and cancellation.cancelled:
            raise TaskCancelled("task cancelled")
        await asyncio.sleep(0)
        try:
            payload = json.loads(await provider_call(attempt))
            validate(instance=payload, schema=schema)
            return payload
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
    raise StructuredOutputError(f"structured output failed: {type(last_error).__name__}")

