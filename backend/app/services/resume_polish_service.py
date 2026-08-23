from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.domain.resume import ResumeBlock, ResumeDocument, ResumeParagraph, ResumeSection
from app.persistence.database import Database
from app.services.ai_schemas import FABRICATED_EXPERIENCE_SCHEMA
from app.services.generation_service import SECTION_TITLES, GenerationService
from app.services.job_service import JobService
from app.services.openai_provider import OpenAITextProvider
from app.services.profile_service import ProfileService
from app.services.resume_config_service import ResumeConfigService

VALID_POLISH_METHODS = {"expand_existing", "adjust_layout", "add_experience"}


class ResumePolishService:
    def __init__(self, database: Database, provider: OpenAITextProvider | None = None) -> None:
        self.database = database
        self.provider = provider
        self.drafts = GenerationService(database)
        self.profiles = ProfileService(database)
        self.configs = ResumeConfigService(database)
        self.jobs = JobService(database)

    def polish(
        self, job_id: str, methods: list[str], allow_fabrication: bool = False
    ) -> dict[str, Any]:
        unknown = set(methods) - VALID_POLISH_METHODS
        if not methods or unknown:
            raise ValueError("请选择至少一种有效的润色方式")
        self.jobs.get(job_id)
        draft = self.drafts.get_draft(job_id)
        document = ResumeDocument.model_validate(draft["document"])
        config = self.configs.get(job_id)["config"]
        added_real = 0
        fabricated = False

        if "expand_existing" in methods:
            self._expand_existing(document)
        if "adjust_layout" in methods:
            document.layout_density = "expanded"
        if "add_experience" in methods:
            added_real = self._add_unused_entries(document, config)
            if added_real == 0 and allow_fabrication:
                self._add_fabricated_experience(document, config, job_id)
                fabricated = True

        saved = self.drafts._save(job_id, document)
        return {
            "draft": saved,
            "added_real_count": added_real,
            "fabricated": fabricated,
            "warnings": (
                ["已加入 AI 编造内容，请逐项核实；虚假经历可能导致背调或录用风险。"]
                if fabricated
                else []
            ),
        }

    def _expand_existing(self, document: ResumeDocument) -> None:
        # Production AI rewriting remains evidence-bound; deterministic tests use a
        # conservative sentence that introduces no company, date, skill or number.
        if self.provider:
            entries = self.profiles.list_entries()
            used_ids = {
                str(source_id)
                for section in document.sections
                for block in section.blocks
                for paragraph in block.paragraphs
                for source_id in paragraph.source_entry_ids
            }
            selected = [entry for entry in entries if entry["id"] in used_ids]
            from app.services.resume_workflow_service import ResumeWorkflowService

            workflow = ResumeWorkflowService(self.database, self.provider)
            workflow._rewrite_with_ai(
                document,
                selected,
                [],
                {"strategies": ["star", "expand_existing"]},
            )
            return
        for section in document.sections:
            for block in section.blocks:
                for paragraph in block.paragraphs:
                    if paragraph.text and "职责、行动与结果" not in paragraph.text:
                        paragraph.text = f"{paragraph.text}；围绕职责、行动与结果补充说明。"

    def _add_unused_entries(self, document: ResumeDocument, config: dict[str, Any]) -> int:
        used_ids = {
            str(source_id)
            for section in document.sections
            for block in section.blocks
            for paragraph in block.paragraphs
            for source_id in paragraph.source_entry_ids
        }
        section_settings = {
            item["section_key"]: item for item in config["sections"] if item["enabled"]
        }
        modes = config.get("entry_modes", {})
        unused = [
            entry
            for entry in self.profiles.list_entries()
            if entry["id"] not in used_ids
            and entry["section_key"] in section_settings
            and modes.get(entry["id"], "ai_decide") != "exclude_this_resume"
            and GenerationService._entry_text(entry)
        ]
        unused.sort(key=lambda entry: (-entry.get("importance", 3), entry["created_at"]))
        if not unused:
            return 0

        sections = {section.section_key: section for section in document.sections}
        for entry in unused:
            section_key = entry["section_key"]
            section = sections.get(section_key)
            if section is None:
                setting = section_settings[section_key]
                section = ResumeSection(
                    section_id=str(uuid4()),
                    section_key=section_key,
                    title=setting.get("title") or SECTION_TITLES.get(section_key, section_key),
                    order=setting["order"],
                    column=(
                        "full"
                        if document.template == "single_column"
                        else setting.get("column", "right")
                    ),
                    blocks=[],
                )
                document.sections.append(section)
                sections[section_key] = section
            section.blocks.append(GenerationService._entry_block(entry))
        document.sections.sort(key=lambda section: section.order)
        return len(unused)

    def _add_fabricated_experience(
        self, document: ResumeDocument, config: dict[str, Any], job_id: str
    ) -> None:
        settings = [
            item
            for item in sorted(config["sections"], key=lambda item: item["order"])
            if item["enabled"]
            and item["section_key"] in {"work", "internship", "project", "campus"}
        ]
        setting = (
            settings[0]
            if settings
            else {
                "section_key": "other",
                "title": "其他经历",
                "order": len(document.sections),
                "column": "right",
            }
        )
        section = next(
            (item for item in document.sections if item.section_key == setting["section_key"]),
            None,
        )
        if section is None:
            section = ResumeSection(
                section_id=str(uuid4()),
                section_key=setting["section_key"],
                title=setting.get("title")
                or SECTION_TITLES.get(setting["section_key"], "其他经历"),
                order=setting["order"],
                column=(
                    "full"
                    if document.template == "single_column"
                    else setting.get("column", "right")
                ),
                blocks=[],
            )
            document.sections.append(section)
        generated = {
            "heading": "AI 补充经历",
            "meta": "请核实并手动修改",
            "text": "根据目标岗位补充的一段示例经历，请在投递前替换为可核实的真实信息。",
        }
        if self.provider:
            job = self.jobs.get(job_id)
            generated = self.provider.complete_json(
                workflow="fabricated_resume_experience",
                instructions=(
                    "用户已明确确认编造经历的风险。生成一段中文简历经历，贴近岗位 JD。"
                    "不得冒用真实知名公司名称；内容必须便于用户后续核实和修改。"
                ),
                payload={"job_title": job.get("title"), "jd_text": job["jd_text"]},
                schema=FABRICATED_EXPERIENCE_SCHEMA,
            )
        section.blocks.append(
            ResumeBlock(
                block_id=str(uuid4()),
                heading=generated["heading"].strip(),
                meta=generated["meta"].strip(),
                paragraphs=[
                    ResumeParagraph(
                        paragraph_id=str(uuid4()),
                        text=generated["text"].strip(),
                        source_entry_ids=[],
                        risk_flags=["fabricated_user_confirmed"],
                    )
                ],
            )
        )
        document.sections.sort(key=lambda item: item.order)
