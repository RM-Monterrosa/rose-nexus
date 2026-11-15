"""SQLite connection setup and forward-only web schema migrations."""

from __future__ import annotations

import pathlib
import sqlite3


SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    space TEXT NOT NULL,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL CHECK (status IN ('pending','running','completed','failed','cancelled')),
    brand TEXT NOT NULL,
    formats TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    UNIQUE(job_id, kind)
);
"""


def connect(path: pathlib.Path | str) -> sqlite3.Connection:
    """Open a request/worker-safe SQLite connection with required pragmas."""

    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations idempotently and return the schema version."""

    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current >= SCHEMA_VERSION:
        return current
    conn.executescript(_SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return SCHEMA_VERSION
