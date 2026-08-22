import json
from pathlib import Path

from app.services.fact_checker import check_hard_facts, explain_violations


ROOT = Path(__file__).resolve().parents[2]


def test_twenty_golden_fact_cases() -> None:
    payload = json.loads((ROOT / "tests/golden-ai/fact_cases.json").read_text(encoding="utf-8"))
    assert len(payload["cases"]) >= 20
    for case in payload["cases"]:
        result = check_hard_facts(case["source"], case["generated"])
        assert result.allowed is case["allowed"], case["id"]


def test_user_provided_chinese_numbers_are_valid_evidence() -> None:
    result = check_hard_facts(
        ["负责三个项目，转化率提升百分之三十"],
        "负责 3 个项目，转化率提升 30%。",
    )

    assert result.allowed is True
    assert result.violations == ()


def test_entry_title_numbers_are_valid_but_new_numbers_are_explained() -> None:
    source = ['{"title":"负责3个项目","payload":{"content":"整理需求"}}']

    allowed = check_hard_facts(source, "负责 3 个项目并整理需求。")
    rejected = check_hard_facts(source, "负责 4 个项目并整理需求。")

    assert allowed.allowed is True
    assert rejected.allowed is False
    assert rejected.violations == ("unsupported_number:4",)
    assert explain_violations(rejected.violations) == (
        "生成内容中的数字“4”没有出现在用户资料或当前原文中"
    )
