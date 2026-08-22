import pytest


@pytest.fixture(autouse=True)
def deterministic_ai_for_automated_tests(monkeypatch):
    """Keep the test suite offline while production endpoints require OpenAI."""
    monkeypatch.setenv("SHADOW_TEST_DETERMINISTIC_AI", "1")
