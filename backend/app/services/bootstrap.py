from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.persistence.database import Database
from app.security.credentials import CredentialStore
from app.services.data_paths import DataPaths
from app.services.file_storage import FileStorage


@dataclass(frozen=True)
class AppServices:
    paths: DataPaths
    database: Database
    credentials: CredentialStore
    files: FileStorage
    voice_credentials: CredentialStore


def bootstrap_services(
    data_root: Path | None,
    credential_store: CredentialStore,
    voice_credential_store: CredentialStore | None = None,
) -> AppServices:
    paths = DataPaths.create(data_root)
    migrations = Path(__file__).resolve().parents[2] / "migrations"
    database = Database(paths.database, migrations)
    database.migrate()
    files = FileStorage(paths.imports, paths.photos, paths.temp)
    files.clean_temp()
    return AppServices(
        paths, database, credential_store, files, voice_credential_store or credential_store
    )
