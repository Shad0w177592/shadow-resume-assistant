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
            with path.open("rb") as stream:
                result = OpenAI(**client_options).audio.transcriptions.create(
                    model=str(settings.get("transcription_model") or "gpt-transcribe"),
                    file=stream,
                    language="zh",
                )
            return result.text.strip()
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
