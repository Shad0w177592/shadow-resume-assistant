from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.word_pdf_conversion import word_to_pdf


def test_word_to_pdf_uses_microsoft_word_and_validates_output(tmp_path: Path) -> None:
    source = tmp_path / "原格式.docx"
    target = tmp_path / "同版.pdf"
    source.write_bytes(b"docx")
    captured = {}

    def fake_runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        Path(kwargs["env"]["SHADOW_PDF_TARGET"]).write_bytes(b"%PDF-result")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    word_to_pdf(source, target, runner=fake_runner)

    assert target.read_bytes() == b"%PDF-result"
    assert captured["command"][0] == "powershell.exe"
    assert "Word.Application" in captured["command"][-1]
    assert "ExportAsFixedFormat" in captured["command"][-1]
    assert captured["kwargs"]["env"]["SHADOW_WORD_SOURCE"] == str(source.resolve())
    assert captured["kwargs"]["env"]["SHADOW_PDF_TARGET"] == str(target.resolve())
    assert captured["kwargs"]["timeout"] == 120


def test_word_to_pdf_reports_missing_word_instead_of_falling_back(tmp_path: Path) -> None:
    source = tmp_path / "原格式.docx"
    source.write_bytes(b"docx")

    def failed_runner(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="Word.Application unavailable")

    with pytest.raises(RuntimeError, match="Microsoft Word"):
        word_to_pdf(source, tmp_path / "同版.pdf", runner=failed_runner)
