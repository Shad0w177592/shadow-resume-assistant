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
        result, {"skills"}, {"character_min": 0, "character_max": 999, "sentence_target": 0}
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
        result, {"skills"}, {"character_min": 0, "character_max": 999, "sentence_target": 0}
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
        result, {"skills"}, {"character_min": 0, "character_max": 999, "sentence_target": 0}
    )

    assert not any("没有写明" in issue for issue in issues)
