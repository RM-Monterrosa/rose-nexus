"""Authenticated experimental LLM screen tests against real HTTP servers."""

from __future__ import annotations

import html
import os
import re
import unittest
import urllib.parse

from tests.ai.fake_server import FakeLlmServer

from .test_api import PASSWORD, WebServerHarness


class LlmWebServerHarness(WebServerHarness):
    """Start uvicorn with an isolated loopback fake inference endpoint."""

    llm_enabled = True
    answer = "Respuesta <script>alert(1)</script> del modelo"

    def setUp(self) -> None:
        self.fake_llm = FakeLlmServer(content=self.answer)
        self.fake_llm.__enter__()
        self._fake_llm_running = True
        keys = (
            "ROSE_LLM_ENABLED",
            "ROSE_LLM_ENDPOINT",
            "ROSE_LLM_CONNECT_TIMEOUT_SECONDS",
            "ROSE_LLM_TIMEOUT_SECONDS",
        )
        self._previous_llm_environment = {key: os.environ.get(key) for key in keys}
        os.environ["ROSE_LLM_ENDPOINT"] = self.fake_llm.endpoint
        os.environ["ROSE_LLM_CONNECT_TIMEOUT_SECONDS"] = "0.2"
        os.environ["ROSE_LLM_TIMEOUT_SECONDS"] = "1"
        if self.llm_enabled:
            os.environ["ROSE_LLM_ENABLED"] = "true"
        else:
            os.environ.pop("ROSE_LLM_ENABLED", None)
        try:
            super().setUp()
        except BaseException:
            self._restore_environment()
            self.stop_fake_llm()
            raise

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            self._restore_environment()
            self.stop_fake_llm()

    def _restore_environment(self) -> None:
        for key, value in self._previous_llm_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def stop_fake_llm(self) -> None:
        """Stop the fake endpoint once, leaving uvicorn running."""

        if self._fake_llm_running:
            self.fake_llm.__exit__(None, None, None)
            self._fake_llm_running = False

    def form_login(self) -> None:
        """Authenticate through the browser form and retain its session cookie."""

        response = self.call(
            "POST",
            "/login",
            data=urllib.parse.urlencode(
                {"username": "alice", "password": PASSWORD}
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(response.status, 200, response.text)
        self.assertTrue(response.url.endswith("/app"))

    def csrf_from_llm(self) -> str:
        """Read the hidden CSRF token from the experimental screen."""

        response = self.call("GET", "/app/llm")
        self.assertEqual(response.status, 200, response.text)
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
        self.assertIsNotNone(match)
        return html.unescape(match.group(1))

    def ask(
        self, prompt: str, csrf: str | None, *, system: str = "Responde con brevedad."
    ):
        """Submit the public browser form with or without a CSRF token."""

        fields = {"system": system, "prompt": prompt, "max_tokens": "512"}
        if csrf is not None:
            fields["csrf_token"] = csrf
        return self.call(
            "POST",
            "/app/llm",
            data=urllib.parse.urlencode(fields).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )


class EnabledLlmScreenTests(LlmWebServerHarness, unittest.TestCase):
    """Verify authentication, CSRF, escaping, metrics and input boundaries."""

    def test_get_without_session_redirects_to_login_without_llm_form(self) -> None:
        response = self.call("GET", "/app/llm", opener=self.new_client())
        self.assertEqual(response.status, 200)
        self.assertTrue(response.url.endswith("/login"))
        self.assertIn("Iniciar sesión", response.text)
        self.assertNotIn('action="/app/llm"', response.text)
        self.assertEqual(self.fake_llm.request_count, 0)

    def test_enabled_get_shows_bounded_form_csrf_and_reachable_status(self) -> None:
        self.form_login()
        response = self.call("GET", "/app/llm")
        self.assertEqual(response.status, 200, response.text)
        self.assertIn('action="/app/llm"', response.text)
        self.assertIn('name="system"', response.text)
        self.assertIn('name="prompt"', response.text)
        self.assertIn('name="max_tokens"', response.text)
        self.assertIn('max="512"', response.text)
        self.assertIn('name="csrf_token"', response.text)
        self.assertIn("Endpoint disponible", response.text)
        self.assertIn("puede equivocarse", response.text)
        self.assertEqual(self.fake_llm.request_count, 0)

    def test_post_without_csrf_is_403_and_never_calls_the_model(self) -> None:
        self.form_login()
        response = self.ask("No enviar", None)
        self.assertEqual(response.status, 403)
        self.assertIn("csrf_failed", response.text)
        self.assertEqual(self.fake_llm.request_count, 0)

    def test_post_escapes_answer_and_renders_measured_metrics(self) -> None:
        self.form_login()
        csrf = self.csrf_from_llm()
        response = self.ask("Pregunta de prueba", csrf)
        self.assertEqual(response.status, 200, response.text)
        self.assertIn(
            "Respuesta &lt;script&gt;alert(1)&lt;/script&gt; del modelo",
            response.text,
        )
        self.assertNotIn("Respuesta <script>alert(1)</script>", response.text)
        self.assertIn("Tokens", response.text)
        self.assertIn("24", response.text)
        self.assertIn("Latencia", response.text)
        self.assertIn("ms", response.text)
        self.assertIn("71.4", response.text)
        self.assertIn("stop", response.text)
        self.assertEqual(self.fake_llm.request_count, 1)
        self.assertEqual(
            self.fake_llm.last_payload["messages"],
            [
                {"role": "system", "content": "Responde con brevedad."},
                {"role": "user", "content": "Pregunta de prueba"},
            ],
        )

    def test_post_rejects_rendered_prompt_over_budget_with_specific_details(self) -> None:
        secret_prompt = "web-over-budget-prompt-secret-2468ace0"
        self.fake_llm.prompt_tokens = 100_000
        self.form_login()
        csrf = self.csrf_from_llm()
        response = self.ask(secret_prompt, csrf)
        self.assertEqual(response.status, 200, response.text)
        self.assertIn("prompt_too_long", response.text)
        self.assertIn(
            "El mensaje supera el presupuesto de contexto del modelo", response.text
        )
        self.assertNotIn("No se pudo consultar al modelo", response.text)
        self.assertIn(
            "Prompt budget exceeded: 100000 prompt tokens + 512 generation tokens "
            "= 100512, but the context limit is 8192",
            response.text,
        )
        self.assertNotIn('aria-label="Respuesta del modelo"', response.text)
        self.assertEqual(response.text.count(secret_prompt), 1)
        self.assertNotIn("Unicode á € 😀", response.text)
        self.assertEqual(self.fake_llm.request_count, 0)

    def test_post_warns_when_finish_reason_is_length(self) -> None:
        secret_prompt = "web-length-finish-prompt-secret-13ad579c"
        self.fake_llm.finish_reason = "length"
        self.form_login()
        csrf = self.csrf_from_llm()
        response = self.ask(secret_prompt, csrf)
        self.assertEqual(response.status, 200, response.text)
        self.assertIn(
            '<p class="error" role="alert"><strong>Respuesta incompleta:</strong> '
            "la generación alcanzó max_tokens y el texto puede no estar completo.</p>",
            response.text,
        )
        self.assertIn(
            "Respuesta &lt;script&gt;alert(1)&lt;/script&gt; del modelo",
            response.text,
        )
        self.assertNotIn("Respuesta <script>alert(1)</script>", response.text)
        self.assertIn("Motivo de finalización", response.text)
        self.assertIn("length", response.text)
        self.assertIn("Tokens", response.text)
        self.assertIn("24", response.text)
        self.assertEqual(response.text.count(secret_prompt), 1)
        self.assertNotIn("Unicode á € 😀", response.text)
        self.assertEqual(self.fake_llm.request_count, 1)

    def test_empty_and_oversized_prompts_render_errors_without_model_calls(self) -> None:
        self.form_login()
        csrf = self.csrf_from_llm()
        cases = (
            ("", "El mensaje no puede estar vacío"),
            ("x" * 8001, "El mensaje no puede superar los 8000 caracteres"),
        )
        for prompt, message in cases:
            with self.subTest(length=len(prompt)):
                response = self.ask(prompt, csrf)
                self.assertEqual(response.status, 200, response.text)
                self.assertIn(message, response.text)
                self.assertEqual(self.fake_llm.request_count, 0)


class DisabledLlmScreenTests(LlmWebServerHarness, unittest.TestCase):
    """Verify that the default-off screen never performs inference."""

    llm_enabled = False

    def test_disabled_get_explains_state_disables_form_and_makes_no_calls(self) -> None:
        self.form_login()
        response = self.call("GET", "/app/llm")
        self.assertEqual(response.status, 200, response.text)
        self.assertIn("La inferencia está deshabilitada", response.text)
        self.assertIn("ROSE_LLM_ENABLED", response.text)
        self.assertIn('action="/app/llm"', response.text)
        self.assertIn("disabled", response.text)
        self.assertEqual(self.fake_llm.request_count, 0)
        self.assertIsNone(self.fake_llm.last_payload)


class UnavailableLlmScreenTests(LlmWebServerHarness, unittest.TestCase):
    """Isolate an unavailable model from the experimental page and main app."""

    def test_stopped_endpoint_degrades_screen_and_preserves_the_rest_of_the_app(self) -> None:
        self.stop_fake_llm()
        self.form_login()
        response = self.call("GET", "/app/llm")
        self.assertEqual(response.status, 200, response.text)
        self.assertIn("Endpoint no disponible", response.text)
        self.assertIn("inference_unavailable", response.text)

        health = self.call("GET", "/api/health")
        self.assertEqual(health.status, 200, health.text)
        application = self.call("GET", "/app")
        self.assertEqual(application.status, 200, application.text)
        self.assertIn("Experimental: consultar al modelo", application.text)

        csrf = self.csrf_from_llm()
        failed = self.ask("El endpoint está detenido", csrf)
        self.assertEqual(failed.status, 200, failed.text)
        self.assertIn("No se pudo consultar al modelo", failed.text)
        self.assertIn("inference_unavailable", failed.text)
        self.assertEqual(self.call("GET", "/api/health").status, 200)


if __name__ == "__main__":
    unittest.main()
