from __future__ import annotations

from pathlib import Path
from uuid import uuid4

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


class TranscriptionService:
    def __init__(
        self, credentials: CredentialStore, temp_dir: Path, database: Database | None = None
    ) -> None:
        self.credentials = credentials
        self.temp_dir = temp_dir
        self.database = database

    def transcribe(self, audio: bytes, suffix: str = ".webm") -> str:
        api_key = self.credentials.get()
        if not api_key:
            raise ValueError("请先在设置中配置 OpenAI API Key")
        path = self.temp_dir / f"voice-{uuid4()}{suffix}"
        path.write_bytes(audio)
        try:
            client_options = {"api_key": api_key}
            settings = {}
            if self.database:
                settings = self.database.get_setting("ai_settings", {})
                base_url = str(settings.get("base_url") or "").strip()
                if base_url:
                    client_options["base_url"] = base_url
            configured_model = str(
                settings.get("transcription_model") or "gpt-transcribe"
            ).strip()
            models = [configured_model]
            if client_options.get("base_url") and configured_model == "gpt-transcribe":
                models.append("whisper-1")

            client = OpenAI(**client_options)
            last_compatibility_error: APIStatusError | None = None
            for model in models:
                try:
                    with path.open("rb") as stream:
                        result = client.audio.transcriptions.create(
                            model=model,
                            file=stream,
                            language="zh",
                        )
                    return result.text.strip()
                except (BadRequestError, NotFoundError) as error:
                    last_compatibility_error = error
                except APIStatusError as error:
                    if error.status_code != 503:
                        raise
                    last_compatibility_error = error

            attempted = "、".join(models)
            status = (
                f"HTTP {last_compatibility_error.status_code}"
                if last_compatibility_error is not None
                else "未知错误"
            )
            raise ValueError(
                f"当前 Base URL 的语音接口不可用（已尝试 {attempted}，{status}）。"
                "请联系网关确认其支持 /audio/transcriptions，或改用支持语音转写的 API 服务"
            ) from last_compatibility_error
        except AuthenticationError as error:
            raise ValueError("语音转写鉴权失败，请检查 API Key") from error
        except (BadRequestError, NotFoundError) as error:
            model = str(settings.get("transcription_model") or "gpt-transcribe")
            raise ValueError(
                f"当前 AI 服务不支持语音转写模型 {model}，请在设置中换成网关支持的模型"
            ) from error
        except RateLimitError as error:
            raise RuntimeError("语音转写额度不足或请求受限，请稍后重试") from error
        except (APITimeoutError, APIConnectionError) as error:
            raise RuntimeError("无法连接语音转写服务，请检查网络和 Base URL") from error
        except APIStatusError as error:
            raise RuntimeError(
                f"语音转写服务返回错误（HTTP {error.status_code}）"
            ) from error
        finally:
            path.unlink(missing_ok=True)
