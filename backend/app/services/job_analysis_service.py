from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from app.persistence.database import Database, utc_now
from app.services.ai_schemas import JOB_PARSE_SCHEMA
from app.services.job_service import JobService
from app.services.openai_provider import AIProviderError, OpenAITextProvider
from app.services.profile_service import ProfileService

TYPE_RULES = [
    ("education", ("学历", "本科", "硕士", "专业")),
    ("nice_to_have", ("加分", "优先", "最好", "有以下经验")),
    ("must_have", ("必须", "要求", "熟悉", "掌握", "具备")),
]
STOP_WORDS = {"负责", "要求", "相关", "以上", "以及", "能够", "具有", "具备", "优先"}
GENERIC_CHINESE_TOKENS = {
    "经验",
    "能力",
    "工作",
    "相关",
    "以上",
    "要求",
    "负责",
    "熟悉",
    "掌握",
    "具备",
    "优先",
}


class AnalysisConflictError(RuntimeError):
    pass


class JobAnalysisService:
    def __init__(self, database: Database, provider: OpenAITextProvider | None = None) -> None:
        self.database = database
        self.provider = provider
        self.jobs = JobService(database)
        self.profiles = ProfileService(database)

    def analyze(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        active = self._active_task(job_id)
        if active:
            raise AnalysisConflictError(active)
        task_id = str(uuid4())
        now = utc_now()
        self._save_task(task_id, job_id, "running", 5)
        try:
            requirements = (
                self._parse_requirements_with_ai(job["jd_text"])
                if self.provider
                else self.parse_requirements(job["jd_text"])
            )
            entries = self.profiles.list_entries()
            with self.database.transaction() as connection:
                connection.execute("DELETE FROM job_requirement WHERE job_target_id=?", (job_id,))
                for requirement in requirements:
                    requirement_id = str(uuid4())
                    connection.execute(
                        "INSERT INTO job_requirement(id, job_target_id, requirement_type, summary, "
                        "source_text, source_start, source_end, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            requirement_id,
                            job_id,
                            requirement["requirement_type"],
                            requirement["summary"],
                            requirement["source_text"],
                            requirement["source_start"],
                            requirement["source_end"],
                            now,
                            now,
                        ),
                    )
                    match = self._best_match(requirement["summary"], entries)
                    connection.execute(
                        "INSERT INTO evidence_link(id, job_requirement_id, profile_entry_id, "
                        "status, reason, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(uuid4()),
                            requirement_id,
                            match["profile_entry_id"],
                            match["status"],
                            match["reason"],
                            now,
                            now,
                        ),
                    )
                connection.execute(
                    "UPDATE job_target SET status='analyzed', updated_at=? WHERE id=?",
                    (now, job_id),
                )
            self._save_task(task_id, job_id, "completed", 100)
            return {"task_id": task_id, **self.report(job_id)}
        except Exception as error:
            self._save_task(task_id, job_id, "failed", 100, str(error))
            raise

    def report(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT r.id, r.requirement_type, r.summary, r.source_text, r.source_start, "
                "r.source_end, r.updated_at, e.profile_entry_id, e.status, e.reason, "
                "p.title, p.payload_json FROM job_requirement r "
                "LEFT JOIN evidence_link e ON e.job_requirement_id=r.id "
                "LEFT JOIN profile_section_entry p ON p.id=e.profile_entry_id "
                "WHERE r.job_target_id=? ORDER BY r.source_start",
                (job_id,),
            ).fetchall()
            latest_profile = connection.execute(
                "SELECT MAX(updated_at) FROM profile_section_entry WHERE deleted_at IS NULL"
            ).fetchone()[0]
        requirements = []
        latest_analysis = None
        for row in rows:
            latest_analysis = max(latest_analysis or row[6], row[6])
            requirements.append(
                {
                    "id": row[0],
                    "requirement_type": row[1],
                    "summary": row[2],
                    "source_text": row[3],
                    "source_start": row[4],
                    "source_end": row[5],
                    "status": row[8],
                    "reason": row[9],
                    "evidence": None
                    if row[7] is None
                    else {"entry_id": row[7], "title": row[10], "payload": json.loads(row[11])},
                }
            )
        return {
            "job": job,
            "requirements": requirements,
            "stale": bool(latest_profile and latest_analysis and latest_profile > latest_analysis),
        }

    @staticmethod
    def parse_requirements(jd_text: str) -> list[dict[str, Any]]:
        requirements = []
        for match in re.finditer(r"[^。；;\n]+[。；;]?", jd_text):
            source = match.group().strip()
            summary = source.rstrip("。；;").strip(" -•\t")
            if not summary:
                continue
            requirement_type = "responsibility"
            for candidate_type, keywords in TYPE_RULES:
                if any(keyword in summary for keyword in keywords):
                    requirement_type = candidate_type
                    break
            requirements.append(
                {
                    "requirement_type": requirement_type,
                    "summary": summary,
                    "source_text": source,
                    "source_start": match.start(),
                    "source_end": match.end(),
                }
            )
        return requirements

    def _parse_requirements_with_ai(self, jd_text: str) -> list[dict[str, Any]]:
        assert self.provider is not None
        result = self.provider.complete_json(
            workflow="job_parse",
            instructions=(
                "你只忠实拆解用户提供的岗位 JD。不得补充常识或猜测。source_text 必须逐字来自 JD；"
                "区分岗位职责、必备要求、加分项和教育要求。"
            ),
            payload={"jd_text": jd_text},
            schema=JOB_PARSE_SCHEMA,
        )
        requirements = []
        cursor = 0
        for item in result["requirements"]:
            source = item["source_text"]
            start = jd_text.find(source, cursor)
            if start < 0:
                start = jd_text.find(source)
            if start < 0:
                raise AIProviderError("invalid_output", "AI 返回了不在岗位原文中的要求，未保存结果")
            end = start + len(source)
            cursor = end
            requirements.append({**item, "source_start": start, "source_end": end})
        if not requirements:
            raise AIProviderError("invalid_output", "AI 没有识别出可用的岗位要求，未保存结果")
        return requirements

    def cancel(self, task_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT status FROM task_run WHERE id=?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row[0] in {"completed", "failed"}:
                return {"task_id": task_id, "status": row[0], "cancelled": False}
            connection.execute(
                "UPDATE task_run SET status='cancelled', updated_at=? WHERE id=?",
                (utc_now(), task_id),
            )
        return {"task_id": task_id, "status": "cancelled", "cancelled": True}

    def retry(self, task_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM task_run WHERE id=?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self.analyze(json.loads(row[0])["job_id"])

    def _active_task(self, job_id: str) -> str | None:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, payload_json FROM task_run WHERE task_type='job_analysis' "
                "AND status IN ('queued', 'running')"
            ).fetchall()
        for row in rows:
            if json.loads(row[1]).get("job_id") == job_id:
                return row[0]
        return None

    def _save_task(
        self, task_id: str, job_id: str, status: str, progress: int, error: str | None = None
    ) -> None:
        now = utc_now()
        payload = json.dumps({"job_id": job_id, "error": error}, ensure_ascii=False)
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO task_run(id, task_type, status, progress, payload_json, "
                "schema_version, created_at, updated_at) "
                "VALUES (?, 'job_analysis', ?, ?, ?, 1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, progress=excluded.progress, "
                "payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (task_id, status, progress, payload, now, now),
            )

    @classmethod
    def _best_match(cls, requirement: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        requirement_tokens = cls._tokens(requirement)
        best_entry = None
        best_overlap: set[str] = set()
        for entry in entries:
            entry_text = (
                f"{entry['title'] or ''} {json.dumps(entry['payload'], ensure_ascii=False)}"
            )
            overlap = requirement_tokens & cls._tokens(entry_text)
            if len(overlap) > len(best_overlap):
                best_entry, best_overlap = entry, overlap
        if not best_entry or not best_overlap:
            return {
                "profile_entry_id": None,
                "status": "missing",
                "reason": "个人资料中暂未找到可追溯证据，可选择补充资料或不强调该要求。",
            }
        status = "full" if len(best_overlap) >= min(2, len(requirement_tokens)) else "partial"
        keywords = "、".join(sorted(best_overlap))
        return {
            "profile_entry_id": best_entry["id"],
            "status": status,
            "reason": f"资料“{best_entry['title'] or '未命名记录'}”包含关键词：{keywords}",
        }

    @staticmethod
    def _tokens(text: str) -> set[str]:
        ascii_tokens = re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{1,}", text.lower())
        chinese_tokens: set[str] = set()
        for sequence in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            for length in range(2, min(4, len(sequence)) + 1):
                chinese_tokens.update(
                    sequence[index : index + length]
                    for index in range(len(sequence) - length + 1)
                )
        return {
            token
            for token in [*ascii_tokens, *chinese_tokens]
            if token not in STOP_WORDS and token not in GENERIC_CHINESE_TOKENS
        }
