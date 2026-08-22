import json
from pathlib import Path

from app.services.job_analysis_service import JobAnalysisService


def test_requirement_source_ranges_reproduce_original_text() -> None:
    jd = "负责 AI 产品设计；熟悉 Python 和 React。加分：有 Agent 项目经验。"
    requirements = JobAnalysisService.parse_requirements(jd)
    assert len(requirements) == 3
    for item in requirements:
        assert (
            jd[item["source_start"] : item["source_end"]].strip() == item["source_text"]
        )
    assert [item["requirement_type"] for item in requirements] == [
        "responsibility",
        "must_have",
        "nice_to_have",
    ]


def test_twenty_matching_cases_have_expected_evidence_behavior() -> None:
    cases = json.loads(
        (
            Path(__file__).resolve().parents[1] / "golden-ai" / "job_match_cases.json"
        ).read_text(encoding="utf-8")
    )
    assert len(cases) == 20
    for index, case in enumerate(cases):
        match = JobAnalysisService._best_match(
            case["jd"],
            [
                {
                    "id": f"entry-{index}",
                    "title": "经历",
                    "payload": {"content": case["profile"]},
                }
            ],
        )
        if case["expect"] == "evidence":
            assert match["profile_entry_id"] == f"entry-{index}", case
            assert match["status"] in {"full", "partial"}
        else:
            assert match["profile_entry_id"] is None, case
            assert match["status"] == "missing"
