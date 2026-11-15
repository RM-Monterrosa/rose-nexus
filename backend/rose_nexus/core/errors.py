"""Stable error types for the Rose Nexus document engine.

Every failure carries a machine-readable ``code`` and a process ``exit_code`` so
the CLI can be verified by tests and scripts.
"""

from __future__ import annotations

from typing import Any


class RoseNexusError(Exception):
    """Base class for expected, reportable failures."""

    code = "internal_error"
    exit_code = 1

    def __init__(
        self,
        message: str,
        *,
        detail: str | None = None,
        code: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail
        if code is not None:
            self.code = code
        if exit_code is not None:
            self.exit_code = exit_code

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": self.detail}

    def __str__(self) -> str:
        if self.detail:
            return f"{self.code}: {self.message} ({self.detail})"
        return f"{self.code}: {self.message}"


class InputValidationError(RoseNexusError):
    """The input document, metadata or configuration is invalid."""

    code = "invalid_input"
    exit_code = 2


class BrandingError(InputValidationError):
    """A brand profile or template is missing or does not satisfy the schema."""

    code = "branding_invalid"


class LatexPolicyViolation(RoseNexusError):
    """Generated content violates a security rule."""

    code = "latex_policy_violation"
    exit_code = 3


class SandboxUnavailableError(RoseNexusError):
    """No container runtime or no pinned TeX image is provisioned."""

    code = "sandbox_unavailable"
    exit_code = 4


class CompileError(RoseNexusError):
    """The sandboxed LaTeX run returned a failure."""

    code = "compile_failed"
    exit_code = 5
