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

FABRICATION_TERMS = ("编造", "虚构", "假装我有", "写一个不存在")


class EditProposalService:
    def __init__(self, database: Database, provider: OpenAITextProvider | None = None) -> None:
        self.database = database
        self.provider = provider
        self.drafts = GenerationService(database)
        self.profiles = ProfileService(database)

    def propose(
        self, job_id: str, target_paragraph_id: str, instruction: str, save_scope: str
    ) -> dict[str, Any]:
        if any(term in instruction for term in FABRICATION_TERMS):
            raise ValueError("不能生成可直接用于正式简历的虚假经历；请改为补充真实证据或写作框架")
        if save_scope not in {"current_resume", "also_profile"}:
            raise ValueError("保存范围无效")
        draft = self.drafts.get_draft(job_id)
        document = ResumeDocument.model_validate(draft["document"])
        paragraph = self._find_paragraph(document, target_paragraph_id)
        before = paragraph.text
        evidence_ids = [str(item) for item in paragraph.source_entry_ids]
        source_texts = []
        for entry_id in evidence_ids:
            entry = self.profiles.get_entry(entry_id)
            source_texts.append(
                json.dumps(
                    {"title": entry["title"], "payload": entry["payload"]},
                    ensure_ascii=False,
                )
            )
        source_texts.append(before)
        if self.provider:
            result = self.provider.complete_json(
                workflow="paragraph_rewrite",
                instructions=(
                    "只修改目标段落的表达，不新增或更改公司、岗位、学校、日期、技能、数字、职责和成果。"
                    "返回修改后的文字及简短理由；这只是建议，不能声称已经保存。"
                ),
                payload={
                    "target_text": before,
                    "instruction": instruction,
                    "evidence": [redact_text_for_ai(value) for value in source_texts],
                },
                schema=EDIT_REWRITE_SCHEMA,
            )
            after, reason = result["text"].strip(), result["reason"].strip()
        else:
            after, reason = self._rewrite(before, instruction)
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
        paragraph = self._find_paragraph(document, proposal["target_block_id"])
        if paragraph.text != proposal["before_text"]:
            raise ValueError("目标段落已变化，请重新生成修改建议")
        paragraph.text = proposal["after_text"]
        self.drafts._save(row[0], document)
        if proposal["payload"]["save_scope"] == "also_profile":
            for entry_id in proposal["payload"]["evidence_ids"]:
                entry = self.profiles.get_entry(entry_id)
                payload = dict(entry["payload"])
                payload["content"] = proposal["after_text"]
                self.profiles.update_entry(entry_id, entry["section_key"], entry["title"], payload)
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
