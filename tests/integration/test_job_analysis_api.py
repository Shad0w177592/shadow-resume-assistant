import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from app.persistence.database import utc_now
from app.security.credentials import InMemoryCredentialStore


HEADERS = {"x-shadow-session": "analysis-session"}


def test_analysis_report_is_traceable_and_becomes_stale(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "analysis-session")
    app = create_app(tmp_path / "data", InMemoryCredentialStore())
    with TestClient(app) as client:
        entry = client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "project",
                "title": "Agent 项目",
                "payload": {"content": "使用 Python 和 React 完成 AI Agent 产品"},
            },
        ).json()
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={
                "company": "影子科技",
                "title": "AI 产品经理",
                "jd_text": "负责 AI Agent 产品；熟悉 Python 和 React；必须会 Java。",
            },
        ).json()
        analyzed = client.post(f"/api/jobs/{job['id']}/analyze", headers=HEADERS)
        assert analyzed.status_code == 200
        report = analyzed.json()
        assert len(report["requirements"]) == 3
        assert all(
            item["evidence"] is not None or item["status"] == "missing"
            for item in report["requirements"]
        )
        assert any(
            item["evidence"] and item["evidence"]["entry_id"] == entry["id"]
            for item in report["requirements"]
        )
        assert report["stale"] is False
        client.put(
            f"/api/profile/entries/{entry['id']}",
            headers=HEADERS,
            json={
                "section_key": "project",
                "title": "Agent 项目（更新）",
                "payload": {"content": "新增岗位证据"},
            },
        )
        assert (
            client.get(f"/api/jobs/{job['id']}/match-report", headers=HEADERS).json()[
                "stale"
            ]
            is True
        )


def test_duplicate_concurrent_analysis_is_rejected_and_task_can_cancel(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "analysis-session")
    app = create_app(tmp_path / "data", InMemoryCredentialStore())
    with TestClient(app) as client:
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={"jd_text": "熟悉 Python", "company": None, "title": None},
        ).json()
        task_id = str(uuid4())
        now = utc_now()
        with app.state.services.database.connect() as connection:
            connection.execute(
                "INSERT INTO task_run(id, task_type, status, progress, payload_json, "
                "schema_version, created_at, updated_at) VALUES (?, 'job_analysis', 'running', "
                "20, ?, 1, ?, ?)",
                (task_id, json.dumps({"job_id": job["id"]}), now, now),
            )
        conflict = client.post(f"/api/jobs/{job['id']}/analyze", headers=HEADERS)
        assert conflict.status_code == 409
        cancelled = client.post(f"/api/tasks/{task_id}/cancel", headers=HEADERS)
        assert cancelled.json()["cancelled"] is True
        retried = client.post(f"/api/tasks/{task_id}/retry", headers=HEADERS)
        assert retried.status_code == 200
