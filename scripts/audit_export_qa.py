from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pdfplumber
from docx import Document


def _body_bottom_ratio(pdf_path: Path, page_index: int) -> float:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        # Ignore the running footer/page number when measuring page usage.
        words = [word for word in page.extract_words() if float(word["top"]) < page.height - 55]
        if not words:
            return 0.0
        return max(float(word["bottom"]) for word in words) / float(page.height)


def audit(output: Path = Path("output/qa-exports")) -> list[str]:
    errors: list[str] = []
    for stem in ("single_column", "technical_double_column"):
        for pages in (1, 2):
            docx_path = output / f"{stem}-{pages}page.docx"
            pdf_path = output / f"{stem}-{pages}page.pdf"
            if not docx_path.exists() or not pdf_path.exists():
                errors.append(f"missing artifact: {stem}-{pages}page")
                continue

            doc = Document(docx_path)
            if abs(doc.sections[0].page_width.cm - 21) >= 0.1:
                errors.append(f"{docx_path.name}: page width is not A4")
            if abs(doc.sections[0].page_height.cm - 29.7) >= 0.1:
                errors.append(f"{docx_path.name}: page height is not A4")
            with ZipFile(docx_path) as archive:
                xml = archive.read("word/document.xml").decode("utf-8")
                styles = archive.read("word/styles.xml").decode("utf-8")
                if "Microsoft YaHei" not in styles:
                    errors.append(f"{docx_path.name}: required font is missing")
                if "■" not in xml:
                    errors.append(f"{docx_path.name}: square decoration is missing")
                if stem == "technical_double_column" and 'w:num="2"' not in xml:
                    errors.append(f"{docx_path.name}: true two-column section is missing")
                if pages == 2 and 'w:type="page"' not in xml:
                    errors.append(f"{docx_path.name}: explicit page break is missing")

            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) != pages:
                    errors.append(f"{pdf_path.name}: expected {pages} page(s), got {len(pdf.pages)}")
            if pages == 1:
                ratio = _body_bottom_ratio(pdf_path, 0)
                if ratio < 0.68:
                    errors.append(f"{pdf_path.name}: one-page body uses only {ratio:.0%} of the page")
            else:
                ratio = _body_bottom_ratio(pdf_path, 1)
                if ratio < 0.55:
                    errors.append(f"{pdf_path.name}: second-page body uses only {ratio:.0%} of the page")
    return errors


def main() -> None:
    errors = audit()
    if errors:
        raise SystemExit("Export QA failed:\n- " + "\n- ".join(errors))
    print("Export QA passed: A4 structure, fonts, decoration, columns, page counts and page fill.")


if __name__ == "__main__":
    main()
