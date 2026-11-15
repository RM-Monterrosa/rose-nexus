"""Tests for content-free inference telemetry."""

from __future__ import annotations

import json
import unittest
import uuid

from rose_nexus.ai.metrics import InferenceMetrics, MetricsRegistry


class InferenceMetricsTests(unittest.TestCase):
    """Verify structured single-line logs and bounded history."""

    def metric(
        self,
        request_id: str,
        *,
        status: str = "ok",
        error_code: str | None = None,
    ) -> InferenceMetrics:
        return InferenceMetrics(
            request_id=request_id,
            model="rose-spark-4b",
            prompt_tokens=22,
            completion_tokens=2,
            total_tokens=24,
            latency_ms=125.5,
            tokens_per_second=71.4 if status == "ok" else None,
            finish_reason="stop" if status == "ok" else None,
            status=status,
            error_code=error_code,
            endpoint_host="127.0.0.1",
            created_at="2026-11-15T12:00:00+00:00",
        )

    def test_as_log_is_sorted_single_line_json_without_message_text(self) -> None:
        secret = f"SECRETPROMPT-{uuid.uuid4()}"
        metrics = self.metric("request-1")
        log = metrics.as_log()
        self.assertNotIn("\n", log)
        self.assertNotIn("\r", log)
        self.assertNotIn(secret, log)
        self.assertNotIn("Answer briefly.", log)
        pairs = json.loads(log, object_pairs_hook=list)
        keys = [key for key, _ in pairs]
        self.assertEqual(keys, sorted(keys))
        self.assertNotIn("message", keys)
        self.assertNotIn("messages", keys)
        self.assertNotIn("prompt", keys)
        self.assertNotIn("content", keys)
        self.assertNotIn("text", keys)

    def test_registry_is_bounded_and_snapshots_are_tuples(self) -> None:
        registry = MetricsRegistry(max_entries=2)
        first = self.metric("first")
        second = self.metric("second")
        third = self.metric("third")
        registry.record(first)
        registry.record(second)
        registry.record(third)
        snapshot = registry.snapshot()
        self.assertIsInstance(snapshot, tuple)
        self.assertEqual(snapshot, (second, third))

    def test_last_error_skips_newer_successful_entries(self) -> None:
        registry = MetricsRegistry()
        registry.record(self.metric("first"))
        error = self.metric("error", status="error", error_code="inference_timeout")
        registry.record(error)
        registry.record(self.metric("last"))
        self.assertEqual(registry.last_error(), error)

    def test_last_error_is_none_without_failures(self) -> None:
        registry = MetricsRegistry()
        self.assertIsNone(registry.last_error())
        registry.record(self.metric("ok"))
        self.assertIsNone(registry.last_error())


if __name__ == "__main__":
    unittest.main()
