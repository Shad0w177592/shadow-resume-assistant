import json
from pathlib import Path

import pytest

from app.security.pii import redact_payload_for_ai, redact_personal_info
from app.services.resume_config_service import ResumeConfigService


def test_pii_is_replaced_with_random_style_tokens_and_restored_locally() -> None:
    envelope = redact_personal_info(
        {
            "name": "张三",
            "phone": "13800138000",
            "email": "zhangsan@example.com",
            "city": "杭州",
        }
    )
    serialized = json.dumps(envelope.redacted, ensure_ascii=False)
    assert "张三" not in serialized
    assert "13800138000" not in serialized
    assert "zhangsan@example.com" not in serialized
    assert envelope.redacted["city"] == "杭州"
    token_text = " / ".join(envelope.mapping)
    restored = envelope.restore_text(token_text)
    assert "张三" in restored and "13800138000" in restored


def test_resume_config_rejects_invalid_layout_strategy_and_modes() -> None:
    config = ResumeConfigService.default()
    ResumeConfigService.validate(config)
    with pytest.raises(ValueError, match="模板"):
        ResumeConfigService.validate({**config, "template": "unknown"})
    with pytest.raises(ValueError, match="写作策略"):
        ResumeConfigService.validate({**config, "strategies": []})
    with pytest.raises(ValueError, match="经历取舍"):
        ResumeConfigService.validate({**config, "entry_modes": {"entry": "fabricate"}})
    with pytest.raises(ValueError, match="AI 修改栏目"):
        ResumeConfigService.validate({**config, "rewrite_sections": ["unknown"]})


def test_default_resume_sections_keep_experience_before_skills() -> None:
    default = ResumeConfigService.default()
    assert default["rewrite_sections"] == ["summary", "skills"]
    sections = sorted(default["sections"], key=lambda item: item["order"])
    assert [item["section_key"] for item in sections] == [
        "summary",
        "education",
        "work",
        "internship",
        "project",
        "campus",
        "skills",
        "awards",
        "other",
    ]


def test_legacy_default_order_is_upgraded_for_existing_jobs() -> None:
    legacy = ResumeConfigService.default()
    legacy_order = [
        "summary",
        "skills",
        "project",
        "work",
        "internship",
        "education",
        "campus",
        "awards",
        "other",
    ]
    order_by_key = {key: order for order, key in enumerate(legacy_order)}
    for section in legacy["sections"]:
        section["order"] = order_by_key[section["section_key"]]
    upgraded = ResumeConfigService._with_defaults(legacy)
    ordered = sorted(upgraded["sections"], key=lambda item: item["order"])
    assert [item["section_key"] for item in ordered[:3]] == [
        "summary",
        "education",
        "work",
    ]
    assert [item["section_key"] for item in ordered].index("skills") == 6


def test_nested_evidence_payload_masks_pii_before_ai_request() -> None:
    redacted = redact_payload_for_ai(
        {
            "contact": "请联系 13800138000 或 private@example.com",
            "nested": {"name": "张三", "address": "某小区"},
        }
    )
    serialized = json.dumps(redacted, ensure_ascii=False)
    assert "13800138000" not in serialized
    assert "private@example.com" not in serialized
    assert "张三" not in serialized
    assert "某小区" not in serialized


def test_nine_writing_strategies_are_versioned_and_forbid_fabrication() -> None:
    registry = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "backend"
            / "app"
            / "prompts"
            / "strategies.json"
        ).read_text(encoding="utf-8")
    )
    assert registry["version"] == 1
    assert len(registry["strategies"]) == 9
    assert all(item["forbidden"] for item in registry["strategies"].values())
