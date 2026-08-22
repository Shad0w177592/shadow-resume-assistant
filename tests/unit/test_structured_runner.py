import asyncio

import pytest

from app.services.structured_runner import CancellationToken, TaskCancelled, run_structured


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status"],
    "properties": {"status": {"const": "ok"}},
}


def test_structured_output_retries_once() -> None:
    async def provider(attempt: int) -> str:
        return "not-json" if attempt == 0 else '{"status":"ok"}'

    result = asyncio.run(run_structured(provider, SCHEMA, retries=1))
    assert result == {"status": "ok"}


def test_structured_output_honors_cancellation() -> None:
    token = CancellationToken()
    token.cancel()

    async def provider(_: int) -> str:
        return '{"status":"ok"}'

    with pytest.raises(TaskCancelled):
        asyncio.run(run_structured(provider, SCHEMA, cancellation=token))

