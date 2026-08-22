from pathlib import Path
from time import perf_counter

from app.persistence.database import Database
from app.services.generation_service import GenerationService
from app.services.job_service import JobService
from app.services.profile_service import ProfileService
from app.services.version_service import VersionService


def test_primary_lists_respond_under_200ms_at_v1_target_scale(tmp_path: Path) -> None:
    database = Database(
        tmp_path / "shadow-resume.db",
        Path(__file__).resolve().parents[2] / "backend" / "migrations",
    )
    database.migrate()
    profiles = ProfileService(database)
    jobs = JobService(database)
    profiles.save_profile({"name": "性能样例"})
    profiles.create_entry("project", "核心项目", {"content": "完成本地工作流"})
    created_jobs = [
        jobs.create(f"公司 {index}", f"岗位 {index}", "熟悉 Python", None)
        for index in range(50)
    ]
    GenerationService(database).generate(created_jobs[0]["id"])
    versions = VersionService(database)
    for index in range(200):
        versions.create(created_jobs[0]["id"], f"版本 {index + 1}")
    for index in range(99):
        profiles.create_entry(
            "other", f"补充经历 {index + 1}", {"content": f"真实资料 {index + 1}"}
        )

    checks = (
        (profiles.list_entries, 100),
        (jobs.list, 50),
        (lambda: versions.list(created_jobs[0]["id"]), 200),
    )
    for operation, expected_count in checks:
        started = perf_counter()
        result = operation()
        elapsed = perf_counter() - started
        assert len(result) == expected_count
        assert elapsed < 0.2, f"list operation took {elapsed:.3f}s at target scale"
