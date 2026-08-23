from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain.documents import ParsedDocument, ParseStatus
from app.persistence.database import Database, utc_now
from app.services.document_parser import DocumentParser
from app.services.entry_titles import concrete_entry_title
from app.services.file_storage import FileStorage
from app.services.profile_service import ProfileService

CATEGORY_RULES = [
    ("summary", ("自我介绍", "自我评价", "个人总结", "个人评价")),
    ("education", ("教育", "学校", "大学", "学院", "学历")),
    ("work", ("工作经历", "任职", "公司")),
    ("internship", ("实习",)),
    ("project", ("项目", "产品", "系统", "平台")),
    ("campus", ("校园", "在校", "校内", "社团", "志愿")),
    ("skills", ("技能", "技术栈", "工具")),
    ("awards", ("证书", "奖项", "获奖")),
]

SECTION_HEADINGS = {
    "summary": ("自我介绍", "自我评价", "个人总结", "个人评价"),
    "education": ("教育经历", "教育背景", "学习经历"),
    "work": ("工作经历", "工作经验", "任职经历"),
    "internship": ("实习经历", "实习经验"),
    "project": ("项目经历", "项目经验"),
    "campus": ("校园经历", "在校经历", "校内经历", "社团经历", "志愿经历", "校园社团及志愿经历"),
    "skills": ("专业技能", "相关技能", "技能特长", "个人技能"),
    "awards": ("证书与奖项", "证书奖项", "获奖经历", "荣誉奖项"),
    "other": ("其他经历", "其他成果"),
}

SECTION_TITLES = {"summary": "自我介绍"}

EXPERIENCE_SECTIONS = {"education", "work", "internship", "project", "campus", "awards", "other"}
DATE_RANGE = re.compile(
    r"^(?:19|20)\d{2}(?:[./年-]\d{1,2})?.{0,12}(?:-|—|–|~|～|至).{0,12}(?:至今|(?:19|20)\d{2})"
)


class ImportService:
    def __init__(self, database: Database, files: FileStorage) -> None:
        self.database = database
        self.files = files
        self.parser = DocumentParser()
        self.profiles = ProfileService(database)

    def import_path(self, path: Path) -> dict[str, Any]:
        stored = self.files.import_file(path)
        parsed = self.parser.parse(stored.path)
        now = utc_now()
        document_id = str(parsed.document_id)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO source_document(id, managed_file_id, original_name, status, "
                "parsed_json, schema_version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    document_id,
                    stored.file_id,
                    stored.original_name,
                    parsed.status.value,
                    parsed.model_dump_json(),
                    now,
                    now,
                ),
            )
            if parsed.status == ParseStatus.PARSED:
                for candidate in self._classify(parsed):
                    connection.execute(
                        "INSERT INTO import_candidate(id, source_document_id, section_key, title, "
                        "payload_json, source_locator_json, confidence, duplicate_of, status, "
                        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                        (
                            candidate["id"],
                            document_id,
                            candidate["section_key"],
                            candidate["title"],
                            json.dumps(candidate["payload"], ensure_ascii=False),
                            json.dumps(candidate["source_locator"], ensure_ascii=False),
                            candidate["confidence"],
                            candidate["duplicate_of"],
                            now,
                            now,
                        ),
                    )
        return self.get(document_id)

    def get(self, document_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            document = connection.execute(
                "SELECT id, original_name, status, parsed_json, created_at, updated_at "
                "FROM source_document WHERE id=?",
                (document_id,),
            ).fetchone()
            candidates = connection.execute(
                "SELECT id, section_key, title, payload_json, source_locator_json, confidence, "
                "duplicate_of, status FROM import_candidate WHERE source_document_id=? "
                "ORDER BY rowid",
                (document_id,),
            ).fetchall()
        if document is None:
            raise KeyError(document_id)
        result = dict(document)
        result["parsed"] = json.loads(result.pop("parsed_json"))
        result["candidates"] = [
            {
                **dict(row),
                "payload": json.loads(row[3]),
                "source_locator": json.loads(row[4]),
            }
            for row in candidates
        ]
        for candidate in result["candidates"]:
            candidate.pop("payload_json", None)
            candidate.pop("source_locator_json", None)
        return result

    def confirm(self, document_id: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        current = {item["id"]: item for item in self.get(document_id)["candidates"]}
        accepted = 0
        ignored = 0
        for decision in decisions:
            candidate = current.get(decision["candidate_id"])
            if candidate is None:
                raise KeyError(decision["candidate_id"])
            action = decision["action"]
            if action == "accept":
                section_key = decision.get("section_key") or candidate["section_key"]
                title = decision.get("title", candidate["title"])
                payload = decision.get("payload") or candidate["payload"]
                payload["source"] = candidate["source_locator"]
                if section_key == "summary":
                    profile = self.profiles.get_profile()["personal_info"]
                    profile["_summary_source"] = candidate["source_locator"]
                    profile["summary"] = str(payload.get("content") or "").strip()
                    self.profiles.save_profile(profile)
                else:
                    self.profiles.create_entry(section_key, title, payload)
                accepted += 1
            elif action == "ignore":
                ignored += 1
            else:
                raise ValueError("action must be accept or ignore")
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE import_candidate SET status=?, updated_at=? WHERE id=?",
                    ("accepted" if action == "accept" else "ignored", utc_now(), candidate["id"]),
                )
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE source_document SET status='confirmed', updated_at=? WHERE id=?",
                (utc_now(), document_id),
            )
        return {"accepted": accepted, "ignored": ignored}

    def suggestions(self) -> list[dict[str, str]]:
        suggestions = []
        for entry in self.profiles.list_entries():
            if not any(str(value).strip() for value in entry["payload"].values() if value):
                suggestions.append(
                    {
                        "entry_id": entry["id"],
                        "level": "optional",
                        "message": "这条记录目前为空，可补充内容或删除；不会阻止生成。",
                    }
                )
        return suggestions

    def _classify(self, parsed: ParsedDocument) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for page in parsed.pages:
            current_section: str | None = None
            section_blocks = []
            for block in sorted(page.blocks, key=lambda item: item.order):
                if not block.text.strip():
                    continue
                heading_section = self._heading_category(block.text)
                if heading_section:
                    self._append_section_candidates(
                        candidates,
                        parsed,
                        page.page_number,
                        current_section,
                        section_blocks,
                    )
                    section_blocks = []
                    current_section = heading_section
                    continue
                if current_section:
                    section_blocks.append(block)
                else:
                    section, confidence = self._category(block.text)
                    candidates.append(
                        self._candidate(parsed, page.page_number, section, [block], confidence)
                    )
            self._append_section_candidates(
                candidates,
                parsed,
                page.page_number,
                current_section,
                section_blocks,
            )
        return candidates

    def _append_section_candidates(self, candidates, parsed, page_number, section, blocks) -> None:
        if not section or not blocks:
            return
        for group in self._segment_section(section, blocks):
            candidates.append(self._candidate(parsed, page_number, section, group, "clear"))

    def _candidate(self, parsed, page_number, section, blocks, confidence):
        content = "\n".join(block.text.strip() for block in blocks if block.text.strip())
        first = blocks[0]
        payload = {"content": content}
        return {
            "id": str(uuid4()),
            "section_key": section,
            "title": SECTION_TITLES.get(
                section, concrete_entry_title(section, first.text, payload)
            ),
            "payload": payload,
            "source_locator": {
                "document_id": str(parsed.document_id),
                "page": page_number,
                "block_id": first.block_id,
                "block_ids": [block.block_id for block in blocks],
            },
            "confidence": confidence,
            "duplicate_of": self._find_duplicate(content),
        }

    @staticmethod
    def _segment_section(section: str, blocks: list) -> list[list]:
        if section == "summary":
            return [blocks]
        if section == "skills":
            return [[block] for block in blocks]
        if section not in EXPERIENCE_SECTIONS:
            return [[block] for block in blocks]
        starts = [
            index for index, block in enumerate(blocks) if DATE_RANGE.search(block.text.strip())
        ]
        if not starts:
            return [[block] for block in blocks]
        groups = [[block] for block in blocks[: starts[0]]]
        for position, start in enumerate(starts):
            end = starts[position + 1] if position + 1 < len(starts) else len(blocks)
            groups.append(blocks[start:end])
        return [group for group in groups if group]

    @staticmethod
    def _heading_category(text: str) -> str | None:
        normalized = re.sub(r"[\s|｜:：·•▪■□/、及和与]", "", text)
        for section, headings in SECTION_HEADINGS.items():
            if normalized in {re.sub(r"[\s|｜:：·•▪■□/、及和与]", "", item) for item in headings}:
                return section
        return None

    @staticmethod
    def _category(text: str) -> tuple[str, str]:
        for section, keywords in CATEGORY_RULES:
            if any(keyword in text for keyword in keywords):
                return section, "clear"
        return "other", "uncertain"

    @staticmethod
    def _title(text: str) -> str:
        first = re.split(r"[\n。；]", text, maxsplit=1)[0].strip()
        return first[:80] or "导入内容"

    def _find_duplicate(self, text: str) -> str | None:
        normalized = re.sub(r"\s+", "", text)
        for entry in self.profiles.list_entries():
            if normalized and normalized in re.sub(
                r"\s+", "", json.dumps(entry["payload"], ensure_ascii=False)
            ):
                return entry["id"]
        return None
