"""Configuration and error-contract tests for inference."""

from __future__ import annotations

import dataclasses
import json
import unittest
import uuid

from rose_nexus.ai.errors import (
    InferenceBusy,
    InferenceConfigurationError,
    InferenceHTTPError,
    InferenceProtocolError,
    InferenceTimeout,
    InferenceUnavailable,
)
from rose_nexus.ai.settings import InferenceSettings


class InferenceSettingsTests(unittest.TestCase):
    """Verify safe defaults, environment parsing and validation."""

    def setUp(self) -> None:
        self.secret = f"SECRETPROMPT-{uuid.uuid4()}"

    def test_defaults(self) -> None:
        settings = InferenceSettings()
        self.assertEqual(settings.endpoint, "http://127.0.0.1:18080/v1")
        self.assertEqual(settings.model, "rose-spark-4b")
        self.assertEqual(settings.timeout_seconds, 60)
        self.assertEqual(settings.connect_timeout_seconds, 5)
        self.assertEqual(settings.max_tokens, 512)
        self.assertEqual(settings.temperature, 0.2)
        self.assertEqual(settings.top_p, 0.95)
        self.assertEqual(settings.context_tokens, 8192)
        self.assertEqual(settings.max_concurrency, 1)
        self.assertEqual(settings.queue_timeout_seconds, 30)
        self.assertIsNone(settings.api_key)
        self.assertFalse(settings.enabled)
        self.assertFalse(settings.allow_remote_endpoint)

    def test_every_environment_override_is_honored(self) -> None:
        settings = InferenceSettings.from_env(
            {
                "ROSE_LLM_ENDPOINT": "https://models.example.test/custom/v1",
                "ROSE_LLM_MODEL": "another-model",
                "ROSE_LLM_TIMEOUT_SECONDS": "12.5",
                "ROSE_LLM_CONNECT_TIMEOUT_SECONDS": "2.5",
                "ROSE_LLM_MAX_TOKENS": "256",
                "ROSE_LLM_TEMPERATURE": "1.25",
                "ROSE_LLM_TOP_P": "0.75",
                "ROSE_LLM_CONTEXT_TOKENS": "4096",
                "ROSE_LLM_MAX_CONCURRENCY": "2",
                "ROSE_LLM_QUEUE_TIMEOUT_SECONDS": "4.5",
                "ROSE_LLM_API_KEY": self.secret,
                "ROSE_LLM_ENABLED": "true",
                "ROSE_LLM_ALLOW_REMOTE_ENDPOINT": "yes",
            }
        )
        self.assertEqual(settings.endpoint, "https://models.example.test/custom/v1")
        self.assertEqual(settings.model, "another-model")
        self.assertEqual(settings.timeout_seconds, 12.5)
        self.assertEqual(settings.connect_timeout_seconds, 2.5)
        self.assertEqual(settings.max_tokens, 256)
        self.assertEqual(settings.temperature, 1.25)
        self.assertEqual(settings.top_p, 0.75)
        self.assertEqual(settings.context_tokens, 4096)
        self.assertEqual(settings.max_concurrency, 2)
        self.assertEqual(settings.queue_timeout_seconds, 4.5)
        self.assertEqual(settings.api_key, self.secret)
        self.assertTrue(settings.enabled)
        self.assertTrue(settings.allow_remote_endpoint)

    def test_invalid_numeric_environment_values_are_rejected(self) -> None:
        invalid_values = {
            "ROSE_LLM_TIMEOUT_SECONDS": "-1",
            "ROSE_LLM_CONNECT_TIMEOUT_SECONDS": "0",
            "ROSE_LLM_MAX_TOKENS": "0",
            "ROSE_LLM_TEMPERATURE": "2.1",
            "ROSE_LLM_TOP_P": "-0.1",
            "ROSE_LLM_CONTEXT_TOKENS": "-8",
            "ROSE_LLM_MAX_CONCURRENCY": "0",
            "ROSE_LLM_QUEUE_TIMEOUT_SECONDS": "-2",
        }
        for key, value in invalid_values.items():
            with self.subTest(key=key, value=value):
                with self.assertRaises(InferenceConfigurationError) as caught:
                    InferenceSettings.from_env({key: value})
                self.assertEqual(caught.exception.code, "inference_configuration_invalid")
                self.assertEqual(caught.exception.exit_code, 2)

    def test_direct_temperature_and_top_p_bounds_are_validated(self) -> None:
        for overrides in (
            {"temperature": -0.01},
            {"temperature": 2.01},
            {"top_p": -0.01},
            {"top_p": 1.01},
            {"timeout_seconds": -1},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(InferenceConfigurationError):
                    InferenceSettings(**overrides)
        self.assertEqual(InferenceSettings(temperature=0, top_p=0).temperature, 0)
        self.assertEqual(InferenceSettings(temperature=2, top_p=1).top_p, 1)

    def test_remote_endpoint_requires_explicit_opt_in(self) -> None:
        remote = "http://models.example.test/v1"
        with self.assertRaises(InferenceConfigurationError):
            InferenceSettings(endpoint=remote)
        with self.assertRaises(InferenceConfigurationError):
            InferenceSettings.from_env({"ROSE_LLM_ENDPOINT": remote})
        settings = InferenceSettings.from_env(
            {
                "ROSE_LLM_ENDPOINT": remote,
                "ROSE_LLM_ALLOW_REMOTE_ENDPOINT": "true",
            }
        )
        self.assertEqual(settings.endpoint, remote)

    def test_endpoint_requires_http_scheme_and_host(self) -> None:
        for endpoint in ("file:///tmp/model", "http:///v1", "not a URL"):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(InferenceConfigurationError):
                    InferenceSettings(endpoint=endpoint)

    def test_redacted_never_exposes_key_or_url_path(self) -> None:
        settings = InferenceSettings(
            endpoint="http://127.0.0.1:18080/private/path",
            api_key=self.secret,
            enabled=True,
        )
        redacted = settings.redacted()
        serialized = json.dumps(redacted)
        self.assertNotIn(self.secret, serialized)
        self.assertNotIn("/private/path", serialized)
        self.assertNotIn("api_key", redacted)
        self.assertNotIn("endpoint", redacted)
        self.assertEqual(redacted["endpoint_host"], "127.0.0.1")

    def test_settings_are_frozen(self) -> None:
        with self.assertRaises(dataclasses.FrozenInstanceError):
            InferenceSettings().model = "changed"  # type: ignore[misc]

    def test_error_codes_and_exit_codes_are_stable(self) -> None:
        cases = (
            (InferenceUnavailable("x"), "inference_unavailable", 4),
            (InferenceTimeout("x"), "inference_timeout", 4),
            (InferenceProtocolError("x"), "inference_protocol_error", 5),
            (InferenceBusy("x"), "inference_busy", 4),
            (InferenceConfigurationError("x"), "inference_configuration_invalid", 2),
        )
        for error, code, exit_code in cases:
            with self.subTest(code=code):
                self.assertEqual(error.code, code)
                self.assertEqual(error.exit_code, exit_code)
        http_error = InferenceHTTPError("x", status=503)
        self.assertEqual(http_error.code, "inference_http_error")
        self.assertEqual(http_error.exit_code, 5)
        self.assertEqual(http_error.status, 503)

    def test_endpoint_userinfo_is_rejected(self) -> None:
        for endpoint in (
            "http://user:password@127.0.0.1:18080/v1",
            "https://user@localhost:18080/v1",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(InferenceConfigurationError) as caught:
                    InferenceSettings(endpoint=endpoint)
                self.assertEqual(caught.exception.code, "inference_configuration_invalid")


if __name__ == "__main__":
    unittest.main()
