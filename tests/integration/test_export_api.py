from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.main import create_app
from app.security.credentials import InMemoryCredentialStore


HEADERS = {"x-shadow-session": "export-session"}


def test_export_api_creates_safe_word_and_pdf_and_blocks_pending_proposal(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "export-session")
    app = create_app(tmp_path / "data", InMemoryCredentialStore())
    with TestClient(app) as client:
        client.put(
            "/api/profile",
            headers=HEADERS,
            json={"personal_info": {"name": "杨丰铭", "email": "test@example.com"}},
        )
        client.post(
            "/api/profile/entries",
            headers=HEADERS,
            json={
                "section_key": "project",
                "title": "影子简历助手",
                "payload": {"content": "完成本地工作流"},
            },
        )
        job = client.post(
            "/api/jobs",
            headers=HEADERS,
            json={"jd_text": "本地工作流", "title": "岗位", "company": "公司"},
        ).json()
        client.post(f"/api/jobs/{job['id']}/analyze", headers=HEADERS)
        draft = client.post(f"/api/jobs/{job['id']}/generate", headers=HEADERS).json()
        exported = client.post(
            f"/api/jobs/{job['id']}/export",
            headers=HEADERS,
            json={"filename": "杨丰铭:AI/简历", "formats": ["docx", "pdf"]},
        )
        assert exported.status_code == 200, exported.text
        paths = [Path(item) for item in exported.json()["files"]]
        assert all(
            path.exists() and ":" not in path.name and "/" not in path.name
            for path in paths
        )
        assert "杨丰铭" in "\n".join(
            paragraph.text for paragraph in Document(paths[0]).paragraphs
        )
        assert len(PdfReader(paths[1]).pages) == 1
        target = draft["document"]["sections"][0]["blocks"][0]["paragraphs"][0][
            "paragraph_id"
        ]
        client.post(
            f"/api/jobs/{job['id']}/edit-proposals",
            headers=HEADERS,
            json={"target_paragraph_id": target, "instruction": "写得更简洁"},
        )
        blocked = client.post(
            f"/api/jobs/{job['id']}/export",
            headers=HEADERS,
            json={"filename": "blocked", "formats": ["pdf"]},
        )
        assert blocked.status_code == 422
        assert "未接受或拒绝" in blocked.json()["detail"]
