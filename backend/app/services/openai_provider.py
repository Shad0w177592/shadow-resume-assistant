from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from jsonschema import ValidationError, validate
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    RateLimitError,
)

from app.persistence.database import Database
from app.security.credentials import CredentialStore


class AIProviderError(RuntimeError):
    def __init__(self, code: str, user_message: str, *, retryable: bool = False) -> None:
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.retryable = retryable


ClientFactory = Callable[..., Any]


class OpenAITextProvider:
    """Stateless OpenAI-compatible adapter; business services remain provider-neutral."""

    def __init__(
        self,
        credentials: CredentialStore,
        database: Database,
        client_factory: ClientFactory = OpenAI,
    ) -> None:
        self.credentials = credentials
        self.database = database
        self.client_factory = client_factory

    def complete_json(
        self,
        *,
        workflow: str,
        instructions: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
        max_output_tokens: int = 4000,
    ) -> dict[str, Any]:
        api_key = self.credentials.get()
        if not api_key:
            raise AIProviderError("missing_key", "请先在设置中配置 OpenAI API Key")
        settings = self.database.get_setting(
            "ai_settings", {"provider": "openai", "model": "gpt-5-mini"}
        )
        if settings.get("provider") != "openai":
            raise AIProviderError("unsupported_provider", "当前版本仅支持 OpenAI 文本服务")
        model = str(settings.get("model") or "gpt-5-mini")
        api_mode = str(settings.get("api_mode") or "responses")
        if api_mode not in {"responses", "chat_completions"}:
            raise AIProviderError("bad_request", "接口模式无效，请在设置中重新选择")
        base_url = str(settings.get("base_url") or "").strip()
        timeout_seconds = 180.0 if base_url else 120.0
        client_options = {
            "api_key": api_key,
            "timeout": timeout_seconds,
            "max_retries": 0 if base_url else 1,
        }
        if base_url:
            client_options["base_url"] = base_url
        client = self.client_factory(**client_options)
        try:
            if api_mode == "chat_completions":
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": self._chat_system_prompt(instructions, schema),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    ],
                    max_tokens=max_output_tokens,
                )
                content = response.choices[0].message.content
                if not isinstance(content, str) or not content.strip():
                    raise json.JSONDecodeError("empty chat completion", "", 0)
                result = json.loads(self._strip_json_fence(content))
            else:
                response = client.responses.create(
                    model=model,
                    store=False,
                    instructions=instructions,
                    input=json.dumps(payload, ensure_ascii=False),
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": workflow,
                            "strict": True,
                            "schema": schema,
                        },
                        "verbosity": "low",
                    },
                    max_output_tokens=max_output_tokens,
                    metadata={"workflow": workflow, "prompt_version": "1.0.0"},
                )
                result = json.loads(response.output_text)
            validate(instance=result, schema=schema)
            return result
        except AuthenticationError as error:
            message = (
                "中转网关拒绝了 API Key，请检查网关密钥和 Base URL"
                if base_url
                else "OpenAI API Key 无效，请在设置中更新"
            )
            raise AIProviderError("invalid_key", message) from error
        except RateLimitError as error:
            raise AIProviderError(
                "rate_limit", "AI 服务请求受限或额度不足，请稍后重试并检查账户额度", retryable=True
            ) from error
        except NotFoundError as error:
            raise AIProviderError(
                "model_unavailable", f"当前 AI 服务不支持模型 {model}，请在设置中更换"
            ) from error
        except APITimeoutError as error:
            target = "AI 中转网关" if base_url else "OpenAI 服务"
            raise AIProviderError(
                "timeout",
                f"{target}响应超时（已等待 {int(timeout_seconds)} 秒）。"
                "余额充足时也可能是模型线路拥堵，请稍后重试或在设置中更换模型",
                retryable=True,
            ) from error
        except APIConnectionError as error:
            raise AIProviderError(
                "network",
                "无法建立到 AI 服务的网络连接，请检查网络、DNS 和 Base URL 后重试；"
                "本地资料和草稿没有丢失",
                retryable=True,
            ) from error
        except BadRequestError as error:
            message = (
                "中转网关拒绝了 Chat Completions 请求，请确认模型名称和网关权限"
                if api_mode == "chat_completions" and base_url
                else "AI 请求无法处理，请检查模型配置或缩短内容"
            )
            raise AIProviderError("bad_request", message) from error
        except APIStatusError as error:
            status = getattr(error, "status_code", None)
            suffix = f"（HTTP {status}）" if status else ""
            message = (
                f"中转网关返回错误{suffix}，请检查接口模式、模型名称或网关状态"
                if base_url
                else f"OpenAI 服务返回错误{suffix}，请稍后重试"
            )
            raise AIProviderError("upstream_error", message, retryable=True) from error
        except (json.JSONDecodeError, ValidationError) as error:
            raise AIProviderError(
                "invalid_output", "AI 返回格式无效，未保存本次结果，请重新生成", retryable=True
            ) from error

    @staticmethod
    def _chat_system_prompt(instructions: str, schema: dict[str, Any]) -> str:
        schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        return (
            f"{instructions}\n\n"
            "你必须只返回一个符合下方 JSON Schema 的 JSON 对象。"
            "不要返回 Markdown 代码围栏、解释或额外文字。\n"
            f"JSON Schema：{schema_text}"
        )

    @staticmethod
    def _strip_json_fence(content: str) -> str:
        value = content.strip()
        if value.startswith("```") and value.endswith("```"):
            lines = value.splitlines()
            if len(lines) >= 3:
                return "\n".join(lines[1:-1]).strip()
        return value


def provider_error_status(error: AIProviderError) -> int:
    if error.code in {"missing_key", "invalid_key", "unsupported_provider", "bad_request"}:
        return 422
    return 503
