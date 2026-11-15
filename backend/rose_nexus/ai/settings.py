"""Environment-based configuration for loopback-first inference."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from .errors import InferenceConfigurationError

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _integer(
    env: Mapping[str, str], key: str, default: int
) -> int:
    """Read a positive integer environment value."""
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise InferenceConfigurationError(f"{key} must be an integer") from error
    if value <= 0:
        raise InferenceConfigurationError(f"{key} must be positive")
    return value


def _number(env: Mapping[str, str], key: str, default: float) -> float:
    """Read a finite floating-point environment value."""
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise InferenceConfigurationError(f"{key} must be a number") from error
    if not math.isfinite(value):
        raise InferenceConfigurationError(f"{key} must be finite")
    return value


def _boolean(env: Mapping[str, str], key: str, default: bool) -> bool:
    """Read an explicit boolean environment value."""
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise InferenceConfigurationError(f"{key} must be a boolean")


def _positive(name: str, value: float) -> None:
    """Reject non-finite or non-positive numeric settings."""
    if not math.isfinite(value) or value <= 0:
        raise InferenceConfigurationError(f"{name} must be positive and finite")


@dataclass(frozen=True)
class InferenceSettings:
    """Validated settings for an OpenAI-compatible inference endpoint."""

    endpoint: str = "http://127.0.0.1:18080/v1"
    model: str = "rose-spark-4b"
    timeout_seconds: float = 60
    connect_timeout_seconds: float = 5
    max_tokens: int = 512
    temperature: float = 0.2
    top_p: float = 0.95
    context_tokens: int = 8192
    max_concurrency: int = 1
    queue_timeout_seconds: float = 30
    api_key: str | None = None
    enabled: bool = False
    allow_remote_endpoint: bool = False

    def __post_init__(self) -> None:
        """Validate direct construction as strictly as environment parsing."""
        for name in (
            "timeout_seconds",
            "connect_timeout_seconds",
            "max_tokens",
            "context_tokens",
            "max_concurrency",
            "queue_timeout_seconds",
        ):
            _positive(name, getattr(self, name))
        if not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2:
            raise InferenceConfigurationError("temperature must be between 0 and 2")
        if not math.isfinite(self.top_p) or not 0 <= self.top_p <= 1:
            raise InferenceConfigurationError("top_p must be between 0 and 1")
        if not self.model.strip():
            raise InferenceConfigurationError("model must not be empty")
        try:
            parsed = urlsplit(self.endpoint)
            host = parsed.hostname
            parsed.port
        except ValueError as error:
            raise InferenceConfigurationError("endpoint must be a valid HTTP URL") from error
        if parsed.scheme not in {"http", "https"} or not host:
            raise InferenceConfigurationError(
                "endpoint must use http or https and include a host"
            )
        if parsed.username is not None or parsed.password is not None:
            raise InferenceConfigurationError("endpoint must not contain userinfo")
        if not self.allow_remote_endpoint and host.lower() not in _LOOPBACK_HOSTS:
            raise InferenceConfigurationError(
                "endpoint host must be loopback unless allow_remote_endpoint is true"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "InferenceSettings":
        """Build settings without loading ambient credential files."""
        source = os.environ if env is None else env
        endpoint = (source.get("ROSE_LLM_ENDPOINT") or cls.endpoint).strip()
        model = (source.get("ROSE_LLM_MODEL") or cls.model).strip()
        raw_key = source.get("ROSE_LLM_API_KEY")
        return cls(
            endpoint=endpoint,
            model=model,
            timeout_seconds=_number(source, "ROSE_LLM_TIMEOUT_SECONDS", 60),
            connect_timeout_seconds=_number(
                source, "ROSE_LLM_CONNECT_TIMEOUT_SECONDS", 5
            ),
            max_tokens=_integer(source, "ROSE_LLM_MAX_TOKENS", 512),
            temperature=_number(source, "ROSE_LLM_TEMPERATURE", 0.2),
            top_p=_number(source, "ROSE_LLM_TOP_P", 0.95),
            context_tokens=_integer(source, "ROSE_LLM_CONTEXT_TOKENS", 8192),
            max_concurrency=_integer(source, "ROSE_LLM_MAX_CONCURRENCY", 1),
            queue_timeout_seconds=_number(
                source, "ROSE_LLM_QUEUE_TIMEOUT_SECONDS", 30
            ),
            api_key=raw_key if raw_key else None,
            enabled=_boolean(source, "ROSE_LLM_ENABLED", False),
            allow_remote_endpoint=_boolean(
                source, "ROSE_LLM_ALLOW_REMOTE_ENDPOINT", False
            ),
        )

    def redacted(self) -> dict[str, object]:
        """Return log-safe settings with no credential or URL path."""
        return {
            "endpoint_host": urlsplit(self.endpoint).hostname or "",
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "context_tokens": self.context_tokens,
            "max_concurrency": self.max_concurrency,
            "queue_timeout_seconds": self.queue_timeout_seconds,
            "api_key_configured": self.api_key is not None,
            "enabled": self.enabled,
            "allow_remote_endpoint": self.allow_remote_endpoint,
        }
