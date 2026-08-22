import json
from pathlib import Path

from app.services.fact_checker import check_hard_facts


ROOT = Path(__file__).resolve().parents[2]


def test_twenty_golden_fact_cases() -> None:
    payload = json.loads((ROOT / "tests/golden-ai/fact_cases.json").read_text(encoding="utf-8"))
    assert len(payload["cases"]) >= 20
    for case in payload["cases"]:
        result = check_hard_facts(case["source"], case["generated"])
        assert result.allowed is case["allowed"], case["id"]

