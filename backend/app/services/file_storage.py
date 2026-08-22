from __future__ import annotations

import hashlib
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

ALLOWED_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


@dataclass(frozen=True)
class StoredFile:
    file_id: str
    path: Path
    original_name: str
    media_type: str
    size: int
    sha256: str


class FileStorageError(ValueError):
    pass


class FileStorage:
    def __init__(
        self,
        imports: Path,
        photos: Path,
        temp: Path,
        max_size: int = 25 * 1024 * 1024,
    ) -> None:
        self.imports = imports.resolve()
        self.photos = photos.resolve()
        self.temp = temp.resolve()
        self.max_size = max_size

    def import_file(self, source: Path, kind: str = "document") -> StoredFile:
        source = source.resolve(strict=True)
        if not source.is_file():
            raise FileStorageError("source is not a file")
        suffix = source.suffix.lower()
        if suffix not in ALLOWED_TYPES:
            raise FileStorageError("unsupported file type")
        size = source.stat().st_size
        if size <= 0 or size > self.max_size:
            raise FileStorageError("file size is outside the allowed range")
        destination_root = self.photos if kind == "photo" else self.imports
        if kind == "photo" and not ALLOWED_TYPES[suffix].startswith("image/"):
            raise FileStorageError("photo must be an image")
        file_id = str(uuid4())
        destination = destination_root / f"{file_id}{suffix}"
        temporary = self.temp / f"{file_id}.partial"
        self._assert_within(destination_root, destination)
        self._assert_within(self.temp, temporary)
        digest = hashlib.sha256()
        with source.open("rb") as input_stream, temporary.open("wb") as output_stream:
            while chunk := input_stream.read(1024 * 1024):
                digest.update(chunk)
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        os.replace(temporary, destination)
        detected = mimetypes.guess_type(source.name)[0] or ALLOWED_TYPES[suffix]
        return StoredFile(file_id, destination, source.name, detected, size, digest.hexdigest())

    def clean_temp(self) -> int:
        removed = 0
        for candidate in self.temp.glob("*.partial"):
            self._assert_within(self.temp, candidate)
            candidate.unlink(missing_ok=True)
            removed += 1
        return removed

    @staticmethod
    def _assert_within(root: Path, candidate: Path) -> None:
        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise FileStorageError("path escapes managed directory") from exc
