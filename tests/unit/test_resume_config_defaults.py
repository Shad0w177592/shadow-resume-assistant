from app.services.resume_config_service import ResumeConfigService


def test_default_resume_config_is_not_shared_between_callers() -> None:
    first = ResumeConfigService.default()
    first["sections"][0]["enabled"] = False
    second = ResumeConfigService.default()
    assert second["sections"][0]["enabled"] is True
