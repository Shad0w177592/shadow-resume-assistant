from pathlib import Path
import re
from uuid import uuid4
from zipfile import ZipFile

import pytest
from docx import Document
from pypdf import PdfReader

from app.domain.resume import (
    PersonalInfo,
    ResumeBlock,
    ResumeDocument,
    ResumeParagraph,
    ResumeSection,
    ResumeTemplate,
)
from app.services.resume_export import to_docx, to_html, to_pdf


def make_resume(template: ResumeTemplate, pages: int) -> ResumeDocument:
    sections = []
    for index, title in enumerate(["个人简介", "项目经历", "教育背景", "专业技能"]):
        sections.append(
            ResumeSection(
                section_id=f"section-{index}",
                section_key=f"section_{index}",
                title=title,
                order=index,
                column="left"
                if template == ResumeTemplate.TECHNICAL_DOUBLE_COLUMN and index > 1
                else "right",
                blocks=[
                    ResumeBlock(
                        block_id=f"block-{index}",
                        heading=f"{title}示例",
                        meta="2025.03-2025.08",
                        paragraphs=[
                            ResumeParagraph(
                                paragraph_id=f"paragraph-{index}",
                                text=f"使用证据完成{title}内容。",
                                source_entry_ids=[uuid4()],
                            )
                        ],
                    )
                ],
            )
        )
    return ResumeDocument(
        resume_id=uuid4(),
        template=template,
        page_target=pages,
        personal_info=PersonalInfo(
            name="李明",
            headline="AI Agent 产品方向",
            contacts=["liming@example.com", "杭州"],
        ),
        sections=sections,
    )


@pytest.mark.integration
@pytest.mark.parametrize("template", list(ResumeTemplate))
@pytest.mark.parametrize("pages", [1, 2])
def test_four_export_combinations_open_and_share_content(
    tmp_path: Path, template: ResumeTemplate, pages: int
) -> None:
    resume = make_resume(template, pages)
    docx_path = tmp_path / f"{template.value}-{pages}.docx"
    pdf_path = tmp_path / f"{template.value}-{pages}.pdf"
    html = to_html(resume)
    to_docx(resume, docx_path)
    to_pdf(resume, pdf_path)
    docx = Document(docx_path)
    pdf = PdfReader(str(pdf_path))
    docx_text = "\n".join(paragraph.text for paragraph in docx.paragraphs)
    pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert len(pdf.pages) == pages
    for keyword in ["李明", "个人简介", "项目经历"]:
        assert keyword in html
        assert keyword in docx_text
        assert keyword in pdf_text

    assert "■" in docx_text
    assert abs(docx.sections[0].page_width.cm - 21) < 0.1
    assert abs(docx.sections[0].page_height.cm - 29.7) < 0.1
    with ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        assert "word/numbering.xml" in archive.namelist()
        if template == ResumeTemplate.TECHNICAL_DOUBLE_COLUMN:
            assert 'w:num="2"' in document_xml


def test_pdf_wraps_long_chinese_text_without_truncating_tail(tmp_path: Path) -> None:
    resume = make_resume(ResumeTemplate.SINGLE_COLUMN, 1)
    tail = "这是必须出现在导出文件中的结尾标记"
    resume.sections[0].blocks[0].paragraphs[0].text = (
        "完成需求分析和原型设计，" * 18 + tail
    )
    target = tmp_path / "long.pdf"
    to_pdf(resume, target)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(target).pages)
    assert tail in re.sub(r"\s+", "", text)
