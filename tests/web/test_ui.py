"""Server-rendered responsive UI tests using the real HTTP server."""

from __future__ import annotations

import html
import re
import unittest
import urllib.parse
from contextlib import closing

from .test_api import (
    CSRF_FIELD,
    PASSWORD,
    WebServerHarness,
    multipart,
)


class UiIntegrationTests(WebServerHarness, unittest.TestCase):
    """Exercise forms, redirects, escaping and job rendering through urllib."""

    def form_login(self, username: str = "alice", password: str = PASSWORD):
        """Submit the public login form and return the redirected response."""

        return self.call(
            "POST",
            "/login",
            data=urllib.parse.urlencode({"username": username, "password": password}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def csrf_from_app(self) -> str:
        """Read the hidden token from the authenticated upload form."""

        response = self.call("GET", "/app")
        self.assertEqual(response.status, 200, response.text)
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
        self.assertIsNotNone(match)
        return html.unescape(match.group(1))

    def ui_upload(self, filename: str, data: bytes, csrf: str | None):
        """Submit the browser upload form, optionally without its CSRF field."""

        body, content_type = multipart(filename, data)
        if csrf is not None:
            boundary = content_type.split("boundary=", 1)[1]
            token = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{CSRF_FIELD}"\r\n\r\n'
                f"{csrf}\r\n"
            ).encode("utf-8")
            marker = f"--{boundary}\r\n".encode("ascii")
            body = token + marker + body.split(marker, 1)[1]
        return self.call(
            "POST",
            "/app/upload",
            data=body,
            headers={"Content-Type": content_type},
        )

    def test_private_pages_redirect_to_login(self) -> None:
        for path in ("/", "/app", "/app/jobs/not-a-job"):
            with self.subTest(path=path):
                response = self.call("GET", path)
                self.assertEqual(response.status, 200)
                self.assertTrue(response.url.endswith("/login"))
                self.assertIn("Iniciar sesión", response.text)
                login = self.call("GET", "/login")
                self.assertNotIn('name="csrf_token"', login.text)

    def test_form_login_sets_cookie_and_app_has_secure_upload_form(self) -> None:
        response = self.form_login()
        self.assertEqual(response.status, 200, response.text)
        self.assertTrue(response.url.endswith("/app"))
        self.assertTrue(any(cookie.name == "rose_session" for cookie in self.cookies))
        self.assertIn('enctype="multipart/form-data"', response.text)
        self.assertIn('name="csrf_token"', response.text)
        self.assertIn('accept=".md,.txt"', response.text)
        self.assertIn(f"{self.max_input_bytes} bytes", response.text)
        self.assertIn("Se generará: TeX", response.text)
        self.assertIn("PDF está deshabilitado", response.text)

        cookie = next(cookie for cookie in self.cookies if cookie.name == "rose_session")
        self.assertTrue(cookie.has_nonstandard_attr("HttpOnly"))
        self.assertEqual(cookie.get_nonstandard_attr("SameSite"), "Lax")

    def test_failed_form_login_is_in_spanish_and_never_echoes_password(self) -> None:
        secret = "do-not-echo-<this-password>"
        response = self.form_login("alice<script>", secret)
        self.assertEqual(response.status, 401)
        self.assertIn("Usuario o contraseña incorrectos", response.text)
        self.assertIn("alice&lt;script&gt;", response.text)
        self.assertNotIn(secret, response.text)
        self.assertNotIn("alice<script>", response.text)

    def test_upload_redirects_and_job_page_changes_from_refresh_to_downloads(self) -> None:
        self.form_login()
        csrf = self.csrf_from_app()
        pending_id = self.create_pending_job()
        pending = self.call("GET", f"/app/jobs/{pending_id}")
        self.assertEqual(pending.status, 200)
        self.assertIn('<meta http-equiv="refresh" content="2">', pending.text)
        self.assertNotIn("/artifacts/tex", pending.text)

        response = self.ui_upload("browser.md", b"# Browser upload\n", csrf)
        self.assertEqual(response.status, 200, response.text)
        self.assertRegex(response.url, r"/app/jobs/[0-9a-f]+$")
        job_id = response.url.rsplit("/", 1)[-1]
        content = response.text
        for _ in range(200):
            if 'meta http-equiv="refresh"' not in content:
                break
            import time

            time.sleep(0.05)
            content = self.call("GET", f"/app/jobs/{job_id}").text
        self.assertNotIn('<meta http-equiv="refresh" content="2">', content)
        self.assertIn("completed", content)
        self.assertIn(f"/api/jobs/{job_id}/artifacts/source", content)
        self.assertIn(f"/api/jobs/{job_id}/artifacts/tex", content)
        self.assertNotIn(f"/api/jobs/{job_id}/artifacts/pdf", content)

    def test_foreign_job_is_404_and_upload_without_csrf_is_403(self) -> None:
        foreign_job = self.create_pending_job("bob")
        self.form_login()
        foreign = self.call("GET", f"/app/jobs/{foreign_job}")
        self.assertEqual(foreign.status, 404)

        response = self.ui_upload("rejected.md", b"# Rejected\n", None)
        self.assertEqual(response.status, 403)
        # The seeded pending job owns one original; rejection must not add metadata.
        from rose_nexus.web.db import connect
        from rose_nexus.web.repository import Repository

        with closing(connect(self.db_path)) as connection:
            repository = Repository(connection)
            user = repository.get_user_by_username("alice")
            self.assertEqual(repository.list_documents(user.id, "default"), [])

    def test_document_filename_is_escaped_everywhere_it_is_rendered(self) -> None:
        self.form_login()
        csrf = self.csrf_from_app()
        filename = "<script>alert(1).md"
        response = self.ui_upload(filename, b"# Escaping\n", csrf)
        self.assertEqual(response.status, 200, response.text)
        library = self.call("GET", "/app").text
        self.assertIn("&lt;script&gt;alert(1).md", library)
        self.assertNotIn("<script>alert(1)", library)

    def test_css_is_same_origin_mobile_first_and_accessible(self) -> None:
        response = self.call("GET", "/static/app.css")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get_content_type(), "text/css")
        self.assertIn("max-width: 760px", response.text)
        self.assertIn("min-height: 44px", response.text)
        self.assertIn("@media (max-width: 639px)", response.text)
        self.assertIn(":focus-visible", response.text)
        self.assertNotIn("@import", response.text)
        self.assertNotIn("url(", response.text)


if __name__ == "__main__":
    unittest.main()
