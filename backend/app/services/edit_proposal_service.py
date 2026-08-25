from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import uuid4

from app.domain.resume import ResumeDocument
from app.persistence.database import Database, utc_now
from app.security.pii import redact_text_for_ai
from app.services.ai_schemas import EDIT_REWRITE_SCHEMA
from app.services.fact_checker import check_hard_facts, explain_violations
from app.services.generation_service import GenerationService
from app.services.openai_provider import OpenAITextProvider
from app.services.profile_service import ProfileService
from app.services.resume_config_service import ResumeConfigService

FABRICATION_TERMS = ("编造", "虚构", "假装我有", "写一个不存在")


class EditProposalService:
    def __init__(self, database: Database, provider: OpenAITextProvider | None = None) -> None:
        self.database = database
        self.provider = provider
        self.drafts = GenerationService(database)
        self.profiles = ProfileService(database)
        self.configs = ResumeConfigService(database)

    def propose(
        self, job_id: str, target_paragraph_id: str, instruction: str, save_scope: str
    ) -> dict[str, Any]:
        if any(term in instruction for term in FABRICATION_TERMS):
            raise ValueError("不能生成可直接用于正式简历的虚假经历；请改为补充真实证据或写作框架")
        if save_scope not in {"current_resume", "also_profile"}:
            raise ValueError("保存范围无效")
        draft = self.drafts.get_draft(job_id)
        document = ResumeDocument.model_validate(draft["document"])
        target_kind, target = self._find_target(document, target_paragraph_id)
        if target_kind == "greeting":
            before = target.greeting_message
            evidence_ids = list(
                dict.fromkeys(
                    str(source_id)
                    for section in target.sections
                    for block in section.blocks
                    for paragraph in block.paragraphs
                    for source_id in paragraph.source_entry_ids
                )
            )
        elif target_kind == "section":
            before = target.title
            evidence_ids = list(
                dict.fromkeys(
                    str(source_id)
                    for block in target.blocks
                    for paragraph in block.paragraphs
                    for source_id in paragraph.source_entry_ids
                )
            )
        elif target_kind == "heading":
            before = target.heading
            evidence_ids = list(
                dict.fromkeys(
                    str(source_id)
                    for paragraph in target.paragraphs
                    for source_id in paragraph.source_entry_ids
                )
            )
        else:
            before = target.text
            evidence_ids = [str(item) for item in target.source_entry_ids]
        source_texts = []
        for entry_id in evidence_ids:
            entry = self.profiles.get_entry(entry_id)
            source_texts.append(
                json.dumps(
                    {"title": entry["title"], "payload": entry["payload"]}, ensure_ascii=False
                )
            )
        source_texts.append(before)
        if self.provider:
            greeting_instruction = (
                "只修改BOSS直聘打招呼语，最多142个字符，突出已有经历、具体技能、"
                "岗位动机和可提供的价值，不编造事实。"
            )
            section_instruction = "只修改简历栏目大标题，保持栏目含义准确，名称简洁清晰。"
            heading_instruction = "只修改目标条目标题，使标题简洁、具体且准确反映已有内容。"
            paragraph_instruction = (
                "只修改目标段落的表达，不新增或更改公司、岗位、学校、日期、技能、数字、职责和成果。"
            )
            instruction_by_kind = {
                "greeting": greeting_instruction,
                "section": section_instruction,
                "heading": heading_instruction,
                "paragraph": paragraph_instruction,
            }
            workflow_by_kind = {
                "greeting": "greeting_rewrite",
                "section": "section_title_rewrite",
                "heading": "heading_rewrite",
                "paragraph": "paragraph_rewrite",
            }
            result = self.provider.complete_json(
                workflow=workflow_by_kind[target_kind],
                instructions=instruction_by_kind[target_kind]
                + "返回修改后的文字及简短理由；这只是建议，不能声称已经保存。",
                payload={
                    "target_kind": target_kind,
                    "target_text": before,
                    "instruction": instruction,
                    "evidence": [redact_text_for_ai(value) for value in source_texts],
                },
                schema=EDIT_REWRITE_SCHEMA,
            )
            after, reason = result["text"].strip(), result["reason"].strip()
        else:
            after, reason = self._rewrite(before, instruction)
        if target_kind == "greeting" and len(after) > 142:
            raise ValueError("打招呼语修改结果超过142个字符，请重新生成")
        fact_result = check_hard_facts(source_texts, after)
        if not fact_result.allowed:
            detail = explain_violations(fact_result.violations)
            raise ValueError(f"修改建议包含无依据内容：{detail}")
        proposal_id = str(uuid4())
        now = utc_now()
        payload = {
            "instruction": instruction,
            "reason": reason,
            "evidence_ids": evidence_ids,
            "save_scope": save_scope,
            "contains_new_fact": False,
            "target_kind": target_kind,
        }
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE edit_proposal SET status='rejected', updated_at=? "
                "WHERE draft_id=? AND status='pending'",
                (now, draft["id"]),
            )
            connection.execute(
                "INSERT INTO edit_proposal(id, draft_id, target_block_id, before_text, "
                "after_text, status, payload_json, schema_version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, 1, ?, ?)",
                (
                    proposal_id,
                    draft["id"],
                    target_paragraph_id,
                    before,
                    after,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get(proposal_id)

    def list_pending(self, job_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT p.id FROM edit_proposal p "
                "JOIN resume_draft d ON d.id=p.draft_id "
                "WHERE d.job_target_id=? AND p.status='pending' "
                "ORDER BY p.created_at DESC",
                (job_id,),
            ).fetchall()
        return [self.get(row["id"]) for row in rows]

    def get(self, proposal_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, draft_id, target_block_id, before_text, after_text, status, "
                "payload_json, created_at, updated_at FROM edit_proposal WHERE id=?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def accept(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.get(proposal_id)
        if proposal["status"] != "pending":
            raise ValueError("修改建议已经处理")
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT job_target_id, document_json FROM resume_draft WHERE id=?",
                (proposal["draft_id"],),
            ).fetchone()
        if row is None:
            raise KeyError(proposal["draft_id"])
        document = ResumeDocument.model_validate_json(row[1])
        target_kind, target = self._find_target(document, proposal["target_block_id"])
        if target_kind == "greeting":
            current_text = target.greeting_message
        elif target_kind == "section":
            current_text = target.title
        elif target_kind == "heading":
            current_text = target.heading
        else:
            current_text = target.text
        if current_text != proposal["before_text"]:
            raise ValueError("目标内容已变化，请重新生成修改建议")
        if target_kind == "greeting":
            target.greeting_message = proposal["after_text"]
        elif target_kind == "section":
            target.title = proposal["after_text"]
        elif target_kind == "heading":
            target.heading = proposal["after_text"]
        else:
            target.text = proposal["after_text"]
        self.drafts._save(row[0], document)
        if target_kind == "section":
            config = self.configs.get(row[0])["config"]
            for section in config["sections"]:
                if section["section_key"] == target.section_key:
                    section["title"] = proposal["after_text"]
                    break
            self.configs.save(row[0], config)
        if proposal["payload"]["save_scope"] == "also_profile" and target_kind not in {
            "greeting",
            "section",
        }:
            evidence_ids = proposal["payload"]["evidence_ids"]
            if target_kind == "heading":
                evidence_ids = evidence_ids[:1]
            for entry_id in evidence_ids:
                entry = self.profiles.get_entry(entry_id)
                payload = dict(entry["payload"])
                title = entry["title"]
                if target_kind == "heading":
                    title = proposal["after_text"]
                else:
                    payload["content"] = proposal["after_text"]
                self.profiles.update_entry(entry_id, entry["section_key"], title, payload)
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE edit_proposal SET status='accepted', updated_at=? WHERE id=?",
                (utc_now(), proposal_id),
            )
        return self.get(proposal_id)

    def reject(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.get(proposal_id)
        if proposal["status"] != "pending":
            raise ValueError("修改建议已经处理")
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE edit_proposal SET status='rejected', updated_at=? WHERE id=?",
                (utc_now(), proposal_id),
            )
        return self.get(proposal_id)

    @staticmethod
    def _find_target(document: ResumeDocument, target_id: str) -> tuple[str, Any]:
        if target_id == "greeting":
            return "greeting", document
        if target_id.startswith("section:"):
            section_id = target_id.removeprefix("section:")
            for section in document.sections:
                if section.section_id == section_id:
                    return "section", section
            raise KeyError(target_id)
        if target_id.startswith("heading:"):
            block_id = target_id.removeprefix("heading:")
            for section in document.sections:
                for block in section.blocks:
                    if block.block_id == block_id:
                        return "heading", block
            raise KeyError(target_id)
        return "paragraph", EditProposalService._find_paragraph(document, target_id)

    @staticmethod
    def _find_paragraph(document: ResumeDocument, paragraph_id: str):
        for section in document.sections:
            for block in section.blocks:
                for paragraph in block.paragraphs:
                    if paragraph.paragraph_id == paragraph_id:
                        return paragraph
        raise KeyError(paragraph_id)

    @staticmethod
    def _rewrite(before: str, instruction: str) -> tuple[str, str]:
        after = before.strip()
        reasons = []
        if "简洁" in instruction or "精简" in instruction:
            after = re.sub(r"(非常|十分|显著|大幅|较为|比较)", "", after)
            after = re.sub(r"\s+", " ", after).strip()
            reasons.append("删除空泛修饰和重复表达")
        if "降低夸张" in instruction or "不要夸张" in instruction:
            after = re.sub(r"(顶尖|领先|卓越|完美)", "", after)
            reasons.append("降低无法验证的强度词")
        if "专业" in instruction:
            after = after.replace("做了", "完成").replace("弄了", "完成")
            reasons.append("使用更明确的行动表达")
        if not reasons:
            reasons.append("保持原有事实，仅调整表达结构")
        return after, "；".join(reasons)

    @staticmethod
    def non_target_hash(document: ResumeDocument, target_id: str) -> str:
        values = []
        for section in document.sections:
            for block in section.blocks:
                for paragraph in block.paragraphs:
                    if paragraph.paragraph_id != target_id:
                        values.append((paragraph.paragraph_id, paragraph.text))
        return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()
