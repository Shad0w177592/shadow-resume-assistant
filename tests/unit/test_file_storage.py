from pathlib import Path

import pytest

from app.services.data_paths import DataPaths
from app.services.file_storage import FileStorage, FileStorageError


def test_import_uses_uuid_name_hash_and_atomic_destination(tmp_path: Path) -> None:
    paths = DataPaths.create(tmp_path / "app")
    source = tmp_path / "我的 简历.txt"
    source.write_text("合成简历内容", encoding="utf-8")
    storage = FileStorage(paths.imports, paths.photos, paths.temp)
    result = storage.import_file(source)
    assert result.original_name == "我的 简历.txt"
    assert result.path.parent == paths.imports
    assert result.path.name != source.name
    assert result.path.read_text(encoding="utf-8") == "合成简历内容"
    assert len(result.sha256) == 64
    assert not list(paths.temp.glob("*.partial"))


def test_rejects_unsupported_or_wrong_photo_type(tmp_path: Path) -> None:
    paths = DataPaths.create(tmp_path / "app")
    storage = FileStorage(paths.imports, paths.photos, paths.temp)
    executable = tmp_path / "attack.exe"
    executable.write_bytes(b"MZ")
    with pytest.raises(FileStorageError, match="unsupported"):
        storage.import_file(executable)
    text = tmp_path / "not-photo.txt"
    text.write_text("x")
    with pytest.raises(FileStorageError, match="photo"):
        storage.import_file(text, kind="photo")


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "managed"
    root.mkdir()
    with pytest.raises(FileStorageError, match="escapes"):
        FileStorage._assert_within(root, tmp_path / "outside.txt")

