import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.security.credentials import InMemoryCredentialStore
from app.services.openai_provider import OpenAITextProvider


HEADERS = {"x-shadow-session": "resume-workflow"}


def test_configured_workflow_respects_order_columns_modes_and_redacts_task_payload(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "resume-workflow")
    app = create_app(tmp_path / "data", InMemoryCredentialStore())
    with TestClient(app) as client:
        client.put(
            "/api/profile",
            headers=HEADERS,
            json={
                "personal_info": {
                    "name": "隐私姓名",
                    "phone": "13800138000",
                    "email": "private@example.com",
                }
            },
        )
        project = client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "project",
                "title": "Agent 项目",
                "payload": {"content": "使用 Python 完成 3 个工作流"},
            },
        ).json()
        excluded = client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "skills",
                "title": "旧技能",
                "payload": {"content": "Java"},
            },
        ).json()
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={
                "jd_text": "熟悉 Python；负责 Agent 工作流",
                "title": "AI Agent",
                "company": "甲",
            },
        ).json()
        client.post(f"/api/jobs/{job['id']}/analyze", headers=HEADERS)
        config_response = client.get(
            f"/api/jobs/{job['id']}/resume-config", headers=HEADERS
        ).json()
        config = config_response["config"]
        config["template"] = "technical_double_column"
        config["page_target"] = 2
        config["entry_modes"] = {
            project["id"]: "must_include",
            excluded["id"]: "exclude_this_resume",
        }
        for section in config["sections"]:
            section["enabled"] = section["section_key"] in {"project", "skills"}
            if section["section_key"] == "project":
                section["order"] = 0
                section["column"] = "right"
            elif section["section_key"] == "skills":
                section["order"] = 1
                section["column"] = "left"
            else:
                section["order"] += 2
        saved = client.put(
            f"/api/jobs/{job['id']}/resume-config",
            headers=HEADERS,
            json={"config": config},
        )
        assert saved.status_code == 200
        generated = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert generated.status_code == 200, generated.text
        body = generated.json()
        assert body["document"]["template"] == "technical_double_column"
        assert body["document"]["page_target"] == 2
        assert [section["section_key"] for section in body["document"]["sections"]] == [
            "project"
        ]
        assert body["document"]["sections"][0]["column"] == "right"
        ids = [
            source_id
            for section in body["document"]["sections"]
            for block in section["blocks"]
            for paragraph in block["paragraphs"]
            for source_id in paragraph["source_entry_ids"]
        ]
        assert ids == [project["id"]]
        task = client.get(
            f"/api/tasks/{body['workflow_task_id']}", headers=HEADERS
        ).json()
        assert set(task["payload"]["steps"].values()) == {"completed"}
        serialized_task = json.dumps(task["payload"], ensure_ascii=False)
        assert "隐私姓名" not in serialized_task
        assert "13800138000" not in serialized_task
        assert "private@example.com" not in serialized_task


def test_must_include_conflict_and_generation_automatically_analyzes(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "resume-workflow")
    app = create_app(tmp_path / "data", InMemoryCredentialStore())
    with TestClient(app) as client:
        entry = client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "project",
                "title": "项目",
                "payload": {"content": "真实内容"},
            },
        ).json()
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={"jd_text": "岗位要求", "title": None, "company": None},
        ).json()
        generated = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert generated.status_code == 200
        report = client.get(
            f"/api/jobs/{job['id']}/match-report", headers=HEADERS
        ).json()
        assert report["requirements"]
        config = client.get(
            f"/api/jobs/{job['id']}/resume-config", headers=HEADERS
        ).json()["config"]
        for section in config["sections"]:
            if section["section_key"] == "project":
                section["enabled"] = False
        config["entry_modes"] = {entry["id"]: "must_include"}
        client.put(
            f"/api/jobs/{job['id']}/resume-config",
            headers=HEADERS,
            json={"config": config},
        )
        conflict = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert conflict.status_code == 422
        assert "必须使用" in conflict.json()["detail"]


def test_production_api_path_calls_ai_for_job_parse_and_resume_rewrite(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "resume-workflow")
    monkeypatch.delenv("SHADOW_TEST_DETERMINISTIC_AI", raising=False)
    calls = []

    def complete_json(self, **request):
        calls.append(request["workflow"])
        if request["workflow"] == "job_parse":
            return {
                "requirements": [
                    {
                        "requirement_type": "must_have",
                        "summary": "熟悉 Python",
                        "source_text": "熟悉 Python",
                    }
                ]
            }
        return {
            "paragraphs": [
                {
                    "paragraph_id": item["paragraph_id"],
                    "text": item["current_text"].replace("做了", "完成")
                    + "，负责2个模块并交付3个项目",
                    "reason": "使用专业行动表达",
                }
                for item in request["payload"]["paragraphs"]
            ]
        }

    monkeypatch.setattr(OpenAITextProvider, "complete_json", complete_json)
    credentials = InMemoryCredentialStore()
    credentials.set("sk-test-key")
    app = create_app(tmp_path / "ai-data", credentials)
    with TestClient(app) as client:
        client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "project",
                "title": "真实项目",
                "payload": {"content": "使用 Python 做了工作流"},
            },
        )
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={"jd_text": "熟悉 Python", "title": "AI Agent", "company": "甲"},
        ).json()
        assert (
            client.post(f"/api/jobs/{job['id']}/analyze", headers=HEADERS).status_code
            == 200
        )
        config = client.get(
            f"/api/jobs/{job['id']}/resume-config", headers=HEADERS
        ).json()["config"]
        config["rewrite_sections"] = ["project"]
        client.put(
            f"/api/jobs/{job['id']}/resume-config",
            headers=HEADERS,
            json={"config": config},
        )
        generated = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert generated.status_code == 200, generated.text
        body = generated.json()
        paragraph = body["document"]["sections"][0]["blocks"][0]["paragraphs"][0]
        text = paragraph["text"]
        assert "完成工作流" in text
        assert "负责2个模块并交付3个项目" in text
        assert "数字“2”" in body["fact_warnings"][0]
        assert "数字“3”" in body["fact_warnings"][0]
        assert paragraph["risk_flags"] == [
            "unsupported_number:2",
            "unsupported_number:3",
        ]
        saved = client.get(f"/api/jobs/{job['id']}/draft", headers=HEADERS)
        assert saved.status_code == 200
        assert (
            "负责2个模块并交付3个项目"
            in saved.json()["document"]["sections"][0]["blocks"][0]["paragraphs"][0][
                "text"
            ]
        )
    assert calls == ["job_parse", "resume_rewrite"]


def test_generation_respects_section_limit_and_user_importance(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "resume-workflow")
    app = create_app(tmp_path / "priority-data", InMemoryCredentialStore())
    with TestClient(app) as client:
        entries = []
        for title, importance in (
            ("用户置顶经历", 1),
            ("高重要经历", 5),
            ("普通经历", 3),
        ):
            entries.append(
                client.post(
                    "/api/profile/entries",
                    headers=HEADERS,
                    json={
                        "section_key": "project",
                        "title": title,
                        "payload": {"content": "负责 Python 项目并完成交付"},
                        "importance": importance,
                    },
                ).json()
            )
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={
                "jd_text": "负责 Python 项目交付",
                "title": "项目岗位",
                "company": "甲",
            },
        ).json()
        config = client.get(
            f"/api/jobs/{job['id']}/resume-config", headers=HEADERS
        ).json()["config"]
        config["rewrite_sections"] = ["project"]
        for section in config["sections"]:
            section["enabled"] = section["section_key"] == "project"
            if section["section_key"] == "project":
                section["max_entries"] = 2
        config["entry_modes"] = {entries[0]["id"]: "must_include"}
        saved = client.put(
            f"/api/jobs/{job['id']}/resume-config",
            headers=HEADERS,
            json={"config": config},
        )
        assert saved.status_code == 200, saved.text

        generated = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert generated.status_code == 200, generated.text
        blocks = generated.json()["document"]["sections"][0]["blocks"]
        assert [block["heading"] for block in blocks] == [
            "用户置顶经历",
            "高重要经历",
        ]
        source_ids = [
            source_id
            for block in blocks
            for paragraph in block["paragraphs"]
            for source_id in paragraph["source_entry_ids"]
        ]
        assert entries[2]["id"] not in source_ids


def test_only_selected_sections_are_rewritten_and_reordered(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "resume-workflow")
    monkeypatch.delenv("SHADOW_TEST_DETERMINISTIC_AI", raising=False)
    requests = []

    def complete_json(self, **request):
        if request["workflow"] == "job_parse":
            return {
                "requirements": [
                    {
                        "requirement_type": "must_have",
                        "summary": "熟悉 AI 工具",
                        "source_text": "熟悉 AI 工具",
                    }
                ]
            }
        requests.append(request)
        return {
            "paragraphs": [
                {
                    "paragraph_id": item["paragraph_id"],
                    "text": item["current_text"] + "（AI 已改写）",
                    "reason": "贴合岗位",
                }
                for item in request["payload"]["paragraphs"]
            ]
        }

    monkeypatch.setattr(OpenAITextProvider, "complete_json", complete_json)
    credentials = InMemoryCredentialStore()
    credentials.set("sk-test-key")
    app = create_app(tmp_path / "selected-sections", credentials)
    with TestClient(app) as client:
        first_work = client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "work",
                "title": "先录入的工作",
                "payload": {"content": "保持原文一"},
                "importance": 1,
            },
        ).json()
        second_work = client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "work",
                "title": "后录入但高重要",
                "payload": {"content": "保持原文二"},
                "importance": 5,
            },
        ).json()
        skill = client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "skills",
                "title": "AI 工具",
                "payload": {"content": "会使用 Codex"},
                "importance": 3,
            },
        ).json()
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={"jd_text": "熟悉 AI 工具", "title": "AI 岗位", "company": "甲"},
        ).json()
        client.post(f"/api/jobs/{job['id']}/analyze", headers=HEADERS)
        config = client.get(
            f"/api/jobs/{job['id']}/resume-config", headers=HEADERS
        ).json()["config"]
        config["rewrite_sections"] = ["skills"]
        for section in config["sections"]:
            section["enabled"] = section["section_key"] in {"work", "skills"}
        saved = client.put(
            f"/api/jobs/{job['id']}/resume-config",
            headers=HEADERS,
            json={"config": config},
        )
        assert saved.status_code == 200, saved.text

        generated = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert generated.status_code == 200, generated.text
        sections = {
            section["section_key"]: section
            for section in generated.json()["document"]["sections"]
        }
        assert [block["heading"] for block in sections["work"]["blocks"]] == [
            "先录入的工作",
            "后录入但高重要",
        ]
        assert [
            block["paragraphs"][0]["text"] for block in sections["work"]["blocks"]
        ] == ["保持原文一", "保持原文二"]
        assert sections["skills"]["blocks"][0]["paragraphs"][0]["text"].endswith(
            "（AI 已改写）"
        )
        assert len(requests) == 1
        sent_source_ids = [
            source_id
            for paragraph in requests[0]["payload"]["paragraphs"]
            for source_id in paragraph["source_entry_ids"]
        ]
        assert sent_source_ids == [skill["id"]]
        assert first_work["id"] not in sent_source_ids
        assert second_work["id"] not in sent_source_ids
