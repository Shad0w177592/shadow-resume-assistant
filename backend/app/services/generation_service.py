from __future__ import annotations

import json
from collections import defaultdict
from typing import Any
from uuid import uuid4

from app.domain.resume import (
    PersonalInfo,
    ResumeBlock,
    ResumeDocument,
    ResumeParagraph,
    ResumeSection,
    ResumeTemplate,
)
from app.persistence.database import Database, utc_now
from app.services.job_service import JobService
from app.services.profile_service import ProfileService

SECTION_TITLES = {
    "summary": "个人简介",
    "education": "教育经历",
    "work": "工作经历",
    "internship": "实习经历",
    "project": "项目经历",
    "campus": "校园、社团及志愿经历",
    "skills": "专业技能",
    "awards": "证书与奖项",
    "other": "其他经历",
}


class GenerationService:
    """Deterministic stage-3 generator; later stages replace selection/writing with AI."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.profiles = ProfileService(database)
        self.jobs = JobService(database)

    def generate(self, job_id: str) -> dict[str, Any]:
        self.jobs.get(job_id)
        profile = self.profiles.get_profile()
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in self.profiles.list_entries():
            if self._entry_text(entry):
                grouped[entry["section_key"]].append(entry)
        if not grouped:
            raise ValueError("请先填写至少一条有内容的个人资料")

        sections: list[ResumeSection] = []
        for order, (section_key, entries) in enumerate(grouped.items()):
            blocks = [self._entry_block(entry) for entry in entries]
            sections.append(
                ResumeSection(
                    section_id=str(uuid4()),
                    section_key=section_key,
                    title=SECTION_TITLES.get(section_key, section_key),
                    order=order,
                    blocks=blocks,
                )
            )
        personal = profile["personal_info"]
        contacts = [str(personal[key]) for key in ("phone", "email", "city") if personal.get(key)]
        document = ResumeDocument(
            resume_id=uuid4(),
            template=ResumeTemplate.SINGLE_COLUMN,
            page_target=1,
            personal_info=PersonalInfo(
                name=str(personal.get("name") or ""),
                headline=str(personal.get("summary") or ""),
                contacts=contacts,
                photo_file_id=personal.get("photo_file_id"),
            ),
            sections=sections,
        )
        return self._save(job_id, document)

    def get_draft(self, job_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, job_target_id, document_json, status, created_at, updated_at "
                "FROM resume_draft WHERE job_target_id=? ORDER BY updated_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        result = dict(row)
        result["document"] = json.loads(result.pop("document_json"))
        return result

    def _save(self, job_id: str, document: ResumeDocument) -> dict[str, Any]:
        now = utc_now()
        payload = document.model_dump_json()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id FROM resume_draft WHERE job_target_id=? "
                "ORDER BY updated_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE resume_draft SET document_json=?, status='draft', "
                    "updated_at=? WHERE id=?",
                    (payload, now, row[0]),
                )
            else:
                connection.execute(
                    "INSERT INTO resume_draft(id, job_target_id, document_json, schema_version, "
                    "status, created_at, updated_at) VALUES (?, ?, ?, 1, 'draft', ?, ?)",
                    (str(uuid4()), job_id, payload, now, now),
                )
        return self.get_draft(job_id)

    @staticmethod
    def _entry_text(entry: dict[str, Any]) -> str:
        values = [str(value).strip() for value in entry["payload"].values() if value]
        return "；".join(value for value in values if value)

    @classmethod
    def _entry_block(cls, entry: dict[str, Any]) -> ResumeBlock:
        payload = entry["payload"]
        meta = " · ".join(str(payload[key]) for key in ("organization", "time") if payload.get(key))
        text = cls._entry_text(entry)
        return ResumeBlock(
            block_id=str(uuid4()),
            heading=entry["title"] or str(payload.get("title") or ""),
            meta=meta,
            paragraphs=[
                ResumeParagraph(
                    paragraph_id=str(uuid4()),
                    text=text,
                    source_entry_ids=[entry["id"]],
                )
            ],
        )
