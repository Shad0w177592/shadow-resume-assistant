from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

from app.persistence.database import Database, utc_now

DEFAULT_SECTIONS = [
    {"section_key": "summary", "title": "自我介绍", "enabled": True, "order": 0, "column": "right"},
    {
        "section_key": "education",
        "title": "教育经历",
        "enabled": True,
        "order": 1,
        "column": "left",
    },
    {"section_key": "work", "title": "工作经历", "enabled": True, "order": 2, "column": "right"},
    {
        "section_key": "internship",
        "title": "实习经历",
        "enabled": True,
        "order": 3,
        "column": "right",
    },
    {"section_key": "project", "title": "项目经历", "enabled": True, "order": 4, "column": "right"},
    {
        "section_key": "campus",
        "title": "校园、社团及志愿经历",
        "enabled": False,
        "order": 5,
        "column": "left",
    },
    {"section_key": "skills", "title": "专业技能", "enabled": True, "order": 6, "column": "left"},
    {
        "section_key": "awards",
        "title": "证书与奖项",
        "enabled": False,
        "order": 7,
        "column": "left",
    },
    {"section_key": "other", "title": "其他经历", "enabled": False, "order": 8, "column": "right"},
]
VALID_STRATEGIES = {
    "star",
    "car",
    "outcome_first",
    "technical",
    "graduate",
    "concise",
    "jd_keywords",
    "quantified",
    "ats",
}


class ResumeConfigService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def default() -> dict[str, Any]:
        sections = deepcopy(DEFAULT_SECTIONS)
        for section in sections:
            section["max_entries"] = None
        return {
            "template": "single_column",
            "page_target": 1,
            "strategies": ["concise", "jd_keywords", "ats"],
            "sections": sections,
            "entry_modes": {},
        }

    def get(self, job_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, config_json, created_at, updated_at FROM resume_config "
                "WHERE job_target_id=? ORDER BY updated_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        if row is None:
            return {"id": None, "job_target_id": job_id, "config": self.default()}
        return {
            "id": row[0],
            "job_target_id": job_id,
            "config": self._with_defaults(json.loads(row[1])),
            "created_at": row[2],
            "updated_at": row[3],
        }

    @staticmethod
    def _with_defaults(config: dict[str, Any]) -> dict[str, Any]:
        normalized = deepcopy(config)
        sections = normalized.get("sections", [])
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
        current_order = [
            item["section_key"] for item in sorted(sections, key=lambda item: item["order"])
        ]
        if current_order == legacy_order:
            new_order = {item["section_key"]: item["order"] for item in DEFAULT_SECTIONS}
            for section in sections:
                section["order"] = new_order[section["section_key"]]
        for section in normalized.get("sections", []):
            section.setdefault("max_entries", None)
        return normalized

    def save(self, job_id: str, config: dict[str, Any]) -> dict[str, Any]:
        self.validate(config)
        current = self.get(job_id)
        now = utc_now()
        payload = json.dumps(config, ensure_ascii=False)
        with self.database.connect() as connection:
            if current["id"]:
                connection.execute(
                    "UPDATE resume_config SET config_json=?, updated_at=? WHERE id=?",
                    (payload, now, current["id"]),
                )
            else:
                connection.execute(
                    "INSERT INTO resume_config(id, job_target_id, config_json, schema_version, "
                    "created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
                    (str(uuid4()), job_id, payload, now, now),
                )
        return self.get(job_id)

    @staticmethod
    def validate(config: dict[str, Any]) -> None:
        if config.get("template") not in {"single_column", "technical_double_column"}:
            raise ValueError("请选择有效模板")
        if config.get("page_target") not in {1, 2}:
            raise ValueError("页数只能选择一页或两页")
        strategies = set(config.get("strategies") or [])
        if not strategies or not strategies <= VALID_STRATEGIES:
            raise ValueError("请至少选择一种有效写作策略")
        sections = config.get("sections") or []
        if not any(section.get("enabled") for section in sections):
            raise ValueError("请至少选择一个栏目")
        orders = [section.get("order") for section in sections]
        if len(orders) != len(set(orders)):
            raise ValueError("栏目顺序不能重复")
        for section in sections:
            limit = section.get("max_entries")
            if limit is not None and (
                isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20
            ):
                raise ValueError("每个栏目的经历条数必须为 1 到 20，或选择不限")
        valid_modes = {"must_include", "exclude_this_resume", "ai_decide"}
        if any(mode not in valid_modes for mode in (config.get("entry_modes") or {}).values()):
            raise ValueError("经历取舍模式无效")
