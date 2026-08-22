from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.persistence.database import Database, utc_now


class JobService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, company, title, jd_text, notes, status, created_at, updated_at "
                "FROM job_target WHERE deleted_at IS NULL ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, job_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, company, title, jd_text, notes, status, created_at, updated_at "
                "FROM job_target WHERE id=? AND deleted_at IS NULL",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def create(
        self, company: str | None, title: str | None, jd_text: str, notes: str | None
    ) -> dict[str, Any]:
        if not jd_text.strip():
            raise ValueError("JD 不能为空")
        job_id = str(uuid4())
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO job_target(id, company, title, jd_text, notes, status, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)",
                (job_id, company, title, jd_text, notes, now, now),
            )
        return self.get(job_id)

    def update(
        self, job_id: str, company: str | None, title: str | None, jd_text: str, notes: str | None
    ) -> dict[str, Any]:
        if not jd_text.strip():
            raise ValueError("JD 不能为空")
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE job_target SET company=?, title=?, jd_text=?, notes=?, updated_at=? "
                "WHERE id=? AND deleted_at IS NULL",
                (company, title, jd_text, notes, utc_now(), job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)
        return self.get(job_id)

    def duplicate(self, job_id: str) -> dict[str, Any]:
        source = self.get(job_id)
        title = f"{source['title']}（副本）" if source["title"] else None
        return self.create(source["company"], title, source["jd_text"], source["notes"])

    def delete(self, job_id: str) -> None:
        with self.database.connect() as connection:
            cursor = connection.execute("DELETE FROM job_target WHERE id=?", (job_id,))
            if cursor.rowcount != 1:
                raise KeyError(job_id)
