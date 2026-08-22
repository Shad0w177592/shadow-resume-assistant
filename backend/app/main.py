from __future__ import annotations

import os
import signal
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from app.security.credentials import CredentialStore, WindowsCredentialStore
from app.services.bootstrap import bootstrap_services


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


def session_guard(
    x_shadow_session: Annotated[str | None, Header()] = None,
) -> None:
    expected = os.getenv("SHADOW_SESSION_TOKEN", "")
    if not expected or x_shadow_session != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")


def create_app(
    data_root: Path | None = None,
    credential_store: CredentialStore | None = None,
) -> FastAPI:
    store = credential_store or WindowsCredentialStore()

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        app_instance.state.services = bootstrap_services(data_root, store)
        yield

    app = FastAPI(
        title="影子简历助手本地 API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="shadow-resume-backend", version="0.1.0")

    @app.get("/api/session-check", dependencies=[Depends(session_guard)])
    async def session_check() -> dict[str, bool]:
        return {"authenticated": True}

    @app.post("/internal/shutdown", dependencies=[Depends(session_guard)])
    async def shutdown() -> dict[str, bool]:
        threading.Timer(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
        return {"stopping": True}

    from app.api.core import router as core_router
    from app.api.imports import router as imports_router
    from app.api.settings import router as settings_router

    app.include_router(core_router)
    app.include_router(imports_router)
    app.include_router(settings_router)

    return app


app = create_app()
