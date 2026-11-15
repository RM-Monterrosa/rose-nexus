"""Exact, content-private context measurement for llama.cpp inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence, runtime_checkable

from .errors import InferenceConfigurationError, InferencePromptTooLong, InferenceProtocolError


@dataclass(frozen=True)
class ContextMeasurement:
    """Numeric-only measurements of a fully rendered chat prompt."""

    server_context_tokens: int
    prompt_tokens: int


@runtime_checkable
class ContextEndpoint(Protocol):
    """Transport boundary required by the context preflight."""

    def measure_context(
        self, messages: Sequence[Mapping[str, str]]
    ) -> ContextMeasurement:
        """Measure messages using the server's model and chat template."""
        ...


class ContextPreflight:
    """Measure requests before admission without retaining prompt content."""

    def __init__(self, endpoint: ContextEndpoint) -> None:
        self._endpoint = endpoint

    def measure(
        self, messages: Sequence[Mapping[str, str]]
    ) -> ContextMeasurement:
        """Return the server context and exact rendered prompt token count."""
        return self._endpoint.measure_context(messages)


@dataclass(frozen=True)
class ContextBudgetReport:
    """Numeric accounting for one request, with no retained message content."""

    context_tokens: int
    prompt_tokens: int
    reserved_output_tokens: int
    required_tokens: int
    remaining_tokens: int


class ContextBudget:
    """Validate exact prompt usage and reserved generation against the context."""

    def __init__(self, configured_context_tokens: int) -> None:
        self._configured_context_tokens = configured_context_tokens

    def evaluate(
        self,
        measurement: ContextMeasurement,
        *,
        max_tokens: int,
    ) -> ContextBudgetReport:
        """Return the budget or reject incompatible and oversized requests."""
        context_tokens = min(
            self._configured_context_tokens,
            measurement.server_context_tokens,
        )
        if type(measurement.prompt_tokens) is not int or measurement.prompt_tokens < 0:
            raise InferenceProtocolError("Measured prompt tokens must be a non-negative integer")
        if type(max_tokens) is not int or max_tokens <= 0:
            raise InferenceConfigurationError("max_tokens must be a positive integer")
        if max_tokens > context_tokens:
            raise InferenceConfigurationError(
                f"max_tokens ({max_tokens}) exceeds the effective context "
                f"limit ({context_tokens})"
            )
        required_tokens = measurement.prompt_tokens + max_tokens
        if required_tokens > context_tokens:
            raise InferencePromptTooLong(
                prompt_tokens=measurement.prompt_tokens,
                max_tokens=max_tokens,
                context_tokens=context_tokens,
            )
        return ContextBudgetReport(
            context_tokens=context_tokens,
            prompt_tokens=measurement.prompt_tokens,
            reserved_output_tokens=max_tokens,
            required_tokens=required_tokens,
            remaining_tokens=context_tokens - required_tokens,
        )
