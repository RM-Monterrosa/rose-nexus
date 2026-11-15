"""Concurrency-limited, content-private inference client.

The concurrency semaphore is per-process. The server must therefore run with a
single uvicorn worker so separate processes cannot each exceed the instance's
inference-slot limit.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from ..core.errors import RoseNexusError
from .context import ContextBudget, ContextEndpoint, ContextPreflight
from .errors import InferenceBusy, InferenceConfigurationError, InferenceUnavailable
from .metrics import InferenceMetrics, MetricsRegistry
from .provider import HealthStatus, LlmProvider, OpenAICompatibleProvider
from .settings import InferenceSettings


@dataclass(frozen=True)
class Answer:
    """Public answer containing only generated text and safe measurements."""

    text: str
    metrics: InferenceMetrics


class InferenceClient:
    """Serialize inference attempts and record exactly one metric per call."""

    def __init__(
        self,
        settings: InferenceSettings,
        provider: LlmProvider | None = None,
        registry: MetricsRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.provider = OpenAICompatibleProvider(settings) if provider is None else provider
        self.registry = MetricsRegistry() if registry is None else registry
        endpoint = (
            self.provider
            if isinstance(self.provider, ContextEndpoint)
            else OpenAICompatibleProvider(settings)
        )
        self.preflight = ContextPreflight(endpoint)
        self.context_budget = ContextBudget(settings.context_tokens)
        self._slots = threading.BoundedSemaphore(settings.max_concurrency)
        self._endpoint_host = urlsplit(settings.endpoint).hostname or ""

    def health(self) -> HealthStatus:
        """Return provider health without performing an inference request."""
        return self.provider.health()

    def ask(self, system: str, user: str) -> Answer:
        """Answer a system/user pair without silently trimming either input."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return self._run(messages, required_inputs=(system, user))

    def ask_messages(self, messages: Sequence[Mapping[str, str]]) -> Answer:
        """Answer an existing message sequence through the same guarded path."""
        return self._run(messages)

    def _run(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        required_inputs: Sequence[str] = (),
    ) -> Answer:
        """Execute one attempt with bounded queuing and content-free telemetry."""
        started = time.monotonic()
        request_id = uuid.uuid4().hex
        acquired = False
        try:
            if not self.settings.enabled:
                raise InferenceUnavailable(
                    "Inference is disabled", code="inference_disabled"
                )
            for value in required_inputs:
                if not isinstance(value, str) or not value.strip():
                    raise InferenceConfigurationError(
                        "system and user inputs must not be empty"
                    )
            measurement = self.preflight.measure(messages)
            self.context_budget.evaluate(
                measurement,
                max_tokens=self.settings.max_tokens,
            )
            acquired = self._slots.acquire(timeout=self.settings.queue_timeout_seconds)
            if not acquired:
                raise InferenceBusy("Inference queue wait timed out")
            completion = self.provider.complete(
                messages,
                max_tokens=self.settings.max_tokens,
                temperature=self.settings.temperature,
                top_p=self.settings.top_p,
                timeout=self.settings.timeout_seconds,
            )
        except Exception as error:
            error_code = error.code if isinstance(error, RoseNexusError) else "internal_error"
            self.registry.record(
                self._metrics(
                    request_id=request_id,
                    started=started,
                    status="error",
                    error_code=error_code,
                )
            )
            raise
        finally:
            if acquired:
                self._slots.release()
        metrics = self._metrics(
            request_id=request_id,
            started=started,
            status="ok",
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            total_tokens=completion.total_tokens,
            tokens_per_second=completion.predicted_tokens_per_second,
            finish_reason=completion.finish_reason,
        )
        self.registry.record(metrics)
        return Answer(text=completion.text, metrics=metrics)

    def _metrics(
        self,
        *,
        request_id: str,
        started: float,
        status: str,
        error_code: str | None = None,
        prompt_tokens: int | None = 0,
        completion_tokens: int | None = 0,
        total_tokens: int | None = 0,
        tokens_per_second: float | None = None,
        finish_reason: str | None = None,
    ) -> InferenceMetrics:
        """Build a measurement without retaining any message text."""
        latency_ms = (time.monotonic() - started) * 1000
        if (
            status == "ok"
            and tokens_per_second is None
            and completion_tokens is not None
            and completion_tokens > 0
            and latency_ms > 0
        ):
            tokens_per_second = completion_tokens * 1000 / latency_ms
        return InferenceMetrics(
            request_id=request_id,
            model=self.settings.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            tokens_per_second=tokens_per_second,
            finish_reason=finish_reason,
            status=status,
            error_code=error_code,
            endpoint_host=self._endpoint_host,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
