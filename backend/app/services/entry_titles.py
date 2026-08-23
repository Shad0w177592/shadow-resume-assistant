from __future__ import annotations

import re
from typing import Any

DATE_PREFIX = re.compile(
    r"^\s*(?:19|20)\d{2}(?:[./年-]\d{1,2}(?:月)?)?\s*"
    r"(?:-|—|–|~|～|至)\s*"
    r"(?:至今|(?:19|20)\d{2}(?:[./年-]\d{1,2}(?:月)?)?)\s*"
)
GENERIC_TITLES = {
    "education": {"教育经历", "教育背景", "学习经历"},
    "work": {"工作经历", "工作经验", "任职经历"},
    "internship": {"实习经历", "实习经验"},
    "project": {"项目经历", "项目经验"},
    "campus": {"校园经历", "在校经历", "校内经历", "社团经历", "志愿经历"},
    "skills": {"专业技能", "相关技能", "技能特长", "个人技能"},
    "awards": {"证书与奖项", "证书奖项", "获奖经历", "荣誉奖项"},
    "other": {"其他经历", "其他成果"},
}


def concrete_entry_title(section_key: str, title: str | None, payload: dict[str, Any]) -> str:
    """Return a concise real-world name instead of a date or generic section label."""
    original = (title or "").strip()
    content_lines = [
        line.strip() for line in str(payload.get("content") or "").splitlines() if line.strip()
    ]
    needs_content = (
        not original
        or original in GENERIC_TITLES.get(section_key, set())
        or bool(DATE_PREFIX.match(original))
    )
    candidates = ([original] if original else []) + (content_lines if needs_content else [])

    for candidate in candidates:
        cleaned = DATE_PREFIX.sub("", candidate).strip(" \t|｜·•▪■□:：")
        if not cleaned or cleaned in GENERIC_TITLES.get(section_key, set()):
            continue
        if section_key in {"skills", "project", "awards"}:
            label, separator, _detail = cleaned.partition("：")
            if not separator:
                label, separator, _detail = cleaned.partition(":")
            if separator and 1 <= len(label.strip()) <= 40:
                cleaned = label.strip()
        return cleaned[:80]

    return original[:80] or "导入内容"
