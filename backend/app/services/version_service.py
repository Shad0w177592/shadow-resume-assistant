from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.domain.resume import ResumeDocument
from app.persistence.database import Database, utc_now
from app.services.generation_service import GenerationService
from app.services.resume_config_service import ResumeConfigService


class VersionService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.drafts = GenerationService(database)
        self.configs = ResumeConfigService(database)

    def create(self, job_id: str, name: str, notes: str | None = None) -> dict[str, Any]:
        draft = self.drafts.get_draft(job_id)
        payload = {
            "document": draft["document"],
            "config": self.configs.get(job_id)["config"],
        }
        version_id = str(uuid4())
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO resume_version(id, draft_id, name, notes, document_json, "
                "schema_version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    version_id,
                    draft["id"],
                    name.strip() or "未命名版本",
                    notes,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get(version_id)

    def list(self, job_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT v.id, v.name, v.notes, v.document_json, v.created_at, v.updated_at "
                "FROM resume_version v JOIN resume_draft d ON d.id=v.draft_id "
                "WHERE d.job_target_id=? ORDER BY v.created_at DESC",
                (job_id,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, version_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, name, notes, document_json, created_at, updated_at "
                "FROM resume_version WHERE id=?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise KeyError(version_id)
        return self._row(row)

    def rename(self, version_id: str, name: str, notes: str | None) -> dict[str, Any]:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE resume_version SET name=?, notes=?, updated_at=? WHERE id=?",
                (name.strip() or "未命名版本", notes, utc_now(), version_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(version_id)
        return self.get(version_id)

    def delete(self, version_id: str) -> None:
        with self.database.connect() as connection:
            cursor = connection.execute("DELETE FROM resume_version WHERE id=?", (version_id,))
            if cursor.rowcount != 1:
                raise KeyError(version_id)

    def restore(self, version_id: str) -> dict[str, Any]:
        version = self.get(version_id)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT d.job_target_id FROM resume_version v "
                "JOIN resume_draft d ON d.id=v.draft_id WHERE v.id=?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise KeyError(version_id)
        self.configs.save(row[0], version["snapshot"]["config"])
        return self.drafts._save(
            row[0], ResumeDocument.model_validate(version["snapshot"]["document"])
        )

    def compare(self, version_id: str, current_document: dict[str, Any]) -> dict[str, Any]:
        before = self.get(version_id)["snapshot"]["document"]
        before_blocks = self._blocks(before)
        after_blocks = self._blocks(current_document)
        changes = []
        for block_id in sorted(set(before_blocks) | set(after_blocks)):
            if block_id not in before_blocks:
                changes.append(
                    {
                        "block_id": block_id,
                        "change": "added",
                        "before": None,
                        "after": after_blocks[block_id],
                    }
                )
            elif block_id not in after_blocks:
                changes.append(
                    {
                        "block_id": block_id,
                        "change": "removed",
                        "before": before_blocks[block_id],
                        "after": None,
                    }
                )
            elif before_blocks[block_id] != after_blocks[block_id]:
                changes.append(
                    {
                        "block_id": block_id,
                        "change": "modified",
                        "before": before_blocks[block_id],
                        "after": after_blocks[block_id],
                    }
                )
        return {"version_id": version_id, "changes": changes}

    @staticmethod
    def _blocks(document: dict[str, Any]) -> dict[str, str]:
        return {
            block["block_id"]: "\n".join(paragraph["text"] for paragraph in block["paragraphs"])
            for section in document["sections"]
            for block in section["blocks"]
        }

    @staticmethod
    def _row(row) -> dict[str, Any]:
        result = dict(row)
        result["snapshot"] = json.loads(result.pop("document_json"))
        return result
