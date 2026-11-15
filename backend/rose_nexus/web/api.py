"""JSON session, document, job and scoped artifact routes."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Header, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from ..core.config import Settings
from ..core.errors import RoseNexusError
from ..studio.branding import load_profile
from . import auth
from .http_security import (
    ApiProblem,
    clear_session_cookie,
    create_session,
    require_csrf,
    require_session,
    set_session_cookie,
)
from .jobs import JobRunner
from .models import Artifact, Document, Job, Session, User
from .repository import Repository
from .storage import Storage, safe_display_name


class LoginPayload(BaseModel):
    """Credentials accepted by the local JSON login endpoint."""

    username: str
    password: str


class JobPayload(BaseModel):
    """A requested conversion and its allowed output format set."""

    document_id: str
    brand: str
    formats: list[str]


def _user_payload(user: User) -> dict[str, object]:
    return {"username": user.username, "is_admin": user.is_admin}


def authenticate(
    request: Request, username: str, password: str
) -> tuple[Session, str, User]:
    """Authenticate through the shared host+username throttle and create a session."""

    host = request.client.host if request.client is not None else "unknown"
    key = f"{host}\x00{username}"
    throttle: auth.LoginThrottle = request.app.state.login_throttle
    if not throttle.allow(key):
        raise ApiProblem(429, "rate_limited", "too many login attempts; try again later")
    repository: Repository = request.app.state.repository
    user = repository.get_user_by_username(username)
    if user is None or not auth.verify_password(password, user.password_hash):
        throttle.record_failure(key)
        raise ApiProblem(401, "invalid_credentials", "invalid username or password")
    throttle.reset(key)
    session, raw_token = create_session(repository, user)
    return session, raw_token, user


async def save_uploaded_document(
    upload: UploadFile,
    *,
    repository: Repository,
    storage: Storage,
    settings: Settings,
    user: User,
) -> tuple[str, str, int]:
    """Validate one upload completely before persisting its original and metadata."""

    display_name = safe_display_name(upload.filename or "")
    if Path(display_name).suffix.lower() not in {".md", ".txt"}:
        raise ApiProblem(
            415, "unsupported_media_type", "only .md and .txt documents are supported"
        )
    data = await upload.read(settings.max_input_bytes + 1)
    if len(data) > settings.max_input_bytes:
        raise ApiProblem(
            413,
            "payload_too_large",
            f"the document exceeds the {settings.max_input_bytes}-byte limit",
        )
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ApiProblem(415, "invalid_encoding", "the document must be strict UTF-8") from error
    original = storage.save_original(data)
    document_id = uuid.uuid4().hex
    repository.create_document(
        Document(
            id=document_id,
            user_id=user.id,
            space="default",
            filename=display_name,
            sha256=original.sha256,
            bytes=len(data),
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
    )
    return document_id, original.sha256, len(data)


def submit_conversion_job(
    *,
    repository: Repository,
    runner: JobRunner,
    settings: Settings,
    user: User,
    document_id: str,
    brand: str,
    formats: list[str],
) -> str:
    """Validate ownership, formats and branding before persist-and-submit."""

    document = repository.get_document(document_id, user.id)
    if document is None:
        raise ApiProblem(404, "document_not_found", "document not found")
    if not formats or any(name not in {"tex", "pdf"} for name in formats):
        raise ApiProblem(400, "unsupported_format", "formats must be a nonempty subset of tex and pdf")
    if len(set(formats)) != len(formats):
        raise ApiProblem(400, "unsupported_format", "formats must not contain duplicates")
    try:
        load_profile(settings.branding_dir, brand)
    except RoseNexusError as error:
        raise ApiProblem(400, error.code, error.message) from error
    job_id = uuid.uuid4().hex
    repository.create_job(
        Job(
            id=job_id,
            document_id=document_id,
            user_id=user.id,
            status="pending",
            brand=brand,
            formats=json.dumps(formats, separators=(",", ":")),
            error_code=None,
            error_message=None,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            started_at=None,
            finished_at=None,
            duration_ms=None,
        )
    )
    runner.submit(job_id)
    return job_id


def _artifact_payload(job_id: str, artifact: Artifact) -> dict[str, object]:
    return {
        "kind": artifact.kind,
        "bytes": artifact.bytes,
        "sha256": artifact.sha256,
        "url": f"/api/jobs/{job_id}/artifacts/{artifact.kind}",
    }


def _job_payload(repository: Repository, job: Job) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": job.id,
        "document_id": job.document_id,
        "status": job.status,
        "brand": job.brand,
        "formats": json.loads(job.formats),
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "duration_ms": job.duration_ms,
    }
    if job.status == "completed":
        payload["artifacts"] = [
            _artifact_payload(job.id, artifact)
            for artifact in repository.list_artifacts(job.id, job.user_id)
        ]
    return payload


def _attachment(filename: str) -> str:
    """Build an ASCII-safe attachment header with a UTF-8 filename annotation."""

    display = safe_display_name(filename)
    ascii_name = display.encode("ascii", "replace").decode("ascii")
    ascii_name = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in ascii_name
    ) or "document"
    escaped = ascii_name.replace("\\", "_").replace('"', "_")
    return f'attachment; filename="{escaped}"; filename*=UTF-8\'\'{quote(display)}'


def create_api_router() -> APIRouter:
    """Create routes that resolve all collaborators from the per-app state."""

    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "status": "ready"}

    @router.post("/session")
    def login(payload: LoginPayload, request: Request) -> JSONResponse:
        session, raw_token, user = authenticate(request, payload.username, payload.password)
        response = JSONResponse({"ok": True, "user": _user_payload(user)})
        set_session_cookie(
            response, raw_token, request.app.state.secret, request.app.state.secure_cookies
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/session")
    def session_info(
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
    ) -> dict[str, object]:
        session, user = resolved
        return {
            "ok": True,
            "user": _user_payload(user),
            "csrf_token": session.csrf_token,
        }

    @router.delete("/session")
    def logout(
        request: Request,
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
        csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> JSONResponse:
        # CSRF on DELETE is stricter than the POST-only minimum and protects logout.
        require_csrf(request, csrf_token)
        session, _ = resolved
        request.app.state.repository.delete_session(session.id)
        response = JSONResponse({"ok": True})
        clear_session_cookie(response, request.app.state.secure_cookies)
        return response

    @router.post("/documents", status_code=201)
    async def upload_document(
        request: Request,
        upload: Annotated[UploadFile, File(alias="file")],
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
        csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> dict[str, object]:
        require_csrf(request, csrf_token)
        _, user = resolved
        document_id, digest, size = await save_uploaded_document(
            upload,
            repository=request.app.state.repository,
            storage=request.app.state.storage,
            settings=request.app.state.settings,
            user=user,
        )
        return {"ok": True, "document_id": document_id, "sha256": digest, "bytes": size}

    @router.post("/jobs", status_code=202)
    def create_job(
        payload: JobPayload,
        request: Request,
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
        csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> dict[str, object]:
        require_csrf(request, csrf_token)
        _, user = resolved
        job_id = submit_conversion_job(
            repository=request.app.state.repository,
            runner=request.app.state.runner,
            settings=request.app.state.settings,
            user=user,
            document_id=payload.document_id,
            brand=payload.brand,
            formats=payload.formats,
        )
        return {"ok": True, "job_id": job_id}

    @router.get("/jobs")
    def list_jobs(
        request: Request,
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
    ) -> dict[str, object]:
        _, user = resolved
        repository: Repository = request.app.state.repository
        jobs = reversed(repository.list_jobs(user.id))
        return {"ok": True, "jobs": [_job_payload(repository, job) for job in jobs]}

    @router.get("/jobs/{job_id}")
    def get_job(
        job_id: str,
        request: Request,
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
    ) -> dict[str, object]:
        _, user = resolved
        repository: Repository = request.app.state.repository
        job = repository.get_job(job_id, user.id)
        if job is None:
            raise ApiProblem(404, "job_not_found", "job not found")
        return {"ok": True, "job": _job_payload(repository, job)}

    @router.get("/jobs/{job_id}/artifacts/{kind}")
    def download_artifact(
        job_id: str,
        kind: str,
        request: Request,
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
    ) -> Response:
        _, user = resolved
        repository: Repository = request.app.state.repository
        storage: Storage = request.app.state.storage
        job = repository.get_job(job_id, user.id)
        if job is None or kind not in {"source", "tex", "pdf"}:
            raise ApiProblem(404, "artifact_not_found", "artifact not found")
        artifact = repository.get_artifact(job_id, kind, user.id)
        if artifact is None:
            raise ApiProblem(404, "artifact_not_found", "artifact not found")
        try:
            data = storage.read_artifact(job_id, kind)
        except (OSError, RoseNexusError):
            raise ApiProblem(404, "artifact_not_found", "artifact not found") from None
        media_types = {
            "source": "text/markdown",
            "tex": "application/x-tex",
            "pdf": "application/pdf",
        }
        if kind == "source":
            document = repository.get_document(job.document_id, user.id)
            filename = document.filename if document is not None else "document.md"
        else:
            filename = f"document.{kind}"
        return Response(
            content=data,
            media_type=media_types[kind],
            headers={"Content-Disposition": _attachment(filename)},
        )

    return router
