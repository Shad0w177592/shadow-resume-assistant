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
from app.services.ai_schemas import RESUME_REWRITE_SCHEMA, RESUME_TAILOR_SCHEMA
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
            selected = self._apply_section_limits(config, selected, warnings)
            selected = self._fit_budget(config, selected, warnings)
            steps["SELECT_EVIDENCE"] = "completed"

            steps["GENERATE_SECTIONS"] = "running"
            document = self._build_document(config, profile["personal_info"], selected)
            ai_addition_warnings: list[str] = []
            if self.provider:
                self._rewrite_with_ai(document, selected, requirements, config)
                ai_addition_warnings = self._tailor_summary_and_skills(
                    document,
                    selected,
                    requirements,
                    config,
                    str(profile["personal_info"].get("summary") or ""),
                )
            steps["GENERATE_SECTIONS"] = "completed"

            steps["DETERMINISTIC_FACT_CHECK"] = "running"
            entry_by_id = {entry["id"]: entry for entry in selected}
            violations = []
            fact_warnings: list[str] = list(ai_addition_warnings)
            for section in document.sections:
                for block in section.blocks:
                    for paragraph in block.paragraphs:
                        if section.section_key == "summary":
                            source_texts = [
                                json.dumps(
                                    {"summary": profile["personal_info"].get("summary") or ""},
                                    ensure_ascii=False,
                                ),
                                *[
                                    json.dumps(
                                        {"title": entry["title"], "payload": entry["payload"]},
                                        ensure_ascii=False,
                                    )
                                    for entry in selected
                                ],
                            ]
                        else:
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
                        paragraph.risk_flags.extend(
                            violation
                            for violation in result.violations
                            if violation not in paragraph.risk_flags
                        )
                        violations.extend(result.violations)
            if violations:
                detail = explain_violations(violations)
                fact_warnings.append(f"{detail}。这些内容已保留在草稿中，请在使用前核实")
            steps["DETERMINISTIC_FACT_CHECK"] = "completed"

            # V1 mock provider performs no semantic rewrite;
            # deterministic checks remain authoritative.
            steps["MODEL_REVIEW"] = "completed"
            steps["COVERAGE_CHECK"] = "completed"
            steps["LAYOUT_CHECK"] = "running"
            layout = self._layout(config, document)
            if layout["status"] == "overflow":
                warnings.append("内容可能超出所选页数；草稿已生成，请在导出前调整内容或页数")
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
            return {
                **draft,
                "workflow_task_id": task_id,
                "layout": layout,
                "warnings": warnings,
                "fact_warnings": fact_warnings,
            }
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
        rewrite_sections = set(config.get("rewrite_sections") or [])
        allowed = {}
        paragraphs = []
        entry_by_id = {entry["id"]: entry for entry in entries}
        for section in document.sections:
            if section.section_key not in rewrite_sections or section.section_key == "summary":
                continue
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
        if not paragraphs:
            return
        result = self.provider.complete_json(
            workflow="resume_rewrite",
            instructions=(
                "你是中文简历编辑器。只重写用户勾选栏目中给定的段落；未勾选栏目不会发送给你。"
                "不新增公司、岗位、学校、日期、技能、数字或成果。"
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

    def _tailor_summary_and_skills(
        self,
        document: ResumeDocument,
        entries: list[dict[str, Any]],
        requirements: list[dict[str, Any]],
        config: dict[str, Any],
        original_summary: str,
    ) -> list[str]:
        assert self.provider is not None
        rewrite_sections = set(config.get("rewrite_sections") or [])
        if not rewrite_sections.intersection({"summary", "skills"}):
            return []
        result = self.provider.complete_json(
            workflow="resume_tailor_profile",
            instructions=(
                "你是中文求职简历编辑器。根据岗位要求和候选人的真实经历完成两个任务。"
                "自我介绍必须使用真实经历中的可迁移能力，说明这些能力如何胜任目标岗位；"
                "不得编造公司、学校、岗位、日期、数字或成果。"
                "专业技能可以按用户授权补充 1 至 2 条目标岗位能力，即使资料中没有直接写出；"
                "这类补充会在生成后明确提示用户核实。技能描述要具体、可编辑，不要虚构任职经历。"
                "只处理 payload 中标记为 true 的栏目。"
            ),
            payload={
                "requirements": requirements,
                "modify_summary": "summary" in rewrite_sections,
                "modify_skills": "skills" in rewrite_sections,
                "original_summary": original_summary,
                "evidence": [
                    {
                        "section_key": entry["section_key"],
                        "title": entry["title"],
                        "payload": redact_payload_for_ai(entry["payload"]),
                    }
                    for entry in entries
                ],
            },
            schema=RESUME_TAILOR_SCHEMA,
        )
        warnings: list[str] = []
        if "summary" in rewrite_sections:
            summary = result["summary"].strip()
            if not summary:
                raise AIProviderError("invalid_output", "AI 没有返回自我介绍，未保存本次结果")
            summary_section = next(
                (section for section in document.sections if section.section_key == "summary"),
                None,
            )
            if summary_section is None:
                raise AIProviderError("invalid_output", "自我介绍栏目缺失，未保存本次结果")
            summary_section.blocks[0].paragraphs[0].text = summary
        if "skills" in rewrite_sections:
            additions = result["skills"][:2]
            if not additions:
                raise AIProviderError("invalid_output", "AI 没有返回岗位专业技能，未保存本次结果")
            skills_section = next(
                (section for section in document.sections if section.section_key == "skills"),
                None,
            )
            if skills_section is None:
                setting = next(
                    item for item in config["sections"] if item["section_key"] == "skills"
                )
                skills_section = ResumeSection(
                    section_id=str(uuid4()),
                    section_key="skills",
                    title=setting["title"],
                    order=setting["order"],
                    column=("full" if config["template"] == "single_column" else setting["column"]),
                    blocks=[],
                )
                document.sections.append(skills_section)
                document.sections.sort(key=lambda section: section.order)
            existing = {
                f"{block.heading.strip()}\n{paragraph.text.strip()}"
                for block in skills_section.blocks
                for paragraph in block.paragraphs
            }
            added_blocks = []
            added_headings = []
            for item in additions:
                heading = item["heading"].strip()
                text = item["text"].strip()
                if not heading or not text or f"{heading}\n{text}" in existing:
                    continue
                added_headings.append(heading)
                added_blocks.append(
                    ResumeBlock(
                        block_id=str(uuid4()),
                        heading=heading,
                        paragraphs=[
                            ResumeParagraph(
                                paragraph_id=str(uuid4()),
                                text=text,
                                source_entry_ids=[],
                                risk_flags=["ai_added_skill"],
                            )
                        ],
                    )
                )
            if not added_blocks:
                raise AIProviderError(
                    "invalid_output", "AI 返回的岗位专业技能与原内容重复，未保存本次结果"
                )
            skills_section.blocks = added_blocks + skills_section.blocks
            warnings.append(
                f"AI 为目标岗位补充了专业技能：{'、'.join(added_headings)}。"
                "这些是 AI 根据岗位要求起草的内容，请确认自己确实掌握后再投递"
            )
        return warnings

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
        for source_index, entry in enumerate(entries):
            mode = modes.get(entry["id"], "ai_decide")
            if mode == "exclude_this_resume" or entry["section_key"] not in enabled:
                continue
            if not any(str(value).strip() for value in entry["payload"].values() if value):
                warnings.append(f"已忽略空记录：{entry['title'] or entry['id']}")
                continue
            item = dict(entry)
            item["selection_mode"] = mode
            item["relevance_score"] = evidence_scores[entry["id"]]
            item["source_index"] = source_index
            selected.append(item)
        section_order = {section["section_key"]: section["order"] for section in config["sections"]}
        rewrite_sections = set(config.get("rewrite_sections") or [])
        selected.sort(
            key=lambda item: (
                section_order.get(item["section_key"], 999),
                (
                    item["selection_mode"] != "must_include",
                    -item.get("importance", 3),
                    -item["relevance_score"],
                    item["source_index"],
                )
                if item["section_key"] in rewrite_sections
                else (False, 0, 0, item["source_index"]),
            )
        )
        return selected, warnings

    @staticmethod
    def _apply_section_limits(
        config: dict[str, Any], entries: list[dict[str, Any]], warnings: list[str]
    ) -> list[dict[str, Any]]:
        limits = {
            section["section_key"]: section.get("max_entries") for section in config["sections"]
        }
        counts: defaultdict[str, int] = defaultdict(int)
        selected = []
        for entry in entries:
            section_key = entry["section_key"]
            limit = limits.get(section_key)
            must_include = entry["selection_mode"] == "must_include"
            if limit is None or counts[section_key] < limit or must_include:
                selected.append(entry)
                counts[section_key] += 1
                continue
            warnings.append(f"因“{section_key}”栏目条数设置省略：{entry['title'] or '未命名记录'}")
        return selected

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
        rewrite_sections = set(config.get("rewrite_sections") or [])

        def size() -> int:
            return sum(len(json.dumps(item["payload"], ensure_ascii=False)) for item in result)

        while size() > maximum:
            removable = next(
                (
                    item
                    for item in reversed(result)
                    if item["selection_mode"] != "must_include"
                    and item["section_key"] in rewrite_sections
                ),
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
        summary_setting = section_config["summary"]
        summary_text = str(personal_info.get("summary") or "").strip()
        if summary_setting["enabled"] and (
            summary_text or "summary" in set(config.get("rewrite_sections") or [])
        ):
            sections.append(
                ResumeSection(
                    section_id=str(uuid4()),
                    section_key="summary",
                    title=summary_setting["title"],
                    order=summary_setting["order"],
                    column=(
                        "full"
                        if config["template"] == "single_column"
                        else summary_setting["column"]
                    ),
                    blocks=[
                        ResumeBlock(
                            block_id=str(uuid4()),
                            heading="",
                            paragraphs=[
                                ResumeParagraph(
                                    paragraph_id=str(uuid4()),
                                    text=summary_text,
                                    source_entry_ids=[entry["id"] for entry in entries],
                                )
                            ],
                        )
                    ],
                )
            )
        for section_key, section_entries in grouped.items():
            setting = section_config[section_key]
            blocks = []
            for entry in section_entries:
                payload = entry["payload"]
                source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
                content = str(payload.get("content") or "").strip()
                text = (
                    ResumeWorkflowService._source_body_text(section_key, content, source)
                    if source and content
                    else "；".join(
                        str(value).strip()
                        for value in payload.values()
                        if value and not isinstance(value, dict)
                    )
                )
                meta = (
                    content.splitlines()[0].strip()
                    if source and content
                    else " · ".join(
                        str(payload[key]) for key in ("organization", "time") if payload.get(key)
                    )
                )
                blocks.append(
                    ResumeBlock(
                        block_id=str(uuid4()),
                        heading=entry["title"] or str(payload.get("title") or ""),
                        meta=meta,
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
                headline="",
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
    def _source_body_text(section_key: str, content: str, source: dict[str, Any]) -> str:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        block_count = len(source.get("block_ids") or [])
        experience_sections = {
            "education",
            "work",
            "internship",
            "project",
            "campus",
            "awards",
            "other",
        }
        if section_key in experience_sections and block_count >= 3 and len(lines) >= 3:
            return "\n".join(lines[2:])
        if section_key in experience_sections and block_count >= 2 and len(lines) >= 2:
            return "\n".join(lines[1:])
        return content

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
