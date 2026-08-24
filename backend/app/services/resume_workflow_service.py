from __future__ import annotations

import json
import re
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
                    job,
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
                        meaningful_violations = tuple(
                            violation
                            for violation in result.violations
                            if not violation.startswith("unsupported_number:")
                        )
                        paragraph.risk_flags.extend(
                            violation
                            for violation in meaningful_violations
                            if violation not in paragraph.risk_flags
                        )
                        violations.extend(meaningful_violations)
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
        job: dict[str, Any],
        config: dict[str, Any],
        original_summary: str,
    ) -> list[str]:
        assert self.provider is not None
        rewrite_sections = set(config.get("rewrite_sections") or [])
        if not rewrite_sections.intersection({"summary", "skills"}):
            return []
        summary_style_target = self._summary_style_target(original_summary)
        tailor_payload = {
            "target_job": {
                "company": job.get("company"),
                "title": job.get("title"),
                "jd_text": job.get("jd_text"),
            },
            "requirements": requirements,
            "modify_summary": "summary" in rewrite_sections,
            "modify_skills": "skills" in rewrite_sections,
            "original_summary": original_summary,
            "summary_style_target": summary_style_target,
            "evidence": [
                {
                    "section_key": entry["section_key"],
                    "title": entry["title"],
                    "payload": redact_payload_for_ai(entry["payload"]),
                }
                for entry in entries
            ],
        }
        instructions = (
            "你是资深中文招聘经理和简历编辑器。只修改用户勾选的栏目。"
            "先依据完整 JD 识别目标岗位的核心任务、交付物、工具和能力，再结合候选人证据写作。"
            "自我介绍必须保持原文的篇幅和信息密度，严格按 payload.summary_style_target 的字符范围"
            "与句数目标写作；原文较长时不得压缩成两句话。直接点明目标岗位，"
            "使用至少 2 项具体经历证据，"
            "说明可迁移能力怎样用于岗位任务；尽量无主语，禁止反复使用‘我/本人’，禁止‘能够胜任、"
            "快速适应、学习能力强、认真负责’等空话，不照抄 JD。"
            "专业技能补充 1 至 2 条：标题必须是候选人可核实的具体工具或可迁移能力。"
            "技能之间必须是不同能力，不得同时返回 AI 信息搜集与 AI 工具应用等语义重叠项；"
            "应合并为一条 AI 工具应用，再优先从证据中选择 Office/PPT/Excel、文档写作、"
            "视频剪辑等另一项不同能力。"
            "简洁到 4 至 14 个字符，"
            "例如‘Excel 数据整理’‘SQL 数据查询’‘市场数据分析’；"
            "目标行业、品种、公司和岗位名称只能写在"
            "正文用途里，禁止写成黑色系数据研究能力这类行业包装标题。数据类技能必须明确写出"
            "候选人使用的 Excel、SQL、Python、Power BI、Tableau、SPSS 等具体工具；正文写清工具或方法、岗位任务及"
            "可交付成果；禁止只写沟通能力、团队协作、执行力、数据整理等泛化标题。"
            "资料中未直接出现的岗位技能允许作为 AI 建议补充，生成后会提示用户核实；"
            "但不得编造公司、学校、岗位、日期、数字、业绩或任职经历。"
        )
        result = self.provider.complete_json(
            workflow="resume_tailor_profile",
            instructions=instructions,
            payload=tailor_payload,
            schema=RESUME_TAILOR_SCHEMA,
        )
        quality_issues = self._tailor_quality_issues(
            result, rewrite_sections, summary_style_target
        )
        if quality_issues:
            try:
                retry_result = self.provider.complete_json(
                    workflow="resume_tailor_profile",
                    instructions=(
                        instructions
                        + "上一次草稿存在下列质量问题。保留真实证据，逐项修正后返回完整新结果。"
                    ),
                    payload={
                        **tailor_payload,
                        "previous_result": result,
                        "quality_issues": quality_issues,
                    },
                    schema=RESUME_TAILOR_SCHEMA,
                )
                retry_issues = self._tailor_quality_issues(
                    retry_result, rewrite_sections, summary_style_target
                )
                if len(retry_issues) <= len(quality_issues):
                    result = retry_result
            except AIProviderError:
                pass
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
            added_topics: set[str] = set()
            for item in additions:
                heading = item["heading"].strip()
                text = item["text"].strip()
                topic = self._skill_topic(heading, text)
                if topic and topic in added_topics:
                    continue
                if not heading or not text or f"{heading}\n{text}" in existing:
                    continue
                if topic:
                    added_topics.add(topic)
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

    @staticmethod
    def _summary_style_target(original_summary: str) -> dict[str, int]:
        compact = re.sub(r"\s+", "", original_summary)
        length = len(compact)
        if length >= 80:
            minimum = max(80, round(length * 0.85))
            maximum = max(minimum + 20, round(length * 1.15))
        else:
            minimum, maximum = 90, 160
        sentence_count = len(re.findall(r"[。！？]", original_summary))
        return {
            "character_min": minimum,
            "character_max": maximum,
            "sentence_target": max(3, sentence_count),
        }

    @staticmethod
    def _tailor_quality_issues(
        result: dict[str, Any],
        rewrite_sections: set[str],
        summary_style_target: dict[str, int],
    ) -> list[str]:
        issues = []
        if "summary" in rewrite_sections:
            summary = str(result.get("summary") or "").strip()
            compact_length = len(re.sub(r"\s+", "", summary))
            if compact_length < summary_style_target["character_min"]:
                issues.append("自我介绍短于原文篇幅目标，不能压缩成两句话")
            if compact_length > summary_style_target["character_max"]:
                issues.append("自我介绍长于原文篇幅目标，需要保持原文密度")
            sentence_count = len(re.findall(r"[。！？]", summary))
            if sentence_count < max(2, summary_style_target["sentence_target"] - 1):
                issues.append("自我介绍句数明显少于原文，应保留相近的信息层次")
            if summary.count("我") > 2:
                issues.append("自我介绍第一人称过多，应改为简洁职业摘要")
            banned = ("能够胜任", "快速适应", "学习能力强", "认真负责")
            if any(value in summary for value in banned):
                issues.append("自我介绍包含空泛评价，应改为证据和岗位任务")
        if "skills" in rewrite_sections:
            generic_headings = {
                "沟通能力",
                "团队协作",
                "执行力",
                "抗压能力",
                "学习能力",
                "数据搜集与结构化整理",
                "沟通跟进与协同推进",
            }
            seen_topics: dict[str, str] = {}
            for skill in result.get("skills") or []:
                heading = str(skill.get("heading") or "").strip()
                text = str(skill.get("text") or "").strip()
                topic = ResumeWorkflowService._skill_topic(heading, text)
                if topic and topic in seen_topics:
                    issues.append(
                        f"技能 {heading} 与 {seen_topics[topic]} 语义重复，应合并后改选另一项不同能力"
                    )
                elif topic:
                    seen_topics[topic] = heading
                if heading in generic_headings:
                    issues.append(f"技能标题“{heading}”过于泛化，需改为具体工具或能力")
                if len(re.sub(r"\s+", "", heading)) > 14:
                    issues.append(f"技能标题“{heading}”过长，应改为简洁的工具或能力名称")
                if re.search(r"黑色系|白色系|有色系|商品期货|金融行业|目标岗位", heading):
                    issues.append(f"技能标题“{heading}”含行业包装，应只保留具体工具或能力")
                if "数据" in heading and not re.search(
                    r"Excel|SQL|Python|Power\s*BI|Tableau|SPSS|R语言",
                    f"{heading} {text}",
                    re.IGNORECASE,
                ):
                    issues.append(f"数据类技能 {heading} 没有写明 Excel、SQL 等具体工具")
                if len(text) < 30 or text.startswith(("可基于", "能够持续")):
                    issues.append(f"技能“{heading or '未命名'}”缺少方法、岗位任务或交付物")
        return issues

    @staticmethod
    def _skill_topic(heading: str, text: str) -> str:
        value = f"{heading} {text}".lower()
        if re.search(r"\bai\b|chatgpt|deepseek|codex|大模型|人工智能", value):
            return "ai_tools"
        if re.search(r"excel|sql|python|power\s*bi|tableau|spss|数据", value):
            return "data"
        if re.search(r"ppt|powerpoint|word|office|文档|报告", value):
            return "office_documents"
        if re.search(r"剪辑|pr\b|premiere|达芬奇|final\s*cut|视频", value):
            return "video_editing"
        return ""

    def _requirements(self, job_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, requirement_type, summary, source_text "
                "FROM job_requirement WHERE job_target_id=?",
                (job_id,),
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
        deduplicated = []
        duplicate_positions: dict[tuple[str, str, str], int] = {}
        for item in selected:
            duplicate_key = self._imported_duplicate_key(item)
            if duplicate_key is None or duplicate_key not in duplicate_positions:
                if duplicate_key is not None:
                    duplicate_positions[duplicate_key] = len(deduplicated)
                deduplicated.append(item)
                continue
            position = duplicate_positions[duplicate_key]
            current = deduplicated[position]
            deduplicated[position] = self._merge_duplicate_entries(current, item)
            warnings.append(f"已合并重复导入经历：{item['title'] or item['id']}")
        selected = deduplicated
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
    def _imported_duplicate_key(entry: dict[str, Any]) -> tuple[str, str, str] | None:
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            return None

        def normalize(value: Any) -> str:
            return re.sub(r"\s+", "", str(value or "")).lower()

        title = normalize(entry.get("title"))
        raw_content = str(payload.get("content") or "")
        content = normalize(raw_content)
        lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
        section_key = str(entry.get("section_key") or "")
        if content and len(lines) >= 2:
            return (section_key, "imported_multiline", content)
        if content and section_key == "skills" and re.search(r"[：:]", raw_content):
            skill_name = normalize(re.split(r"[：:]", raw_content, maxsplit=1)[0])
            return (section_key, skill_name, content)
        if content:
            return (section_key, title, content)
        return (section_key, "title", title) if title else None

    @staticmethod
    def _merge_duplicate_entries(
        current: dict[str, Any], candidate: dict[str, Any]
    ) -> dict[str, Any]:
        def has_source(item: dict[str, Any]) -> bool:
            payload = item.get("payload")
            return isinstance(payload, dict) and isinstance(payload.get("source"), dict)

        canonical = candidate if has_source(candidate) and not has_source(current) else current
        merged = dict(canonical)
        merged["payload"] = dict(canonical.get("payload") or {})
        merged["selection_mode"] = (
            "must_include"
            if "must_include"
            in {current.get("selection_mode"), candidate.get("selection_mode")}
            else canonical.get("selection_mode", "ai_decide")
        )
        merged["importance"] = max(
            int(current.get("importance", 3)), int(candidate.get("importance", 3))
        )
        merged["relevance_score"] = max(
            int(current.get("relevance_score", 0)),
            int(candidate.get("relevance_score", 0)),
        )
        merged["source_index"] = min(
            int(current.get("source_index", 0)), int(candidate.get("source_index", 0))
        )
        return merged

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
