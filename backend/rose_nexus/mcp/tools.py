"""Owner-bound document tools exposed by the supervised MCP server."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from ..core.config import Settings
from ..core.errors import RoseNexusError
from ..web.document_service import (
    get_document_metadata,
    get_document_status,
    list_brand_profiles,
    submit_render,
)
from ..web.jobs import JobRunner
from ..web.models import User
from ..web.repository import Repository
from .server import MCPTool, MCPToolError

DEFAULT_RATE_LIMIT_CALLS = 60
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60.0
DEFAULT_RENDER_RATE_LIMIT_CALLS = 3
MAX_IDENTIFIER_CHARS = 128
MAX_BRANDING_PROFILE_CHARS = 64


class MCPToolRateLimiter:
    """Apply one bounded sliding-window limit across a server's document tools."""

    def __init__(
        self,
        *,
        max_calls: int = DEFAULT_RATE_LIMIT_CALLS,
        window_seconds: float = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create an isolated limiter; inject ``clock`` for deterministic tests."""

        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("max_calls must be a positive integer")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max_calls = max_calls
        self._window_seconds = window_seconds
        self._clock = clock
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Consume one call slot or raise a stable rate-limit tool error."""

        with self._lock:
            now = self._clock()
            while self._calls and now - self._calls[0] >= self._window_seconds:
                self._calls.popleft()
            if len(self._calls) >= self._max_calls:
                raise MCPToolError(
                    "tool request rate limit exceeded", code="rate_limited"
                )
            self._calls.append(now)


def _object_schema(
    properties: dict[str, dict[str, Any]], required: list[str]
) -> dict[str, Any]:
    """Return a closed JSON object schema for one tool."""

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _require_fields(arguments: dict[str, Any], expected: set[str]) -> None:
    """Reject missing and unexpected tool fields before calling domain services."""

    if set(arguments) != expected:
        raise MCPToolError("invalid tool arguments", code="invalid_input")


def _bounded_string(value: Any, *, maximum: int, field: str) -> str:
    """Validate a nonempty bounded string without control characters or padding."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise MCPToolError(f"{field} is invalid", code="invalid_input")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise MCPToolError(f"{field} is invalid", code="invalid_input") from error
    return value


def create_document_tools(
    *,
    repository: Repository,
    runner: JobRunner,
    settings: Settings,
    principal: User,
    rate_limiter: MCPToolRateLimiter | None = None,
    render_rate_limiter: MCPToolRateLimiter | None = None,
) -> tuple[MCPTool, ...]:
    """Build four read/submit tools bound to one trusted local web user.

    The principal is captured by each handler and cannot be selected through MCP
    arguments. Authorization and ownership checks remain in the shared web services.
    """

    if not isinstance(principal, User):
        raise ValueError("a trusted local user principal is required")
    limiter = rate_limiter if rate_limiter is not None else MCPToolRateLimiter()
    render_limiter = (
        render_rate_limiter
        if render_rate_limiter is not None
        else MCPToolRateLimiter(max_calls=DEFAULT_RENDER_RATE_LIMIT_CALLS)
    )

    def guarded(
        operation: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        additional_limiter: MCPToolRateLimiter | None = None,
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
        def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            limiter.acquire()
            if additional_limiter is not None:
                additional_limiter.acquire()
            try:
                return operation(arguments)
            except RoseNexusError as error:
                raise MCPToolError(error.message, code=error.code) from error

        return handler

    def render(arguments: dict[str, Any]) -> dict[str, Any]:
        _require_fields(arguments, {"source_id", "branding_profile", "output_format"})
        source_id = _bounded_string(
            arguments["source_id"], maximum=MAX_IDENTIFIER_CHARS, field="source_id"
        )
        branding_profile = _bounded_string(
            arguments["branding_profile"],
            maximum=MAX_BRANDING_PROFILE_CHARS,
            field="branding_profile",
        )
        output_format = arguments["output_format"]
        if not isinstance(output_format, str) or output_format not in {"tex", "pdf"}:
            raise MCPToolError("output_format is invalid", code="invalid_input")
        return submit_render(
            repository=repository,
            runner=runner,
            settings=settings,
            user=principal,
            document_id=source_id,
            brand=branding_profile,
            output_format=output_format,
        )

    def status(arguments: dict[str, Any]) -> dict[str, Any]:
        _require_fields(arguments, {"job_id"})
        job_id = _bounded_string(
            arguments["job_id"], maximum=MAX_IDENTIFIER_CHARS, field="job_id"
        )
        return get_document_status(repository=repository, user=principal, job_id=job_id)

    def profiles(arguments: dict[str, Any]) -> dict[str, Any]:
        _require_fields(arguments, set())
        return {"profiles": list_brand_profiles(settings)}

    def metadata(arguments: dict[str, Any]) -> dict[str, Any]:
        _require_fields(arguments, {"document_id"})
        document_id = _bounded_string(
            arguments["document_id"], maximum=MAX_IDENTIFIER_CHARS, field="document_id"
        )
        return get_document_metadata(
            repository=repository, user=principal, document_id=document_id
        )

    return (
        MCPTool(
            name="render_document",
            description="Queue a controlled render for a document owned by the configured user.",
            input_schema=_object_schema(
                {
                    "source_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_IDENTIFIER_CHARS,
                    },
                    "branding_profile": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_BRANDING_PROFILE_CHARS,
                    },
                    "output_format": {"type": "string", "enum": ["tex", "pdf"]},
                },
                ["source_id", "branding_profile", "output_format"],
            ),
            handler=guarded(render, additional_limiter=render_limiter),
        ),
        MCPTool(
            name="get_document_status",
            description="Get the safe status and artifact metadata for an owned render job.",
            input_schema=_object_schema(
                {
                    "job_id": {"type": "string", "minLength": 1, "maxLength": MAX_IDENTIFIER_CHARS}
                },
                ["job_id"],
            ),
            handler=guarded(status),
        ),
        MCPTool(
            name="list_branding_profiles",
            description="List installed and validated branding profiles.",
            input_schema=_object_schema({}, []),
            handler=guarded(profiles),
        ),
        MCPTool(
            name="get_document_metadata",
            description="Get safe metadata for a document owned by the configured user.",
            input_schema=_object_schema(
                {
                    "document_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_IDENTIFIER_CHARS,
                    }
                },
                ["document_id"],
            ),
            handler=guarded(metadata),
        ),
    )
