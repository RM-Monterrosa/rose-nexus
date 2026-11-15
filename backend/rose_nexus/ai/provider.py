"""Strict OpenAI-compatible inference transport using the standard library."""

from __future__ import annotations

import ipaddress
import json
import math
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence, runtime_checkable
from urllib.parse import urlsplit

from .errors import (
    InferenceConfigurationError,
    InferenceHTTPError,
    InferenceProtocolError,
    InferenceTimeout,
    InferenceUnavailable,
)
from .settings import InferenceSettings

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_ERROR_DETAIL = 300


@dataclass(frozen=True)
class HealthStatus:
    """Measured model-discovery status."""

    available: bool
    model_present: bool
    models: tuple[str, ...]
    latency_ms: float


@dataclass(frozen=True)
class Completion:
    """Validated completion data without the raw response payload."""

    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    finish_reason: str | None
    predicted_tokens_per_second: float | None


@runtime_checkable
class LlmProvider(Protocol):
    """Provider boundary consumed by the inference client."""

    def health(self) -> HealthStatus:
        """Return endpoint and configured-model availability."""
        ...

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        timeout: float | None = None,
    ) -> Completion:
        """Return one validated chat completion."""
        ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Turn every redirect into an HTTP error instead of following it."""

    def redirect_request(self, *_: object, **__: object) -> None:
        return None


class OpenAICompatibleProvider:
    """Call a local OpenAI-compatible endpoint with bounded responses."""

    def __init__(self, settings: InferenceSettings) -> None:
        self.settings = settings
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    def health(self) -> HealthStatus:
        """Discover models using either OpenAI or llama.cpp response shapes."""
        started = time.monotonic()
        request = urllib.request.Request(
            self.settings.endpoint.rstrip("/") + "/models", method="GET"
        )
        payload = self._request_json(
            request, timeout=self.settings.connect_timeout_seconds, sensitive_values=()
        )
        if not isinstance(payload, dict):
            raise InferenceProtocolError("Model discovery response must be an object")
        if "data" in payload:
            entries = payload["data"]
            identifier = "id"
        elif "models" in payload:
            entries = payload["models"]
            identifier = "name"
        else:
            raise InferenceProtocolError("Model discovery response has no model list")
        if not isinstance(entries, list):
            raise InferenceProtocolError("Model discovery model list must be an array")
        models: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get(identifier), str):
                raise InferenceProtocolError("Model discovery contains an invalid model")
            models.append(entry[identifier])
        return HealthStatus(
            available=True,
            model_present=self.settings.model in models,
            models=tuple(models),
            latency_ms=(time.monotonic() - started) * 1000,
        )

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        timeout: float | None = None,
    ) -> Completion:
        """Submit one completion request and strictly validate its response."""
        body = {
            "model": self.settings.model,
            "messages": list(messages),
            "max_tokens": self.settings.max_tokens if max_tokens is None else max_tokens,
            "temperature": self.settings.temperature if temperature is None else temperature,
            "top_p": self.settings.top_p if top_p is None else top_p,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        request = urllib.request.Request(
            self.settings.endpoint.rstrip("/") + "/chat/completions",
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        sensitive_values = [self.settings.api_key or ""]
        sensitive_values.extend(
            message.get("content", "") for message in messages
        )
        payload = self._request_json(
            request,
            timeout=self.settings.timeout_seconds if timeout is None else timeout,
            sensitive_values=sensitive_values,
        )
        return self._parse_completion(payload)

    def _request_json(
        self,
        request: urllib.request.Request,
        *,
        timeout: float,
        sensitive_values: Sequence[str],
    ) -> object:
        """Open one request without redirects and bound its decoded response."""
        self._enforce_loopback_resolution()
        try:
            with self._opener.open(request, timeout=timeout) as response:
                status = response.status
                if status != 200:
                    raise InferenceHTTPError(
                        "Inference endpoint returned a non-success status",
                        status=status,
                    )
                raw_body = response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            try:
                raw_detail = error.read(4096)
            finally:
                error.close()
            detail = raw_detail.decode("utf-8", errors="replace")
            for value in sensitive_values:
                if value:
                    detail = detail.replace(value, "[redacted]")
            raise InferenceHTTPError(
                "Inference endpoint returned an HTTP error",
                status=error.code,
                detail=detail[:_MAX_ERROR_DETAIL],
            ) from error
        except (socket.timeout, TimeoutError) as error:
            raise InferenceTimeout("Inference request timed out") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, (socket.timeout, TimeoutError)):
                raise InferenceTimeout("Inference request timed out") from error
            raise InferenceUnavailable("Inference endpoint is unavailable") from error
        except (ConnectionError, OSError) as error:
            raise InferenceUnavailable("Inference endpoint is unavailable") from error
        if len(raw_body) > _MAX_RESPONSE_BYTES:
            raise InferenceProtocolError("Inference response exceeds the 2 MiB limit")
        try:
            text = raw_body.decode("utf-8")
            return json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InferenceProtocolError("Inference response is not valid JSON") from error

    def _enforce_loopback_resolution(self) -> None:
        """Resolve the endpoint afresh and reject every non-loopback address."""
        if self.settings.allow_remote_endpoint:
            return
        parsed = urlsplit(self.settings.endpoint)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as error:
            raise InferenceUnavailable("Inference endpoint could not be resolved") from error
        if not addresses:
            raise InferenceConfigurationError(
                "Inference endpoint did not resolve to a loopback address",
                code="inference_endpoint_not_loopback",
            )
        for address in addresses:
            try:
                raw_address = address[4][0].split("%", 1)[0]
                resolved = ipaddress.ip_address(raw_address)
            except (IndexError, TypeError, ValueError) as error:
                raise InferenceConfigurationError(
                    "Inference endpoint resolved to an invalid address",
                    code="inference_endpoint_not_loopback",
                ) from error
            if not resolved.is_loopback:
                raise InferenceConfigurationError(
                    "Inference endpoint did not resolve exclusively to loopback",
                    code="inference_endpoint_not_loopback",
                )

    def _parse_completion(self, payload: object) -> Completion:
        """Validate only the completion fields exposed to callers."""
        if not isinstance(payload, dict) or payload.get("object") != "chat.completion":
            raise InferenceProtocolError("Completion response has an invalid object type")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise InferenceProtocolError("Completion response has no choices")
        first = choices[0]
        if not isinstance(first, dict) or not isinstance(first.get("message"), dict):
            raise InferenceProtocolError("Completion response has an invalid choice")
        message = first["message"]
        if message.get("role") != "assistant" or not isinstance(
            message.get("content"), str
        ):
            raise InferenceProtocolError("Completion response has an invalid assistant message")
        usage = payload.get("usage", {})
        if not isinstance(usage, dict):
            raise InferenceProtocolError("Completion usage must be an object")

        def token_count(name: str) -> int | None:
            if name not in usage:
                return None
            value = usage[name]
            if type(value) is not int:
                raise InferenceProtocolError(f"Completion usage {name} must be an integer")
            return value

        finish_reason = first.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise InferenceProtocolError("Completion finish_reason must be a string or null")
        speed = self._predicted_speed(payload.get("timings"))
        return Completion(
            text=message["content"],
            prompt_tokens=token_count("prompt_tokens"),
            completion_tokens=token_count("completion_tokens"),
            total_tokens=token_count("total_tokens"),
            finish_reason=finish_reason,
            predicted_tokens_per_second=speed,
        )

    def _predicted_speed(self, timings: object) -> float | None:
        """Extract the optional measured llama.cpp generation speed."""
        if timings is None:
            return None
        if not isinstance(timings, dict):
            raise InferenceProtocolError("Completion timings must be an object")
        if "predicted_per_second" not in timings:
            return None
        value = timings["predicted_per_second"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InferenceProtocolError("Completion predicted speed must be numeric")
        speed = float(value)
        if not math.isfinite(speed):
            raise InferenceProtocolError("Completion predicted speed must be finite")
        return speed
