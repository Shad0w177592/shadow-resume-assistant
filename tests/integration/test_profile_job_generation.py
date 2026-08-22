from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.security.credentials import InMemoryCredentialStore


HEADERS = {"x-shadow-session": "stage-3"}


def make_client(monkeypatch, data_root: Path) -> TestClient:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "stage-3")
    return TestClient(create_app(data_root, InMemoryCredentialStore()))


def add_entry(client: TestClient, title: str = "校园项目") -> dict:
    response = client.post(
        "/api/profile/entries",
        headers=HEADERS,
        json={
            "section_key": "project",
            "title": title,
            "payload": {"content": "负责需求梳理并完成原型", "skills": "Figma"},
        },
    )
    assert response.status_code == 201
    return response.json()


def add_job(client: TestClient, company: str) -> dict:
    response = client.post(
        "/api/jobs",
        headers=HEADERS,
        json={
            "company": company,
            "title": "AI 产品实习生",
            "jd_text": "负责 AI 产品设计",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_all_profile_fields_are_optional_and_entry_crud_works(
    monkeypatch, tmp_path: Path
) -> None:
    with make_client(monkeypatch, tmp_path / "data") as client:
        saved = client.put("/api/profile", headers=HEADERS, json={"personal_info": {}})
        assert saved.status_code == 200
        entry = add_entry(client)
        duplicate = client.post(
            f"/api/profile/entries/{entry['id']}/duplicate", headers=HEADERS
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["title"].endswith("（副本）")
        updated = client.put(
            f"/api/profile/entries/{entry['id']}",
            headers=HEADERS,
            json={
                "section_key": "other",
                "title": None,
                "payload": {"note": "自由内容"},
            },
        )
        assert updated.json()["payload"] == {"note": "自由内容"}
        deleted = client.delete(f"/api/profile/entries/{entry['id']}", headers=HEADERS)
        assert deleted.status_code == 204
        profile = client.get("/api/profile", headers=HEADERS).json()
        assert len(profile["entries"]) == 1


def test_job_crud_draft_evidence_and_job_isolation(monkeypatch, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    with make_client(monkeypatch, data_root) as client:
        client.put(
            "/api/profile",
            headers=HEADERS,
            json={"personal_info": {"name": "测试用户", "email": "user@example.test"}},
        )
        entry = add_entry(client)
        first = add_job(client, "甲公司")
        second = add_job(client, "乙公司")
        copied = client.post(f"/api/jobs/{first['id']}/duplicate", headers=HEADERS)
        assert copied.status_code == 201
        first_draft = client.post(
            f"/api/jobs/{first['id']}/generate", headers=HEADERS
        ).json()
        second_draft = client.post(
            f"/api/jobs/{second['id']}/generate", headers=HEADERS
        ).json()
        generated_report = client.get(
            f"/api/jobs/{first['id']}/match-report", headers=HEADERS
        ).json()
        assert generated_report["requirements"]
        assert first_draft["id"] != second_draft["id"]
        paragraphs = [
            paragraph
            for section in first_draft["document"]["sections"]
            for block in section["blocks"]
            for paragraph in block["paragraphs"]
        ]
        assert paragraphs
        assert all(
            paragraph["source_entry_ids"] == [entry["id"]] for paragraph in paragraphs
        )
        assert (
            client.delete(
                f"/api/jobs/{copied.json()['id']}", headers=HEADERS
            ).status_code
            == 204
        )

    # A new application process using the same directory must see the same data.
    with make_client(monkeypatch, data_root) as restarted:
        assert (
            restarted.get("/api/profile", headers=HEADERS).json()["personal_info"][
                "name"
            ]
            == "测试用户"
        )
        assert (
            restarted.get(f"/api/jobs/{first['id']}", headers=HEADERS).json()["company"]
            == "甲公司"
        )
        persisted = restarted.get(f"/api/jobs/{first['id']}/draft", headers=HEADERS)
        assert persisted.status_code == 200
        assert persisted.json()["id"] == first_draft["id"]


def test_generation_requires_nonempty_profile_entry(
    monkeypatch, tmp_path: Path
) -> None:
    with make_client(monkeypatch, tmp_path / "data") as client:
        job = add_job(client, "甲公司")
        client.post(f"/api/jobs/{job['id']}/analyze", headers=HEADERS)
        response = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert response.status_code == 422
        assert "至少一条" in response.json()["detail"]


def test_home_summarizes_local_state(monkeypatch, tmp_path: Path) -> None:
    with make_client(monkeypatch, tmp_path / "data") as client:
        add_entry(client)
        add_job(client, "甲公司")
        home = client.get("/api/home", headers=HEADERS)
        assert home.status_code == 200
        assert home.json()["profile_entry_count"] == 1
        assert len(home.json()["recent_jobs"]) == 1
        assert home.json()["data_directory"].endswith("data")
