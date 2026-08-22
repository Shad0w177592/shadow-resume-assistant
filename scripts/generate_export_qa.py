from pathlib import Path
from uuid import uuid4

from app.domain.resume import (
    PersonalInfo,
    ResumeBlock,
    ResumeDocument,
    ResumeParagraph,
    ResumeSection,
    ResumeTemplate,
)
from app.services.resume_export import to_docx, to_pdf


TITLES = ["专业技能", "教育经历", "项目经历", "工作经历", "实习经历", "校园经历", "证书与奖项", "其他经历"]


def make_resume(template: ResumeTemplate, pages: int) -> ResumeDocument:
    sections = []
    count = 6 if pages == 1 else 8
    for index, title in enumerate(TITLES[:count]):
        left = template == ResumeTemplate.TECHNICAL_DOUBLE_COLUMN and index < 2
        # The QA corpus deliberately resembles a content-complete resume.  It is
        # dense enough to exercise the product requirement that a one-page
        # export should visually use most of the page, while the second page of
        # a two-page export must be more than half full.
        if template == ResumeTemplate.SINGLE_COLUMN:
            text_length = 60 if pages == 1 else 125
        elif left:
            text_length = 82 if pages == 1 else 96
        else:
            text_length = 92 if pages == 1 else 185
        text = ("围绕真实需求完成分析、方案设计、协作推进与结果复盘，" * 8)[:text_length]
        blocks = []
        for block_index in range(1 if left else 2):
            blocks.append(
                ResumeBlock(
                    block_id=f"block-{index}-{block_index}",
                    heading=f"{title}示例 {block_index + 1}",
                    meta="2024.09 - 2026.06",
                    paragraphs=[
                        ResumeParagraph(
                            paragraph_id=f"paragraph-{index}-{block_index}",
                            text=text,
                            source_entry_ids=[uuid4()],
                        )
                    ],
                )
            )
        sections.append(
            ResumeSection(
                section_id=f"section-{index}",
                section_key=f"section_{index}",
                title=title,
                order=index,
                column="left" if left else "right",
                blocks=blocks,
            )
        )
    return ResumeDocument(
        resume_id=uuid4(),
        template=template,
        page_target=pages,
        personal_info=PersonalInfo(
            name="杨丰铭",
            headline="AI Agent 产品与应用方向",
            contacts=["138****8000", "resume@example.com", "杭州"],
        ),
        sections=sections,
    )


def main() -> None:
    output = Path("output/qa-exports")
    output.mkdir(parents=True, exist_ok=True)
    for template in ResumeTemplate:
        for pages in (1, 2):
            resume = make_resume(template, pages)
            stem = f"{template.value}-{pages}page"
            to_docx(resume, output / f"{stem}.docx")
            to_pdf(resume, output / f"{stem}.pdf")


if __name__ == "__main__":
    main()
