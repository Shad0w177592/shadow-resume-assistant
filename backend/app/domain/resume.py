from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class ResumeTemplate(StrEnum):
    SINGLE_COLUMN = "single_column"
    TECHNICAL_DOUBLE_COLUMN = "technical_double_column"


class ResumeParagraph(BaseModel):
    paragraph_id: str
    text: str
    source_entry_ids: list[UUID] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class ResumeBlock(BaseModel):
    block_id: str
    heading: str
    meta: str = ""
    paragraphs: list[ResumeParagraph]


class ResumeSection(BaseModel):
    section_id: str
    section_key: str
    title: str
    order: int = Field(ge=0)
    column: str = "full"
    blocks: list[ResumeBlock]


class PersonalInfo(BaseModel):
    name: str
    headline: str = ""
    contacts: list[str] = Field(default_factory=list)
    photo_file_id: str | None = None


class ResumeDocument(BaseModel):
    schema_version: int = 1
    resume_id: UUID
    template: ResumeTemplate
    page_target: int = Field(ge=1, le=2)
    layout_density: str = "auto"
    personal_info: PersonalInfo
    sections: list[ResumeSection]

    def plain_text(self) -> str:
        chunks = [
            self.personal_info.name,
            self.personal_info.headline,
            *self.personal_info.contacts,
        ]
        for section in sorted(self.sections, key=lambda item: item.order):
            chunks.append(section.title)
            for block in section.blocks:
                chunks.extend([block.heading, block.meta])
                chunks.extend(paragraph.text for paragraph in block.paragraphs)
        return "\n".join(chunk for chunk in chunks if chunk)
