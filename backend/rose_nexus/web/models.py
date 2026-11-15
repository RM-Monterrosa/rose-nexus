"""Typed rows shared by the web repository and application layers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    """A local web user."""

    id: str
    username: str
    password_hash: str
    created_at: str
    is_admin: bool = False


@dataclass(frozen=True)
class Session:
    """A session identified in storage only by its token digest."""

    id: str
    user_id: str
    token_hash: str
    csrf_token: str
    created_at: str
    expires_at: str


@dataclass(frozen=True)
class Document:
    """Metadata for one uploaded source document."""

    id: str
    user_id: str
    space: str
    filename: str
    sha256: str
    bytes: int
    created_at: str


@dataclass(frozen=True)
class Job:
    """A conversion request and its current lifecycle state."""

    id: str
    document_id: str
    user_id: str
    status: str
    brand: str
    formats: str
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None


@dataclass(frozen=True)
class Artifact:
    """Metadata for one immutable job artifact."""

    id: int
    job_id: str
    kind: str
    relative_path: str
    sha256: str
    bytes: int
