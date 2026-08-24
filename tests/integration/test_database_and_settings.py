from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.persistence.database import Database
from app.security.credentials import InMemoryCredentialStore
from app.services.openai_provider import AIProviderError, OpenAITextProvider
from app.services.data_paths import DataPaths


EXPECTED_TABLES = {
    "user_profile",
    "profile_section_entry",
    "source_document",
    "job_target",
    "job_requirement",
    "evidence_link",
    "resume_config",
    "resume_draft",
    "resume_version",
    "edit_proposal",
    "app_setting",
    "task_run",
    "backup_record",
    "import_candidate",
}


def test_initial_migration_creates_required_tables_and_settings_survive_restart(
    tmp_path: Path,
) -> None:
    paths = DataPaths.create(tmp_path / "app-data")
    migrations = Path(__file__).resolve().parents[2] / "backend" / "migrations"
    database = Database(paths.database, migrations)
    database.migrate()
    database.set_setting("initialized", True)
    with database.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        profile_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(profile_section_entry)")
        }
    assert EXPECTED_TABLES <= tables
    assert "importance" in profile_columns
    restarted = Database(paths.database, migrations)
    restarted.migrate()
    assert restarted.get_setting("initialized") is True


def test_onboarding_and_api_key_are_separated_from_sqlite(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "session")
    credentials = InMemoryCredentialStore()
    app = create_app(tmp_path / "app-data", credentials)
    headers = {"x-shadow-session": "session"}
    secret = "sk-test-secret-value"
    with TestClient(app) as client:
        initial = client.get("/api/bootstrap", headers=headers)
        assert initial.json()["initialized"] is False
        updated = client.patch(
            "/api/bootstrap",
            headers=headers,
            json={"privacy_accepted": True, "onboarding_step": 2},
        )
        configured = client.put(
            "/api/credentials/openai", headers=headers, json={"api_key": secret}
        )
    assert updated.json()["privacy_accepted"] is True
    assert configured.json() == {"configured": True}
    assert credentials.get() == secret
    database_bytes = app.state.services.paths.database.read_bytes()
    assert secret.encode() not in database_bytes


def test_invalid_api_key_does_not_replace_existing_key(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "session")
    credentials = InMemoryCredentialStore()
    credentials.set("sk-existing-secret")
    app = create_app(tmp_path / "app-data", credentials)
    with TestClient(app) as client:
        response = client.put(
            "/api/credentials/openai",
            headers={"x-shadow-session": "session"},
            json={"api_key": "invalid-key"},
        )
    assert response.status_code == 422
    assert credentials.get() == "sk-existing-secret"


def test_failed_openai_capability_check_keeps_previous_valid_key(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "session")
    monkeypatch.delenv("SHADOW_TEST_DETERMINISTIC_AI", raising=False)
    credentials = InMemoryCredentialStore()
    credentials.set("sk-existing-secret")

    def fail_check(self, **_kwargs):
        raise AIProviderError("model_unavailable", "模型不可用")

    monkeypatch.setattr(OpenAITextProvider, "complete_json", fail_check)
    app = create_app(tmp_path / "capability-data", credentials)
    with TestClient(app) as client:
        response = client.put(
            "/api/credentials/openai",
            headers={"x-shadow-session": "session"},
            json={"api_key": "sk-new-candidate"},
        )
    assert response.status_code == 503
    assert credentials.get() == "sk-existing-secret"


def test_custom_base_url_is_normalized_persisted_and_validated(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "session")
    app = create_app(tmp_path / "base-url-data", InMemoryCredentialStore())
    headers = {"x-shadow-session": "session"}
    with TestClient(app) as client:
        saved = client.put(
            "/api/settings",
            headers=headers,
            json={
                "provider": "openai",
                "model": "gateway-model",
                "api_mode": "chat_completions",
                "base_url": "https://gateway.example.com/openai/v1///",
                "transcription_model": "whisper-1",
                "voice_device_id": None,
            },
        )
        assert saved.status_code == 200
        assert saved.json()["base_url"] == "https://gateway.example.com/openai/v1"
        assert saved.json()["api_mode"] == "chat_completions"
        assert saved.json()["transcription_model"] == "whisper-1"
        assert client.get("/api/settings", headers=headers).json()["base_url"] == (
            "https://gateway.example.com/openai/v1"
        )

        for invalid in (
            "gateway.example.com/v1",
            "http://gateway.example.com/v1",
            "https://user:pass@gateway.example.com/v1",
            "https://gateway.example.com/v1/responses",
        ):
            response = client.put(
                "/api/settings",
                headers=headers,
                json={"model": "gateway-model", "base_url": invalid},
            )
            assert response.status_code == 422

        local = client.put(
            "/api/settings",
            headers=headers,
            json={"model": "local-model", "base_url": "http://127.0.0.1:8080/v1/"},
        )
        assert local.status_code == 200
        assert local.json()["base_url"] == "http://127.0.0.1:8080/v1"

        invalid_mode = client.put(
            "/api/settings",
            headers=headers,
            json={"model": "local-model", "api_mode": "legacy_completions"},
        )
        assert invalid_mode.status_code == 422

        gateway_key = client.put(
            "/api/credentials/openai",
            headers=headers,
            json={"api_key": "gateway-token-without-sk-prefix"},
        )
        assert gateway_key.status_code == 200
