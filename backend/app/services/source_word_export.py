from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree

from app.domain.resume import ResumeDocument
from app.persistence.database import Database
from app.services.data_paths import DataPaths

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W_NS}
EXPERIENCE_SECTIONS = {"education", "work", "internship", "project", "campus", "awards", "other"}


class SourceWordExport:
    def __init__(self, database: Database, paths: DataPaths) -> None:
        self.database = database
        self.paths = paths

    def resolve(self, document: ResumeDocument) -> dict[str, Any] | None:
        draft_blocks = self._draft_blocks(document)
        summary_section = next(
            (section for section in document.sections if section.section_key == "summary"),
            None,
        )
        with self.database.connect() as connection:
            entry_rows = connection.execute(
                "SELECT id, section_key, title, payload_json, created_at "
                "FROM profile_section_entry WHERE deleted_at IS NULL ORDER BY created_at, id"
            ).fetchall()
            document_rows = connection.execute(
                "SELECT id, managed_file_id, original_name, created_at "
                "FROM source_document ORDER BY created_at, id"
            ).fetchall()
            profile_row = connection.execute(
                "SELECT payload_json FROM user_profile ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            summary_rows = connection.execute(
                "SELECT source_document_id, source_locator_json FROM import_candidate "
                "WHERE section_key='summary' AND status='accepted' ORDER BY rowid"
            ).fetchall()
        entries = [self._entry(row) for row in entry_rows]
        entry_by_id = {entry["id"]: entry for entry in entries}
        documents = self._source_documents(document_rows)
        if not documents:
            return None
        linked_document_ids = {
            entry_by_id[source_id]["source"].get("document_id")
            for block in draft_blocks
            for source_id in block["source_ids"]
            if source_id in entry_by_id and entry_by_id[source_id]["source"].get("document_id")
        }
        personal_info = json.loads(profile_row[0]) if profile_row else {}
        summary_source = (
            personal_info.get("_summary_source")
            if isinstance(personal_info.get("_summary_source"), dict)
            else {}
        )
        if summary_source.get("document_id"):
            linked_document_ids.add(summary_source["document_id"])
        chosen, compatible_ids = self._choose_document(documents, entries, linked_document_ids)
        compatible_entries = [
            entry
            for entry in entries
            if entry["source"].get("document_id") in compatible_ids
            and not self._looks_like_personal_info(entry)
        ]
        source_entries = self._deduplicate_source_entries(
            compatible_entries,
            chosen["id"],
        )
        if not source_entries and draft_blocks:
            return None

        by_signature = {
            self._source_signature(entry): entry
            for entry in source_entries
            if self._source_signature(entry) is not None
        }
        unused = {entry["id"] for entry in source_entries}
        selected: dict[str, dict[str, Any]] = {}
        selected_order: list[str] = []
        selected_by_signature: dict[tuple[str, tuple[str, ...]], str] = {}
        novel_by_section: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        for block in draft_blocks:
            match = self._direct_match(block, entry_by_id, by_signature, unused)
            if match is None:
                match = self._fuzzy_match(block, source_entries, unused)
            if match is None:
                duplicate_id = self._selected_duplicate_id(
                    block, entry_by_id, selected_by_signature, selected
                )
                if duplicate_id is not None:
                    if duplicate_id in block["source_ids"]:
                        selected[duplicate_id] = {
                            "section_key": block["section_key"],
                            "heading": block["heading"],
                            "meta": block["meta"],
                            "text": block["text"],
                        }
                    continue
                if block["section_key"] == "skills":
                    novel_by_section["skills"].append(
                        {
                            "heading": block["heading"],
                            "text": block["text"],
                        }
                    )
                    continue
                return None
            unused.remove(match["id"])
            selected_order.append(match["id"])
            selected[match["id"]] = {
                "section_key": block["section_key"],
                "heading": block["heading"],
                "meta": block["meta"],
                "text": block["text"],
            }
            signature = self._source_signature(match)
            if signature is not None:
                selected_by_signature[signature] = match["id"]

        locator = self._summary_locator(
            chosen["id"],
            compatible_ids,
            summary_source,
            summary_rows,
        )
        summary = None
        if summary_section is not None:
            summary_text = "\n".join(
                paragraph.text for block in summary_section.blocks for paragraph in block.paragraphs
            ).strip()
            if locator is None:
                if summary_text:
                    return None
            else:
                summary = {"source": locator, "text": summary_text}
        elif locator is not None:
            legacy_summary = document.personal_info.headline.strip()
            summary = {"source": locator, "text": legacy_summary or None}

        return {
            "path": chosen["path"],
            "source_document_id": chosen["id"],
            "selected_order": selected_order,
            "selected": selected,
            "source_entries": source_entries,
            "novel_by_section": dict(novel_by_section),
            "summary": summary,
        }

    def expects_source_word(self, document: ResumeDocument) -> bool:
        source_ids = {
            source_id for block in self._draft_blocks(document) for source_id in block["source_ids"]
        }
        document_ids = set()
        with self.database.connect() as connection:
            if source_ids:
                rows = [
                    row
                    for source_id in source_ids
                    if (
                        row := connection.execute(
                            "SELECT payload_json FROM profile_section_entry WHERE id=?",
                            (source_id,),
                        ).fetchone()
                    )
                ]
                for row in rows:
                    payload = json.loads(row[0])
                    source = (
                        payload.get("source") if isinstance(payload.get("source"), dict) else {}
                    )
                    if source.get("document_id"):
                        document_ids.add(str(source["document_id"]))
            profile_row = connection.execute(
                "SELECT payload_json FROM user_profile ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if profile_row and any(
                section.section_key == "summary" for section in document.sections
            ):
                profile = json.loads(profile_row[0])
                summary_source = profile.get("_summary_source")
                if isinstance(summary_source, dict) and summary_source.get("document_id"):
                    document_ids.add(str(summary_source["document_id"]))
            if not document_ids:
                return False
            rows = [
                row
                for document_id in document_ids
                if (
                    row := connection.execute(
                        "SELECT original_name FROM source_document WHERE id=?",
                        (document_id,),
                    ).fetchone()
                )
            ]
        return any(str(row[0]).lower().endswith(".docx") for row in rows)

    def write(self, resolved: dict[str, Any], target: Path) -> None:
        source_path = Path(resolved["path"])
        temporary = target.with_suffix(".source-word.partial.docx")
        temporary.unlink(missing_ok=True)
        try:
            with ZipFile(source_path, "r") as source_archive:
                document_xml = source_archive.read("word/document.xml")
                root = etree.fromstring(document_xml)
                self._edit_document_xml(root, resolved)
                updated_xml = etree.tostring(
                    root, xml_declaration=True, encoding="UTF-8", standalone=True
                )
                with ZipFile(temporary, "w", ZIP_DEFLATED) as output_archive:
                    for info in source_archive.infolist():
                        data = (
                            updated_xml
                            if info.filename == "word/document.xml"
                            else source_archive.read(info.filename)
                        )
                        output_archive.writestr(info, data)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _edit_document_xml(self, root, resolved: dict[str, Any]) -> None:
        body = root.find("w:body", NS)
        if body is None:
            raise ValueError("原 Word 文档缺少正文结构")
        element_by_block = self._body_block_map(body)
        groups = {}
        for entry in resolved["source_entries"]:
            block_ids = entry["source"].get("block_ids") or [entry["source"].get("block_id")]
            elements = [element_by_block[value] for value in block_ids if value in element_by_block]
            if elements:
                groups[entry["id"]] = elements

        selected = resolved["selected"]
        for entry_id, content in selected.items():
            elements = groups.get(entry_id)
            if not elements:
                continue
            editable = self._editable_elements(content["section_key"], elements)
            self._replace_group_text(editable, content["text"])

        summary = resolved.get("summary")
        if summary:
            source = summary["source"]
            block_ids = source.get("block_ids") or [source.get("block_id")]
            elements = [element_by_block[value] for value in block_ids if value in element_by_block]
            if not elements:
                raise ValueError("无法在原 Word 中定位自我介绍")
            if summary["text"] is None:
                for element in elements:
                    body.remove(element)
            else:
                self._replace_group_text(elements, summary["text"])

        by_section = defaultdict(list)
        for entry in resolved["source_entries"]:
            if entry["id"] in groups:
                by_section[entry["section_key"]].append(entry["id"])
        for section_key, source_ids in by_section.items():
            selected_ids = [
                entry_id
                for entry_id in resolved["selected_order"]
                if entry_id in groups
                and selected.get(entry_id, {}).get("section_key") == section_key
            ]
            novel = resolved.get("novel_by_section", {}).get(section_key, [])
            if not selected_ids and not novel:
                continue
            all_elements = [element for entry_id in source_ids for element in groups[entry_id]]
            anchor = min(body.index(element) for element in all_elements)
            for element in all_elements:
                body.remove(element)
            insertion = anchor
            if novel:
                template_id = next(
                    (entry_id for entry_id in selected_ids if entry_id in groups),
                    source_ids[0],
                )
                for item in novel:
                    cloned = [deepcopy(element) for element in groups[template_id]]
                    editable = self._editable_elements(section_key, cloned)
                    self._replace_group_text(
                        editable,
                        f"{item['heading']}：{item['text']}".strip("："),
                    )
                    for element in cloned:
                        body.insert(insertion, element)
                        insertion += 1
            for entry_id in selected_ids:
                for element in groups[entry_id]:
                    body.insert(insertion, element)
                    insertion += 1

    def _source_documents(self, rows) -> list[dict[str, Any]]:
        documents = []
        for row in rows:
            if not str(row[2]).lower().endswith(".docx"):
                continue
            matches = list(self.paths.imports.glob(f"{row[1]}.docx"))
            if len(matches) != 1:
                continue
            documents.append(
                {
                    "id": str(row[0]),
                    "path": matches[0],
                    "created_at": str(row[3]),
                    "sha256": self._sha256(matches[0]),
                }
            )
        return documents

    @staticmethod
    def _choose_document(
        documents: list[dict[str, Any]],
        entries: list[dict[str, Any]],
        linked_document_ids: set[str],
    ) -> tuple[dict[str, Any], set[str]]:
        by_id = {document["id"]: document for document in documents}
        linked_hashes = Counter(
            by_id[document_id]["sha256"]
            for document_id in linked_document_ids
            if document_id in by_id
        )
        if linked_hashes:
            chosen_hash = max(
                linked_hashes,
                key=lambda value: (
                    linked_hashes[value],
                    max(
                        document["created_at"]
                        for document in documents
                        if document["sha256"] == value
                    ),
                ),
            )
        else:
            chosen_hash = max(documents, key=lambda item: item["created_at"])["sha256"]
        compatible = [item for item in documents if item["sha256"] == chosen_hash]
        entry_counts = Counter(
            entry["source"].get("document_id")
            for entry in entries
            if entry["source"].get("document_id")
        )
        chosen = max(
            compatible,
            key=lambda item: (entry_counts[item["id"]], item["created_at"]),
        )
        return chosen, {item["id"] for item in compatible}

    @staticmethod
    def _draft_blocks(document: ResumeDocument) -> list[dict[str, Any]]:
        return [
            {
                "section_key": section.section_key,
                "heading": block.heading.strip(),
                "meta": block.meta.strip(),
                "text": "\n".join(paragraph.text for paragraph in block.paragraphs).strip(),
                "source_ids": [
                    str(source_id)
                    for paragraph in block.paragraphs
                    for source_id in paragraph.source_entry_ids
                ],
            }
            for section in document.sections
            if section.section_key != "summary"
            for block in section.blocks
        ]

    @classmethod
    def _selected_duplicate_id(
        cls, block, entry_by_id, selected_by_signature, selected
    ) -> str | None:
        for source_id in block["source_ids"]:
            entry = entry_by_id.get(source_id)
            if entry is None:
                continue
            signature = cls._source_signature(entry)
            selected_id = selected_by_signature.get(signature)
            if selected_id is None:
                continue
            existing = selected[selected_id]
            if existing["section_key"] == block["section_key"]:
                return selected_id
        return None

    @classmethod
    def _direct_match(cls, block, entry_by_id, by_signature, unused):
        for source_id in block["source_ids"]:
            entry = entry_by_id.get(source_id)
            if entry is None:
                continue
            signature = cls._source_signature(entry)
            match = by_signature.get(signature)
            if match and match["id"] in unused and match["section_key"] == block["section_key"]:
                return match
        return None

    @classmethod
    def _fuzzy_match(cls, block, source_entries, unused):
        candidates = [
            entry
            for entry in source_entries
            if entry["id"] in unused and entry["section_key"] == block["section_key"]
        ]
        if not candidates:
            return None
        ranked = sorted(
            ((cls._match_score(block, entry), entry) for entry in candidates),
            key=lambda item: item[0],
            reverse=True,
        )
        return ranked[0][1] if ranked[0][0] >= 0.42 else None

    @classmethod
    def _match_score(cls, block, entry) -> float:
        heading = cls._normalize(block["heading"])
        title = cls._normalize(entry["title"])
        text = cls._normalize(block["text"])
        source_text = cls._normalize(entry["content"])
        title_score = SequenceMatcher(None, heading, title).ratio() if heading and title else 0
        if heading and title and (heading in title or title in heading):
            title_score = max(title_score, 0.9)
        content_score = (
            SequenceMatcher(None, text[:500], source_text[:500]).ratio()
            if text and source_text
            else 0
        )
        return title_score * 0.75 + content_score * 0.25

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())

    @staticmethod
    def _summary_locator(chosen_id, compatible_ids, profile_source, summary_rows):
        if (
            profile_source
            and profile_source.get("document_id") in compatible_ids
            and profile_source.get("block_ids")
        ):
            return profile_source
        locators = []
        for document_id, payload in summary_rows:
            if str(document_id) not in compatible_ids:
                continue
            locator = json.loads(payload)
            locators.append((str(document_id), locator))
        direct = next(
            (locator for document_id, locator in locators if document_id == chosen_id), None
        )
        return direct or (locators[-1][1] if locators else None)

    @classmethod
    def _deduplicate_source_entries(cls, entries, chosen_id):
        preferred = sorted(
            entries,
            key=lambda entry: (
                entry["source"].get("document_id") != chosen_id,
                entry["created_at"],
                entry["id"],
            ),
        )
        result = []
        seen = set()
        for entry in preferred:
            signature = cls._source_signature(entry)
            if signature is not None and signature in seen:
                continue
            if signature is not None:
                seen.add(signature)
            result.append(entry)
        return result

    @staticmethod
    def _source_signature(entry) -> tuple[str, tuple[str, ...]] | None:
        source = entry["source"]
        block_ids = source.get("block_ids") or [source.get("block_id")]
        normalized = tuple(str(value) for value in block_ids if value)
        return (entry["section_key"], normalized) if normalized else None

    @staticmethod
    def _looks_like_personal_info(entry) -> bool:
        source = entry["source"]
        block_ids = source.get("block_ids") or [source.get("block_id")]
        if entry["section_key"] != "other" or not any(
            str(value).startswith("table-") for value in block_ids if value
        ):
            return False
        return bool(re.search(r"姓名|性别|电话|手机|邮箱|@|1[3-9]\d{9}", entry["content"]))

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _body_block_map(body) -> dict[str, Any]:
        mapping = {}
        paragraph_index = 0
        table_index = 0
        for element in body:
            if element.tag == f"{{{W_NS}}}p":
                mapping[f"paragraph-{paragraph_index}"] = element
                paragraph_index += 1
            elif element.tag == f"{{{W_NS}}}tbl":
                mapping[f"table-{table_index}"] = element
                table_index += 1
        return mapping

    @staticmethod
    def _editable_elements(section_key: str, elements: list[Any]) -> list[Any]:
        if section_key in EXPERIENCE_SECTIONS and len(elements) >= 3:
            return elements[2:]
        if section_key in EXPERIENCE_SECTIONS and len(elements) >= 2:
            return elements[1:]
        return elements

    @classmethod
    def _replace_group_text(cls, elements: list[Any], text: str) -> None:
        if not elements:
            return
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            lines = [""]
        for index, element in enumerate(elements):
            if index < len(elements) - 1:
                value = lines[index] if index < len(lines) else ""
            else:
                value = "；".join(lines[index:]) if index < len(lines) else ""
            cls._replace_element_text(element, value)

    @staticmethod
    def _replace_element_text(element, text: str) -> None:
        text_nodes = element.xpath(".//w:t", namespaces=NS)
        if not text_nodes:
            return
        normalized = "；".join(part.strip() for part in text.splitlines() if part.strip())
        text_nodes[0].text = normalized
        text_nodes[0].set(f"{{{XML_NS}}}space", "preserve")
        for node in text_nodes[1:]:
            node.text = ""

    @staticmethod
    def _entry(row) -> dict[str, Any]:
        payload = json.loads(row[3])
        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        return {
            "id": str(row[0]),
            "section_key": str(row[1]),
            "title": str(row[2] or payload.get("title") or ""),
            "content": str(payload.get("content") or ""),
            "source": source,
            "created_at": str(row[4]),
        }
