from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataPaths:
    root: Path
    database: Path
    imports: Path
    photos: Path
    exports: Path
    backups: Path
    temp: Path
    logs: Path

    @classmethod
    def create(cls, root: Path | None = None) -> DataPaths:
        if root is None:
            configured = os.getenv("SHADOW_DATA_DIR")
            if configured:
                root = Path(configured)
        if root is None:
            local_app_data = os.getenv("LOCALAPPDATA")
            if not local_app_data:
                raise RuntimeError("LOCALAPPDATA is unavailable")
            root = Path(local_app_data) / "ShadowResumeAssistant"
        resolved = root.resolve()
        paths = cls(
            root=resolved,
            database=resolved / "data" / "app.db",
            imports=resolved / "documents" / "imports",
            photos=resolved / "documents" / "photos",
            exports=resolved / "exports",
            backups=resolved / "backups",
            temp=resolved / "temp",
            logs=resolved / "logs",
        )
        for directory in (
            paths.database.parent,
            paths.imports,
            paths.photos,
            paths.exports,
            paths.backups,
            paths.temp,
            paths.logs,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return paths
