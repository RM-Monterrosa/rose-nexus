"""PDF output through a simulated container runtime.

The runtime is a stub, so the assertions are about program behavior: the compiled
job must declare every file it contains and must never leave compiler scratch
directories behind.
"""

import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest
from unittest import mock

from rose_nexus.core.config import Settings
from rose_nexus.storage.artifacts import sha256_file
from rose_nexus.studio.pipeline import convert_document

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BRANDING = REPO_ROOT / "branding"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "markdown"
IMAGE = "rose-nexus/texlive-sandbox@sha256:" + "b" * 64

STUB_TEMPLATE = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["STUB_RECORD"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
for argument in sys.argv[1:]:
    if argument.startswith("--mount=") and "dst=/out" in argument:
        out = argument.split("src=")[1].split(",")[0]
        with open(os.path.join(out, "document.pdf"), "wb") as handle:
            handle.write(b"%PDF-1.4 stub")
        with open(os.path.join(out, "document.aux"), "wb") as handle:
            handle.write(b"\\relax")
sys.exit(0)
"""


class PdfPipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self._tmp.name)
        self.out = self.base / "build"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.record = self.base / "argv.jsonl"
        stub = self.bin / "podman"
        stub.write_text(
            STUB_TEMPLATE.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1),
            encoding="utf-8",
        )
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        self.env = mock.patch.dict(
            os.environ,
            {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", "STUB_RECORD": str(self.record)},
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self._tmp.cleanup()

    def settings(self, **overrides):
        values = {
            "branding_dir": BRANDING,
            "output_dir": self.out,
            "sandbox_image": IMAGE,
            "container_runtime": "podman",
        }
        values.update(overrides)
        return Settings(**values)

    def convert(self):
        return convert_document(
            FIXTURES / "01-headings.md",
            brand="demo",
            formats=("tex", "pdf"),
            settings=self.settings(),
        )

    def test_compiled_job_contains_only_declared_artifacts(self):
        result = self.convert()
        self.assertEqual(result.manifest["status"], "compiled")
        self.assertTrue(result.pdf_path.is_file())
        declared = sorted(
            ["manifest.json"] + [artifact["path"] for artifact in result.manifest["artifacts"]]
        )
        on_disk = sorted(
            path.relative_to(result.job_dir).as_posix()
            for path in result.job_dir.rglob("*")
            if path.is_file()
        )
        self.assertEqual(on_disk, declared, "compiler scratch files must not reach the job")

    def test_pdf_is_recorded_as_an_artifact_with_its_hash(self):
        result = self.convert()
        records = {artifact["path"]: artifact for artifact in result.manifest["artifacts"]}
        self.assertIn("document.pdf", records)
        self.assertEqual(records["document.pdf"]["kind"], "pdf")
        self.assertEqual(records["document.pdf"]["sha256"], sha256_file(result.pdf_path))
        self.assertGreater(records["document.pdf"]["bytes"], 0)

    def test_compilation_goes_through_two_hardened_container_runs(self):
        self.convert()
        runs = [json.loads(line) for line in self.record.read_text().splitlines() if line]
        self.assertEqual(len(runs), 2)
        for run in runs:
            self.assertIn("--network=none", run)
            self.assertIn("--read-only", run)
            self.assertIn("-no-shell-escape", run)

    def test_manifest_tools_record_the_pinned_image(self):
        result = self.convert()
        self.assertEqual(result.manifest["tools"]["container_runtime"], "podman")
        self.assertEqual(result.manifest["tools"]["sandbox_image"], IMAGE)


if __name__ == "__main__":
    unittest.main()
