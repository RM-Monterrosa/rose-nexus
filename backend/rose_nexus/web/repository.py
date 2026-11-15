"""Explicit, user-scoped persistence operations for the web application."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from typing import Any, Callable

from .models import Artifact, Document, Job, Session, User


class Repository:
    """Serialize access to one SQLite connection and map rows to typed models."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._lock = threading.RLock()

    def _write(self, statement: str, parameters: Iterable[Any]) -> sqlite3.Cursor:
        with self._lock, self._connection:
            return self._connection.execute(statement, tuple(parameters))

    def _read_one(
        self,
        statement: str,
        parameters: Iterable[Any],
        mapper: Callable[[sqlite3.Row], Any],
    ) -> Any | None:
        with self._lock:
            row = self._connection.execute(statement, tuple(parameters)).fetchone()
        return mapper(row) if row is not None else None

    def _read_all(
        self,
        statement: str,
        parameters: Iterable[Any],
        mapper: Callable[[sqlite3.Row], Any],
    ) -> list[Any]:
        with self._lock:
            rows = self._connection.execute(statement, tuple(parameters)).fetchall()
        return [mapper(row) for row in rows]

    @staticmethod
    def _user(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            created_at=row["created_at"],
            is_admin=bool(row["is_admin"]),
        )

    @staticmethod
    def _session(row: sqlite3.Row) -> Session:
        return Session(**dict(row))

    @staticmethod
    def _document(row: sqlite3.Row) -> Document:
        return Document(**dict(row))

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(**dict(row))

    @staticmethod
    def _artifact(row: sqlite3.Row) -> Artifact:
        return Artifact(**dict(row))

    def create_user(self, user: User) -> User:
        """Insert and return a user, preserving the database uniqueness rules."""

        self._write(
            "INSERT INTO users (id, username, password_hash, created_at, is_admin) "
            "VALUES (?, ?, ?, ?, ?)",
            (user.id, user.username, user.password_hash, user.created_at, int(user.is_admin)),
        )
        return user

    def get_user_by_username(self, username: str) -> User | None:
        """Return the local account with ``username``, if it exists."""

        return self._read_one(
            "SELECT * FROM users WHERE username = ?", (username,), self._user
        )

    def get_user(self, user_id: str) -> User | None:
        """Return a local account by stable identifier."""

        return self._read_one("SELECT * FROM users WHERE id = ?", (user_id,), self._user)

    def create_session(self, session: Session) -> Session:
        """Store a session containing only a digest of its bearer token."""

        self._write(
            "INSERT INTO sessions (id, user_id, token_hash, csrf_token, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                session.id,
                session.user_id,
                session.token_hash,
                session.csrf_token,
                session.created_at,
                session.expires_at,
            ),
        )
        return session

    def get_session_by_token_hash(self, token_hash: str) -> Session | None:
        """Resolve a hashed bearer token without storing the bearer token itself."""

        return self._read_one(
            "SELECT * FROM sessions WHERE token_hash = ?", (token_hash,), self._session
        )

    def delete_session(self, session_id: str) -> bool:
        """Delete one session and report whether it existed."""

        cursor = self._write("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cursor.rowcount > 0

    def delete_expired_sessions(self, now: str) -> int:
        """Delete sessions whose normalized UTC expiry is at or before ``now``."""

        cursor = self._write("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        return cursor.rowcount

    def create_document(self, document: Document) -> Document:
        """Store metadata for an original whose bytes are content-addressed."""

        self._write(
            "INSERT INTO documents (id, user_id, space, filename, sha256, bytes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                document.id,
                document.user_id,
                document.space,
                document.filename,
                document.sha256,
                document.bytes,
                document.created_at,
            ),
        )
        return document

    def get_document(self, document_id: str, user_id: str | None = None) -> Document | None:
        """Return a document, hiding another user's row when ``user_id`` is given."""

        if user_id is None:
            return self._read_one(
                "SELECT * FROM documents WHERE id = ?", (document_id,), self._document
            )
        return self._read_one(
            "SELECT * FROM documents WHERE id = ? AND user_id = ?",
            (document_id, user_id),
            self._document,
        )

    def list_documents(self, user_id: str, space: str) -> list[Document]:
        """List only documents belonging to both the requested user and space."""

        return self._read_all(
            "SELECT * FROM documents WHERE user_id = ? AND space = ? ORDER BY created_at, id",
            (user_id, space),
            self._document,
        )

    def create_job(self, job: Job) -> Job:
        """Insert a conversion job and let SQLite enforce its status and ownership."""

        self._write(
            "INSERT INTO jobs (id, document_id, user_id, status, brand, formats, "
            "error_code, error_message, created_at, started_at, finished_at, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job.id,
                job.document_id,
                job.user_id,
                job.status,
                job.brand,
                job.formats,
                job.error_code,
                job.error_message,
                job.created_at,
                job.started_at,
                job.finished_at,
                job.duration_ms,
            ),
        )
        return job

    def get_job(self, job_id: str, user_id: str | None = None) -> Job | None:
        """Return a job, scoped to its owner for request-serving reads."""

        if user_id is None:
            return self._read_one("SELECT * FROM jobs WHERE id = ?", (job_id,), self._job)
        return self._read_one(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id), self._job
        )

    def list_jobs(self, user_id: str | None = None) -> list[Job]:
        """List a user's jobs; the worker may omit ``user_id`` for recovery."""

        if user_id is None:
            return self._read_all("SELECT * FROM jobs ORDER BY created_at, id", (), self._job)
        return self._read_all(
            "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at, id", (user_id,), self._job
        )

    def update_job_status(
        self,
        job_id: str,
        status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        duration_ms: int | None = None,
    ) -> Job | None:
        """Update lifecycle fields and return the resulting job row."""

        self._write(
            "UPDATE jobs SET status = ?, error_code = ?, error_message = ?, "
            "started_at = COALESCE(?, started_at), finished_at = ?, duration_ms = ? WHERE id = ?",
            (
                status,
                error_code,
                error_message,
                started_at,
                finished_at,
                duration_ms,
                job_id,
            ),
        )
        return self.get_job(job_id)

    def add_artifact(
        self,
        *,
        job_id: str,
        kind: str,
        relative_path: str,
        sha256: str,
        bytes: int,
    ) -> Artifact:
        """Attach one artifact, enforcing at most one artifact of each kind per job."""

        cursor = self._write(
            "INSERT INTO artifacts (job_id, kind, relative_path, sha256, bytes) "
            "VALUES (?, ?, ?, ?, ?)",
            (job_id, kind, relative_path, sha256, bytes),
        )
        if cursor.lastrowid is None:  # pragma: no cover - SQLite always assigns this id
            raise RuntimeError("SQLite did not assign an artifact id")
        return Artifact(cursor.lastrowid, job_id, kind, relative_path, sha256, bytes)

    def list_artifacts(self, job_id: str, user_id: str | None = None) -> list[Artifact]:
        """List artifacts in stable insertion order with optional owner scoping."""

        if user_id is None:
            return self._read_all(
                "SELECT * FROM artifacts WHERE job_id = ? ORDER BY id", (job_id,), self._artifact
            )
        return self._read_all(
            "SELECT a.* FROM artifacts AS a JOIN jobs AS j ON j.id = a.job_id "
            "WHERE a.job_id = ? AND j.user_id = ? ORDER BY a.id",
            (job_id, user_id),
            self._artifact,
        )

    def get_artifact(
        self, job_id: str, kind: str, user_id: str | None = None
    ) -> Artifact | None:
        """Return one job artifact, scoped to the job owner when requested."""

        if user_id is None:
            return self._read_one(
                "SELECT * FROM artifacts WHERE job_id = ? AND kind = ?",
                (job_id, kind),
                self._artifact,
            )
        return self._read_one(
            "SELECT a.* FROM artifacts AS a JOIN jobs AS j ON j.id = a.job_id "
            "WHERE a.job_id = ? AND a.kind = ? AND j.user_id = ?",
            (job_id, kind, user_id),
            self._artifact,
        )
