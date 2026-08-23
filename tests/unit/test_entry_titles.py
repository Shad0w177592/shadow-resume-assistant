from app.services.entry_titles import concrete_entry_title


def test_concrete_title_removes_date_and_uses_real_organization() -> None:
    assert (
        concrete_entry_title(
            "education",
            "2022.09-2026.06 聊城大学",
            {"content": "2022.09-2026.06 聊城大学\n经济学 | 本科"},
        )
        == "聊城大学"
    )
    assert (
        concrete_entry_title(
            "internship",
            "2025.7-2025.10",
            {"content": "2025.7-2025.10\n杭州音速文化创意有限公司\n实习运营"},
        )
        == "杭州音速文化创意有限公司"
    )


def test_concrete_title_uses_skill_or_project_name_instead_of_generic_label() -> None:
    assert (
        concrete_entry_title(
            "skills", "专业技能", {"content": "视频剪辑：熟练使用 Premiere"}
        )
        == "视频剪辑"
    )
    assert (
        concrete_entry_title("project", "影子简历助手：完成本地工作流", {"content": ""})
        == "影子简历助手"
    )


def test_concrete_title_keeps_an_explicit_user_title() -> None:
    assert (
        concrete_entry_title("work", "腾讯产品实习", {"content": "其他内容"})
        == "腾讯产品实习"
    )
