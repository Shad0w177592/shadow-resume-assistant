from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.persistence.database import Database, utc_now

PROFILE_ID = "00000000-0000-0000-0000-000000000001"


class ProfileService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_profile(self) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT display_name, payload_json FROM user_profile WHERE id = ?", (PROFILE_ID,)
            ).fetchone()
        if row is None:
            return {"id": PROFILE_ID, "display_name": "", "personal_info": {}}
        return {
            "id": PROFILE_ID,
            "display_name": row[0] or "",
            "personal_info": json.loads(row[1]),
        }

    def save_profile(self, personal_info: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        display_name = str(personal_info.get("name") or "")
        payload = json.dumps(personal_info, ensure_ascii=False)
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO user_profile(id, display_name, payload_json, schema_version, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, 1, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "display_name=excluded.display_name, payload_json=excluded.payload_json, "
                "updated_at=excluded.updated_at",
                (PROFILE_ID, display_name, payload, now, now),
            )
        return self.get_profile()

    def list_entries(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, section_key, title, payload_json, created_at, updated_at "
                "FROM profile_section_entry WHERE profile_id = ? AND deleted_at IS NULL "
                "ORDER BY created_at, id",
                (PROFILE_ID,),
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def create_entry(
        self, section_key: str, title: str | None, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if not section_key.strip():
            raise ValueError("section_key is required")
        entry_id = str(uuid4())
        now = utc_now()
        with self.database.connect() as connection:
            self._ensure_profile(connection, now)
            connection.execute(
                "INSERT INTO profile_section_entry(id, profile_id, section_key, title, "
                "payload_json, "
                "schema_version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    entry_id,
                    PROFILE_ID,
                    section_key,
                    title,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_entry(entry_id)

    def get_entry(self, entry_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, section_key, title, payload_json, created_at, updated_at "
                "FROM profile_section_entry WHERE id = ? AND profile_id = ? AND deleted_at IS NULL",
                (entry_id, PROFILE_ID),
            ).fetchone()
        if row is None:
            raise KeyError(entry_id)
        return self._row_to_entry(row)

    def update_entry(
        self, entry_id: str, section_key: str, title: str | None, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE profile_section_entry SET section_key=?, title=?, payload_json=?, "
                "updated_at=? "
                "WHERE id=? AND profile_id=? AND deleted_at IS NULL",
                (
                    section_key,
                    title,
                    json.dumps(payload, ensure_ascii=False),
                    utc_now(),
                    entry_id,
                    PROFILE_ID,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(entry_id)
        return self.get_entry(entry_id)

    def duplicate_entry(self, entry_id: str) -> dict[str, Any]:
        source = self.get_entry(entry_id)
        title = f"{source['title']}（副本）" if source["title"] else None
        return self.create_entry(source["section_key"], title, source["payload"])

    def delete_entry(self, entry_id: str) -> None:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM profile_section_entry WHERE id=? AND profile_id=?",
                (entry_id, PROFILE_ID),
            )
            if cursor.rowcount != 1:
                raise KeyError(entry_id)

    @staticmethod
    def _ensure_profile(connection, now: str) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO user_profile(id, display_name, payload_json, "
            "schema_version, created_at, updated_at) "
            "VALUES (?, '', '{}', 1, ?, ?)",
            (PROFILE_ID, now, now),
        )

    @staticmethod
    def _row_to_entry(row) -> dict[str, Any]:
        return {
            "id": row[0],
            "section_key": row[1],
            "title": row[2],
            "payload": json.loads(row[3]),
            "created_at": row[4],
            "updated_at": row[5],
        }
