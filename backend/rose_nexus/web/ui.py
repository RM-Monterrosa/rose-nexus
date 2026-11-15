"""Spanish server-rendered login, library, upload and job-detail routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.datastructures import UploadFile as StarletteUploadFile

from .api import ApiProblem, authenticate, save_uploaded_document, submit_conversion_job
from .http_security import (
    clear_session_cookie,
    current_session,
    require_csrf,
    require_session,
    set_session_cookie,
)
from .html import app_page, job_page, login_page
from .models import Session, User
from .repository import Repository


def _redirect(path: str) -> RedirectResponse:
    """Use a post/redirect/get-safe redirect consistently throughout the UI."""

    return RedirectResponse(path, status_code=303)


def _text(value: object) -> str:
    """Accept only scalar form values as credentials or CSRF tokens."""

    return value if isinstance(value, str) else ""


def _with_llm_navigation(content: str) -> str:
    """Add the experimental destination without changing the common HTML renderer."""

    link = '<a href="/app/llm">Experimental: consultar al modelo</a>'
    return content.replace("</nav>", f"{link}</nav>", 1)


def create_ui_router() -> APIRouter:
    """Create browser routes resolved against the current application state."""

    router = APIRouter()

    @router.get("/", include_in_schema=False)
    def index(request: Request) -> RedirectResponse:
        return _redirect("/app" if current_session(request) is not None else "/login")

    @router.get("/login", include_in_schema=False)
    def login_form(request: Request) -> Response:
        if current_session(request) is not None:
            return _redirect("/app")
        return HTMLResponse(login_page())

    @router.post("/login", include_in_schema=False)
    async def login_submit(request: Request) -> Response:
        form = await request.form()
        username = _text(form.get("username"))
        password = _text(form.get("password"))
        try:
            _, raw_token, _ = authenticate(request, username, password)
        except ApiProblem as problem:
            if problem.code == "rate_limited":
                message = "Demasiados intentos. Inténtalo de nuevo más tarde."
            else:
                message = "Usuario o contraseña incorrectos."
            return HTMLResponse(login_page(username, message), status_code=problem.status_code)
        response = _redirect("/app")
        set_session_cookie(
            response, raw_token, request.app.state.secret, request.app.state.secure_cookies
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.post("/logout", include_in_schema=False)
    async def logout(
        request: Request,
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
    ) -> RedirectResponse:
        form = await request.form()
        require_csrf(request, _text(form.get("csrf_token")) or None)
        session, _ = resolved
        request.app.state.repository.delete_session(session.id)
        response = _redirect("/login")
        clear_session_cookie(response, request.app.state.secure_cookies)
        return response

    @router.get("/app", include_in_schema=False)
    def application(
        request: Request,
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
    ) -> HTMLResponse:
        session, user = resolved
        repository: Repository = request.app.state.repository
        documents = list(reversed(repository.list_documents(user.id, "default")))
        jobs = list(reversed(repository.list_jobs(user.id)))
        content = app_page(
            user,
            session.csrf_token,
            documents,
            jobs,
            request.app.state.settings.max_input_bytes,
            bool(request.app.state.settings.sandbox_image),
        )
        content = _with_llm_navigation(content)
        return HTMLResponse(content, headers={"Cache-Control": "no-store"})

    @router.post("/app/upload", include_in_schema=False)
    async def upload(
        request: Request,
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
    ) -> RedirectResponse:
        form = await request.form()
        require_csrf(request, _text(form.get("csrf_token")) or None)
        upload = form.get("file")
        if not isinstance(upload, StarletteUploadFile):
            raise ApiProblem(400, "file_required", "a document file is required")
        _, user = resolved
        document_id, _, _ = await save_uploaded_document(
            upload,
            repository=request.app.state.repository,
            storage=request.app.state.storage,
            settings=request.app.state.settings,
            user=user,
        )
        formats = ["tex", "pdf"] if request.app.state.settings.sandbox_image else ["tex"]
        job_id = submit_conversion_job(
            repository=request.app.state.repository,
            runner=request.app.state.runner,
            settings=request.app.state.settings,
            user=user,
            document_id=document_id,
            brand="invering",
            formats=formats,
        )
        return _redirect(f"/app/jobs/{job_id}")

    @router.get("/app/jobs/{job_id}", include_in_schema=False)
    def job_detail(
        job_id: str,
        request: Request,
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
    ) -> HTMLResponse:
        _, user = resolved
        repository: Repository = request.app.state.repository
        job = repository.get_job(job_id, user.id)
        if job is None:
            raise ApiProblem(404, "job_not_found", "job not found")
        artifacts = repository.list_artifacts(job.id, user.id)
        return HTMLResponse(
            job_page(job, artifacts), headers={"Cache-Control": "no-store"}
        )

    @router.get("/static/app.css", include_in_schema=False)
    def stylesheet() -> FileResponse:
        return FileResponse(
            Path(__file__).resolve().parent / "static" / "app.css",
            media_type="text/css",
        )

    return router
