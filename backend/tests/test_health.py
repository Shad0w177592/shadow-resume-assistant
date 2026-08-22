from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.security.credentials import InMemoryCredentialStore


def make_app(tmp_path: Path):
    return create_app(tmp_path / "data", InMemoryCredentialStore())


def test_health_is_available_without_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "test-secret")
    with TestClient(make_app(tmp_path)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_rejects_missing_or_wrong_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "test-secret")
    with TestClient(make_app(tmp_path)) as client:
        missing = client.get("/api/session-check")
        wrong = client.get("/api/session-check", headers={"x-shadow-session": "wrong"})
    assert missing.status_code == 401
    assert wrong.status_code == 401


def test_api_accepts_current_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "test-secret")
    with TestClient(make_app(tmp_path)) as client:
        response = client.get(
            "/api/session-check", headers={"x-shadow-session": "test-secret"}
        )
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
