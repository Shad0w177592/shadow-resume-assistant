from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ManagedConnection(sqlite3.Connection):
    """Commit/rollback like sqlite3's context manager and always release Windows locks."""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, path: Path, migrations_dir: Path) -> None:
        self.path = path
        self.migrations_dir = migrations_dir
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, factory=ManagedConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migration "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                row[0] for row in connection.execute("SELECT version FROM schema_migration")
            }
            for migration in sorted(self.migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
                version = int(migration.name.split("_", 1)[0])
                if version in applied:
                    continue
                connection.executescript(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migration(version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM app_setting WHERE setting_key = ?", (key,)
            ).fetchone()
        return default if row is None else json.loads(row[0])

    def set_setting(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO app_setting(setting_key, value_json, schema_version, updated_at) "
                "VALUES (?, ?, 1, ?) ON CONFLICT(setting_key) DO UPDATE SET "
                "value_json=excluded.value_json, schema_version=1, updated_at=excluded.updated_at",
                (key, payload, utc_now()),
            )
