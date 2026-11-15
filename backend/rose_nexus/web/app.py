"""FastAPI application factories with all mutable state scoped to one app."""

from __future__ import annotations

import os
import pathlib
import secrets
from typing import Mapping

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from ..core.config import Settings
from .api import create_api_router
from .db import connect, migrate
from .http_security import (
    ApiProblem,
    AuthenticationRequired,
    SecurityHeadersMiddleware,
    json_problem,
)
from .jobs import JobRunner
from .repository import Repository
from .storage import Storage
from .ui import create_ui_router


def create_app(
    repository: Repository,
    storage: Storage,
    runner: JobRunner,
    settings: Settings,
    secret: bytes,
    secure_cookies: bool = False,
) -> FastAPI:
    """Build an isolated application around explicitly supplied web collaborators."""

    app = FastAPI(title="Rose Nexus")
    app.state.repository = repository
    app.state.storage = storage
    app.state.runner = runner
    app.state.settings = settings
    app.state.secret = secret
    app.state.secure_cookies = secure_cookies
    # The imported class is intentionally instantiated once per application.
    from .auth import LoginThrottle

    app.state.login_throttle = LoginThrottle()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.exception_handler(AuthenticationRequired)
    async def authentication_required(
        request: Request, _exception: AuthenticationRequired
    ) -> JSONResponse | RedirectResponse:
        if request.url.path.startswith("/api/"):
            problem = ApiProblem(401, "authentication_required", "authentication required")
            return JSONResponse(json_problem(problem), status_code=problem.status_code)
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(ApiProblem)
    async def api_problem(request: Request, problem: ApiProblem) -> JSONResponse | PlainTextResponse:
        if request.url.path.startswith("/api/"):
            return JSONResponse(json_problem(problem), status_code=problem.status_code)
        return PlainTextResponse(problem.message, status_code=problem.status_code)

    app.include_router(create_api_router())
    app.include_router(create_ui_router())

    @app.on_event("shutdown")
    def stop_runner() -> None:
        runner.stop()

    return app


def _load_secret(storage_root: pathlib.Path, environment: Mapping[str, str]) -> bytes:
    """Read an environment secret or atomically create a private persistent key."""

    configured = environment.get("ROSE_SECRET_KEY")
    if configured:
        return configured.encode("utf-8")
    path = storage_root / ".secret"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        data = path.read_bytes()
        if not data:
            raise RuntimeError(f"the session secret file is empty: {path}")
        return data
    with os.fdopen(descriptor, "wb") as handle:
        data = secrets.token_bytes(32)
        handle.write(data)
    os.chmod(path, 0o600)
    return data


def build_app_from_env() -> FastAPI:
    """Resolve environment paths, migrate storage and start the owned job runner."""

    environment = os.environ
    settings = Settings.from_env()
    database_path = pathlib.Path(
        environment.get("ROSE_DB_PATH") or settings.output_dir / "rose-nexus.db"
    )
    storage_root = pathlib.Path(
        environment.get("ROSE_STORAGE_DIR") or settings.output_dir / "storage"
    )
    database_path.parent.mkdir(parents=True, exist_ok=True)
    storage_root.mkdir(parents=True, exist_ok=True)
    secret = _load_secret(storage_root, environment)
    connection = connect(database_path)
    migrate(connection)
    repository = Repository(connection)
    storage = Storage(storage_root)
    runner = JobRunner(repository, storage, settings)
    runner.recover_interrupted()
    runner.start()
    secure_cookies = environment.get("ROSE_SECURE_COOKIES", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    app = create_app(
        repository,
        storage,
        runner,
        settings,
        secret,
        secure_cookies=secure_cookies,
    )

    @app.on_event("shutdown")
    def close_database() -> None:
        connection.close()

    return app
