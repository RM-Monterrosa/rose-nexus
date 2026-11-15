"""Integration tests for the ``rose`` command line interface.

The CLI is exercised as a subprocess so exit codes and streams are verified the
way a script or a person would see them.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "markdown"


def run_cli(*arguments, env_extra=None):
    environment = {key: value for key, value in os.environ.items() if not key.startswith("ROSE_")}
    environment["PYTHONPATH"] = str(BACKEND)
    environment.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "rose_nexus.cli", *arguments],
        capture_output=True,
        text=True,
        timeout=180,
        env=environment,
        check=False,
    )


class ConvertCommandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = pathlib.Path(self._tmp.name) / "build"

    def tearDown(self):
        self._tmp.cleanup()

    def test_convert_writes_tex_and_reports_paths(self):
        result = run_cli(
            "convert",
            str(FIXTURES / "01-headings.md"),
            "--brand",
            "demo",
            "--out",
            str(self.out),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("document.tex", result.stdout)
        self.assertEqual(result.stderr, "")
        jobs = [path for path in self.out.iterdir() if path.is_dir()]
        self.assertEqual(len(jobs), 1)
        self.assertTrue((jobs[0] / "document.tex").is_file())
        self.assertTrue((jobs[0] / "manifest.json").is_file())

    def test_convert_json_output_is_machine_readable(self):
        result = run_cli(
            "convert",
            str(FIXTURES / "02-emphasis.md"),
            "--brand",
            "demo",
            "--out",
            str(self.out),
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["brand"]["provisional"])
        self.assertIn("document.tex", [item["path"] for item in payload["artifacts"]])
        self.assertTrue(pathlib.Path(payload["job_dir"]).is_dir())

    def test_unknown_brand_exits_with_validation_code(self):
        result = run_cli(
            "convert",
            str(FIXTURES / "01-headings.md"),
            "--brand",
            "marca-inexistente",
            "--out",
            str(self.out),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("branding_profile_not_found", result.stderr)

    def test_failure_json_reports_the_error_object(self):
        result = run_cli(
            "convert",
            str(FIXTURES / "01-headings.md"),
            "--brand",
            "marca-inexistente",
            "--out",
            str(self.out),
            "--json",
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "branding_profile_not_found")

    def test_missing_source_exits_with_validation_code(self):
        result = run_cli("convert", str(self.out / "no-existe.md"), "--out", str(self.out))
        self.assertEqual(result.returncode, 2)
        self.assertIn("source_not_found", result.stderr)

    def test_pdf_without_sandbox_exits_with_four(self):
        result = run_cli(
            "convert",
            str(FIXTURES / "01-headings.md"),
            "--brand",
            "demo",
            "--out",
            str(self.out),
            "--format",
            "pdf",
        )
        self.assertEqual(result.returncode, 4)
        self.assertIn("sandbox_unavailable", result.stderr)
        self.assertFalse(self.out.exists())


class IntrospectionCommandTests(unittest.TestCase):
    def test_version(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("0.1.0", result.stdout)

    def test_help_lists_the_three_commands(self):
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0)
        for command in ("convert", "brands", "doctor"):
            self.assertIn(command, result.stdout)

    def test_brands_lists_both_profiles(self):
        result = run_cli("brands", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        by_name = {profile["name"]: profile for profile in payload["profiles"]}
        self.assertEqual(sorted(by_name), ["demo", "invering"])
        self.assertTrue(by_name["demo"]["provisional"])
        self.assertFalse(by_name["invering"]["provisional"])
        self.assertEqual(
            by_name["invering"]["source"], "bd5dd8aff92e3ffdb43cc99b78f3d8da1f6b8cb2"
        )

    def test_brands_human_output_mentions_provisional(self):
        result = run_cli("brands")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("demo", result.stdout)
        self.assertIn("provisional", result.stdout.lower())

    def test_doctor_json_reports_environment(self):
        result = run_cli("doctor", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(report["status"], {"ready", "degraded"})
        for key in ("python", "container", "branding"):
            self.assertIn(key, report)
        self.assertIn(report["container"]["image"]["pinned"], {True, False})
        self.assertGreaterEqual(report["python"]["version_info"][0], 3)


if __name__ == "__main__":
    unittest.main()
