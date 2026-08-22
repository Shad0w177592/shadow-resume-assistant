from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.security.credentials import InMemoryCredentialStore


def test_profile_photo_is_managed_locally_and_embedded_in_docx(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHADOW_SESSION_TOKEN", "photo-test")
    source = tmp_path / "photo.png"
    Image.new("RGB", (120, 160), "#173B67").save(source)
    app = create_app(tmp_path / "data", InMemoryCredentialStore())
    headers = {"x-shadow-session": "photo-test"}
    with TestClient(app) as client:
        photo = client.post(
            "/api/profile/photo/from-path", headers=headers, json={"path": str(source)}
        )
        assert photo.status_code == 201
        file_id = photo.json()["file_id"]
        assert photo.json()["data_url"].startswith("data:image/png;base64,")
        loaded = client.get(f"/api/profile/photo/{file_id}", headers=headers)
        assert loaded.json()["data_url"] == photo.json()["data_url"]

    managed = list(app.state.services.paths.photos.glob(f"{file_id}.*"))
    assert len(managed) == 1

    from app.domain.resume import (
        PersonalInfo,
        ResumeBlock,
        ResumeDocument,
        ResumeParagraph,
        ResumeSection,
        ResumeTemplate,
    )
    from app.services.resume_export import to_docx

    document = ResumeDocument(
        resume_id=uuid4(),
        template=ResumeTemplate.SINGLE_COLUMN,
        page_target=1,
        personal_info=PersonalInfo(name="照片测试", photo_file_id=file_id),
        sections=[
            ResumeSection(
                section_id="section",
                section_key="project",
                title="项目经历",
                order=0,
                blocks=[
                    ResumeBlock(
                        block_id="block",
                        heading="项目",
                        paragraphs=[
                            ResumeParagraph(
                                paragraph_id="paragraph",
                                text="真实内容",
                                source_entry_ids=[uuid4()],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    target = tmp_path / "photo.docx"
    to_docx(document, target, photo_path=managed[0])
    with ZipFile(target) as archive:
        assert any(name.startswith("word/media/") for name in archive.namelist())
