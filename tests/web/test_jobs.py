"""Behavior tests for the single-threaded web conversion job runner."""

import hashlib
import tempfile
import time
import unittest
from pathlib import Path

from rose_nexus.core.config import Settings
from rose_nexus.core.errors import InputValidationError
from rose_nexus.studio.pipeline import ConversionResult
from rose_nexus.web.db import connect, migrate
from rose_nexus.web.jobs import JobRunner
from rose_nexus.web.models import Document, Job, User
from rose_nexus.web.repository import Repository
from rose_nexus.web.storage import Storage


CREATED_AT = "2026-11-15T12:00:00Z"


class JobRunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.conn = connect(self.root / "web.sqlite3")
        migrate(self.conn)
        self.repo = Repository(self.conn)
        self.storage = Storage(self.root / "stored")
        self.settings = Settings(
            branding_dir=self.root / "branding",
            output_dir=self.root / "conversion-output",
        )
        self.repo.create_user(User("user-1", "alice", "hash", CREATED_AT, False))
        self.runners = []

    def tearDown(self):
        for runner in self.runners:
            runner.stop()
        self.conn.close()
        self._tmp.cleanup()

    def create_job(self, job_id, data=b"# Heading", filename="report.md"):
        original = self.storage.save_original(data)
        self.repo.create_document(
            Document(
                f"document-{job_id}",
                "user-1",
                "default",
                filename,
                original.sha256,
                len(data),
                CREATED_AT,
            )
        )
        self.repo.create_job(
            Job(
                job_id,
                f"document-{job_id}",
                "user-1",
                "pending",
                "demo",
                '["tex"]',
                None,
                None,
                CREATED_AT,
                None,
                None,
                None,
            )
        )
        return job_id

    def runner(self, converter):
        runner = JobRunner(self.repo, self.storage, self.settings, converter=converter)
        self.runners.append(runner)
        return runner

    def wait_for_terminal(self, job_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = self.repo.get_job(job_id)
            if current.status in {"completed", "failed", "cancelled"}:
                return current
            time.sleep(0.005)
        self.fail(f"job {job_id} did not reach a terminal state")

    def successful_conversion(self, source, *, brand, formats, settings):
        converted = Path(tempfile.mkdtemp(dir=self.root))
        source_copy = converted / "source" / source.name
        source_copy.parent.mkdir(parents=True)
        source_copy.write_bytes(source.read_bytes())
        tex_path = converted / "document.tex"
        tex_path.write_bytes(b"generated latex")
        manifest_path = converted / "manifest.json"
        manifest_path.write_text("{}", encoding="utf-8")
        return ConversionResult(converted, tex_path, None, manifest_path, {}, ())

    def test_success_records_source_and_tex_and_completes(self):
        observed = {}

        def converter(source, *, brand, formats, settings):
            observed.update(name=source.name, brand=brand, formats=formats, settings=settings)
            return self.successful_conversion(source, brand=brand, formats=formats, settings=settings)

        runner = self.runner(converter)
        runner.start()
        runner.submit(self.create_job("job-success", filename="report.md"))
        completed = self.wait_for_terminal("job-success")

        self.assertEqual(completed.status, "completed")
        self.assertIsNotNone(completed.started_at)
        self.assertIsNotNone(completed.finished_at)
        self.assertIsInstance(completed.duration_ms, int)
        self.assertGreaterEqual(completed.duration_ms, 0)
        self.assertEqual(observed["name"], "report.md")
        self.assertEqual(observed["brand"], "demo")
        self.assertEqual(observed["formats"], ("tex",))
        self.assertIs(observed["settings"], self.settings)
        artifacts = {item.kind: item for item in self.repo.list_artifacts("job-success")}
        self.assertEqual(set(artifacts), {"source", "tex"})
        self.assertEqual(artifacts["source"].relative_path, "source/report.md")
        self.assertEqual(artifacts["source"].sha256, hashlib.sha256(b"# Heading").hexdigest())
        self.assertEqual(self.storage.read_artifact("job-success", "tex"), b"generated latex")

    def test_engine_error_records_its_stable_code(self):
        def converter(source, *, brand, formats, settings):
            raise InputValidationError("bad input", code="bad_source")

        runner = self.runner(converter)
        runner.start()
        runner.submit(self.create_job("job-invalid"))
        failed = self.wait_for_terminal("job-invalid")

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error_code, "bad_source")
        self.assertEqual(failed.error_message, "bad input")
        self.assertIsNotNone(failed.finished_at)
        self.assertEqual(self.repo.list_artifacts("job-invalid"), [])

    def test_unexpected_error_records_internal_error_and_worker_survives(self):
        def converter(source, *, brand, formats, settings):
            if source.read_bytes() == b"explode":
                raise RuntimeError("unexpected failure")
            return self.successful_conversion(source, brand=brand, formats=formats, settings=settings)

        runner = self.runner(converter)
        runner.start()
        runner.submit(self.create_job("job-crash", data=b"explode"))
        failed = self.wait_for_terminal("job-crash")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error_code, "internal_error")
        self.assertEqual(failed.error_message, "unexpected failure")

        runner.submit(self.create_job("job-after-crash", data=b"safe"))
        completed = self.wait_for_terminal("job-after-crash")
        self.assertEqual(completed.status, "completed")
        self.assertEqual(self.storage.read_artifact("job-after-crash", "tex"), b"generated latex")

    def test_recover_interrupted_flips_running_to_failed(self):
        self.create_job("job-interrupted")
        self.repo.update_job_status("job-interrupted", "running", started_at=CREATED_AT)
        runner = self.runner(self.successful_conversion)

        runner.recover_interrupted()
        recovered = self.repo.get_job("job-interrupted")
        self.assertEqual(recovered.status, "failed")
        self.assertEqual(recovered.error_code, "interrupted")
        self.assertEqual(recovered.error_message, "the worker restarted before this job finished")
        self.assertIsNotNone(recovered.finished_at)


if __name__ == "__main__":
    unittest.main()
