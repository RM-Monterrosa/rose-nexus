"""Exact, content-private context measurement for llama.cpp inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class ContextMeasurement:
    """Numeric-only measurements of a fully rendered chat prompt."""

    server_context_tokens: int
    prompt_tokens: int


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
