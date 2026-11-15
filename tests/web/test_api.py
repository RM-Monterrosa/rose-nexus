"""End-to-end HTTP API tests against a real uvicorn subprocess."""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from typing import Mapping

from rose_nexus.web.bootstrap import ensure_user
from rose_nexus.web.db import connect, migrate
from rose_nexus.web.models import Document, Job
from rose_nexus.web.repository import Repository
from rose_nexus.web.storage import Storage


ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "correct horse battery staple"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FIELD = "csrf_token"


@dataclass(frozen=True)
class HttpResult:
    """A fully buffered urllib response, including expected HTTP errors."""

    status: int
    headers: Message
    body: bytes
    url: str

    def json(self) -> dict:
        """Decode a JSON object response."""

        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self) -> str:
        """Decode an HTML or plain-text response."""

        return self.body.decode("utf-8")


def request(
    method: str,
    url: str,
    *,
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    opener: urllib.request.OpenerDirector | None = None,
) -> HttpResult:
    """Issue one request without turning expected 4xx responses into test errors."""

    client = opener or urllib.request.build_opener()
    req = urllib.request.Request(url, data=data, headers=dict(headers or {}), method=method)
    try:
        with client.open(req, timeout=3) as response:
            return HttpResult(
                response.status, response.headers, response.read(), response.geturl()
            )
    except urllib.error.HTTPError as error:
        with error:
            return HttpResult(error.code, error.headers, error.read(), error.geturl())


def multipart(filename: str, data: bytes, *, field: str = "file") -> tuple[bytes, str]:
    """Build one deterministic multipart upload body and its content type."""

    boundary = "----rose-nexus-test-boundary"
    safe_name = filename.replace('"', "%22")
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{safe_name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    body += data + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, f"multipart/form-data; boundary={boundary}"


class WebServerHarness:
    """Own an isolated temporary database, storage tree and uvicorn process."""

    max_input_bytes = 512

    def setUp(self) -> None:
        super().setUp()
        self._temporary = tempfile.TemporaryDirectory(prefix="rose-web-test-")
        self.root = Path(self._temporary.name)
        self.db_path = self.root / "rose-nexus.db"
        self.storage_dir = self.root / "storage"
        connection = connect(self.db_path)
        try:
            migrate(connection)
            repository = Repository(connection)
            ensure_user(repository, "alice", PASSWORD)
            ensure_user(repository, "bob", PASSWORD)
        finally:
            connection.close()

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONPATH": str(ROOT / "backend"),
                "ROSE_DB_PATH": str(self.db_path),
                "ROSE_STORAGE_DIR": str(self.storage_dir),
                "ROSE_SECRET_KEY": "test-only-web-session-secret",
                "ROSE_OUTPUT_DIR": str(self.root / "conversion-output"),
                "ROSE_MAX_INPUT_BYTES": str(self.max_input_bytes),
                "ROSE_SANDBOX_IMAGE": "",
            }
        )
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "rose_nexus.web",
                "--serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )
        deadline = time.monotonic() + 15
        while True:
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate(timeout=2)
                self.fail(f"web server exited early\nstdout: {stdout}\nstderr: {stderr}")
            try:
                health = self.call("GET", "/api/health")
                if health.status == 200:
                    break
            except (OSError, urllib.error.URLError):
                pass
            if time.monotonic() >= deadline:
                self.fail("web server did not become healthy within 15 seconds")
            time.sleep(0.05)

    def tearDown(self) -> None:
        if hasattr(self, "process") and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if hasattr(self, "process") and self.process.stdout is not None:
            self.process.stdout.close()
        if hasattr(self, "process") and self.process.stderr is not None:
            self.process.stderr.close()
        if hasattr(self, "_temporary"):
            self._temporary.cleanup()
        super().tearDown()

    def call(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> HttpResult:
        """Call this test's server through urllib."""

        return request(
            method,
            self.base_url + path,
            data=data,
            headers=headers,
            opener=opener or self.opener,
        )

    def new_client(self) -> urllib.request.OpenerDirector:
        """Return a client with independent cookies."""

        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def api_login(
        self, username: str = "alice", *, opener: urllib.request.OpenerDirector | None = None
    ) -> str:
        """Authenticate one JSON client and return its current CSRF token."""

        client = opener or self.opener
        response = self.call(
            "POST",
            "/api/session",
            data=json.dumps({"username": username, "password": PASSWORD}).encode(),
            headers={"Content-Type": "application/json"},
            opener=client,
        )
        self.assertEqual(response.status, 200, response.text)
        current = self.call("GET", "/api/session", opener=client)
        self.assertEqual(current.status, 200, current.text)
        return current.json()[CSRF_FIELD]

    def upload(
        self,
        filename: str,
        data: bytes,
        csrf: str,
        *,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> HttpResult:
        """Upload one file through the public JSON API."""

        body, content_type = multipart(filename, data)
        return self.call(
            "POST",
            "/api/documents",
            data=body,
            headers={"Content-Type": content_type, CSRF_HEADER: csrf},
            opener=opener,
        )

    def wait_for_job(self, job_id: str) -> dict:
        """Poll the public job endpoint until conversion reaches a terminal state."""

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            response = self.call("GET", f"/api/jobs/{job_id}")
            self.assertEqual(response.status, 200, response.text)
            job = response.json()["job"]
            if job["status"] == "completed":
                return job
            if job["status"] in {"failed", "cancelled"}:
                self.fail(f"job failed: {job}")
            time.sleep(0.05)
        self.fail(f"job {job_id} did not complete within 15 seconds")

    def create_pending_job(self, username: str = "alice", filename: str = "pending.md") -> str:
        """Seed one owned pending job without submitting it to the worker."""

        connection = connect(self.db_path)
        try:
            repository = Repository(connection)
            user = repository.get_user_by_username(username)
            self.assertIsNotNone(user)
            original = Storage(self.storage_dir).save_original(b"# Pending\n")
            document_id = uuid.uuid4().hex
            job_id = uuid.uuid4().hex
            created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            repository.create_document(
                Document(
                    document_id,
                    user.id,
                    "default",
                    filename,
                    original.sha256,
                    len(b"# Pending\n"),
                    created_at,
                )
            )
            repository.create_job(
                Job(
                    job_id,
                    document_id,
                    user.id,
                    "pending",
                    "invering",
                    '["tex"]',
                    None,
                    None,
                    created_at,
                    None,
                    None,
                    None,
                )
            )
            return job_id
        finally:
            connection.close()


class ApiIntegrationTests(WebServerHarness, unittest.TestCase):
    """Verify authentication, CSRF, conversion and scoped artifact delivery."""

    def test_health_and_security_headers_on_api_and_login(self) -> None:
        health = self.call("GET", "/api/health")
        self.assertEqual(health.status, 200)
        self.assertEqual(health.json(), {"ok": True, "status": "ready"})
        for path in ("/api/health", "/login"):
            response = self.call("GET", path)
            self.assertEqual(
                response.headers["Content-Security-Policy"],
                "default-src 'self'; style-src 'self'",
            )
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")

    def test_login_rejects_bad_password_and_sets_hardened_cookie(self) -> None:
        wrong = self.call(
            "POST",
            "/api/session",
            data=json.dumps({"username": "alice", "password": "wrong"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(wrong.status, 401)
        self.assertEqual(wrong.json()["error"]["code"], "invalid_credentials")

        csrf = self.api_login()
        self.assertTrue(csrf)
        cookie = next(cookie for cookie in self.cookies if cookie.name == "rose_session")
        self.assertIn(".", cookie.value)
        self.assertEqual(cookie.path, "/")
        # urllib exposes non-standard HttpOnly/SameSite attributes in rest.
        self.assertTrue(cookie.has_nonstandard_attr("HttpOnly"))
        self.assertEqual(cookie.get_nonstandard_attr("SameSite"), "Lax")
        self.assertFalse(cookie.secure)
        current = self.call("GET", "/api/session")
        self.assertEqual(current.json()["user"], {"username": "alice", "is_admin": False})

    def test_login_throttle_is_scoped_to_host_and_username(self) -> None:
        for _ in range(5):
            response = self.call(
                "POST",
                "/api/session",
                data=json.dumps({"username": "alice", "password": "bad"}).encode(),
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(response.status, 401)
        limited = self.call(
            "POST",
            "/api/session",
            data=json.dumps({"username": "alice", "password": PASSWORD}).encode(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(limited.status, 429)
        self.assertEqual(limited.json()["error"]["code"], "rate_limited")
        other_user = self.call(
            "POST",
            "/api/session",
            data=json.dumps({"username": "bob", "password": "bad"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(other_user.status, 401)

    def test_jobs_require_a_session(self) -> None:
        response = self.call("GET", "/api/jobs")
        self.assertEqual(response.status, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")

    def test_document_upload_requires_csrf_and_writes_nothing(self) -> None:
        self.api_login()
        body, content_type = multipart("no-csrf.md", b"# Rejected")
        response = self.call(
            "POST",
            "/api/documents",
            data=body,
            headers={"Content-Type": content_type},
        )
        self.assertEqual(response.status, 403)
        self.assertEqual(response.json()["error"]["code"], "csrf_failed")
        with closing(connect(self.db_path)) as connection:
            self.assertEqual(Repository(connection).list_jobs("missing"), [])
            user = Repository(connection).get_user_by_username("alice")
            self.assertEqual(Repository(connection).list_documents(user.id, "default"), [])
        self.assertFalse((self.storage_dir / "originals").exists())

    def test_markdown_and_text_uploads_return_stable_digests(self) -> None:
        csrf = self.api_login()
        for filename, data in (("report.md", b"# Title\n"), ("notes.txt", b"plain text\n")):
            with self.subTest(filename=filename):
                response = self.upload(filename, data, csrf)
                self.assertEqual(response.status, 201, response.text)
                payload = response.json()
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["sha256"], hashlib.sha256(data).hexdigest())
                self.assertEqual(payload["bytes"], len(data))
                self.assertTrue(payload["document_id"])

    def test_upload_rejects_type_size_and_non_utf8_without_metadata(self) -> None:
        csrf = self.api_login()
        cases = (
            ("document.docx", b"not a document", 415, "unsupported_media_type"),
            ("large.md", b"x" * (self.max_input_bytes + 1), 413, "payload_too_large"),
            ("invalid.md", b"\xff\xfe", 415, "invalid_encoding"),
        )
        for filename, data, status, code in cases:
            with self.subTest(filename=filename):
                response = self.upload(filename, data, csrf)
                self.assertEqual(response.status, status, response.text)
                self.assertEqual(response.json()["error"]["code"], code)
        with closing(connect(self.db_path)) as connection:
            repository = Repository(connection)
            user = repository.get_user_by_username("alice")
            self.assertEqual(repository.list_documents(user.id, "default"), [])
        self.assertFalse((self.storage_dir / "originals").exists())

    def test_job_lifecycle_list_order_and_artifact_downloads(self) -> None:
        csrf = self.api_login()
        source = b"# Report\n\nDeterministic output.\n"
        document = self.upload("report.md", source, csrf).json()
        first = self.call(
            "POST",
            "/api/jobs",
            data=json.dumps(
                {"document_id": document["document_id"], "brand": "invering", "formats": ["tex"]}
            ).encode(),
            headers={"Content-Type": "application/json", CSRF_HEADER: csrf},
        )
        self.assertEqual(first.status, 202, first.text)
        first_id = first.json()["job_id"]
        first_job = self.wait_for_job(first_id)
        self.assertEqual(first_job["formats"], ["tex"])
        self.assertEqual({a["kind"] for a in first_job["artifacts"]}, {"source", "tex"})

        time.sleep(0.002)
        second = self.call(
            "POST",
            "/api/jobs",
            data=json.dumps(
                {"document_id": document["document_id"], "brand": "invering", "formats": ["tex"]}
            ).encode(),
            headers={"Content-Type": "application/json", CSRF_HEADER: csrf},
        )
        second_id = second.json()["job_id"]
        self.wait_for_job(second_id)
        listing = self.call("GET", "/api/jobs")
        self.assertEqual(listing.status, 200)
        self.assertEqual([job["id"] for job in listing.json()["jobs"][:2]], [second_id, first_id])

        tex = self.call("GET", f"/api/jobs/{first_id}/artifacts/tex")
        self.assertEqual(tex.status, 200, tex.text)
        self.assertTrue(tex.headers.get_content_type() == "application/x-tex")
        self.assertIn("attachment", tex.headers["Content-Disposition"])
        self.assertIn("document.tex", tex.headers["Content-Disposition"])
        self.assertIn(b"rose-nexus generated document", tex.body)
        original = self.call("GET", f"/api/jobs/{first_id}/artifacts/source")
        self.assertEqual(original.status, 200)
        self.assertEqual(original.body, source)
        missing_pdf = self.call("GET", f"/api/jobs/{first_id}/artifacts/pdf")
        self.assertEqual(missing_pdf.status, 404)

    def test_job_validation_errors_do_not_create_jobs(self) -> None:
        csrf = self.api_login()
        document = self.upload("report.md", b"# Report\n", csrf).json()
        common = {"document_id": document["document_id"], "brand": "invering"}
        cases = (
            ({**common, "formats": []}, 400, "unsupported_format", "formats must be a nonempty subset of tex and pdf"),
            ({**common, "formats": ["tex", "tex"]}, 400, "unsupported_format", "formats must not contain duplicates"),
            ({**common, "formats": ["docx"]}, 400, "unsupported_format", "formats must be a nonempty subset of tex and pdf"),
            ({**common, "formats": ["tex"], "brand": "absent"}, 400, "branding_profile_not_found", "brand profile 'absent' was not found"),
            ({"document_id": "missing", "brand": "invering", "formats": ["tex"]}, 404, "document_not_found", "document not found"),
        )
        for payload, status, code, message in cases:
            with self.subTest(code=code, payload=payload):
                response = self.call(
                    "POST",
                    "/api/jobs",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json", CSRF_HEADER: csrf},
                )
                self.assertEqual(response.status, status, response.text)
                self.assertEqual(
                    response.json(),
                    {"ok": False, "error": {"code": code, "message": message}},
                )
        with closing(connect(self.db_path)) as connection:
            self.assertEqual(Repository(connection).list_jobs(), [])

    def test_foreign_documents_jobs_and_artifacts_are_not_found(self) -> None:
        csrf = self.api_login()
        document = self.upload("private.md", b"# Private\n", csrf).json()
        created = self.call(
            "POST",
            "/api/jobs",
            data=json.dumps(
                {"document_id": document["document_id"], "brand": "invering", "formats": ["tex"]}
            ).encode(),
            headers={"Content-Type": "application/json", CSRF_HEADER: csrf},
        )
        job_id = created.json()["job_id"]
        self.wait_for_job(job_id)

        other = self.new_client()
        other_csrf = self.api_login("bob", opener=other)
        self.assertEqual(self.call("GET", f"/api/jobs/{job_id}", opener=other).status, 404)
        self.assertEqual(
            self.call("GET", f"/api/jobs/{job_id}/artifacts/tex", opener=other).status, 404
        )
        foreign_document = self.call(
            "POST",
            "/api/jobs",
            data=json.dumps(
                {"document_id": document["document_id"], "brand": "invering", "formats": ["tex"]}
            ).encode(),
            headers={"Content-Type": "application/json", CSRF_HEADER: other_csrf},
            opener=other,
        )
        self.assertEqual(foreign_document.status, 404)


if __name__ == "__main__":
    unittest.main()
