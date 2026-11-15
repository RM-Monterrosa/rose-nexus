"""HTTP transport tests using only loopback fake servers."""

from __future__ import annotations

import socket
import unittest
import uuid
from unittest import mock

from rose_nexus.ai.errors import (
    InferenceConfigurationError,
    InferenceHTTPError,
    InferenceProtocolError,
    InferenceTimeout,
    InferenceUnavailable,
)
from rose_nexus.ai.provider import LlmProvider, OpenAICompatibleProvider
from rose_nexus.ai.settings import InferenceSettings
from tests.ai.fake_server import FakeLlmServer


class OpenAICompatibleProviderTests(unittest.TestCase):
    """Verify strict response validation and safe transport failures."""

    def setUp(self) -> None:
        self.secret = f"SECRETPROMPT-{uuid.uuid4()}"
        self.messages = [
            {"role": "system", "content": "Answer briefly."},
            {"role": "user", "content": self.secret},
        ]

    def settings(self, server: FakeLlmServer, **overrides: object) -> InferenceSettings:
        values: dict[str, object] = {
            "endpoint": server.endpoint,
            "timeout_seconds": 2,
            "connect_timeout_seconds": 1,
        }
        values.update(overrides)
        return InferenceSettings(**values)  # type: ignore[arg-type]

    def test_success_parses_usage_and_sends_expected_request(self) -> None:
        with FakeLlmServer() as server:
            provider = OpenAICompatibleProvider(self.settings(server, api_key=self.secret))
            self.assertIsInstance(provider, LlmProvider)
            completion = provider.complete(
                self.messages, max_tokens=99, temperature=0.4, top_p=0.8
            )
            self.assertEqual(completion.text, "A measured answer.")
            self.assertEqual(completion.prompt_tokens, 22)
            self.assertEqual(completion.completion_tokens, 2)
            self.assertEqual(completion.total_tokens, 24)
            self.assertEqual(completion.finish_reason, "stop")
            self.assertEqual(completion.predicted_tokens_per_second, 71.4)
            self.assertEqual(server.last_payload["model"], "rose-spark-4b")
            self.assertEqual(server.last_payload["messages"], self.messages)
            self.assertEqual(server.last_payload["max_tokens"], 99)
            self.assertEqual(server.last_payload["temperature"], 0.4)
            self.assertEqual(server.last_payload["top_p"], 0.8)
            self.assertFalse(server.last_payload["stream"])
            self.assertEqual(server.last_headers["Content-Type"], "application/json")
            self.assertEqual(server.last_headers["Authorization"], f"Bearer {self.secret}")

    def test_health_accepts_openai_and_llama_shapes(self) -> None:
        for shape in ("openai", "llama"):
            with self.subTest(shape=shape), FakeLlmServer(health_shape=shape) as server:
                health = OpenAICompatibleProvider(self.settings(server)).health()
                self.assertTrue(health.available)
                self.assertTrue(health.model_present)
                self.assertEqual(health.models, ("rose-spark-4b",))
                self.assertGreaterEqual(health.latency_ms, 0)

    def test_health_reports_an_absent_configured_model(self) -> None:
        with FakeLlmServer(health_shape="missing_model") as server:
            health = OpenAICompatibleProvider(self.settings(server)).health()
            self.assertTrue(health.available)
            self.assertFalse(health.model_present)
            self.assertEqual(health.models, ("another-model",))

    def test_http_500_has_status_bounded_detail_and_no_prompt(self) -> None:
        with FakeLlmServer(
            behavior="http_500", error_body=f"failure {self.secret} " + "x" * 500
        ) as server:
            provider = OpenAICompatibleProvider(self.settings(server))
            with self.assertRaises(InferenceHTTPError) as caught:
                provider.complete(self.messages)
            error = caught.exception
            self.assertEqual(error.status, 500)
            self.assertIsNotNone(error.detail)
            self.assertLessEqual(len(error.detail or ""), 300)
            self.assertEqual(len(error.detail or ""), 300)
            self.assertNotIn(self.secret, str(error))
            self.assertNotIn(self.secret, error.detail or "")

    def test_invalid_json_is_a_protocol_error(self) -> None:
        with FakeLlmServer(behavior="invalid_json") as server:
            with self.assertRaises(InferenceProtocolError) as caught:
                OpenAICompatibleProvider(self.settings(server)).complete(self.messages)
            self.assertNotIn(self.secret, str(caught.exception))

    def test_missing_choices_is_a_protocol_error(self) -> None:
        with FakeLlmServer(behavior="missing_choices") as server:
            with self.assertRaises(InferenceProtocolError):
                OpenAICompatibleProvider(self.settings(server)).complete(self.messages)

    def test_non_string_content_is_a_protocol_error(self) -> None:
        with FakeLlmServer(behavior="non_string_content") as server:
            with self.assertRaises(InferenceProtocolError):
                OpenAICompatibleProvider(self.settings(server)).complete(self.messages)

    def test_oversized_body_is_a_protocol_error(self) -> None:
        with FakeLlmServer(behavior="oversized") as server:
            with self.assertRaises(InferenceProtocolError) as caught:
                OpenAICompatibleProvider(self.settings(server)).complete(self.messages)
            self.assertNotIn(self.secret, str(caught.exception))

    def test_connection_refused_is_unavailable(self) -> None:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        settings = InferenceSettings(
            endpoint=f"http://127.0.0.1:{port}/v1",
            timeout_seconds=0.2,
        )
        with self.assertRaises(InferenceUnavailable) as caught:
            OpenAICompatibleProvider(settings).complete(self.messages)
        self.assertNotIn(self.secret, str(caught.exception))

    def test_slow_server_honors_explicit_timeout(self) -> None:
        with FakeLlmServer(behavior="slow", delay_seconds=1.2) as server:
            provider = OpenAICompatibleProvider(self.settings(server))
            with self.assertRaises(InferenceTimeout) as caught:
                provider.complete(self.messages, timeout=1)
            self.assertNotIn(self.secret, str(caught.exception))

    def test_redirect_is_rejected_and_not_followed(self) -> None:
        with FakeLlmServer(behavior="redirect") as server:
            provider = OpenAICompatibleProvider(self.settings(server))
            with self.assertRaises(InferenceHTTPError) as caught:
                provider.complete(self.messages)
            self.assertEqual(caught.exception.status, 302)
            self.assertEqual(server.request_count, 1)

    def test_every_resolved_address_must_be_loopback_at_call_time(self) -> None:
        addresses = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 18080)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.25", 18080)),
        ]
        for operation in ("health", "complete"):
            with self.subTest(operation=operation), FakeLlmServer() as server:
                settings = self.settings(server)
                settings = InferenceSettings(
                    endpoint=settings.endpoint.replace("127.0.0.1", "localhost"),
                    timeout_seconds=2,
                )
                provider = OpenAICompatibleProvider(settings)
                with mock.patch(
                    "rose_nexus.ai.provider.socket.getaddrinfo", return_value=addresses
                ) as resolver:
                    with self.assertRaises(InferenceConfigurationError) as caught:
                        if operation == "health":
                            provider.health()
                        else:
                            provider.complete(self.messages)
                self.assertEqual(caught.exception.code, "inference_endpoint_not_loopback")
                self.assertNotIn(self.secret, str(caught.exception))
                resolver.assert_called()
                self.assertEqual(server.request_count, 0)

    def test_completion_without_usage_uses_none_token_counts(self) -> None:
        with FakeLlmServer(behavior="no_usage") as server:
            completion = OpenAICompatibleProvider(self.settings(server)).complete(
                self.messages
            )
            self.assertIsNone(completion.prompt_tokens)
            self.assertIsNone(completion.completion_tokens)
            self.assertIsNone(completion.total_tokens)
            self.assertEqual(completion.predicted_tokens_per_second, 71.4)

    def test_usage_without_total_tokens_keeps_total_none(self) -> None:
        with FakeLlmServer(behavior="usage_without_total") as server:
            completion = OpenAICompatibleProvider(self.settings(server)).complete(
                self.messages
            )
            self.assertEqual(completion.prompt_tokens, 22)
            self.assertEqual(completion.completion_tokens, 2)
            self.assertIsNone(completion.total_tokens)

    def test_timings_without_predicted_speed_leaves_speed_unreported(self) -> None:
        with FakeLlmServer(behavior="timings_without_speed") as server:
            completion = OpenAICompatibleProvider(self.settings(server)).complete(
                self.messages
            )
            self.assertEqual(completion.completion_tokens, 2)
            self.assertIsNone(completion.predicted_tokens_per_second)


if __name__ == "__main__":
    unittest.main()
