from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.security.credentials import InMemoryCredentialStore
from app.services.openai_provider import OpenAITextProvider

HEADERS = {"x-shadow-session": "polish-test"}


def test_polish_expands_layout_and_prefers_unused_real_experience(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "polish-test")
    app = create_app(tmp_path / "data", InMemoryCredentialStore())
    with TestClient(app) as client:
        entries = []
        for title, importance in (("首选项目", 5), ("资料库备用项目", 4)):
            entries.append(
                client.post(
                    "/api/profile/entries",
                    headers=HEADERS,
                    json={
                        "section_key": "project",
                        "title": title,
                        "payload": {"content": f"{title}的真实工作内容"},
                        "importance": importance,
                    },
                ).json()
            )
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={"jd_text": "负责项目交付", "title": "项目岗位"},
        ).json()
        config = client.get(
            f"/api/jobs/{job['id']}/resume-config", headers=HEADERS
        ).json()["config"]
        for section in config["sections"]:
            section["enabled"] = section["section_key"] == "project"
            if section["section_key"] == "project":
                section["max_entries"] = 1
        client.put(
            f"/api/jobs/{job['id']}/resume-config",
            headers=HEADERS,
            json={"config": config},
        )
        generated = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert generated.status_code == 200, generated.text

        polished = client.post(
            f"/api/jobs/{job['id']}/polish",
            headers=HEADERS,
            json={
                "methods": [
                    "expand_existing",
                    "adjust_layout",
                    "add_experience",
                ],
                "allow_fabrication": False,
            },
        )
        assert polished.status_code == 200, polished.text
        result = polished.json()
        assert result["added_real_count"] == 1
        assert result["fabricated"] is False
        document = result["draft"]["document"]
        assert document["layout_density"] == "expanded"
        blocks = document["sections"][0]["blocks"]
        assert [block["heading"] for block in blocks] == ["首选项目", "资料库备用项目"]
        assert "职责、行动与结果" in blocks[0]["paragraphs"][0]["text"]
        assert blocks[1]["paragraphs"][0]["source_entry_ids"] == [entries[1]["id"]]

        no_fabrication = client.post(
            f"/api/jobs/{job['id']}/polish",
            headers=HEADERS,
            json={"methods": ["add_experience"], "allow_fabrication": False},
        ).json()
        assert no_fabrication["added_real_count"] == 0
        assert no_fabrication["fabricated"] is False


def test_fabrication_requires_explicit_confirmation_and_is_risk_marked(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "polish-test")
    app = create_app(tmp_path / "fabrication-data", InMemoryCredentialStore())
    with TestClient(app) as client:
        client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "project",
                "title": "真实项目",
                "payload": {"content": "真实工作内容"},
            },
        )
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={"jd_text": "负责项目交付", "title": "项目岗位"},
        ).json()
        client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)

        result = client.post(
            f"/api/jobs/{job['id']}/polish",
            headers=HEADERS,
            json={"methods": ["add_experience"], "allow_fabrication": True},
        )
        assert result.status_code == 200, result.text
        payload = result.json()
        assert payload["fabricated"] is True
        assert payload["warnings"]
        paragraphs = [
            paragraph
            for section in payload["draft"]["document"]["sections"]
            for block in section["blocks"]
            for paragraph in block["paragraphs"]
        ]
        fabricated = [
            paragraph
            for paragraph in paragraphs
            if "fabricated_user_confirmed" in paragraph["risk_flags"]
        ]
        assert len(fabricated) == 1
        assert fabricated[0]["source_entry_ids"] == []

        invalid = client.post(
            f"/api/jobs/{job['id']}/polish",
            headers=HEADERS,
            json={"methods": ["unknown_method"]},
        )
        assert invalid.status_code == 422


def test_confirmed_fabrication_uses_ai_in_production_mode(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "polish-test")
    monkeypatch.setenv("SHADOW_TEST_DETERMINISTIC_AI", "1")
    credentials = InMemoryCredentialStore()
    credentials.set("sk-test-key")
    app = create_app(tmp_path / "ai-data", credentials)
    calls = []

    def complete_json(self, **request):
        calls.append(request["workflow"])
        return {
            "heading": "模拟行业项目",
            "meta": "AI 生成，待核实",
            "text": "围绕岗位需求完成示例项目内容。",
        }

    monkeypatch.setattr(OpenAITextProvider, "complete_json", complete_json)
    with TestClient(app) as client:
        client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "project",
                "title": "真实项目",
                "payload": {"content": "真实工作内容"},
            },
        )
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={"jd_text": "负责行业研究", "title": "研究岗位"},
        ).json()
        client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        monkeypatch.delenv("SHADOW_TEST_DETERMINISTIC_AI")

        result = client.post(
            f"/api/jobs/{job['id']}/polish",
            headers=HEADERS,
            json={"methods": ["add_experience"], "allow_fabrication": True},
        )
        assert result.status_code == 200, result.text
        headings = [
            block["heading"]
            for section in result.json()["draft"]["document"]["sections"]
            for block in section["blocks"]
        ]
        assert "模拟行业项目" in headings
    assert calls == ["fabricated_resume_experience"]


def test_expand_existing_sends_all_existing_sections_to_ai_and_reports_change(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "polish-test")
    monkeypatch.setenv("SHADOW_TEST_DETERMINISTIC_AI", "1")
    credentials = InMemoryCredentialStore()
    credentials.set("sk-test-key")
    app = create_app(tmp_path / "expand-ai-data", credentials)
    requests = []

    def complete_json(self, **request):
        requests.append(request)
        assert request["workflow"] == "resume_rewrite"
        assert request["payload"]["requirements"]
        assert request["payload"]["paragraphs"]
        return {
            "paragraphs": [
                {
                    "paragraph_id": item["paragraph_id"],
                    "text": f"{item['current_text']}，补充了具体行动和结果。",
                }
                for item in request["payload"]["paragraphs"]
            ]
        }

    monkeypatch.setattr(OpenAITextProvider, "complete_json", complete_json)
    with TestClient(app) as client:
        client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "project",
                "title": "真实项目",
                "payload": {"content": "完成需求整理与项目交付"},
            },
        )
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={"jd_text": "负责需求整理与项目交付。", "title": "项目岗位"},
        ).json()
        config = client.get(
            f"/api/jobs/{job['id']}/resume-config", headers=HEADERS
        ).json()["config"]
        for section in config["sections"]:
            section["enabled"] = section["section_key"] == "project"
        client.put(
            f"/api/jobs/{job['id']}/resume-config",
            headers=HEADERS,
            json={"config": config},
        )
        generated = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert generated.status_code == 200, generated.text
        before = generated.json()["document"]["sections"][0]["blocks"][0][
            "paragraphs"
        ][0]["text"]
        monkeypatch.delenv("SHADOW_TEST_DETERMINISTIC_AI")

        response = client.post(
            f"/api/jobs/{job['id']}/polish",
            headers=HEADERS,
            json={"methods": ["expand_existing"], "allow_fabrication": False},
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["changed"] is True
        after = payload["draft"]["document"]["sections"][0]["blocks"][0][
            "paragraphs"
        ][0]["text"]
        assert after != before
        assert "补充了具体行动和结果" in after
        assert len(requests) == 1
