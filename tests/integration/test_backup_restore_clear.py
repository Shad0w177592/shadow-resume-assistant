import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.security.credentials import InMemoryCredentialStore


HEADERS = {"x-shadow-session": "backup-session"}


def test_backup_excludes_key_restores_exact_data_and_validates_hashes(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "backup-session")
    credentials = InMemoryCredentialStore()
    credentials.set("sk-super-secret-never-in-backup")
    app = create_app(tmp_path / "data", credentials)
    with TestClient(app) as client:
        entry = client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "project",
                "title": "原始项目",
                "payload": {"content": "原始内容"},
            },
        ).json()
        backup = client.post("/api/backups", headers=HEADERS)
        assert backup.status_code == 201
        backup_path = Path(backup.json()["path"])
        assert b"sk-super-secret-never-in-backup" not in backup_path.read_bytes()
        with zipfile.ZipFile(backup_path) as archive:
            assert "manifest.json" in archive.namelist()
            assert "data/app.db" in archive.namelist()
            assert all(
                "logs" not in name and "temp" not in name for name in archive.namelist()
            )
        client.put(
            f"/api/profile/entries/{entry['id']}",
            headers=HEADERS,
            json={
                "section_key": "project",
                "title": "已修改",
                "payload": {"content": "新内容"},
            },
        )
        restored = client.post(
            "/api/backups/restore", headers=HEADERS, json={"path": str(backup_path)}
        )
        assert restored.status_code == 200, restored.text
        profile = client.get("/api/profile", headers=HEADERS).json()
        assert profile["entries"][0]["title"] == "原始项目"
        assert Path(restored.json()["automatic_backup"]).exists()
        assert credentials.get() == "sk-super-secret-never-in-backup"


def test_zip_slip_tamper_and_clear_confirmation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "backup-session")
    credentials = InMemoryCredentialStore()
    credentials.set("sk-secret")
    app = create_app(tmp_path / "data", credentials)
    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../escape.txt", "bad")
        archive.writestr(
            "manifest.json", json.dumps({"backup_version": 1, "files": []})
        )
    with TestClient(app) as client:
        rejected = client.post(
            "/api/backups/restore", headers=HEADERS, json={"path": str(unsafe)}
        )
        assert rejected.status_code == 422
        wrong = client.post(
            "/api/data/clear",
            headers=HEADERS,
            json={"confirmation": "全部清除", "include_api_key": True},
        )
        assert wrong.status_code == 422
        client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={"section_key": "project", "title": "待清除", "payload": {}},
        )
        cleared = client.post(
            "/api/data/clear",
            headers=HEADERS,
            json={"confirmation": "清除全部数据", "include_api_key": True},
        )
        assert cleared.json()["cleared"] is True
        assert client.get("/api/profile", headers=HEADERS).json()["entries"] == []
        assert credentials.get() is None
