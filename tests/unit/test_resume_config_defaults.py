import pytest

from app.services.resume_config_service import ResumeConfigService


def test_default_resume_config_is_not_shared_between_callers() -> None:
    first = ResumeConfigService.default()
    first["sections"][0]["enabled"] = False
    first["sections"][0]["max_entries"] = 2
    second = ResumeConfigService.default()
    assert second["sections"][0]["enabled"] is True
    assert second["sections"][0]["max_entries"] is None


def test_resume_config_validates_section_entry_limit() -> None:
    config = ResumeConfigService.default()
    config["sections"][0]["max_entries"] = 3
    ResumeConfigService.validate(config)

    config["sections"][0]["max_entries"] = 0
    with pytest.raises(ValueError, match="1 到 20"):
        ResumeConfigService.validate(config)
