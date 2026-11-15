"""Bounded inference telemetry that never stores message content."""

from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class InferenceMetrics:
    """Measurements for exactly one inference attempt."""

    request_id: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: float
    tokens_per_second: float | None
    finish_reason: str | None
    status: str
    error_code: str | None
    endpoint_host: str
    created_at: str

    def as_log(self) -> str:
        """Serialize one deterministic, single-line JSON log record."""
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )


class MetricsRegistry:
    """Keep a thread-safe, bounded history of inference measurements."""

    def __init__(self, max_entries: int = 100) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._entries: deque[InferenceMetrics] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def record(self, metrics: InferenceMetrics) -> None:
        """Append one measurement, evicting the oldest when full."""
        with self._lock:
            self._entries.append(metrics)

    def snapshot(self) -> tuple[InferenceMetrics, ...]:
        """Return an immutable oldest-to-newest view of retained metrics."""
        with self._lock:
            return tuple(self._entries)

    def last_error(self) -> InferenceMetrics | None:
        """Return the most recent failed attempt, if one is retained."""
        with self._lock:
            return next(
                (metrics for metrics in reversed(self._entries) if metrics.status == "error"),
                None,
            )
