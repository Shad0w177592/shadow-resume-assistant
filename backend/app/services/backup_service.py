from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from app.persistence.database import Database, utc_now
from app.services.data_paths import DataPaths

BACKUP_VERSION = 1
MAX_FILES = 10_000
MAX_UNCOMPRESSED = 500 * 1024 * 1024


class BackupValidationError(ValueError):
    pass


class BackupService:
    def __init__(self, database: Database, paths: DataPaths) -> None:
        self.database = database
        self.paths = paths

    def create(self, target: Path | None = None) -> dict[str, Any]:
        timestamp = utc_now().replace(":", "-")
        target = (
            target or self.paths.backups / f"shadow-resume-backup-{timestamp}-{uuid4().hex[:8]}.zip"
        )
        target = target.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.paths.temp) as temporary:
            staging = Path(temporary)
            database_copy = staging / "data" / "app.db"
            database_copy.parent.mkdir(parents=True)
            source = sqlite3.connect(self.paths.database)
            destination = sqlite3.connect(database_copy)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            files = [(database_copy, "data/app.db")]
            for root, prefix in (
                (self.paths.imports, "documents/imports"),
                (self.paths.photos, "documents/photos"),
            ):
                files.extend(
                    (path, f"{prefix}/{path.name}") for path in root.iterdir() if path.is_file()
                )
            manifest_files = [
                {"path": archive_name, "size": path.stat().st_size, "sha256": self._sha256(path)}
                for path, archive_name in files
            ]
            manifest = {
                "backup_version": BACKUP_VERSION,
                "schema_version": self._schema_version(database_copy),
                "created_at": utc_now(),
                "files": manifest_files,
            }
            temporary_target = target.with_suffix(target.suffix + ".partial")
            try:
                with zipfile.ZipFile(temporary_target, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr(
                        "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
                    )
                    for path, archive_name in files:
                        archive.write(path, archive_name)
                os.replace(temporary_target, target)
            finally:
                temporary_target.unlink(missing_ok=True)
        record_id = str(uuid4())
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO backup_record(id, file_name, status, manifest_json, schema_version, "
                "created_at, updated_at) VALUES (?, ?, 'completed', ?, 1, ?, ?)",
                (record_id, target.name, json.dumps(manifest, ensure_ascii=False), now, now),
            )
        return {"id": record_id, "path": str(target), "manifest": manifest}

    def validate(self, source: Path) -> dict[str, Any]:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES:
                raise BackupValidationError("备份文件数量异常")
            total = 0
            for info in infos:
                path = PurePosixPath(info.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                    raise BackupValidationError("备份包含不安全路径")
                total += info.file_size
                if info.file_size > 50 * 1024 * 1024 and info.compress_size * 100 < info.file_size:
                    raise BackupValidationError("备份压缩比异常")
            if total > MAX_UNCOMPRESSED:
                raise BackupValidationError("备份解压后过大")
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (KeyError, json.JSONDecodeError) as error:
                raise BackupValidationError("缺少有效 manifest.json") from error
            if manifest.get("backup_version") != BACKUP_VERSION:
                raise BackupValidationError("不支持的备份版本")
            expected = {item["path"]: item for item in manifest.get("files", [])}
            for name, item in expected.items():
                try:
                    content = archive.read(name)
                except KeyError as error:
                    raise BackupValidationError(f"备份缺少文件：{name}") from error
                if (
                    len(content) != item["size"]
                    or hashlib.sha256(content).hexdigest() != item["sha256"]
                ):
                    raise BackupValidationError(f"备份校验失败：{name}")
            if "data/app.db" not in expected:
                raise BackupValidationError("备份缺少数据库")
            return manifest

    def restore(self, source: Path) -> dict[str, Any]:
        manifest = self.validate(source)
        automatic = self.create()
        with tempfile.TemporaryDirectory(dir=self.paths.temp) as temporary:
            staging = Path(temporary) / "staging"
            rollback = Path(temporary) / "rollback"
            staging.mkdir()
            rollback.mkdir()
            with zipfile.ZipFile(source) as archive:
                archive.extractall(staging)
            targets = [
                (staging / "data" / "app.db", self.paths.database),
                (staging / "documents" / "imports", self.paths.imports),
                (staging / "documents" / "photos", self.paths.photos),
            ]
            try:
                current = sqlite3.connect(self.paths.database)
                rollback_db = sqlite3.connect(rollback / "app.db")
                try:
                    current.backup(rollback_db)
                finally:
                    rollback_db.close()
                    current.close()
                shutil.copytree(self.paths.imports, rollback / "imports")
                shutil.copytree(self.paths.photos, rollback / "photos")
                self._remove_sqlite_sidecars()
                shutil.copy2(targets[0][0], self.paths.database)
                for staged, target in targets[1:]:
                    shutil.rmtree(target)
                    shutil.copytree(staged, target) if staged.exists() else target.mkdir(
                        parents=True
                    )
                self.database.migrate()
            except Exception:
                self._remove_sqlite_sidecars()
                shutil.copy2(rollback / "app.db", self.paths.database)
                for name, target in (
                    ("imports", self.paths.imports),
                    ("photos", self.paths.photos),
                ):
                    shutil.rmtree(target, ignore_errors=True)
                    shutil.copytree(rollback / name, target)
                raise
        return {"restored_files": len(manifest["files"]), "automatic_backup": automatic["path"]}

    def clear_all(self, include_api_key: bool = False) -> dict[str, Any]:
        with self.database.transaction() as connection:
            connection.executescript(
                "DELETE FROM edit_proposal; DELETE FROM resume_version; "
                "DELETE FROM resume_draft; DELETE FROM resume_config; "
                "DELETE FROM evidence_link; DELETE FROM job_requirement; "
                "DELETE FROM job_target; DELETE FROM import_candidate; "
                "DELETE FROM source_document; DELETE FROM profile_section_entry; "
                "DELETE FROM user_profile; DELETE FROM task_run; "
                "DELETE FROM backup_record; DELETE FROM app_setting;"
            )
        removed = 0
        for directory in (
            self.paths.imports,
            self.paths.photos,
            self.paths.exports,
            self.paths.temp,
        ):
            for path in directory.iterdir():
                if path.is_file():
                    path.unlink()
                    removed += 1
                elif path.is_dir():
                    shutil.rmtree(path)
                    removed += 1
        return {"cleared": True, "files_removed": removed, "api_key_requested": include_api_key}

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _schema_version(database: Path) -> int:
        connection = sqlite3.connect(database)
        try:
            return int(
                connection.execute("SELECT MAX(version) FROM schema_migration").fetchone()[0] or 0
            )
        finally:
            connection.close()

    def _remove_sqlite_sidecars(self) -> None:
        Path(f"{self.paths.database}-wal").unlink(missing_ok=True)
        Path(f"{self.paths.database}-shm").unlink(missing_ok=True)
