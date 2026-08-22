from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.security.credentials import InMemoryCredentialStore


HEADERS = {"x-shadow-session": "version-session"}


def prepare_draft(client: TestClient) -> tuple[dict, dict]:
    client.post(
        "/api/profile/entries",
        headers=HEADERS,
        json={
            "section_key": "project",
            "title": "项目",
            "payload": {"content": "初始内容"},
        },
    )
    job = client.post(
        "/api/jobs",
        headers=HEADERS,
        json={"jd_text": "项目经验", "title": "岗位", "company": "公司"},
    ).json()
    client.post(f"/api/jobs/{job['id']}/analyze", headers=HEADERS)
    draft = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS).json()
    return job, draft


def test_versions_are_immutable_compare_and_restore_without_deleting_snapshot(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "version-session")
    app = create_app(tmp_path / "data", InMemoryCredentialStore())
    with TestClient(app) as client:
        job, draft = prepare_draft(client)
        version = client.post(
            f"/api/jobs/{job['id']}/versions",
            headers=HEADERS,
            json={"name": "投递版 1", "notes": "第一次保存"},
        )
        assert version.status_code == 201
        snapshot = version.json()["snapshot"]
        modified = draft["document"]
        modified["sections"][0]["blocks"][0]["paragraphs"][0]["text"] = "修改后的内容"
        client.put(
            f"/api/jobs/{job['id']}/draft", headers=HEADERS, json={"document": modified}
        )
        compared = client.post(
            f"/api/versions/{version.json()['id']}/compare",
            headers=HEADERS,
            json={"current_document": modified},
        ).json()
        assert compared["changes"][0]["change"] == "modified"
        unchanged_version = client.get(
            f"/api/versions/{version.json()['id']}", headers=HEADERS
        ).json()
        assert unchanged_version["snapshot"] == snapshot
        renamed = client.patch(
            f"/api/versions/{version.json()['id']}",
            headers=HEADERS,
            json={"name": "正式投递版", "notes": "仅改名称"},
        ).json()
        assert renamed["snapshot"] == snapshot
        exported = client.post(
            f"/api/versions/{version.json()['id']}/export",
            headers=HEADERS,
            json={"filename": "正式投递版", "formats": ["docx", "pdf"]},
        )
        assert exported.status_code == 200, exported.text
        assert all(Path(path).is_file() for path in exported.json()["files"])
        restored = client.post(
            f"/api/versions/{version.json()['id']}/restore", headers=HEADERS
        ).json()
        assert restored["document"] == snapshot["document"]
        assert (
            len(client.get(f"/api/jobs/{job['id']}/versions", headers=HEADERS).json())
            == 1
        )


def test_normal_edits_do_not_create_versions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "version-session")
    app = create_app(tmp_path / "data", InMemoryCredentialStore())
    with TestClient(app) as client:
        job, draft = prepare_draft(client)
        client.put(
            f"/api/jobs/{job['id']}/draft",
            headers=HEADERS,
            json={"document": draft["document"]},
        )
        assert (
            client.get(f"/api/jobs/{job['id']}/versions", headers=HEADERS).json() == []
        )
