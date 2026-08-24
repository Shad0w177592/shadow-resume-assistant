from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import InternalServerError

from app.security.credentials import InMemoryCredentialStore
from app.services.transcription_service import TranscriptionService


class FakeOpenAI:
    should_fail = False
    options = {}
    request = {}

    def __init__(self, api_key: str, **kwargs) -> None:
        assert api_key == "sk-test-key"
        type(self).options = {"api_key": api_key, **kwargs}
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.create))

    @classmethod
    def create(cls, **kwargs):
        cls.request = kwargs
        if cls.should_fail:
            raise RuntimeError("network")
        return SimpleNamespace(text="请把这一段写得更简洁")


def test_transcription_temp_audio_is_deleted_on_success_and_failure(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("app.services.transcription_service.OpenAI", FakeOpenAI)
    credentials = InMemoryCredentialStore()
    credentials.set("sk-test-key")
    service = TranscriptionService(credentials, tmp_path)
    assert service.transcribe(b"voice") == "请把这一段写得更简洁"
    assert list(tmp_path.iterdir()) == []
    FakeOpenAI.should_fail = True
    with pytest.raises(RuntimeError):
        service.transcribe(b"voice")
    assert list(tmp_path.iterdir()) == []
    FakeOpenAI.should_fail = False


def test_transcription_uses_configured_gateway(monkeypatch, tmp_path: Path) -> None:
    class Database:
        @staticmethod
        def get_setting(_key, _default):
            return {
                "base_url": "https://gateway.example.com/v1",
                "transcription_base_url": "https://speech.example.com/v1",
                "transcription_model": "whisper-1",
            }

    monkeypatch.setattr("app.services.transcription_service.OpenAI", FakeOpenAI)
    credentials = InMemoryCredentialStore()
    credentials.set("sk-test-key")
    service = TranscriptionService(credentials, tmp_path, Database())
    assert service.transcribe(b"voice")
    assert FakeOpenAI.options["base_url"] == "https://speech.example.com/v1"
    assert FakeOpenAI.request["model"] == "whisper-1"
    assert FakeOpenAI.request["language"] == "zh"


def test_custom_gateway_falls_back_to_whisper_after_503(
    monkeypatch, tmp_path: Path
) -> None:
    requested_models: list[str] = []

    class GatewayOpenAI(FakeOpenAI):
        @classmethod
        def create(cls, **kwargs):
            requested_models.append(kwargs["model"])
            if kwargs["model"] == "gpt-transcribe":
                request = httpx.Request(
                    "POST", "https://gateway.example.com/v1/audio/transcriptions"
                )
                response = httpx.Response(503, request=request)
                raise InternalServerError("unavailable", response=response, body=None)
            return SimpleNamespace(text="语音已经正确转成文字")

    class Database:
        @staticmethod
        def get_setting(_key, _default):
            return {
                "base_url": "https://gateway.example.com/v1",
                "transcription_model": "gpt-transcribe",
            }

    monkeypatch.setattr("app.services.transcription_service.OpenAI", GatewayOpenAI)
    credentials = InMemoryCredentialStore()
    credentials.set("sk-test-key")
    result = TranscriptionService(credentials, tmp_path, Database()).transcribe(
        b"voice"
    )
    assert result == "语音已经正确转成文字"
    assert requested_models == ["gpt-transcribe", "whisper-1"]


def test_transcription_requires_api_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="API Key"):
        TranscriptionService(InMemoryCredentialStore(), tmp_path).transcribe(b"voice")
