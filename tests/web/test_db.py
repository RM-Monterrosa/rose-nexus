"""Tests for SQLite migrations and user-scoped repository reads."""

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rose_nexus.web.db import connect, migrate
from rose_nexus.web.models import Artifact, Document, Job, Session, User
from rose_nexus.web.repository import Repository


CREATED_AT = "2026-11-15T12:00:00Z"


def user(user_id="user-1", username="alice"):
    return User(user_id, username, "password-hash", CREATED_AT, False)


def document(document_id="document-1", user_id="user-1"):
    return Document(
        document_id, user_id, "default", "demo.md", hashlib.sha256(b"demo").hexdigest(), 4, CREATED_AT
    )


def job(job_id="job-1", document_id="document-1", user_id="user-1", status="pending"):
    return Job(
        job_id,
        document_id,
        user_id,
        status,
        "demo",
        '["tex"]',
        None,
        None,
        CREATED_AT,
        None,
        None,
        None,
    )


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "web.sqlite3"
        self.conn = connect(self.path)
        self.repo = Repository(self.conn)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_migrate_twice_is_idempotent(self):
        self.assertEqual(migrate(self.conn), 1)
        self.assertEqual(migrate(self.conn), 1)
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_foreign_keys_are_enforced(self):
        migrate(self.conn)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                ("session", "missing-user", "token", "csrf", CREATED_AT, CREATED_AT),
            )

    def test_job_status_check_rejects_invalid_status(self):
        migrate(self.conn)
        self.repo.create_user(user())
        self.repo.create_document(document())
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.create_job(job(status="invented"))

    def test_wal_is_enabled(self):
        mode = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

    def test_request_reads_do_not_expose_another_users_rows(self):
        migrate(self.conn)
        other = user("user-2", "bob")
        self.repo.create_user(user())
        self.repo.create_user(other)
        self.repo.create_document(document())
        owned = job()
        self.repo.create_job(owned)
        artifact = self.repo.add_artifact(
            job_id=owned.id,
            kind="tex",
            relative_path="document.tex",
            sha256=hashlib.sha256(b"tex").hexdigest(),
            bytes=3,
        )

        self.assertEqual(self.repo.get_document(owned.document_id, other.id), None)
        self.assertEqual(self.repo.get_job(owned.id, other.id), None)
        self.assertEqual(self.repo.list_documents(other.id, "default"), [])
        self.assertEqual(self.repo.list_jobs(other.id), [])
        self.assertEqual(self.repo.list_artifacts(owned.id, other.id), [])
        self.assertEqual(self.repo.get_artifact(owned.id, "tex", other.id), None)
        self.assertEqual(self.repo.get_artifact(owned.id, "tex", "user-1"), artifact)

    def test_session_lifecycle_and_expiry(self):
        migrate(self.conn)
        self.repo.create_user(user())
        active = Session("session-1", "user-1", "hash-1", "csrf-1", CREATED_AT, "2999-01-01T00:00:00Z")
        expired = Session("session-2", "user-1", "hash-2", "csrf-2", CREATED_AT, "2000-01-01T00:00:00Z")
        self.repo.create_session(active)
        self.repo.create_session(expired)
        self.assertEqual(self.repo.get_session_by_token_hash("hash-1"), active)
        self.assertEqual(self.repo.delete_expired_sessions(CREATED_AT), 1)
        self.assertEqual(self.repo.get_session_by_token_hash("hash-2"), None)
        self.assertTrue(self.repo.delete_session(active.id))
        self.assertEqual(self.repo.get_session_by_token_hash("hash-1"), None)


if __name__ == "__main__":
    unittest.main()
