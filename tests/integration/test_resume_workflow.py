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
        assert body["fact_warnings"] == []
        assert paragraph["risk_flags"] == []
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


def test_selected_summary_and_skills_are_tailored_without_changing_work(
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
        if request["workflow"] == "resume_tailor_profile":
            return {
                "summary": "传媒工作培养了沟通协作能力，能够用于 AI 项目需求澄清与跨团队推进。",
                "skills": [
                    {
                        "heading": "AI Agent 项目交付",
                        "text": "能够使用 Codex 完成 AI 项目从0到1搭建。",
                        "reason": "岗位要求 AI 工具与项目落地能力",
                    },
                    {
                        "heading": "AI 信息搜集",
                        "text": "使用 ChatGPT 和 DeepSeek 搜集资料、归纳要点并整理岗位研究材料。",
                        "reason": "岗位需要 AI 信息处理能力",
                    }
                ],
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
        client.put(
            "/api/profile",
            headers=HEADERS,
            json={"personal_info": {"name": "杨丰铭", "summary": "原来的自我介绍"}},
        )
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
        config["rewrite_sections"] = ["summary", "skills"]
        for section in config["sections"]:
            section["enabled"] = section["section_key"] in {"work", "skills", "summary"}
        saved = client.put(
            f"/api/jobs/{job['id']}/resume-config",
            headers=HEADERS,
            json={"config": config},
        )
        assert saved.status_code == 200, saved.text

        generated = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert generated.status_code == 200, generated.text
        body = generated.json()
        sections = {
            section["section_key"]: section for section in body["document"]["sections"]
        }
        assert body["document"]["personal_info"]["headline"] == ""
        assert list(sections)[-1] == "summary"
        assert (
            sections["summary"]["blocks"][0]["paragraphs"][0]["text"]
            == "传媒工作培养了沟通协作能力，能够用于 AI 项目需求澄清与跨团队推进。"
        )
        assert [block["heading"] for block in sections["work"]["blocks"]] == [
            "先录入的工作",
            "后录入但高重要",
        ]
        assert [
            block["paragraphs"][0]["text"] for block in sections["work"]["blocks"]
        ] == ["保持原文一", "保持原文二"]
        assert sections["skills"]["blocks"][0]["heading"] == "AI Agent 项目交付"
        assert "AI 信息搜集" not in [
            block["heading"] for block in sections["skills"]["blocks"]
        ]
        added_skill = sections["skills"]["blocks"][0]["paragraphs"][0]
        assert added_skill["source_entry_ids"] == []
        assert "ai_added_skill" in added_skill["risk_flags"]
        assert all(
            flag == "ai_added_skill" or flag.startswith("unsupported_number:")
            for flag in added_skill["risk_flags"]
        )
        assert set(
            sections["summary"]["blocks"][0]["paragraphs"][0]["source_entry_ids"]
        ) == {first_work["id"], second_work["id"], skill["id"]}
        original_skill = next(
            block
            for block in sections["skills"]["blocks"]
            if block["heading"] == "AI 工具"
        )
        assert original_skill["paragraphs"][0]["text"].endswith("（AI 已改写）")
        assert any(
            "AI 为目标岗位补充了专业技能：AI Agent 项目交付" in warning
            for warning in body["fact_warnings"]
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


def test_tailoring_retries_generic_content_with_full_jd_context(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "resume-workflow")
    monkeypatch.delenv("SHADOW_TEST_DETERMINISTIC_AI", raising=False)
    tailor_calls = []
    original_summary = (
        "作为经济学专业应届生，四年的学习让我习惯从数据中找规律、用逻辑解释现象，"
        "因此具备较强的数据敏感度和结构化拆解能力，也养成了用数据验证想法的习惯。"
        "在过往实习和社团经历中，锻炼了良好的沟通协调与多任务推进能力，能快速融入新环境并与团队配合。"
        "对内容创作和用户洞察有一定体感，能独立完成短视频选题、拍摄与剪辑，也熟悉内容平台基本逻辑。"
        "尤其擅长将 Codex、DeepSeek 等 AI 工具融入日常工作和学习，用于信息搜集、文案撰写、"
        "数据整理和思路梳理。我自驱力强，对基础工作保持耐心，愿意持续学习岗位所需知识。"
    )
    tailored_summary = (
        "经济学专业应届生，四年学习形成从数据中识别规律、用逻辑解释业务现象的习惯，"
        "具备数据敏感度、结构化拆解和信息核验意识。运营实习中持续复盘主播招募数据，"
        "通过渠道台账和沟通记录优化跟进方式，可迁移至商品期货产业链数据维护、日常更新与异常追踪。"
        "自媒体经历覆盖选题、脚本、拍摄、剪辑和发布，能够将分散资讯整理为结构清晰的日报周报。"
        "社团活动中积累跨对象协调和多任务推进经验，可支持调研访谈、市场信息核实与研究协同。"
        "熟悉 Excel、Codex 和 DeepSeek 等工具，可用于数据整理、资料检索、内容复盘和研究提纲撰写，"
        "希望在真实业务中持续补充产业链知识并形成可复查的研究输出。"
    )

    def complete_json(self, **request):
        if request["workflow"] == "job_parse":
            return {
                "requirements": [
                    {
                        "requirement_type": "responsibility",
                        "summary": "维护产业链数据库并更新日报周报",
                        "source_text": "搜集更新产业链数据，维护数据库，更新日报、周报",
                    }
                ]
            }
        assert request["workflow"] == "resume_tailor_profile"
        tailor_calls.append(request)
        if len(tailor_calls) == 1:
            return {
                "summary": "我学习能力强，我认真负责，我能够胜任岗位。",
                "skills": [
                    {
                        "heading": "黑色系的数据研究能力",
                        "text": "可基于现有习惯整理数据。",
                        "reason": "岗位需要数据",
                    },
                    {
                        "heading": "沟通跟进与协同推进",
                        "text": "能够持续沟通并推进任务。",
                        "reason": "岗位需要协作",
                    },
                ],
            }
        return {
            "summary": tailored_summary,
            "skills": [
                {
                    "heading": "Excel 数据整理",
                    "text": (
                        "使用表格化字段、来源标记和交叉核验方法持续更新产业链数据库，"
                        "整理日度市场变化与周度跟踪结论，形成可复查的研究简报。"
                    ),
                    "reason": "对应数据库维护与日报周报职责",
                }
            ],
        }

    monkeypatch.setattr(OpenAITextProvider, "complete_json", complete_json)
    credentials = InMemoryCredentialStore()
    credentials.set("sk-test-key")
    app = create_app(tmp_path / "tailor-quality", credentials)
    with TestClient(app) as client:
        client.put(
            "/api/profile",
            headers=HEADERS,
            json={"personal_info": {"name": "候选人", "summary": original_summary}},
        )
        client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "work",
                "title": "内容运营",
                "payload": {"content": "负责主播招募、数据复盘与问题协调"},
            },
        )
        jd_text = (
            "搜集更新产业链数据，维护数据库，更新日报、周报，并参与市场分析和调研。"
        )
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={"jd_text": jd_text, "title": "商品期货研究员", "company": "目标机构"},
        ).json()
        assert (
            client.post(f"/api/jobs/{job['id']}/analyze", headers=HEADERS).status_code
            == 200
        )
        config = client.get(
            f"/api/jobs/{job['id']}/resume-config", headers=HEADERS
        ).json()["config"]
        config["rewrite_sections"] = ["summary", "skills"]
        saved = client.put(
            f"/api/jobs/{job['id']}/resume-config",
            headers=HEADERS,
            json={"config": config},
        )
        assert saved.status_code == 200, saved.text
        generated = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert generated.status_code == 200, generated.text

    assert len(tailor_calls) == 2
    assert tailor_calls[0]["payload"]["target_job"]["jd_text"] == jd_text
    assert tailor_calls[0]["payload"]["requirements"][0]["source_text"].startswith(
        "搜集更新"
    )
    issues = tailor_calls[1]["payload"]["quality_issues"]
    assert any("空泛评价" in issue for issue in issues)
    assert any("行业包装" in issue for issue in issues)
    assert any("短于原文篇幅目标" in issue for issue in issues)
    sections = {
        section["section_key"]: section
        for section in generated.json()["document"]["sections"]
    }
    summary = sections["summary"]["blocks"][0]["paragraphs"][0]["text"]
    assert "产业链数据维护" in summary
    assert "能够胜任" not in summary
    target = tailor_calls[0]["payload"]["summary_style_target"]
    assert target["character_min"] <= len(original_summary.replace(" ", ""))
    assert len(summary.replace(" ", "")) >= target["character_min"]
    assert "黑色系数据研究能力" in tailor_calls[0]["instructions"]
    assert "语义重叠" in tailor_calls[0]["instructions"]
    assert "Excel、SQL" in tailor_calls[0]["instructions"]
    assert sections["skills"]["blocks"][0]["heading"] == "Excel 数据整理"
