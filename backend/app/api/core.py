from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from app.api.settings import services
from app.domain.resume import ResumeDocument
from app.main import session_guard
from app.services.backup_service import BackupService, BackupValidationError
from app.services.bootstrap import AppServices
from app.services.edit_proposal_service import EditProposalService
from app.services.export_service import ExportService
from app.services.generation_service import GenerationService
from app.services.job_analysis_service import AnalysisConflictError, JobAnalysisService
from app.services.job_service import JobService
from app.services.openai_provider import AIProviderError, OpenAITextProvider, provider_error_status
from app.services.profile_service import ProfileService
from app.services.resume_config_service import ResumeConfigService
from app.services.resume_workflow_service import ResumeWorkflowService
from app.services.transcription_service import TranscriptionService
from app.services.version_service import VersionService

router = APIRouter(prefix="/api", dependencies=[Depends(session_guard)])


class ProfileInput(BaseModel):
    personal_info: dict[str, Any] = Field(default_factory=dict)


class EntryInput(BaseModel):
    section_key: str = Field(min_length=1, max_length=80)
    title: str | None = Field(default=None, max_length=240)
    payload: dict[str, Any] = Field(default_factory=dict)
    importance: int = Field(default=3, ge=1, le=5)


class JobInput(BaseModel):
    company: str | None = Field(default=None, max_length=240)
    title: str | None = Field(default=None, max_length=240)
    jd_text: str = Field(min_length=1)
    notes: str | None = None


class ResumeConfigInput(BaseModel):
    config: dict[str, Any]


class DraftInput(BaseModel):
    document: dict[str, Any]


class ProposalInput(BaseModel):
    target_paragraph_id: str
    instruction: str = Field(min_length=1, max_length=2000)
    save_scope: str = "current_resume"


class VersionInput(BaseModel):
    name: str = Field(default="未命名版本", max_length=200)
    notes: str | None = None


class CompareInput(BaseModel):
    current_document: dict[str, Any]


class ExportInput(BaseModel):
    filename: str = Field(default="影子简历", max_length=240)
    formats: list[str] = Field(min_length=1)


class RestoreBackupInput(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class ClearDataInput(BaseModel):
    confirmation: str
    include_api_key: bool = False


def _not_found(error: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail=f"记录不存在：{error.args[0]}")


def _text_provider(app: AppServices) -> OpenAITextProvider | None:
    # Automated tests exercise the deterministic workflow without external calls.
    # Production builds never set this flag and therefore require a configured key.
    if os.getenv("SHADOW_TEST_DETERMINISTIC_AI") == "1":
        return None
    return OpenAITextProvider(app.credentials, app.database)


def _ai_error(error: AIProviderError) -> HTTPException:
    return HTTPException(status_code=provider_error_status(error), detail=error.user_message)


@router.get("/home")
def home(app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    jobs = JobService(app.database).list()
    entries = ProfileService(app.database).list_entries()
    with app.database.connect() as connection:
        draft = connection.execute(
            "SELECT id, job_target_id, updated_at FROM resume_draft "
            "ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        version_count = connection.execute("SELECT COUNT(*) FROM resume_version").fetchone()[0]
    return {
        "api_configured": app.credentials.get() is not None,
        "profile_entry_count": len(entries),
        "recent_jobs": jobs[:5],
        "current_draft": dict(draft) if draft else None,
        "version_count": version_count,
        "data_directory": str(app.paths.root),
    }


@router.get("/profile")
def get_profile(app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    service = ProfileService(app.database)
    return {**service.get_profile(), "entries": service.list_entries()}


@router.put("/profile")
def put_profile(
    payload: ProfileInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    return ProfileService(app.database).save_profile(payload.personal_info)


@router.post("/profile/entries", status_code=201)
def create_entry(
    payload: EntryInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    return ProfileService(app.database).create_entry(
        payload.section_key, payload.title, payload.payload, payload.importance
    )


@router.put("/profile/entries/{entry_id}")
def update_entry(
    entry_id: str, payload: EntryInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        return ProfileService(app.database).update_entry(
            entry_id, payload.section_key, payload.title, payload.payload, payload.importance
        )
    except KeyError as error:
        raise _not_found(error) from error


@router.post("/profile/entries/{entry_id}/duplicate", status_code=201)
def duplicate_entry(
    entry_id: str, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        return ProfileService(app.database).duplicate_entry(entry_id)
    except KeyError as error:
        raise _not_found(error) from error


@router.delete("/profile/entries/{entry_id}", status_code=204, response_class=Response)
def delete_entry(entry_id: str, app: Annotated[AppServices, Depends(services)]) -> Response:
    try:
        ProfileService(app.database).delete_entry(entry_id)
    except KeyError as error:
        raise _not_found(error) from error
    return Response(status_code=204)


@router.get("/jobs")
def list_jobs(app: Annotated[AppServices, Depends(services)]) -> list[dict[str, Any]]:
    return JobService(app.database).list()


@router.post("/jobs", status_code=201)
def create_job(payload: JobInput, app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    return JobService(app.database).create(
        payload.company, payload.title, payload.jd_text, payload.notes
    )


@router.get("/jobs/{job_id}")
def get_job(job_id: str, app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    try:
        return JobService(app.database).get(job_id)
    except KeyError as error:
        raise _not_found(error) from error


@router.put("/jobs/{job_id}")
def update_job(
    job_id: str, payload: JobInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        return JobService(app.database).update(
            job_id, payload.company, payload.title, payload.jd_text, payload.notes
        )
    except KeyError as error:
        raise _not_found(error) from error


@router.post("/jobs/{job_id}/duplicate", status_code=201)
def duplicate_job(job_id: str, app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    try:
        return JobService(app.database).duplicate(job_id)
    except KeyError as error:
        raise _not_found(error) from error


@router.delete("/jobs/{job_id}", status_code=204, response_class=Response)
def delete_job(job_id: str, app: Annotated[AppServices, Depends(services)]) -> Response:
    try:
        JobService(app.database).delete(job_id)
    except KeyError as error:
        raise _not_found(error) from error
    return Response(status_code=204)


@router.post("/jobs/{job_id}/generate")
def generate(job_id: str, app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    try:
        return ResumeWorkflowService(app.database, _text_provider(app)).generate(job_id)
    except KeyError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AIProviderError as error:
        raise _ai_error(error) from error


@router.get("/jobs/{job_id}/draft")
def get_draft(job_id: str, app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    try:
        return GenerationService(app.database).get_draft(job_id)
    except KeyError as error:
        raise _not_found(error) from error


@router.put("/jobs/{job_id}/draft")
def put_draft(
    job_id: str, payload: DraftInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        JobService(app.database).get(job_id)
        document = ResumeDocument.model_validate(payload.document)
        return GenerationService(app.database)._save(job_id, document)
    except KeyError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/jobs/{job_id}/resume-config")
def get_resume_config(
    job_id: str, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        JobService(app.database).get(job_id)
        return ResumeConfigService(app.database).get(job_id)
    except KeyError as error:
        raise _not_found(error) from error


@router.put("/jobs/{job_id}/resume-config")
def put_resume_config(
    job_id: str,
    payload: ResumeConfigInput,
    app: Annotated[AppServices, Depends(services)],
) -> dict[str, Any]:
    try:
        JobService(app.database).get(job_id)
        return ResumeConfigService(app.database).save(job_id, payload.config)
    except KeyError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/tasks/{task_id}")
def get_task(task_id: str, app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    with app.database.connect() as connection:
        row = connection.execute(
            "SELECT id, task_type, status, progress, payload_json, created_at, updated_at "
            "FROM task_run WHERE id=?",
            (task_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = dict(row)
    result["payload"] = json.loads(result.pop("payload_json"))
    return result


@router.post("/jobs/{job_id}/edit-proposals", status_code=201)
def create_edit_proposal(
    job_id: str,
    payload: ProposalInput,
    app: Annotated[AppServices, Depends(services)],
) -> dict[str, Any]:
    try:
        return EditProposalService(app.database, _text_provider(app)).propose(
            job_id, payload.target_paragraph_id, payload.instruction, payload.save_scope
        )
    except KeyError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AIProviderError as error:
        raise _ai_error(error) from error


@router.post("/edit-proposals/{proposal_id}/accept")
def accept_edit_proposal(
    proposal_id: str, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        return EditProposalService(app.database).accept(proposal_id)
    except KeyError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/edit-proposals/{proposal_id}/reject")
def reject_edit_proposal(
    proposal_id: str, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        return EditProposalService(app.database).reject(proposal_id)
    except KeyError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/transcriptions")
async def transcribe_audio(
    app: Annotated[AppServices, Depends(services)],
    audio: Annotated[UploadFile, File()],
) -> dict[str, str]:
    content = await audio.read()
    if not content or len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="录音为空或超过 15MB")
    suffix = ".webm" if "webm" in (audio.content_type or "") else ".wav"
    try:
        text = TranscriptionService(app.credentials, app.paths.temp, app.database).transcribe(
            content, suffix
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="语音转写失败，请重试或使用文字输入") from error
    return {"text": text}


@router.get("/jobs/{job_id}/versions")
def list_versions(
    job_id: str, app: Annotated[AppServices, Depends(services)]
) -> list[dict[str, Any]]:
    return VersionService(app.database).list(job_id)


@router.post("/jobs/{job_id}/versions", status_code=201)
def create_version(
    job_id: str, payload: VersionInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        return VersionService(app.database).create(job_id, payload.name, payload.notes)
    except KeyError as error:
        raise _not_found(error) from error


@router.get("/versions/{version_id}")
def get_version(version_id: str, app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    try:
        return VersionService(app.database).get(version_id)
    except KeyError as error:
        raise _not_found(error) from error


@router.patch("/versions/{version_id}")
def rename_version(
    version_id: str, payload: VersionInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        return VersionService(app.database).rename(version_id, payload.name, payload.notes)
    except KeyError as error:
        raise _not_found(error) from error


@router.post("/versions/{version_id}/compare")
def compare_version(
    version_id: str, payload: CompareInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        return VersionService(app.database).compare(version_id, payload.current_document)
    except KeyError as error:
        raise _not_found(error) from error


@router.post("/versions/{version_id}/restore")
def restore_version(
    version_id: str, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        return VersionService(app.database).restore(version_id)
    except KeyError as error:
        raise _not_found(error) from error


@router.post("/versions/{version_id}/export")
def export_version(
    version_id: str,
    payload: ExportInput,
    app: Annotated[AppServices, Depends(services)],
) -> dict[str, Any]:
    try:
        return ExportService(app.database, app.paths).export_version(
            version_id, payload.filename, payload.formats
        )
    except KeyError as error:
        raise _not_found(error) from error
    except (ValueError, RuntimeError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/versions/{version_id}", status_code=204, response_class=Response)
def delete_version(version_id: str, app: Annotated[AppServices, Depends(services)]) -> Response:
    try:
        VersionService(app.database).delete(version_id)
    except KeyError as error:
        raise _not_found(error) from error
    return Response(status_code=204)


@router.post("/jobs/{job_id}/export")
def export_resume(
    job_id: str, payload: ExportInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        return ExportService(app.database, app.paths).export(
            job_id, payload.filename, payload.formats
        )
    except KeyError as error:
        raise _not_found(error) from error
    except (ValueError, RuntimeError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/backups", status_code=201)
def create_backup(app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    return BackupService(app.database, app.paths).create()


@router.post("/backups/restore")
def restore_backup(
    payload: RestoreBackupInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    try:
        return BackupService(app.database, app.paths).restore(Path(payload.path))
    except (BackupValidationError, FileNotFoundError, OSError, zipfile.BadZipFile) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/data/clear")
def clear_data(
    payload: ClearDataInput, app: Annotated[AppServices, Depends(services)]
) -> dict[str, Any]:
    if payload.confirmation != "清除全部数据":
        raise HTTPException(status_code=422, detail="请输入“清除全部数据”")
    result = BackupService(app.database, app.paths).clear_all(payload.include_api_key)
    if payload.include_api_key:
        app.credentials.delete()
    return result


@router.post("/jobs/{job_id}/analyze")
def analyze_job(job_id: str, app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    try:
        return JobAnalysisService(app.database, _text_provider(app)).analyze(job_id)
    except KeyError as error:
        raise _not_found(error) from error
    except AnalysisConflictError as error:
        raise HTTPException(status_code=409, detail=f"岗位分析正在运行：{error}") from error
    except AIProviderError as error:
        raise _ai_error(error) from error


@router.get("/jobs/{job_id}/match-report")
def match_report(job_id: str, app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    try:
        return JobAnalysisService(app.database).report(job_id)
    except KeyError as error:
        raise _not_found(error) from error


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    try:
        return JobAnalysisService(app.database).cancel(task_id)
    except KeyError as error:
        raise _not_found(error) from error


@router.post("/tasks/{task_id}/retry")
def retry_task(task_id: str, app: Annotated[AppServices, Depends(services)]) -> dict[str, Any]:
    try:
        return JobAnalysisService(app.database).retry(task_id)
    except KeyError as error:
        raise _not_found(error) from error
    except AnalysisConflictError as error:
        raise HTTPException(status_code=409, detail=f"岗位分析正在运行：{error}") from error
