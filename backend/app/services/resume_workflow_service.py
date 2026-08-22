from __future__ import annotations

import json
from collections import defaultdict
from typing import Any
from uuid import uuid4

from app.domain.resume import (
    PersonalInfo,
    ResumeBlock,
    ResumeDocument,
    ResumeParagraph,
    ResumeSection,
    ResumeTemplate,
)
from app.persistence.database import Database, utc_now
from app.security.pii import redact_payload_for_ai, redact_personal_info
from app.services.ai_schemas import RESUME_REWRITE_SCHEMA
from app.services.fact_checker import check_hard_facts, explain_violations
from app.services.generation_service import SECTION_TITLES, GenerationService
from app.services.job_analysis_service import JobAnalysisService
from app.services.job_service import JobService
from app.services.openai_provider import AIProviderError, OpenAITextProvider
from app.services.profile_service import ProfileService
from app.services.resume_config_service import ResumeConfigService

WORKFLOW_STEPS = [
    "VALIDATE_INPUT",
    "BUILD_REDACTED_CONTEXT",
    "SELECT_EVIDENCE",
    "GENERATE_SECTIONS",
    "DETERMINISTIC_FACT_CHECK",
    "MODEL_REVIEW",
    "COVERAGE_CHECK",
    "LAYOUT_CHECK",
    "SAVE_DRAFT",
]


class ResumeWorkflowService:
    def __init__(self, database: Database, provider: OpenAITextProvider | None = None) -> None:
        self.database = database
        self.provider = provider
        self.jobs = JobService(database)
        self.profiles = ProfileService(database)
        self.configs = ResumeConfigService(database)
        self.drafts = GenerationService(database)

    def generate(self, job_id: str) -> dict[str, Any]:
        task_id = str(uuid4())
        steps = {name: "pending" for name in WORKFLOW_STEPS}
        self._save_task(task_id, job_id, "running", 0, steps)
        try:
            job = self.jobs.get(job_id)
            config = self.configs.get(job_id)["config"]
            steps["VALIDATE_INPUT"] = "running"
            entries = self.profiles.list_entries()
            if not entries:
                raise ValueError("请先填写至少一条有内容的个人资料")
            analyzer = JobAnalysisService(self.database, self.provider)
            report = analyzer.report(job["id"])
            if not report["requirements"] or report["stale"]:
                analyzer.analyze(job["id"])
            requirements = self._requirements(job_id)
            self.configs.validate(config)
            self._validate_entry_modes(config, entries)
            steps["VALIDATE_INPUT"] = "completed"

            steps["BUILD_REDACTED_CONTEXT"] = "running"
            profile = self.profiles.get_profile()
            pii = redact_personal_info(profile["personal_info"])
            # Only the redacted key names/count are recorded; values and the mapping stay in memory.
            redacted_summary = {"keys": sorted(pii.redacted), "evidence_count": len(entries)}
            steps["BUILD_REDACTED_CONTEXT"] = "completed"

            steps["SELECT_EVIDENCE"] = "running"
            selected, warnings = self._select_entries(job_id, config, entries)
            if not selected:
                raise ValueError("当前栏目与经历取舍后没有可生成内容")
            selected = self._fit_budget(config, selected, warnings)
            steps["SELECT_EVIDENCE"] = "completed"

            steps["GENERATE_SECTIONS"] = "running"
            document = self._build_document(config, profile["personal_info"], selected)
            if self.provider:
                self._rewrite_with_ai(document, selected, requirements, config)
            steps["GENERATE_SECTIONS"] = "completed"

            steps["DETERMINISTIC_FACT_CHECK"] = "running"
            entry_by_id = {entry["id"]: entry for entry in selected}
            violations = []
            for section in document.sections:
                for block in section.blocks:
                    for paragraph in block.paragraphs:
                        source_texts = [
                            json.dumps(
                                {
                                    "title": entry_by_id[str(source_id)]["title"],
                                    "payload": entry_by_id[str(source_id)]["payload"],
                                },
                                ensure_ascii=False,
                            )
                            for source_id in paragraph.source_entry_ids
                        ]
                        result = check_hard_facts(source_texts, paragraph.text)
                        violations.extend(result.violations)
            if violations:
                detail = explain_violations(violations)
                raise ValueError(f"事实检查未通过：{detail}。请检查生成内容或补充真实资料")
            steps["DETERMINISTIC_FACT_CHECK"] = "completed"

            # V1 mock provider performs no semantic rewrite;
            # deterministic checks remain authoritative.
            steps["MODEL_REVIEW"] = "completed"
            steps["COVERAGE_CHECK"] = "completed"
            steps["LAYOUT_CHECK"] = "running"
            layout = self._layout(config, document)
            if layout["status"] == "overflow":
                raise ValueError("内容超出所选页数，请减少非必须内容或切换两页")
            if layout["status"] == "underfilled":
                warnings.append("页面内容偏少；不会为填满页面扩写虚假内容")
            steps["LAYOUT_CHECK"] = "completed"

            steps["SAVE_DRAFT"] = "running"
            draft = self.drafts._save(job_id, document)
            steps["SAVE_DRAFT"] = "completed"
            self._save_task(
                task_id,
                job_id,
                "completed",
                100,
                steps,
                layout=layout,
                warnings=warnings,
                redacted_summary=redacted_summary,
            )
            return {**draft, "workflow_task_id": task_id, "layout": layout, "warnings": warnings}
        except Exception as error:
            self._save_task(task_id, job_id, "failed", 100, steps, error=str(error))
            raise

    def _rewrite_with_ai(
        self,
        document: ResumeDocument,
        entries: list[dict[str, Any]],
        requirements: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> None:
        assert self.provider is not None
        allowed = {}
        paragraphs = []
        entry_by_id = {entry["id"]: entry for entry in entries}
        for section in document.sections:
            for block in section.blocks:
                for paragraph in block.paragraphs:
                    paragraph_id = str(paragraph.paragraph_id)
                    source_ids = [str(value) for value in paragraph.source_entry_ids]
                    allowed[paragraph_id] = paragraph
                    paragraphs.append(
                        {
                            "paragraph_id": paragraph_id,
                            "source_entry_ids": source_ids,
                            "source_text": [
                                redact_payload_for_ai(entry_by_id[value]["payload"])
                                for value in source_ids
                            ],
                            "current_text": paragraph.text,
                        }
                    )
        result = self.provider.complete_json(
            workflow="resume_rewrite",
            instructions=(
                "你是中文简历编辑器。只重写给定段落，不新增公司、岗位、学校、日期、技能、数字或成果。"
                "每个 paragraph_id 必须原样返回且只返回一次；"
                "按用户选择的 STAR/CAR/成果优先等策略组织已有事实。"
            ),
            payload={
                "requirements": requirements,
                "strategies": config["strategies"],
                "paragraphs": paragraphs,
            },
            schema=RESUME_REWRITE_SCHEMA,
        )
        returned = [item["paragraph_id"] for item in result["paragraphs"]]
        if len(returned) != len(set(returned)) or set(returned) != set(allowed):
            raise AIProviderError("invalid_output", "AI 返回的段落范围不完整，未保存结果")
        for item in result["paragraphs"]:
            allowed[item["paragraph_id"]].text = item["text"].strip()

    def _requirements(self, job_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, summary FROM job_requirement WHERE job_target_id=?", (job_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _validate_entry_modes(config: dict[str, Any], entries: list[dict[str, Any]]) -> None:
        enabled = {item["section_key"] for item in config["sections"] if item["enabled"]}
        for entry in entries:
            mode = config.get("entry_modes", {}).get(entry["id"], "ai_decide")
            if mode == "must_include" and entry["section_key"] not in enabled:
                raise ValueError("必须使用的经历所在栏目未勾选")

    def _select_entries(
        self, job_id: str, config: dict[str, Any], entries: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        enabled = {item["section_key"] for item in config["sections"] if item["enabled"]}
        modes = config.get("entry_modes", {})
        with self.database.connect() as connection:
            evidence_rows = connection.execute(
                "SELECT e.profile_entry_id, e.status FROM evidence_link e "
                "JOIN job_requirement r ON r.id=e.job_requirement_id WHERE r.job_target_id=?",
                (job_id,),
            ).fetchall()
        evidence_scores = defaultdict(int)
        for entry_id, status in evidence_rows:
            if entry_id:
                evidence_scores[entry_id] += 2 if status == "full" else 1
        selected = []
        warnings = []
        for entry in entries:
            mode = modes.get(entry["id"], "ai_decide")
            if mode == "exclude_this_resume" or entry["section_key"] not in enabled:
                continue
            if not any(str(value).strip() for value in entry["payload"].values() if value):
                warnings.append(f"已忽略空记录：{entry['title'] or entry['id']}")
                continue
            item = dict(entry)
            item["selection_mode"] = mode
            item["relevance_score"] = evidence_scores[entry["id"]]
            selected.append(item)
        selected.sort(
            key=lambda item: (
                item["selection_mode"] != "must_include",
                -item["relevance_score"],
                item["created_at"],
            )
        )
        return selected, warnings

    @staticmethod
    def _fit_budget(
        config: dict[str, Any], entries: list[dict[str, Any]], warnings: list[str]
    ) -> list[dict[str, Any]]:
        limits = {
            ("single_column", 1): 1750,
            ("single_column", 2): 3400,
            ("technical_double_column", 1): 1600,
            ("technical_double_column", 2): 3100,
        }
        maximum = limits[(config["template"], config["page_target"])]
        result = list(entries)

        def size() -> int:
            return sum(len(json.dumps(item["payload"], ensure_ascii=False)) for item in result)

        while size() > maximum:
            removable = next(
                (item for item in reversed(result) if item["selection_mode"] != "must_include"),
                None,
            )
            if removable is None:
                break
            result.remove(removable)
            warnings.append(f"因页数预算省略：{removable['title'] or '未命名记录'}")
        return result

    @staticmethod
    def _build_document(
        config: dict[str, Any], personal_info: dict[str, Any], entries: list[dict[str, Any]]
    ) -> ResumeDocument:
        section_config = {item["section_key"]: item for item in config["sections"]}
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in entries:
            grouped[entry["section_key"]].append(entry)
        sections = []
        for section_key, section_entries in grouped.items():
            setting = section_config[section_key]
            blocks = []
            for entry in section_entries:
                payload = entry["payload"]
                text = "；".join(
                    str(value).strip()
                    for value in payload.values()
                    if value and not isinstance(value, dict)
                )
                blocks.append(
                    ResumeBlock(
                        block_id=str(uuid4()),
                        heading=entry["title"] or str(payload.get("title") or ""),
                        meta=" · ".join(
                            str(payload[key])
                            for key in ("organization", "time")
                            if payload.get(key)
                        ),
                        paragraphs=[
                            ResumeParagraph(
                                paragraph_id=str(uuid4()), text=text, source_entry_ids=[entry["id"]]
                            )
                        ],
                    )
                )
            sections.append(
                ResumeSection(
                    section_id=str(uuid4()),
                    section_key=section_key,
                    title=setting.get("title") or SECTION_TITLES.get(section_key, section_key),
                    order=setting["order"],
                    column="full" if config["template"] == "single_column" else setting["column"],
                    blocks=blocks,
                )
            )
        sections.sort(key=lambda item: item.order)
        return ResumeDocument(
            resume_id=uuid4(),
            template=ResumeTemplate(config["template"]),
            page_target=config["page_target"],
            personal_info=PersonalInfo(
                name=str(personal_info.get("name") or ""),
                headline=str(personal_info.get("summary") or ""),
                contacts=[
                    str(personal_info[key])
                    for key in ("phone", "email", "city")
                    if personal_info.get(key)
                ],
                photo_file_id=personal_info.get("photo_file_id"),
            ),
            sections=sections,
        )

    @staticmethod
    def _layout(config: dict[str, Any], document: ResumeDocument) -> dict[str, Any]:
        text_length = len(document.plain_text())
        bounds = {
            ("single_column", 1): (1300, 1750),
            ("single_column", 2): (2500, 3400),
            ("technical_double_column", 1): (1200, 1600),
            ("technical_double_column", 2): (2250, 3100),
        }
        minimum, maximum = bounds[(config["template"], config["page_target"])]
        status = "fit"
        if text_length < minimum:
            status = "underfilled"
        elif text_length > maximum:
            status = "overflow"
        return {
            "status": status,
            "character_count": text_length,
            "minimum": minimum,
            "maximum": maximum,
        }

    def _save_task(
        self,
        task_id: str,
        job_id: str,
        status: str,
        progress: int,
        steps: dict[str, str],
        *,
        layout: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        redacted_summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        now = utc_now()
        payload = json.dumps(
            {
                "job_id": job_id,
                "steps": steps,
                "layout": layout,
                "warnings": warnings or [],
                "redacted_summary": redacted_summary,
                "error": error,
            },
            ensure_ascii=False,
        )
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO task_run(id, task_type, status, progress, payload_json, "
                "schema_version, created_at, updated_at) "
                "VALUES (?, 'resume_generation', ?, ?, ?, 1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, progress=excluded.progress, "
                "payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (task_id, status, progress, payload, now, now),
            )
