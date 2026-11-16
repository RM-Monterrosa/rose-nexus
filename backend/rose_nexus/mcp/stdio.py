"""Bounded newline framing for MCP's UTF-8 JSON-RPC stdio transport."""

from __future__ import annotations

import json
from typing import Any, BinaryIO

DEFAULT_MAX_MESSAGE_BYTES = 64 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 256 * 1024


class StdioFrameError(ValueError):
    """Base class for bounded stdio transport failures."""


class StdioMessageLimitError(StdioFrameError):
    """A frame exceeded its configured byte limit."""


class StdioSerializationError(StdioFrameError):
    """A protocol message could not be encoded as JSON UTF-8."""


class StdioWriteError(StdioFrameError):
    """A serialized protocol frame could not be written."""


class StdioTransport:
    """Read and write one bounded JSON message per newline-delimited frame."""

    def __init__(
        self,
        *,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        """Set positive byte limits for complete inbound and outbound frames."""

        if max_message_bytes < 1 or max_response_bytes < 1:
            raise ValueError("message limits must be positive")
        self.max_message_bytes = max_message_bytes
        self.max_response_bytes = max_response_bytes

    def read_frame(self, stream: BinaryIO) -> bytes | None:
        """Return one complete frame without its newline, or `None` at EOF."""

        line = stream.readline(self.max_message_bytes + 2)
        if not line:
            return None
        if not line.endswith(b"\n"):
            if len(line) > self.max_message_bytes:
                raise StdioMessageLimitError("message exceeds the configured size limit")
            return None
        frame = line[:-1]
        if len(frame) > self.max_message_bytes:
            raise StdioMessageLimitError("message exceeds the configured size limit")
        return frame

    def write_message(self, message: dict[str, Any], stream: BinaryIO) -> None:
        """Serialize and flush one compact UTF-8 JSON message followed by newline."""

        try:
            encoded = json.dumps(
                message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            raise StdioSerializationError("protocol message could not be serialized") from error
        if len(encoded) > self.max_response_bytes:
            raise StdioMessageLimitError("response exceeds the configured size limit")
        try:
            stream.write(encoded + b"\n")
            stream.flush()
        except (OSError, ValueError) as error:
            raise StdioWriteError("could not write protocol message") from error
