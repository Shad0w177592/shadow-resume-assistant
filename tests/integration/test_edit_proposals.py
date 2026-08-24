import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.security.credentials import InMemoryCredentialStore


HEADERS = {"x-shadow-session": "edit-session"}


def document_non_target_hash(document: dict, target: str) -> str:
    values = []
    for section in document["sections"]:
        for block in section["blocks"]:
            for paragraph in block["paragraphs"]:
                if paragraph["paragraph_id"] != target:
                    values.append((paragraph["paragraph_id"], paragraph["text"]))
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def prepare(client: TestClient) -> tuple[dict, list[dict]]:
    entries = []
    for title, content in [
        ("项目一", "非常认真地使用 Python 完成需求分析"),
        ("项目二", "使用 React 完成交互原型"),
    ]:
        entries.append(
            client.post(
                "/api/profile/entries",
                headers=HEADERS,
                json={
                    "section_key": "project",
                    "title": title,
                    "payload": {"content": content},
                },
            ).json()
        )
    job = client.post(
        "/api/jobs",
        headers=HEADERS,
        json={"jd_text": "熟悉 Python 和 React", "title": "产品", "company": "甲"},
    ).json()
    client.post(f"/api/jobs/{job['id']}/analyze", headers=HEADERS)
    draft = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS).json()
    return draft, entries


def test_proposal_does_not_modify_before_accept_and_only_changes_target(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "edit-session")
    app = create_app(tmp_path / "data", InMemoryCredentialStore())
    with TestClient(app) as client:
        draft, _entries = prepare(client)
        paragraphs = [
            paragraph
            for section in draft["document"]["sections"]
            for block in section["blocks"]
            for paragraph in block["paragraphs"]
        ]
        target = paragraphs[0]["paragraph_id"]
        original_hash = document_non_target_hash(draft["document"], target)
        proposal = client.post(
            f"/api/jobs/{draft['job_target_id']}/edit-proposals",
            headers=HEADERS,
            json={
                "target_paragraph_id": target,
                "instruction": "写得更简洁，降低夸张程度",
                "save_scope": "current_resume",
            },
        )
        assert proposal.status_code == 201
        assert proposal.json()["before_text"] != proposal.json()["after_text"]
        unchanged = client.get(
            f"/api/jobs/{draft['job_target_id']}/draft", headers=HEADERS
        ).json()
        assert unchanged["document"] == draft["document"]
        accepted = client.post(
            f"/api/edit-proposals/{proposal.json()['id']}/accept", headers=HEADERS
        )
        assert accepted.json()["status"] == "accepted"
        changed = client.get(
            f"/api/jobs/{draft['job_target_id']}/draft", headers=HEADERS
        ).json()["document"]
        assert document_non_target_hash(changed, target) == original_hash
        changed_target = next(
            paragraph
            for section in changed["sections"]
            for block in section["blocks"]
            for paragraph in block["paragraphs"]
            if paragraph["paragraph_id"] == target
        )
        assert changed_target["text"] == proposal.json()["after_text"]


def test_reject_fabrication_block_and_optional_profile_update(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "edit-session")
    app = create_app(tmp_path / "data", InMemoryCredentialStore())
    with TestClient(app) as client:
        draft, entries = prepare(client)
        target = draft["document"]["sections"][0]["blocks"][0]["paragraphs"][0][
            "paragraph_id"
        ]
        blocked = client.post(
            f"/api/jobs/{draft['job_target_id']}/edit-proposals",
            headers=HEADERS,
            json={"target_paragraph_id": target, "instruction": "编造一段大厂工作经历"},
        )
        assert blocked.status_code == 422
        proposal = client.post(
            f"/api/jobs/{draft['job_target_id']}/edit-proposals",
            headers=HEADERS,
            json={
                "target_paragraph_id": target,
                "instruction": "写得更简洁",
                "save_scope": "also_profile",
            },
        ).json()
        rejected = client.post(
            f"/api/edit-proposals/{proposal['id']}/reject", headers=HEADERS
        )
        assert rejected.json()["status"] == "rejected"
        assert (
            client.get(
                f"/api/jobs/{draft['job_target_id']}/draft", headers=HEADERS
            ).json()["document"]
            == draft["document"]
        )
        second = client.post(
            f"/api/jobs/{draft['job_target_id']}/edit-proposals",
            headers=HEADERS,
            json={
                "target_paragraph_id": target,
                "instruction": "写得更简洁",
                "save_scope": "also_profile",
            },
        ).json()
        client.post(f"/api/edit-proposals/{second['id']}/accept", headers=HEADERS)
        profile = client.get("/api/profile", headers=HEADERS).json()["entries"]
        updated = next(entry for entry in profile if entry["id"] == entries[0]["id"])
        assert updated["payload"]["content"] == second["after_text"]


def test_pending_proposal_survives_reload_and_new_proposal_supersedes_old_one(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "edit-session")
    app = create_app(tmp_path / "pending-data", InMemoryCredentialStore())
    with TestClient(app) as client:
        draft, _entries = prepare(client)
        target = draft["document"]["sections"][0]["blocks"][0]["paragraphs"][0][
            "paragraph_id"
        ]
        first = client.post(
            f"/api/jobs/{draft['job_target_id']}/edit-proposals",
            headers=HEADERS,
            json={"target_paragraph_id": target, "instruction": "写得更简洁"},
        ).json()
        loaded = client.get(
            f"/api/jobs/{draft['job_target_id']}/edit-proposals/pending",
            headers=HEADERS,
        ).json()
        assert [item["id"] for item in loaded] == [first["id"]]

        second = client.post(
            f"/api/jobs/{draft['job_target_id']}/edit-proposals",
            headers=HEADERS,
            json={"target_paragraph_id": target, "instruction": "表达更专业"},
        ).json()
        loaded = client.get(
            f"/api/jobs/{draft['job_target_id']}/edit-proposals/pending",
            headers=HEADERS,
        ).json()
        assert [item["id"] for item in loaded] == [second["id"]]
        with app.state.services.database.connect() as connection:
            first_status = connection.execute(
                "SELECT status FROM edit_proposal WHERE id=?", (first["id"],)
            ).fetchone()[0]
        assert first_status == "rejected"

        accepted = client.post(
            f"/api/edit-proposals/{second['id']}/accept", headers=HEADERS
        )
        assert accepted.status_code == 200
        assert client.get(
            f"/api/jobs/{draft['job_target_id']}/edit-proposals/pending",
            headers=HEADERS,
        ).json() == []