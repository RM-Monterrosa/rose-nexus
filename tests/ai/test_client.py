"""Behavior tests for the concurrency-limited inference client."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import unittest
import uuid

from rose_nexus.ai.client import InferenceClient
from rose_nexus.ai.errors import (
    InferenceBusy,
    InferenceConfigurationError,
    InferenceHTTPError,
    InferenceUnavailable,
)
from rose_nexus.ai.metrics import MetricsRegistry
from rose_nexus.ai.settings import InferenceSettings
from tests.ai.fake_server import FakeLlmServer


class InferenceClientTests(unittest.TestCase):
    """Verify answers, failure metrics and the single-instance queue."""

    def setUp(self) -> None:
        self.secret = f"SECRETPROMPT-{uuid.uuid4()}"

    def settings(self, server: FakeLlmServer, **overrides: object) -> InferenceSettings:
        values: dict[str, object] = {
            "endpoint": server.endpoint,
            "enabled": True,
            "timeout_seconds": 2,
            "queue_timeout_seconds": 2,
        }
        values.update(overrides)
        return InferenceSettings(**values)  # type: ignore[arg-type]

    def test_successful_ask_returns_only_text_and_complete_metrics(self) -> None:
        with FakeLlmServer() as server:
            registry = MetricsRegistry()
            client = InferenceClient(self.settings(server), registry=registry)
            answer = client.ask("Answer briefly.", self.secret)
            self.assertEqual(answer.text, "A measured answer.")
            self.assertEqual(
                tuple(field.name for field in dataclasses.fields(answer)),
                ("text", "metrics"),
            )
            metrics = answer.metrics
            self.assertEqual(metrics.status, "ok")
            self.assertIsNone(metrics.error_code)
            self.assertEqual(metrics.prompt_tokens, 22)
            self.assertEqual(metrics.completion_tokens, 2)
            self.assertEqual(metrics.total_tokens, 24)
            self.assertEqual(metrics.tokens_per_second, 71.4)
            self.assertEqual(metrics.finish_reason, "stop")
            self.assertEqual(metrics.endpoint_host, "127.0.0.1")
            self.assertTrue(metrics.request_id)
            self.assertTrue(metrics.created_at.endswith("+00:00"))
            self.assertGreaterEqual(metrics.latency_ms, 0)
            self.assertEqual(registry.snapshot(), (metrics,))
            self.assertIsNone(registry.last_error())
            self.assertNotIn(self.secret, metrics.as_log())

    def test_failure_records_one_error_metric_and_reraises_without_retry(self) -> None:
        with FakeLlmServer(behavior="http_500", error_body=self.secret) as server:
            registry = MetricsRegistry()
            client = InferenceClient(self.settings(server), registry=registry)
            with self.assertRaises(InferenceHTTPError) as caught:
                client.ask("Answer briefly.", self.secret)
            self.assertNotIn(self.secret, str(caught.exception))
            snapshot = registry.snapshot()
            self.assertEqual(len(snapshot), 1)
            self.assertEqual(snapshot[0].status, "error")
            self.assertEqual(snapshot[0].error_code, "inference_http_error")
            self.assertEqual(snapshot[0].prompt_tokens, 0)
            self.assertEqual(snapshot[0].completion_tokens, 0)
            self.assertEqual(registry.last_error(), snapshot[0])
            self.assertNotIn(self.secret, snapshot[0].as_log())
            self.assertEqual(server.request_count, 1)

    def test_disabled_client_raises_inference_disabled_and_records_error(self) -> None:
        registry = MetricsRegistry()
        client = InferenceClient(InferenceSettings(), registry=registry)
        with self.assertRaises(InferenceUnavailable) as caught:
            client.ask("Answer briefly.", self.secret)
        self.assertEqual(caught.exception.code, "inference_disabled")
        self.assertEqual(caught.exception.exit_code, 4)
        self.assertNotIn(self.secret, str(caught.exception))
        self.assertEqual(len(registry.snapshot()), 1)
        self.assertEqual(registry.snapshot()[0].error_code, "inference_disabled")

    def test_empty_system_or_user_is_rejected_without_calling_provider(self) -> None:
        for system, user in (("", self.secret), ("Answer briefly.", ""), ("   ", self.secret)):
            with self.subTest(system=system, user=user):
                registry = MetricsRegistry()
                client = InferenceClient(
                    InferenceSettings(enabled=True),
                    provider=object(),  # type: ignore[arg-type]
                    registry=registry,
                )
                with self.assertRaises(InferenceConfigurationError) as caught:
                    client.ask(system, user)
                self.assertNotIn(self.secret, str(caught.exception))
                self.assertEqual(len(registry.snapshot()), 1)
                self.assertEqual(
                    registry.snapshot()[0].error_code, "inference_configuration_invalid"
                )

    def test_concurrency_one_serializes_parallel_asks(self) -> None:
        with FakeLlmServer(delay_seconds=0.2) as server:
            registry = MetricsRegistry()
            client = InferenceClient(self.settings(server), registry=registry)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(client.ask, "Answer briefly.", f"{self.secret}-{index}")
                    for index in range(2)
                ]
                answers = [future.result(timeout=3) for future in futures]
            self.assertEqual([answer.text for answer in answers], ["A measured answer."] * 2)
            self.assertEqual(server.max_simultaneous, 1)
            self.assertEqual(server.request_count, 2)
            self.assertEqual(len(registry.snapshot()), 2)
            self.assertNotIn(self.secret, "".join(metric.as_log() for metric in registry.snapshot()))

    def test_full_queue_with_tiny_timeout_raises_busy(self) -> None:
        with FakeLlmServer(delay_seconds=0.4) as server:
            registry = MetricsRegistry()
            client = InferenceClient(
                self.settings(server, queue_timeout_seconds=0.02), registry=registry
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                first = executor.submit(client.ask, "Answer briefly.", self.secret)
                self.assertTrue(server.request_started.wait(timeout=1))
                with self.assertRaises(InferenceBusy) as caught:
                    client.ask("Answer briefly.", self.secret)
                self.assertEqual(caught.exception.code, "inference_busy")
                self.assertNotIn(self.secret, str(caught.exception))
                self.assertEqual(first.result(timeout=3).text, "A measured answer.")
            snapshot = registry.snapshot()
            self.assertEqual(len(snapshot), 2)
            self.assertEqual(
                sorted(metric.status for metric in snapshot), ["error", "ok"]
            )
            self.assertIsNotNone(registry.last_error())
            self.assertEqual(registry.last_error().error_code, "inference_busy")  # type: ignore[union-attr]
            self.assertEqual(server.max_simultaneous, 1)

    def test_ask_messages_uses_the_same_public_answer_contract(self) -> None:
        with FakeLlmServer() as server:
            client = InferenceClient(self.settings(server))
            answer = client.ask_messages(
                [
                    {"role": "system", "content": "Answer briefly."},
                    {"role": "user", "content": self.secret},
                ]
            )
            self.assertEqual(answer.text, "A measured answer.")
            self.assertEqual(answer.metrics.total_tokens, 24)

    def test_health_delegates_to_the_provider(self) -> None:
        with FakeLlmServer() as server:
            health = InferenceClient(self.settings(server)).health()
            self.assertTrue(health.available)
            self.assertTrue(health.model_present)

    def test_absent_usage_and_timings_stay_null_in_metrics(self) -> None:
        with FakeLlmServer(behavior="no_usage_no_timings") as server:
            answer = InferenceClient(self.settings(server)).ask(
                "Answer briefly.", self.secret
            )
            metrics = answer.metrics
            self.assertEqual(metrics.status, "ok")
            self.assertIsNone(metrics.prompt_tokens)
            self.assertIsNone(metrics.completion_tokens)
            self.assertIsNone(metrics.total_tokens)
            self.assertIsNone(metrics.tokens_per_second)
            logged = json.loads(metrics.as_log())
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "tokens_per_second",
            ):
                self.assertIn(key, logged)
                self.assertIsNone(logged[key])
            self.assertNotIn(self.secret, metrics.as_log())

    def test_missing_reported_speed_is_derived_when_tokens_and_latency_allow(self) -> None:
        with FakeLlmServer(behavior="timings_without_speed") as server:
            answer = InferenceClient(self.settings(server)).ask(
                "Answer briefly.", self.secret
            )
            self.assertEqual(answer.metrics.completion_tokens, 2)
            self.assertIsNotNone(answer.metrics.tokens_per_second)
            self.assertGreater(answer.metrics.tokens_per_second or 0, 0)

    def test_client_rejects_cross_port_redirect_without_hitting_target(self) -> None:
        with FakeLlmServer() as target:
            with FakeLlmServer(
                behavior="redirect", redirect_endpoint=target.endpoint
            ) as source:
                registry = MetricsRegistry()
                client = InferenceClient(self.settings(source), registry=registry)
                with self.assertRaises(InferenceHTTPError) as caught:
                    client.ask("Answer briefly.", self.secret)
                self.assertEqual(caught.exception.status, 302)
                self.assertEqual(source.request_count, 1)
                self.assertEqual(target.request_count, 0)
                self.assertEqual(len(registry.snapshot()), 1)
                self.assertEqual(registry.snapshot()[0].status, "error")


if __name__ == "__main__":
    unittest.main()
