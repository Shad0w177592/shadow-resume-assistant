from __future__ import annotations

import os
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.main import session_guard
from app.security.credentials import InMemoryCredentialStore
from app.services.bootstrap import AppServices
from app.services.openai_provider import AIProviderError, OpenAITextProvider, provider_error_status

router = APIRouter(prefix="/api", dependencies=[Depends(session_guard)])


class BootstrapState(BaseModel):
    privacy_accepted: bool
    initialized: bool
    onboarding_step: int
    api_key_configured: bool
    data_directory: str


class OnboardingUpdate(BaseModel):
    privacy_accepted: bool | None = None
    initialized: bool | None = None
    onboarding_step: int | None = Field(default=None, ge=0, le=4)


class SettingsUpdate(BaseModel):
    provider: str = "openai"
    model: str = "gpt-5-mini"
    api_mode: Literal["responses", "chat_completions"] = "responses"
    base_url: str = ""
    voice_device_id: str | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Base URL 必须是完整的 http:// 或 https:// 地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Base URL 不能包含账号密码、查询参数或片段")
        is_local = parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not is_local:
            raise ValueError("远程 Base URL 必须使用 HTTPS；HTTP 仅允许本机地址")
        path = parsed.path.rstrip("/")
        if path.lower().endswith(("/responses", "/chat/completions")):
            raise ValueError("请填写 API 根地址（通常以 /v1 结尾），不要填写具体接口路径")
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class ApiKeyInput(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)


def services(request: Request) -> AppServices:
    return request.app.state.services


@router.get("/bootstrap", response_model=BootstrapState)
def get_bootstrap(app: Annotated[AppServices, Depends(services)]) -> BootstrapState:
    return BootstrapState(
        privacy_accepted=bool(app.database.get_setting("privacy_accepted", False)),
        initialized=bool(app.database.get_setting("initialized", False)),
        onboarding_step=int(app.database.get_setting("onboarding_step", 0)),
        api_key_configured=app.credentials.get() is not None,
        data_directory=str(app.paths.root),
    )


@router.patch("/bootstrap", response_model=BootstrapState)
def update_bootstrap(
    payload: OnboardingUpdate,
    app: Annotated[AppServices, Depends(services)],
) -> BootstrapState:
    for key, value in payload.model_dump(exclude_none=True).items():
        app.database.set_setting(key, value)
    return get_bootstrap(app)


@router.get("/settings")
def get_settings(app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    return app.database.get_setting(
        "ai_settings",
        {
            "provider": "openai",
            "model": "gpt-5-mini",
            "api_mode": "responses",
            "base_url": "",
            "voice_device_id": None,
        },
    )


@router.put("/settings")
def update_settings(
    payload: SettingsUpdate,
    app: Annotated[AppServices, Depends(services)],
) -> dict[str, Any]:
    value = payload.model_dump()
    app.database.set_setting("ai_settings", value)
    return value


@router.put("/credentials/openai")
def put_openai_key(
    payload: ApiKeyInput,
    app: Annotated[AppServices, Depends(services)],
) -> dict[str, bool]:
    settings = app.database.get_setting("ai_settings", {})
    uses_official_endpoint = not str(settings.get("base_url") or "").strip()
    if uses_official_endpoint and not payload.api_key.startswith("sk-"):
        raise HTTPException(status_code=422, detail="API Key 格式不正确")
    if os.getenv("SHADOW_TEST_DETERMINISTIC_AI") != "1":
        candidate = InMemoryCredentialStore()
        candidate.set(payload.api_key)
        try:
            OpenAITextProvider(candidate, app.database).complete_json(
                workflow="connection_test",
                instructions="返回固定的中文结构化结果。",
                payload={"request": "连接测试"},
                schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["status", "language"],
                    "properties": {
                        "status": {"const": "ok"},
                        "language": {"const": "中文"},
                    },
                },
                max_output_tokens=100,
            )
        except AIProviderError as error:
            raise HTTPException(
                status_code=provider_error_status(error), detail=error.user_message
            ) from error
    app.credentials.set(payload.api_key)
    return {"configured": True}


@router.delete("/credentials/openai")
def delete_openai_key(app: Annotated[AppServices, Depends(services)]) -> dict[str, bool]:
    app.credentials.delete()
    return {"configured": False}
