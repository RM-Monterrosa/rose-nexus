"""Tests for content-addressed originals and safe web job artifacts."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from rose_nexus.core.errors import LatexPolicyViolation
from rose_nexus.web.storage import Storage, safe_display_name


class StorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.storage = Storage(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_same_bytes_are_stored_at_one_deduplicated_path(self):
        first = self.storage.save_original(b"same bytes")
        second = self.storage.save_original(b"same bytes")
        self.assertEqual(first, second)
        self.assertEqual(first.sha256, hashlib.sha256(b"same bytes").hexdigest())
        self.assertEqual(self.storage.read_original(first.sha256), b"same bytes")
        files = [path for path in (self.root / "originals").rglob("*") if path.is_file()]
        self.assertEqual(files, [first.path])

    def test_artifact_roundtrip_records_hash_and_source_name(self):
        tex = self.storage.write_artifact("job-1", "tex", b"latex")
        self.assertEqual(tex.relative_path, "document.tex")
        self.assertEqual(tex.sha256, hashlib.sha256(b"latex").hexdigest())
        self.assertEqual(tex.bytes, 5)
        self.assertEqual(self.storage.read_artifact("job-1", "tex"), b"latex")

        source = self.storage.write_artifact("job-1", "source", b"# Title", name="../report.md")
        self.assertEqual(source.relative_path, "source/report.md")
        self.assertEqual(self.storage.read_artifact("job-1", "source"), b"# Title")

    def test_traversal_job_id_and_dotdot_kind_are_rejected(self):
        for job_id in ("../escape", "/absolute", "not/a/slug", ".."):
            with self.subTest(job_id=job_id):
                with self.assertRaises(LatexPolicyViolation) as caught:
                    self.storage.write_artifact(job_id, "tex", b"latex")
                self.assertEqual(caught.exception.code, "unsafe_web_path")
        with self.assertRaises(LatexPolicyViolation) as caught:
            self.storage.write_artifact("job-1", "..", b"latex")
        self.assertEqual(caught.exception.code, "unsafe_web_path")
        self.assertFalse((self.root / "jobs").exists())

    def test_safe_display_name_strips_directories_and_controls(self):
        cleaned = safe_display_name("../../etc/passwd")
        self.assertNotIn("/", cleaned)
        self.assertEqual(cleaned, "passwd")
        self.assertNotIn("\\", safe_display_name(r"..\windows\report.md"))
        self.assertEqual(safe_display_name("\x00\n"), "document")


if __name__ == "__main__":
    unittest.main()
