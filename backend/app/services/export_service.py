from __future__ import annotations

import re
from typing import Any

from app.domain.resume import ResumeDocument
from app.persistence.database import Database
from app.services.data_paths import DataPaths
from app.services.generation_service import GenerationService
from app.services.resume_export import to_docx, to_pdf
from app.services.source_word_export import SourceWordExport
from app.services.version_service import VersionService


class ExportService:
    def __init__(self, database: Database, paths: DataPaths) -> None:
        self.database = database
        self.paths = paths
        self.drafts = GenerationService(database)
        self.source_word = SourceWordExport(database, paths)

    def export(self, job_id: str, filename: str, formats: list[str]) -> dict[str, Any]:
        draft = self.drafts.get_draft(job_id)
        document = ResumeDocument.model_validate(draft["document"])
        warnings = self.preflight(draft["id"], document)
        if warnings:
            raise ValueError("；".join(warnings))
        return self._write_resolved(document, filename, formats)

    def export_version(self, version_id: str, filename: str, formats: list[str]) -> dict[str, Any]:
        version = VersionService(self.database).get(version_id)
        document = ResumeDocument.model_validate(version["snapshot"]["document"])
        warnings = self._document_warnings(document)
        if warnings:
            raise ValueError("；".join(warnings))
        return self._write_resolved(document, filename, formats)

    def _write_resolved(
        self, document: ResumeDocument, filename: str, formats: list[str]
    ) -> dict[str, Any]:
        source_word = self.source_word.resolve(document)
        if source_word is None and self.source_word.expects_source_word(document):
            raise ValueError(
                "无法安全套用原 Word 排版，本次未导出，避免照片、字体、间距或栏目顺序被改变。"
                "请重新导入原 Word 后再生成，或检查新增栏目是否能对应原文件。"
            )
        return self._write(document, filename, formats, source_word)

    def _write(
        self,
        document: ResumeDocument,
        filename: str,
        formats: list[str],
        source_word: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_name = self._safe_filename(filename)
        photo_path = self._photo_path(document.personal_info.photo_file_id)
        outputs = []
        for output_format in dict.fromkeys(formats):
            if output_format not in {"docx", "pdf"}:
                raise ValueError("仅支持 Word 和 PDF")
            target = self.paths.exports / f"{safe_name}.{output_format}"
            if output_format == "docx":
                if source_word:
                    self.source_word.write(source_word, target)
                else:
                    to_docx(document, target, photo_path=photo_path)
            else:
                to_pdf(document, target, photo_path=photo_path)
            if not target.is_file() or target.stat().st_size == 0:
                raise RuntimeError(f"导出文件生成失败：{target.name}")
            outputs.append(str(target))
        return {
            "files": outputs,
            "page_target": document.page_target,
            "word_mode": "source_format" if source_word else "generated_template",
            "source_word": str(source_word["path"]) if source_word else None,
        }

    def _photo_path(self, file_id: str | None):
        if not file_id:
            return None
        matches = list(self.paths.photos.glob(f"{file_id}.*"))
        return matches[0] if len(matches) == 1 else None

    def preflight(self, draft_id: str, document: ResumeDocument) -> list[str]:
        warnings = self._document_warnings(document)
        with self.database.connect() as connection:
            pending = connection.execute(
                "SELECT COUNT(*) FROM edit_proposal WHERE draft_id=? AND status='pending'",
                (draft_id,),
            ).fetchone()[0]
        if pending:
            warnings.append("存在未接受或拒绝的 AI 修改建议")
        return warnings

    @staticmethod
    def _document_warnings(document: ResumeDocument) -> list[str]:
        warnings = []
        serialized = document.model_dump_json()
        if "[[" in serialized or "]]" in serialized:
            warnings.append("存在未替换占位符")
        if any(not section.blocks for section in document.sections):
            warnings.append("存在空栏目")
        if not document.sections:
            warnings.append("简历没有可导出内容")
        return warnings

    @staticmethod
    def _safe_filename(value: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
        return (safe or "影子简历")[:100]
