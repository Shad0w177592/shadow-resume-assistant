from pathlib import Path

from scripts.audit_export_qa import audit
from scripts.generate_export_qa import main as generate_qa_exports


def test_generated_export_matrix_passes_structural_and_fill_audit(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    generate_qa_exports()
    assert audit(tmp_path / "output" / "qa-exports") == []
