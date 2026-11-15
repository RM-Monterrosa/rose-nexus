"""Unit tests for the job directory and manifest helpers."""

import json
import pathlib
import tempfile
import unittest

from rose_nexus.core.errors import LatexPolicyViolation
from rose_nexus.storage.artifacts import (
    abort_job,
    create_job,
    finalize_job,
    sha256_bytes,
    sha256_file,
    write_bytes,
)


class JobTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_bytes_records_hash_and_size(self):
        job = create_job(self.out, "demo")
        record = write_bytes(job, "source/demo.md", b"hola")
        self.assertEqual(record["path"], "source/demo.md")
        self.assertEqual(record["bytes"], 4)
        self.assertEqual(record["sha256"], sha256_bytes(b"hola"))

    def test_finalize_writes_manifest_and_moves_the_directory(self):
        job = create_job(self.out, "demo")
        write_bytes(job, "document.tex", b"\\begin{document}x\\end{document}")
        root = finalize_job(job, {"schema_version": 1, "job_id": job.job_id})
        self.assertTrue((root / "document.tex").is_file())
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["job_id"], job.job_id)
        self.assertFalse(job.work.exists())

    def test_abort_removes_the_temporary_directory(self):
        job = create_job(self.out, "demo")
        write_bytes(job, "document.tex", b"x")
        abort_job(job)
        self.assertFalse(job.work.exists())
        self.assertFalse(job.root.exists())

    def test_traversal_relative_path_is_rejected(self):
        job = create_job(self.out, "demo")
        with self.assertRaises(LatexPolicyViolation) as caught:
            write_bytes(job, "../escape.md", b"x")
        self.assertEqual(caught.exception.code, "unsafe_artifact_path")

    def test_absolute_relative_path_is_rejected(self):
        job = create_job(self.out, "demo")
        with self.assertRaises(LatexPolicyViolation):
            write_bytes(job, "/etc/passwd", b"x")

    def test_existing_job_directory_is_never_reused(self):
        job = create_job(self.out, "demo")
        write_bytes(job, "document.tex", b"x")
        finalize_job(job, {"schema_version": 1})
        with self.assertRaises(LatexPolicyViolation) as caught:
            create_job(self.out, "demo", job_id=job.job_id)
        self.assertEqual(caught.exception.code, "job_exists")

    def test_sha256_file_matches_bytes(self):
        target = self.out / "x.bin"
        target.write_bytes(b"abc")
        self.assertEqual(sha256_file(target), sha256_bytes(b"abc"))


if __name__ == "__main__":
    unittest.main()
