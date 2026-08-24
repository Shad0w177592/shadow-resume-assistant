from app.services.resume_workflow_service import ResumeWorkflowService


def test_skill_quality_rejects_semantically_duplicate_ai_skills() -> None:
    result = {
        "summary": "",
        "skills": [
            {
                "heading": "AI 信息搜集",
                "text": "使用 ChatGPT 和 DeepSeek 检索公开资料、归纳要点并整理成岗位研究材料。",
            },
            {
                "heading": "AI 工具应用",
                "text": "使用 Codex 和生成式 AI 完成资料整理、文案撰写与工作流辅助。",
            },
        ],
    }

    issues = ResumeWorkflowService._tailor_quality_issues(
        result,
        {"skills"},
        {"character_min": 0, "character_max": 999, "sentence_target": 0},
    )

    assert any("语义重复" in issue for issue in issues)


def test_data_skill_quality_requires_concrete_tools() -> None:
    result = {
        "summary": "",
        "skills": [
            {
                "heading": "数据复盘分析",
                "text": "按渠道、时间和结果拆解变化，持续复盘业务表现并输出阶段性结论。",
            }
        ],
    }

    issues = ResumeWorkflowService._tailor_quality_issues(
        result,
        {"skills"},
        {"character_min": 0, "character_max": 999, "sentence_target": 0},
    )

    assert any("Excel、SQL" in issue for issue in issues)


def test_data_skill_with_excel_and_sql_passes_tool_check() -> None:
    result = {
        "summary": "",
        "skills": [
            {
                "heading": "数据复盘分析",
                "text": "使用 Excel 和 SQL 按渠道、时间及结果拆解业务变化，输出可复查的阶段性结论。",
            }
        ],
    }

    issues = ResumeWorkflowService._tailor_quality_issues(
        result,
        {"skills"},
        {"character_min": 0, "character_max": 999, "sentence_target": 0},
    )

    assert not any("没有写明" in issue for issue in issues)


def test_summary_quality_rejects_job_first_fragmented_opening() -> None:
    result = {
        "summary": (
            "面向商品研究岗位，经济学本科训练形成用数据解释市场现象、以逻辑拆解问题的工作方式。"
            "AI 工具、数据分析、沟通协作，可用于产业链信息维护。"
        ),
        "skills": [],
    }

    issues = ResumeWorkflowService._tailor_quality_issues(
        result,
        {"summary"},
        {"character_min": 0, "character_max": 999, "sentence_target": 2},
    )

    assert any("人物定位" in issue for issue in issues)
    assert any("具体经历" in issue for issue in issues)


def test_summary_quality_accepts_identity_and_experience_narrative() -> None:
    result = {
        "summary": (
            "作为经济学专业应届生，四年学习形成了数据敏感度和结构化分析习惯。"
            "在内容运营实习中，通过复盘招募数据与维护渠道台账，积累了数据整理和跨团队沟通经验。"
            "这些能力可迁移到产业链信息维护、市场跟踪和研究材料撰写中。"
        ),
        "skills": [],
    }

    issues = ResumeWorkflowService._tailor_quality_issues(
        result,
        {"summary"},
        {"character_min": 0, "character_max": 999, "sentence_target": 3},
    )

    assert not any("人物定位" in issue for issue in issues)
    assert not any("具体经历" in issue for issue in issues)


def test_imported_skill_body_is_not_duplicated_as_meta() -> None:
    config = {
        "template": "single_column",
        "page_target": 1,
        "rewrite_sections": [],
        "sections": [
            {
                "section_key": "summary",
                "title": "自我介绍",
                "enabled": True,
                "order": 1,
                "column": "full",
            },
            {
                "section_key": "skills",
                "title": "专业技能",
                "enabled": True,
                "order": 0,
                "column": "full",
            },
        ],
    }
    document = ResumeWorkflowService._build_document(
        config,
        {},
        [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "section_key": "skills",
                "title": "AI 工具应用",
                "payload": {
                    "content": "AI 工具应用：熟练使用 ChatGPT、DeepSeek 辅助资料整理。",
                    "source": {"document_id": "source-1", "block_ids": ["p-1"]},
                },
            }
        ],
    )

    skill = next(
        section for section in document.sections if section.section_key == "skills"
    )
    assert skill.blocks[0].meta == ""


def test_summary_quality_rejects_company_repetition_and_metric_dumping() -> None:
    result = {
        "summary": (
            "作为经济学专业应届生，具备数据分析和内容运营基础。"
            "在杭州音速文化创意有限公司实习期间，累计签约30人，月均招募10人；"
            "自媒体视频最高播放量23万，并连续直播3个月，可用于电商内容运营。"
        ),
        "skills": [],
    }

    issues = ResumeWorkflowService._tailor_quality_issues(
        result,
        {"summary"},
        {"character_min": 0, "character_max": 999, "sentence_target": 3},
    )

    assert any("公司全称" in issue for issue in issues)
    assert any("过多职责数字" in issue for issue in issues)


def test_summary_quality_requires_clear_target_job_value() -> None:
    result = {
        "summary": (
            "作为经济学专业应届生，学习中形成了数据敏感度和结构化分析习惯。"
            "内容运营实习中积累了用户沟通和任务推进经验。"
        ),
        "skills": [],
    }

    issues = ResumeWorkflowService._tailor_quality_issues(
        result,
        {"summary"},
        {"character_min": 0, "character_max": 999, "sentence_target": 2},
    )

    assert any("能为目标岗位完成什么" in issue for issue in issues)


def test_configured_skill_count_controls_ai_output_and_final_section() -> None:
    class Provider:
        request = None

        def complete_json(self, **request):
            self.request = request
            return {
                "summary": "",
                "greeting_message": "Boss您好，我是杨丰铭，具备 AI 工具应用和数据复盘经验，可以支持电商运营的数据整理与活动优化，希望方便时进一步沟通。",
                "skills": [
                    {
                        "heading": "AI 工具应用",
                        "text": "使用 ChatGPT、DeepSeek 和 Codex 整理公开资料、归纳需求并辅助形成电商运营方案。",
                        "reason": "对应岗位的信息整理任务",
                    },
                    {
                        "heading": "Excel 数据分析",
                        "text": "使用 Excel 整理销售和活动数据，按渠道与周期复盘变化并输出可检查的运营结论。",
                        "reason": "对应岗位的数据复盘任务",
                    },
                    {
                        "heading": "文档与方案写作",
                        "text": "使用 Word 和 PPT 梳理活动思路、执行步骤与复盘结果，形成便于协作的方案材料。",
                        "reason": "对应岗位的方案交付任务",
                    },
                ],
            }

    config = {
        "template": "single_column",
        "page_target": 1,
        "strategies": ["concise"],
        "rewrite_sections": ["skills"],
        "sections": [
            {
                "section_key": "summary",
                "title": "自我介绍",
                "enabled": False,
                "order": 1,
                "column": "full",
                "max_entries": None,
            },
            {
                "section_key": "skills",
                "title": "专业技能",
                "enabled": True,
                "order": 0,
                "column": "full",
                "max_entries": 3,
            },
        ],
    }
    entries = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "section_key": "skills",
            "title": "AI 工具",
            "payload": {"content": "会使用 ChatGPT、DeepSeek 和 Codex"},
        }
    ]
    document = ResumeWorkflowService._build_document(config, {}, entries)
    provider = Provider()
    service = ResumeWorkflowService(None, provider)

    service._tailor_summary_and_skills(
        document,
        entries,
        [],
        {
            "title": "电商运营",
            "company": "目标公司",
            "jd_text": "负责数据复盘和活动方案",
        },
        config,
        "",
    )

    skills = next(
        section for section in document.sections if section.section_key == "skills"
    )
    assert len(skills.blocks) == 3
    assert provider.request["payload"]["skill_count_target"] == 3
    assert "统计范围、周期、前后变化" in provider.request["instructions"]
    assert "两页简历应让第一页填满、第二页超过半页" in provider.request["instructions"]
    assert provider.request["payload"]["page_layout_target"] == {
        "page_target": 1,
        "minimum_total_fill_ratio": 0.8,
        "rule": "一页内容至少覆盖页面可用区域的 80%",
    }
    assert document.greeting_message.startswith("Boss您好")
    assert "BOSS 直聘首次沟通" in provider.request["instructions"]
    assert "定位—证据—迁移—价值" in provider.request["instructions"]
    assert "严格遵守 payload.skill_count_target" in provider.request["instructions"]


def test_explicit_section_count_is_not_reduced_by_page_budget() -> None:
    config = {
        "template": "single_column",
        "page_target": 1,
        "rewrite_sections": ["work"],
        "sections": [
            {"section_key": "work", "max_entries": 3},
        ],
    }
    entries = [
        {
            "id": str(index),
            "section_key": "work",
            "title": f"工作经历 {index}",
            "payload": {"content": "职责与成果" * 180},
            "selection_mode": "ai_decide",
        }
        for index in range(3)
    ]
    warnings: list[str] = []

    result = ResumeWorkflowService._fit_budget(config, entries, warnings)

    assert len(result) == 3
    assert not any("页数预算省略" in warning for warning in warnings)


def test_layout_fill_thresholds_follow_selected_page_count() -> None:
    class Document:
        def __init__(self, length: int) -> None:
            self.length = length

        def plain_text(self) -> str:
            return "字" * self.length

    one_result = ResumeWorkflowService._layout(
        {"template": "single_column", "page_target": 1}, Document(1399)
    )
    two_result = ResumeWorkflowService._layout(
        {"template": "technical_double_column", "page_target": 2}, Document(2324)
    )

    assert one_result["status"] == "underfilled"
    assert one_result["minimum"] == 1400
    assert two_result["status"] == "underfilled"
    assert two_result["minimum"] == 2325

def test_greeting_message_quality_checks_structure_and_limit() -> None:
    valid = {
        "greeting_message": (
            "Boss您好，我是经济学专业应届生，具备 Excel 数据复盘和内容运营经验，"
            "可以支持电商岗位的日常数据跟踪与活动执行，希望方便时进一步沟通，谢谢。"
        ),
        "summary": "",
        "skills": [],
    }
    assert ResumeWorkflowService._tailor_quality_issues(
        valid, set(), {"character_min": 0, "character_max": 200, "sentence_target": 0}
    ) == []

    invalid = {
        "greeting_message": "你好，很高兴与您共事，希望给个机会。",
        "summary": "",
        "skills": [],
    }
    issues = ResumeWorkflowService._tailor_quality_issues(
        invalid, set(), {"character_min": 0, "character_max": 200, "sentence_target": 0}
    )
    assert any("过短" in issue for issue in issues)
    assert any("Boss您好" in issue for issue in issues)
    assert any("尚未入职" in issue for issue in issues)