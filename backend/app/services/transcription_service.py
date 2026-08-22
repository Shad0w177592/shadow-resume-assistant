from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from openai import OpenAI

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
            if self.database:
                settings = self.database.get_setting("ai_settings", {})
                base_url = str(settings.get("base_url") or "").strip()
                if base_url:
                    client_options["base_url"] = base_url
            with path.open("rb") as stream:
                result = OpenAI(**client_options).audio.transcriptions.create(
                    model="gpt-4o-mini-transcribe", file=stream, language="zh"
                )
            return result.text.strip()
        finally:
            path.unlink(missing_ok=True)
