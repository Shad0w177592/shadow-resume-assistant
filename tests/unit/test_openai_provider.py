from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError, OpenAI

from app.security.credentials import InMemoryCredentialStore
from app.services.openai_provider import AIProviderError, OpenAITextProvider


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status"],
    "properties": {"status": {"const": "ok"}},
}


class SettingsDatabase:
    def __init__(
        self,
        base_url: str = "",
        api_mode: str = "responses",
        provider: str = "openai",
        model: str = "gpt-5-mini",
    ) -> None:
        self.base_url = base_url
        self.api_mode = api_mode
        self.provider = provider
        self.model = model

    def get_setting(self, _key, _default):
        return {
            "provider": self.provider,
            "model": self.model,
            "api_mode": self.api_mode,
            "base_url": self.base_url,
        }


def test_provider_uses_official_deepseek_chat_completions_defaults() -> None:
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            captured["request"] = kwargs
            message = SimpleNamespace(content='{"status":"ok"}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    credentials = InMemoryCredentialStore()
    credentials.set("sk-deepseek-test")
    result = OpenAITextProvider(
        credentials,
        SettingsDatabase(provider="deepseek", model="deepseek-v4-flash"),
        Client,
    ).complete_json(workflow="deepseek", instructions="", payload={}, schema=SCHEMA)

    assert result == {"status": "ok"}
    assert captured["client"]["base_url"] == "https://api.deepseek.com"
    assert captured["request"]["model"] == "deepseek-v4-flash"
    assert "messages" in captured["request"]


def test_provider_uses_stateless_strict_structured_output_without_pii_metadata() -> (
    None
):
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.responses = SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(output_text='{"status":"ok"}')

    credentials = InMemoryCredentialStore()
    credentials.set("sk-test-key")
    result = OpenAITextProvider(credentials, SettingsDatabase(), Client).complete_json(
        workflow="test_workflow",
        instructions="只返回结构化结果",
        payload={"private": "仅位于 input"},
        schema=SCHEMA,
    )
    assert result == {"status": "ok"}
    request = captured["request"]
    assert request["store"] is False
    assert request["text"]["format"]["strict"] is True
    assert request["text"]["format"]["schema"] == SCHEMA
    assert request["metadata"] == {
        "workflow": "test_workflow",
        "prompt_version": "1.0.0",
    }
    assert "private" not in str(request["metadata"])
    assert "base_url" not in captured["client"]


def test_provider_passes_custom_base_url_to_openai_client() -> None:
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.responses = SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(output_text='{"status":"ok"}')
            )

    credentials = InMemoryCredentialStore()
    credentials.set("sk-gateway-key")
    result = OpenAITextProvider(
        credentials,
        SettingsDatabase("https://gateway.example.com/openai/v1"),
        Client,
    ).complete_json(workflow="gateway", instructions="", payload={}, schema=SCHEMA)
    assert result == {"status": "ok"}
    assert captured["base_url"] == "https://gateway.example.com/openai/v1"
    assert captured["timeout"] == 180.0
    assert captured["max_retries"] == 0


def test_gateway_timeout_is_not_reported_as_a_network_configuration_error() -> None:
    class TimeoutClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        @staticmethod
        def create(**_kwargs):
            request = httpx.Request(
                "POST", "https://gateway.example.com/v1/chat/completions"
            )
            raise APITimeoutError(request=request)

    credentials = InMemoryCredentialStore()
    credentials.set("gateway-token")
    with pytest.raises(AIProviderError) as failure:
        OpenAITextProvider(
            credentials,
            SettingsDatabase("https://gateway.example.com/v1", "chat_completions"),
            TimeoutClient,
        ).complete_json(workflow="timeout", instructions="", payload={}, schema=SCHEMA)

    assert failure.value.code == "timeout"
    assert "已等待 180 秒" in failure.value.user_message
    assert "模型线路拥堵" in failure.value.user_message


def test_provider_uses_minimal_chat_completions_request_and_validates_result() -> None:
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            captured["request"] = kwargs
            message = SimpleNamespace(content='```json\n{"status":"ok"}\n```')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    credentials = InMemoryCredentialStore()
    credentials.set("gateway-token")
    result = OpenAITextProvider(
        credentials,
        SettingsDatabase("https://www.juapi.net/v1", "chat_completions"),
        Client,
    ).complete_json(
        workflow="connection_test",
        instructions="返回固定结构",
        payload={"request": "连接测试"},
        schema=SCHEMA,
        max_output_tokens=100,
    )

    assert result == {"status": "ok"}
    assert captured["client"]["base_url"] == "https://www.juapi.net/v1"
    request = captured["request"]
    assert request["model"] == "gpt-5-mini"
    assert request["max_tokens"] == 100
    assert request["messages"][0]["role"] == "system"
    assert "JSON Schema" in request["messages"][0]["content"]
    assert request["messages"][1]["role"] == "user"
    assert "response_format" not in request
    assert "metadata" not in request


def test_chat_completions_mode_calls_gateway_chat_endpoint_with_openai_sdk() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "gateway-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"status":"ok"}'},
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    def client_factory(**kwargs):
        return OpenAI(
            **kwargs,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    credentials = InMemoryCredentialStore()
    credentials.set("gateway-token")
    result = OpenAITextProvider(
        credentials,
        SettingsDatabase("https://www.juapi.net/v1", "chat_completions"),
        client_factory,
    ).complete_json(
        workflow="connection_test", instructions="", payload={}, schema=SCHEMA
    )

    assert result == {"status": "ok"}
    assert captured["url"] == "https://www.juapi.net/v1/chat/completions"
    body = captured["body"]
    assert '"messages"' in body
    assert '"max_tokens":4000' in body
    assert '"response_format"' not in body


def test_provider_blocks_missing_key_and_invalid_structured_output() -> None:
    with pytest.raises(AIProviderError, match="API Key") as missing:
        OpenAITextProvider(InMemoryCredentialStore(), SettingsDatabase()).complete_json(
            workflow="test", instructions="", payload={}, schema=SCHEMA
        )
    assert missing.value.code == "missing_key"

    class InvalidClient:
        def __init__(self, **_kwargs):
            self.responses = SimpleNamespace(
                create=lambda **_request: SimpleNamespace(output_text="not-json")
            )

    credentials = InMemoryCredentialStore()
    credentials.set("sk-test-key")
    with pytest.raises(AIProviderError) as invalid:
        OpenAITextProvider(
            credentials, SettingsDatabase(), InvalidClient
        ).complete_json(workflow="test", instructions="", payload={}, schema=SCHEMA)
    assert invalid.value.code == "invalid_output"
