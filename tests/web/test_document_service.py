"""Tests for the transport-independent document and job service."""

import json
import tempfile
import unittest
from pathlib import Path

from rose_nexus.core.config import Settings
from rose_nexus.core.errors import RoseNexusError
from rose_nexus.web.db import connect, migrate
from rose_nexus.web.document_service import (
    get_document_metadata,
    get_document_status,
    list_brand_profiles,
    submit_render,
)
from rose_nexus.web.models import Document, User
from rose_nexus.web.repository import Repository
from rose_nexus.web.storage import Storage


ROOT = Path(__file__).resolve().parents[2]
CREATED_AT = "2026-11-15T12:00:00Z"


class RecordingRunner:
    """Record queued ids without starting a worker or running a converter."""

    def __init__(self):
        self.submitted = []

    def submit(self, job_id):
        self.submitted.append(job_id)


class DocumentServiceTests(unittest.TestCase):
    """Exercise every operation with isolated storage and owned test rows."""

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="rose-document-service-")
        self.root = Path(self._temporary.name)
        self.connection = connect(self.root / "web.sqlite3")
        migrate(self.connection)
        self.repository = Repository(self.connection)
        self.storage = Storage(self.root / "storage")
        self.settings = Settings(
            branding_dir=ROOT / "branding",
            output_dir=self.root / "conversion-output",
        )
        self.runner = RecordingRunner()
        self.alice = self.repository.create_user(
            User("user-alice", "alice", "test-hash", CREATED_AT)
        )
        self.bob = self.repository.create_user(
            User("user-bob", "bob", "test-hash", CREATED_AT)
        )
        self.document = self.create_document("alice-document", self.alice, "report.md")
        self.create_document("bob-document", self.bob, "private.txt", b"private\n")

    def tearDown(self):
        self.connection.close()
        self._temporary.cleanup()

    def create_document(self, document_id, user, filename, data=b"# Title\n"):
        original = self.storage.save_original(data)
        return self.repository.create_document(
            Document(
                document_id,
                user.id,
                "default",
                filename,
                original.sha256,
                len(data),
                CREATED_AT,
            )
        )

    def submit(self, **overrides):
        arguments = {
            "repository": self.repository,
            "runner": self.runner,
            "settings": self.settings,
            "user": self.alice,
            "document_id": self.document.id,
            "brand": "invering",
            "output_format": "tex",
        }
        arguments.update(overrides)
        return submit_render(**arguments)

    def assert_service_error(self, code, message, callable_, *args, **kwargs):
        with self.assertRaises(RoseNexusError) as caught:
            callable_(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.message, message)

    def test_submit_render_maps_outputs_and_returns_web_job_id(self):
        tex = self.submit()
        pdf = self.submit(output_format="pdf")

        self.assertEqual(tex, {"job_id": tex["job_id"], "status": "pending"})
        self.assertEqual(pdf, {"job_id": pdf["job_id"], "status": "pending"})
        self.assertNotEqual(tex["job_id"], pdf["job_id"])
        self.assertEqual(self.runner.submitted, [tex["job_id"], pdf["job_id"]])
        tex_job = self.repository.get_job(tex["job_id"], self.alice.id)
        pdf_job = self.repository.get_job(pdf["job_id"], self.alice.id)
        self.assertEqual(tex_job.formats, '["tex"]')
        self.assertEqual(pdf_job.formats, '["tex","pdf"]')
        for job in (tex_job, pdf_job):
            self.assertEqual(job.document_id, self.document.id)
            self.assertEqual(job.user_id, self.alice.id)
            self.assertEqual(job.status, "pending")
            self.assertEqual(job.brand, "invering")

    def test_submit_render_rejects_without_adding_or_queueing_jobs(self):
        cases = (
            (
                {"output_format": "latex"},
                "unsupported_format",
                "output_format must be 'tex' or 'pdf'",
            ),
            (
                {"user": self.bob},
                "document_not_found",
                "document not found",
            ),
            (
                {"brand": "absent"},
                "branding_profile_not_found",
                "brand profile 'absent' was not found",
            ),
        )
        for overrides, code, message in cases:
            with self.subTest(code=code):
                self.assert_service_error(code, message, self.submit, **overrides)
                self.assertEqual(self.repository.list_jobs(), [])
                self.assertEqual(self.runner.submitted, [])

    def test_document_status_has_only_safe_bounded_fields(self):
        submitted = self.submit()
        job_id = submitted["job_id"]
        self.repository.update_job_status(job_id, "completed", finished_at=CREATED_AT)
        self.repository.add_artifact(
            job_id=job_id,
            kind="tex",
            relative_path="private/host/document.tex",
            sha256="a" * 64,
            bytes=17,
        )
        status = get_document_status(
            repository=self.repository, user=self.alice, job_id=job_id
        )
        self.assertEqual(
            status,
            {
                "job_id": job_id,
                "status": "completed",
                "error_code": None,
                "error_message": None,
                "artifacts": [{"kind": "tex", "bytes": 17, "sha256": "a" * 64}],
            },
        )
        serialized = json.dumps(status)
        for forbidden in (str(self.root), "private/host", "relative_path", "/api/", "url"):
            self.assertNotIn(forbidden, serialized)

        failed_id = self.submit()["job_id"]
        self.repository.update_job_status(
            failed_id,
            "failed",
            error_code="bad_source",
            error_message="bad input",
            finished_at=CREATED_AT,
        )
        failed = get_document_status(
            repository=self.repository, user=self.alice, job_id=failed_id
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error_code"], "bad_source")
        self.assertEqual(failed["error_message"], "bad input")
        self.assertEqual(failed["artifacts"], [])
        self.assert_service_error(
            "job_not_found",
            "job not found",
            get_document_status,
            repository=self.repository,
            user=self.bob,
            job_id=job_id,
        )

    def test_internal_job_error_message_does_not_expose_exception_details(self):
        job_id = self.submit()["job_id"]
        self.repository.update_job_status(
            job_id,
            "failed",
            error_code="internal_error",
            error_message="cannot access /srv/rose/private/storage/source.md",
            finished_at=CREATED_AT,
        )

        status = get_document_status(
            repository=self.repository, user=self.alice, job_id=job_id
        )

        self.assertEqual(status["error_code"], "internal_error")
        self.assertEqual(status["error_message"], "the job failed due to an internal error")
        self.assertNotIn("/srv/rose/private", json.dumps(status))

    def test_document_metadata_is_safe_and_owner_scoped(self):
        metadata = get_document_metadata(
            repository=self.repository,
            user=self.alice,
            document_id=self.document.id,
        )
        self.assertEqual(
            metadata,
            {
                "document_id": self.document.id,
                "filename": "report.md",
                "space": "default",
                "created_at": CREATED_AT,
                "bytes": 8,
                "sha256": self.document.sha256,
            },
        )
        serialized = json.dumps(metadata)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("# Title", serialized)
        self.assertNotIn(self.alice.password_hash, serialized)
        self.assert_service_error(
            "document_not_found",
            "document not found",
            get_document_metadata,
            repository=self.repository,
            user=self.bob,
            document_id=self.document.id,
        )

    def test_list_brand_profiles_returns_validated_installed_manifests(self):
        profiles = list_brand_profiles(self.settings)
        by_name = {profile["name"]: profile for profile in profiles}
        self.assertEqual(set(by_name), {"demo", "invering"})
        self.assertTrue(by_name["demo"]["provisional"])
        self.assertTrue(by_name["demo"]["provisional_note"])
        self.assertFalse(by_name["invering"]["provisional"])
        self.assertEqual(
            by_name["invering"]["source"],
            "bd5dd8aff92e3ffdb43cc99b78f3d8da1f6b8cb2",
        )
        serialized = json.dumps(profiles)
        self.assertNotIn(str(self.settings.branding_dir), serialized)
        self.assertFalse(Path(by_name["invering"]["template"]).is_absolute())

        missing = Settings(
            branding_dir=self.root / "missing-branding",
            output_dir=self.root / "conversion-output",
        )
        with self.assertRaises(RoseNexusError) as caught:
            list_brand_profiles(missing)
        self.assertEqual(caught.exception.code, "branding_root_missing")


if __name__ == "__main__":
    unittest.main()
