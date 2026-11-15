"""Stable, reportable errors for local inference."""

from __future__ import annotations

from ..core.errors import RoseNexusError


class InferenceUnavailable(RoseNexusError):
    """The inference endpoint cannot be reached or is disabled."""

    code = "inference_unavailable"
    exit_code = 4


class InferenceTimeout(InferenceUnavailable):
    """The inference endpoint exceeded the configured timeout."""

    code = "inference_timeout"


class InferenceProtocolError(RoseNexusError):
    """The endpoint returned an invalid or unsupported response."""

    code = "inference_protocol_error"
    exit_code = 5


class InferenceHTTPError(RoseNexusError):
    """The endpoint returned a non-success HTTP status."""

    code = "inference_http_error"
    exit_code = 5

    def __init__(
        self,
        message: str,
        *,
        status: int,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, detail=detail)
        self.status = status


class InferenceBusy(InferenceUnavailable):
    """No inference slot became available before the queue timeout."""

    code = "inference_busy"


class InferenceConfigurationError(RoseNexusError):
    """Inference configuration or direct client input is invalid."""

    code = "inference_configuration_invalid"
    exit_code = 2
