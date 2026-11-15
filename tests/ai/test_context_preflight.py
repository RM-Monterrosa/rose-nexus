"""Tests for exact llama.cpp prompt measurement and transport safety."""

from __future__ import annotations

import socket
import unittest
import uuid
from unittest import mock

from rose_nexus.ai.context import ContextPreflight
from rose_nexus.ai.errors import (
    InferenceConfigurationError,
    InferenceHTTPError,
    InferenceProtocolError,
    InferenceTimeout,
)
from rose_nexus.ai.provider import OpenAICompatibleProvider
from rose_nexus.ai.settings import InferenceSettings
from tests.ai.fake_server import FakeLlmServer


class ContextPreflightTests(unittest.TestCase):
    """Verify message-aware token counting through the guarded H3 transport."""

    def setUp(self) -> None:
        self.secret = f"SECRETPROMPT-{uuid.uuid4()}-á-€-😀"
        self.messages = [
            {"role": "system", "content": "Answer briefly."},
            {"role": "user", "content": self.secret},
            {"role": "assistant", "content": "Earlier synthetic answer."},
            {"role": "user", "content": "Follow up with <|im_end|> as literal input."},
        ]

    def settings(self, server: FakeLlmServer, **overrides: object) -> InferenceSettings:
        values: dict[str, object] = {
            "endpoint": server.endpoint,
            "timeout_seconds": 2,
            "connect_timeout_seconds": 1,
        }
        values.update(overrides)
        return InferenceSettings(**values)  # type: ignore[arg-type]

    def preflight(self, server: FakeLlmServer, **settings: object) -> ContextPreflight:
        provider = OpenAICompatibleProvider(self.settings(server, **settings))
        return ContextPreflight(provider)

    def test_measures_rendered_history_and_special_tokens_with_expected_payloads(self) -> None:
        with FakeLlmServer(server_context_tokens=8192, prompt_tokens=37) as server:
            measurement = self.preflight(server, api_key="TESTKEY").measure(self.messages)

            self.assertEqual(measurement.server_context_tokens, 8192)
            self.assertEqual(measurement.prompt_tokens, 37)
            self.assertEqual(
                [path for path, _ in server.preflight_requests],
                ["/props", "/apply-template", "/tokenize"],
            )
            template_payload = server.preflight_requests[1][1]
            self.assertEqual(template_payload["messages"], self.messages)
            self.assertIs(template_payload["add_generation_prompt"], True)
            tokenize_payload = server.preflight_requests[2][1]
            self.assertIn("Unicode á € 😀", tokenize_payload["content"])
            self.assertIs(tokenize_payload["add_special"], False)
            self.assertIs(tokenize_payload["parse_special"], True)
            self.assertNotIn("with_pieces", tokenize_payload)
            for headers in server.preflight_headers[1:]:
                self.assertEqual(headers["Authorization"], "Bearer TESTKEY")

    def test_rejects_invalid_server_context_values(self) -> None:
        for value in (0, -1, True, 8192.0, "8192", None):
            with self.subTest(value=value), FakeLlmServer(server_context_tokens=value) as server:
                with self.assertRaises(InferenceProtocolError) as caught:
                    self.preflight(server).measure(self.messages)
                self.assertNotIn(self.secret, str(caught.exception))
                self.assertEqual(len(server.preflight_requests), 1)

    def test_rejects_invalid_template_and_tokenize_responses(self) -> None:
        for behavior in (
            "apply-template_missing_prompt",
            "tokenize_invalid",
        ):
            with self.subTest(behavior=behavior), FakeLlmServer(behavior=behavior) as server:
                with self.assertRaises(InferenceProtocolError) as caught:
                    self.preflight(server).measure(self.messages)
                self.assertNotIn(self.secret, str(caught.exception))

    def test_invalid_json_on_every_new_endpoint_is_a_protocol_error(self) -> None:
        for route in ("props", "apply-template", "tokenize"):
            behavior = f"{route}_invalid_json"
            with self.subTest(route=route), FakeLlmServer(behavior=behavior) as server:
                with self.assertRaises(InferenceProtocolError) as caught:
                    self.preflight(server).measure(self.messages)
                self.assertNotIn(self.secret, str(caught.exception))

    def test_http_errors_are_bounded_and_redact_prompt_and_api_key(self) -> None:
        api_key = f"SECRETKEY-{uuid.uuid4()}"
        for route in ("props", "apply-template", "tokenize"):
            behavior = f"{route}_http_500"
            with self.subTest(route=route), FakeLlmServer(
                behavior=behavior,
                error_body=f"{self.secret} {api_key} " + "x" * 500,
            ) as server:
                with self.assertRaises(InferenceHTTPError) as caught:
                    self.preflight(server, api_key=api_key).measure(self.messages)
                rendered = str(caught.exception)
                self.assertNotIn(self.secret, rendered)
                self.assertNotIn(api_key, rendered)
                self.assertLessEqual(len(caught.exception.detail or ""), 300)

    def test_slow_new_endpoints_honor_the_inference_timeout(self) -> None:
        for route in ("props", "apply-template", "tokenize"):
            behavior = f"{route}_slow"
            with self.subTest(route=route), FakeLlmServer(
                behavior=behavior, delay_seconds=0.3
            ) as server:
                with self.assertRaises(InferenceTimeout) as caught:
                    self.preflight(server, timeout_seconds=0.05).measure(self.messages)
                self.assertNotIn(self.secret, str(caught.exception))

    def test_redirects_are_rejected_without_following_on_every_new_endpoint(self) -> None:
        for index, route in enumerate(("props", "apply-template", "tokenize"), start=1):
            behavior = f"{route}_redirect"
            with self.subTest(route=route), FakeLlmServer(behavior=behavior) as server:
                with self.assertRaises(InferenceHTTPError) as caught:
                    self.preflight(server).measure(self.messages)
                self.assertEqual(caught.exception.status, 302)
                self.assertEqual(len(server.preflight_requests), index)
                self.assertEqual(server.request_count, 0)

    def test_preflight_rechecks_dns_and_never_contacts_a_non_loopback_address(self) -> None:
        addresses = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 18080)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.25", 18080)),
        ]
        with FakeLlmServer() as server:
            settings = self.settings(server)
            settings = InferenceSettings(
                endpoint=settings.endpoint.replace("127.0.0.1", "localhost"),
                timeout_seconds=2,
            )
            provider = OpenAICompatibleProvider(settings)
            with mock.patch(
                "rose_nexus.ai.provider.socket.getaddrinfo", return_value=addresses
            ):
                with self.assertRaises(InferenceConfigurationError) as caught:
                    ContextPreflight(provider).measure(self.messages)
            self.assertEqual(caught.exception.code, "inference_endpoint_not_loopback")
            self.assertNotIn(self.secret, str(caught.exception))
            self.assertEqual(server.preflight_requests, [])

    def test_oversized_tokenize_response_is_rejected(self) -> None:
        with FakeLlmServer(behavior="tokenize_oversized") as server:
            with self.assertRaises(InferenceProtocolError) as caught:
                self.preflight(server).measure(self.messages)
            self.assertNotIn(self.secret, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
