"""Unit tests for the container sandbox used to compile LaTeX.

The container binary is simulated with an executable stub, so the tests verify the
constructed argv, the timeout and the failure handling without needing Docker.
"""

import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest
from unittest import mock

from rose_nexus.core.errors import CompileError, SandboxUnavailableError
from rose_nexus.security.sandbox import (
    SandboxLimits,
    build_compile_argv,
    compile_document,
    detect_runtime,
    validate_image_reference,
)

DIGEST = "@sha256:" + "a" * 64
IMAGE = "rose-nexus/texlive-sandbox" + DIGEST

STUB_TEMPLATE = """#!/usr/bin/env python3
import json, os, sys, time
record = os.environ["STUB_RECORD"]
with open(record, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("STUB_SLEEP"):
    time.sleep(float(os.environ["STUB_SLEEP"]))
if os.environ.get("STUB_FAIL"):
    print("! LaTeX Error: boom", file=sys.stderr)
    sys.exit(1)
for argument in sys.argv[1:]:
    if argument.startswith("--mount=") and "dst=/out" in argument:
        out = argument.split("src=")[1].split(",")[0]
        with open(os.path.join(out, "document.pdf"), "wb") as handle:
            handle.write(b"%PDF-1.4 stub")
sys.exit(0)
"""


class SandboxTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.record = self.root / "argv.jsonl"
        stub = self.bin / "podman"
        stub.write_text(
            STUB_TEMPLATE.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1),
            encoding="utf-8",
        )
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        self.env = mock.patch.dict(
            os.environ,
            {"PATH": str(self.bin), "STUB_RECORD": str(self.record)},
            clear=False,
        )
        self.env.start()
        for key in ("STUB_SLEEP", "STUB_FAIL"):
            os.environ.pop(key, None)
        self.src = self.root / "src"
        self.src.mkdir()
        (self.src / "document.tex").write_text("\\begin{document}x\\end{document}")
        self.out = self.root / "out"
        self.out.mkdir()

    def tearDown(self):
        self.env.stop()
        self._tmp.cleanup()

    def recorded(self):
        if not self.record.is_file():
            return []
        return [json.loads(line) for line in self.record.read_text().splitlines() if line]


class ArgvHardeningTests(SandboxTestBase):
    def test_required_isolation_flags_are_present(self):
        argv = build_compile_argv(
            detect_runtime("podman"),
            image=IMAGE,
            source_dir=self.src,
            output_dir=self.out,
            limits=SandboxLimits(),
        )
        joined = " ".join(argv)
        for flag in (
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            "--pids-limit=",
            "--memory=",
            "--memory-swap=",
            "--cpus=",
            "noexec",
            "dst=/src,ro",
            "-no-shell-escape",
            "-halt-on-error",
        ):
            self.assertIn(flag, joined)
        self.assertIn("SOURCE_DATE_EPOCH=0", joined)

    def test_mount_source_is_the_given_directory(self):
        argv = build_compile_argv(
            detect_runtime("podman"),
            image=IMAGE,
            source_dir=self.src,
            output_dir=self.out,
            limits=SandboxLimits(),
        )
        joined = " ".join(argv)
        self.assertIn(f"src={self.src.resolve()}", joined)
        self.assertIn(f"src={self.out.resolve()}", joined)

    def test_mount_path_with_comma_is_rejected(self):
        weird = self.root / "with,comma"
        weird.mkdir()
        with self.assertRaises(SandboxUnavailableError) as caught:
            build_compile_argv(
                detect_runtime("podman"),
                image=IMAGE,
                source_dir=weird,
                output_dir=self.out,
                limits=SandboxLimits(),
            )
        self.assertEqual(caught.exception.code, "sandbox_mount_path_invalid")

    def test_tagged_image_is_rejected(self):
        with self.assertRaises(SandboxUnavailableError) as caught:
            validate_image_reference("rose-nexus/texlive-sandbox:latest")
        self.assertEqual(caught.exception.code, "sandbox_image_not_pinned")

    def test_empty_image_is_rejected(self):
        with self.assertRaises(SandboxUnavailableError) as caught:
            validate_image_reference("")
        self.assertEqual(caught.exception.code, "sandbox_image_not_provisioned")

    def test_digest_image_is_accepted(self):
        self.assertEqual(validate_image_reference(IMAGE), IMAGE)

    def test_missing_runtime_is_reported(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.root / "empty")}):
            self.assertIsNone(detect_runtime(None))


class CompileExecutionTests(SandboxTestBase):
    def test_successful_compile_returns_the_pdf(self):
        result = compile_document(
            self.src / "document.tex",
            image=IMAGE,
            limits=SandboxLimits(timeout_seconds=30),
            runtime_name="podman",
        )
        self.assertTrue(result.pdf_path.is_file())
        runs = self.recorded()
        self.assertEqual(len(runs), 2)  # two passes for cross-references
        self.assertIn("-no-shell-escape", runs[0])

    def test_failure_raises_compile_error_with_log(self):
        os.environ["STUB_FAIL"] = "1"
        with self.assertRaises(CompileError) as caught:
            compile_document(
                self.src / "document.tex",
                image=IMAGE,
                limits=SandboxLimits(timeout_seconds=30),
                runtime_name="podman",
            )
        self.assertEqual(caught.exception.code, "compile_failed")
        self.assertIn("LaTeX Error", caught.exception.detail or "")

    def test_timeout_is_reported_and_does_not_hang(self):
        os.environ["STUB_SLEEP"] = "5"
        with self.assertRaises(CompileError) as caught:
            compile_document(
                self.src / "document.tex",
                image=IMAGE,
                limits=SandboxLimits(timeout_seconds=1),
                runtime_name="podman",
            )
        self.assertEqual(caught.exception.code, "compile_timeout")

    def test_missing_image_blocks_compilation(self):
        with self.assertRaises(SandboxUnavailableError) as caught:
            compile_document(
                self.src / "document.tex",
                image="",
                limits=SandboxLimits(),
                runtime_name="podman",
            )
        self.assertEqual(caught.exception.code, "sandbox_image_not_provisioned")


if __name__ == "__main__":
    unittest.main()
