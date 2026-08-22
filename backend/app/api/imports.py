from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.settings import services
from app.main import session_guard
from app.services.bootstrap import AppServices
from app.services.file_storage import FileStorageError
from app.services.import_service import ImportService

router = APIRouter(prefix="/api", dependencies=[Depends(session_guard)])


class ImportPathInput(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


def _photo_payload(path: Path, file_id: str) -> dict[str, str]:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"file_id": file_id, "data_url": f"data:{mime};base64,{encoded}"}


class CandidateDecision(BaseModel):
    candidate_id: str
    action: Literal["accept", "ignore"]
    section_key: str | None = None
    title: str | None = None
    payload: dict[str, Any] | None = None


class ConfirmInput(BaseModel):
    decisions: list[CandidateDecision]


@router.post("/imports/from-path", status_code=201)
def import_from_path(
    payload: ImportPathInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        return ImportService(app.database, app.files).import_path(Path(payload.path))
    except (FileNotFoundError, FileStorageError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/profile/photo/from-path", status_code=201)
def import_profile_photo(
    payload: ImportPathInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, str]:
    try:
        stored = app.files.import_file(Path(payload.path), kind="photo")
        return _photo_payload(stored.path, stored.file_id)
    except (FileNotFoundError, FileStorageError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/profile/photo/{file_id}")
def get_profile_photo(
    file_id: str, app: Annotated[AppServices, Depends(services)]
) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f-]{36}", file_id):
        raise HTTPException(status_code=404, detail="照片不存在")
    matches = list(app.paths.photos.glob(f"{file_id}.*"))
    if len(matches) != 1:
        raise HTTPException(status_code=404, detail="照片不存在")
    return _photo_payload(matches[0], file_id)


@router.get("/imports/{document_id}")
def get_import(document_id: str, app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    try:
        return ImportService(app.database, app.files).get(document_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="导入记录不存在") from error


@router.post("/imports/{document_id}/confirm")
def confirm_import(
    document_id: str,
    payload: ConfirmInput,
    app: Annotated[AppServices, Depends(services)],
) -> dict[str, Any]:
    try:
        return ImportService(app.database, app.files).confirm(
            document_id, [decision.model_dump(exclude_none=True) for decision in payload.decisions]
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="候选记录不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/profile/suggestions")
def profile_suggestions(
    app: Annotated[AppServices, Depends(services)],
) -> list[dict[str, str]]:
    return ImportService(app.database, app.files).suggestions()
