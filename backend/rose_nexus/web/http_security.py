"""HTTP security middleware, signed sessions, authentication and CSRF guards."""

from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request, Response
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import auth
from .models import Session, User
from .repository import Repository


SESSION_COOKIE = "rose_session"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FIELD = "csrf_token"
SESSION_LIFETIME = timedelta(days=7)


class AuthenticationRequired(Exception):
    """Signal that an API response or a page redirect needs authentication."""


class ApiProblem(Exception):
    """An expected HTTP failure with a stable machine-readable code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class SecurityHeadersMiddleware:
    """Add the ADR-006 security headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'"
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Frame-Options"] = "DENY"
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _utc_now() -> datetime:
    """Return an aware UTC timestamp for session expiration checks."""

    return datetime.now(timezone.utc)


def create_session(repository: Repository, user: User) -> tuple[Session, str]:
    """Persist only a bearer-token digest and return the raw token for its cookie."""

    raw_token = auth.new_token(32)
    now = _utc_now()
    session = Session(
        id=uuid.uuid4().hex,
        user_id=user.id,
        token_hash=auth.token_digest(raw_token),
        csrf_token=auth.new_token(32),
        created_at=now.isoformat().replace("+00:00", "Z"),
        expires_at=(now + SESSION_LIFETIME).isoformat().replace("+00:00", "Z"),
    )
    repository.create_session(session)
    return session, raw_token


def current_session(request: Request) -> tuple[Session, User] | None:
    """Resolve a valid signed cookie, hiding invalid, expired and orphaned sessions."""

    signed_value = request.cookies.get(SESSION_COOKIE)
    if not signed_value:
        return None
    raw_token = auth.verify_session(signed_value, request.app.state.secret)
    if raw_token is None:
        return None
    repository: Repository = request.app.state.repository
    session = repository.get_session_by_token_hash(auth.token_digest(raw_token))
    if session is None:
        return None
    try:
        expires_at = datetime.fromisoformat(session.expires_at.replace("Z", "+00:00"))
    except ValueError:
        expires_at = datetime.min.replace(tzinfo=timezone.utc)
    if expires_at.tzinfo is None or expires_at <= _utc_now():
        repository.delete_session(session.id)
        return None
    user = repository.get_user(session.user_id)
    if user is None:
        repository.delete_session(session.id)
        return None
    return session, user


def require_session(request: Request) -> tuple[Session, User]:
    """Require authentication; the app handler chooses JSON or a login redirect."""

    resolved = current_session(request)
    if resolved is None:
        raise AuthenticationRequired
    return resolved


def require_csrf(request: Request, submitted: str | None) -> None:
    """Compare a submitted token to the current session using constant-time equality."""

    session, _ = require_session(request)
    if not submitted:
        raise ApiProblem(403, "csrf_failed", "a valid CSRF token is required")
    expected_bytes = session.csrf_token.encode("utf-8")
    submitted_bytes = submitted.encode("utf-8")
    if not hmac.compare_digest(expected_bytes, submitted_bytes):
        raise ApiProblem(403, "csrf_failed", "a valid CSRF token is required")


def set_session_cookie(
    response: Response, raw_token: str, secret: bytes, secure_cookies: bool
) -> None:
    """Set the signed, HTTP-only session cookie with deployment-aware Secure."""

    response.set_cookie(
        key=SESSION_COOKIE,
        value=auth.sign_session(raw_token, secret),
        httponly=True,
        secure=secure_cookies,
        samesite="Lax",
        path="/",
    )


def clear_session_cookie(response: Response, secure_cookies: bool) -> None:
    """Remove every attribute scope used by the session cookie."""

    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        secure=secure_cookies,
        httponly=True,
        samesite="Lax",
    )


def json_problem(problem: ApiProblem) -> dict[str, Any]:
    """Return the stable JSON error envelope shared by all API failures."""

    return {
        "ok": False,
        "error": {"code": problem.code, "message": problem.message},
    }
