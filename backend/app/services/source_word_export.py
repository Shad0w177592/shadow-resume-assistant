from __future__ import annotations

import json
import os
from collections import defaultdict
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
        ordered_ids = [
            str(source_id)
            for section in document.sections
            for block in section.blocks
            for paragraph in block.paragraphs
            for source_id in paragraph.source_entry_ids
        ]
        if not ordered_ids:
            return None
        unique_ids = list(dict.fromkeys(ordered_ids))
        with self.database.connect() as connection:
            available_rows = connection.execute(
                "SELECT id, section_key, payload_json FROM profile_section_entry "
                "WHERE deleted_at IS NULL"
            ).fetchall()
        wanted = set(unique_ids)
        rows = [row for row in available_rows if row[0] in wanted]
        if len(rows) != len(unique_ids):
            return None
        entries = {row[0]: self._entry(row) for row in rows}
        document_ids = {
            entry["source"].get("document_id")
            for entry in entries.values()
            if entry["source"].get("document_id")
        }
        if len(document_ids) != 1 or any(not entry["source"] for entry in entries.values()):
            return None
        source_document_id = str(next(iter(document_ids)))
        with self.database.connect() as connection:
            source = connection.execute(
                "SELECT managed_file_id, original_name FROM source_document WHERE id=?",
                (source_document_id,),
            ).fetchone()
            all_rows = connection.execute(
                "SELECT id, section_key, payload_json FROM profile_section_entry "
                "WHERE deleted_at IS NULL ORDER BY created_at, id"
            ).fetchall()
        if source is None or not str(source[1]).lower().endswith(".docx"):
            return None
        matches = list(self.paths.imports.glob(f"{source[0]}.docx"))
        if len(matches) != 1:
            return None
        source_entries = []
        for row in all_rows:
            entry = self._entry(row)
            if entry["source"].get("document_id") == source_document_id:
                source_entries.append(entry)
        block_by_entry = {}
        for section in document.sections:
            for block in section.blocks:
                source_ids = [
                    str(source_id)
                    for paragraph in block.paragraphs
                    for source_id in paragraph.source_entry_ids
                ]
                if len(set(source_ids)) != 1:
                    return None
                entry_id = source_ids[0]
                if entry_id not in entries:
                    return None
                block_by_entry[entry_id] = {
                    "section_key": section.section_key,
                    "text": "\n".join(paragraph.text for paragraph in block.paragraphs).strip(),
                }
        return {
            "path": matches[0],
            "source_document_id": source_document_id,
            "selected_order": unique_ids,
            "selected": block_by_entry,
            "source_entries": source_entries,
        }

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
            if editable:
                self._replace_element_text(editable[0], content["text"])
                for extra in editable[1:]:
                    self._replace_element_text(extra, "")

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
            all_elements = [element for entry_id in source_ids for element in groups[entry_id]]
            anchor = min(body.index(element) for element in all_elements)
            for element in all_elements:
                body.remove(element)
            insertion = anchor
            for entry_id in selected_ids:
                for element in groups[entry_id]:
                    body.insert(insertion, element)
                    insertion += 1

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
        payload = json.loads(row[2])
        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        return {"id": row[0], "section_key": row[1], "source": source}
