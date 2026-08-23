from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.shared import Pt, RGBColor
from fastapi.testclient import TestClient

from app.main import create_app
from app.security.credentials import InMemoryCredentialStore

HEADERS = {"x-shadow-session": "source-word-export"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_hashes(path: Path) -> dict[str, str]:
    with ZipFile(path) as archive:
        return {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name != "word/document.xml"
        }


def _experience(document: Document, company: str, body: str) -> None:
    date = document.add_paragraph()
    date.paragraph_format.space_after = Pt(3)
    date_run = date.add_run(f"2025.01-2025.06 {company}")
    date_run.bold = True
    date_run.font.color.rgb = RGBColor(31, 78, 120)
    role = document.add_paragraph()
    role_run = role.add_run("运营实习生")
    role_run.italic = True
    content = document.add_paragraph()
    content.paragraph_format.line_spacing = 1.25
    content_run = content.add_run(body)
    content_run.font.size = Pt(10.5)


def test_word_source_export_preserves_format_and_reorders_entries(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "source-word-export")
    source = tmp_path / "原排版简历.docx"
    original = Document()
    original.sections[0].header.paragraphs[0].text = "原简历页眉装饰"
    original.sections[0].footer.paragraphs[0].text = "原简历页脚"
    heading = original.add_paragraph()
    heading.paragraph_format.space_before = Pt(8)
    heading_run = heading.add_run("工作经历")
    heading_run.bold = True
    heading_run.font.color.rgb = RGBColor(31, 78, 120)
    _experience(original, "甲公司", "负责甲公司的原始内容")
    _experience(original, "乙公司", "负责乙公司的原始内容")
    original.save(source)
    source_hash = _sha256(source)
    source_parts = _package_hashes(source)

    app = create_app(tmp_path / "data", InMemoryCredentialStore())
    with TestClient(app) as client:
        imported = client.post(
            "/api/imports/from-path", headers=HEADERS, json={"path": str(source)}
        ).json()
        assert [item["section_key"] for item in imported["candidates"]] == [
            "work",
            "work",
        ]
        confirmed = client.post(
            f"/api/imports/{imported['id']}/confirm",
            headers=HEADERS,
            json={
                "decisions": [
                    {"candidate_id": item["id"], "action": "accept"}
                    for item in imported["candidates"]
                ]
            },
        )
        assert confirmed.status_code == 200
        entries = client.get("/api/profile", headers=HEADERS).json()["entries"]
        for entry in entries:
            importance = 5 if "乙公司" in entry["title"] else 1
            updated = client.put(
                f"/api/profile/entries/{entry['id']}",
                headers=HEADERS,
                json={
                    "section_key": entry["section_key"],
                    "title": entry["title"],
                    "payload": entry["payload"],
                    "importance": importance,
                },
            )
            assert updated.status_code == 200

        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={"jd_text": "乙公司相关岗位", "title": "运营", "company": "目标公司"},
        ).json()
        client.post(f"/api/jobs/{job['id']}/analyze", headers=HEADERS)
        generated = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert generated.status_code == 200, generated.text
        draft = generated.json()
        blocks = draft["document"]["sections"][0]["blocks"]
        assert [block["heading"] for block in blocks] == ["乙公司", "甲公司"]
        for block in blocks:
            block["paragraphs"][0]["text"] = f"{block['heading']}针对岗位调整后的正文"
        saved = client.put(
            f"/api/jobs/{job['id']}/draft",
            headers=HEADERS,
            json={"document": draft["document"]},
        )
        assert saved.status_code == 200
        exported = client.post(
            f"/api/jobs/{job['id']}/export",
            headers=HEADERS,
            json={"filename": "保留原排版", "formats": ["docx"]},
        )
        assert exported.status_code == 200, exported.text
        assert exported.json()["word_mode"] == "source_format"
        target = Path(exported.json()["files"][0])

    assert _sha256(source) == source_hash
    assert _package_hashes(target) == source_parts
    result = Document(target)
    texts = [paragraph.text for paragraph in result.paragraphs]
    assert texts.index("2025.01-2025.06 乙公司") < texts.index("2025.01-2025.06 甲公司")
    assert "乙公司针对岗位调整后的正文" in texts
    assert "甲公司针对岗位调整后的正文" in texts
    exported_heading = next(
        paragraph for paragraph in result.paragraphs if paragraph.text == "工作经历"
    )
    assert exported_heading.runs[0].bold is True
    assert exported_heading.runs[0].font.color.rgb == RGBColor(31, 78, 120)
    assert result.sections[0].header.paragraphs[0].text == "原简历页眉装饰"
    assert result.sections[0].footer.paragraphs[0].text == "原简历页脚"


def test_overflow_is_reported_after_draft_is_saved(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "source-word-export")
    app = create_app(tmp_path / "overflow-data", InMemoryCredentialStore())
    with TestClient(app) as client:
        entry = client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "project",
                "title": "长项目",
                "payload": {"content": "真实项目内容" * 400},
                "importance": 5,
            },
        ).json()
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={"jd_text": "项目经验", "title": "岗位", "company": "公司"},
        ).json()
        config = client.get(
            f"/api/jobs/{job['id']}/resume-config", headers=HEADERS
        ).json()["config"]
        config["entry_modes"][entry["id"]] = "must_include"
        saved = client.put(
            f"/api/jobs/{job['id']}/resume-config",
            headers=HEADERS,
            json={"config": config},
        )
        assert saved.status_code == 200
        generated = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS)
        assert generated.status_code == 200, generated.text
        assert generated.json()["layout"]["status"] == "overflow"
        assert any("草稿已生成" in warning for warning in generated.json()["warnings"])
        persisted = client.get(f"/api/jobs/{job['id']}/draft", headers=HEADERS)
        assert persisted.status_code == 200
