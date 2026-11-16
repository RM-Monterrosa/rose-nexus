"""A bounded JSON-RPC stdio server for the MCP 2025-11-25 subset."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable, TextIO

from .stdio import (
    DEFAULT_MAX_MESSAGE_BYTES,
    DEFAULT_MAX_RESPONSE_BYTES,
    StdioFrameError,
    StdioMessageLimitError,
    StdioSerializationError,
    StdioTransport,
    StdioWriteError,
)

PROTOCOL_VERSION = "2025-11-25"
MAX_TOOL_ERROR_CHARS = 2_000

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


class MCPToolError(Exception):
    """A safe, actionable tool failure with a stable machine-readable code."""

    def __init__(self, message: str, *, code: str = "tool_error") -> None:
        """Retain only the public message and stable error identifier."""

        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MCPTool:
    """One static tool definition and its local handler."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


class MCPStdioServer:
    """Serve MCP requests over newline-delimited UTF-8 JSON-RPC on stdio."""

    def __init__(
        self,
        *,
        tools: tuple[MCPTool, ...] | list[MCPTool],
        server_name: str = "rose-documents",
        server_version: str = "0.1.0",
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        """Validate static server metadata and retain bounded transport settings."""

        if not server_name or not server_version:
            raise ValueError("server name and version must not be empty")
        if max_message_bytes < 1 or max_response_bytes < 1:
            raise ValueError("message limits must be positive")
        names: list[str] = []
        for tool in tools:
            if not isinstance(tool.name, str) or not 1 <= len(tool.name) <= 128:
                raise ValueError("tool names must be 1 to 128 characters")
            if any(
                not char.isascii() or not (char.isalnum() or char in "_.-")
                for char in tool.name
            ):
                raise ValueError("tool names contain unsupported characters")
            if not isinstance(tool.description, str) or not tool.description:
                raise ValueError("tool descriptions are required")
            if not isinstance(tool.input_schema, dict) or tool.input_schema.get("type") != "object":
                raise ValueError("tool input schema must be an object schema")
            try:
                json.dumps(tool.input_schema, allow_nan=False)
            except (TypeError, ValueError) as error:
                raise ValueError("tool input schema must be JSON serializable") from error
            if not callable(tool.handler):
                raise ValueError("tool handler must be callable")
            names.append(tool.name)
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        self._tools = tuple(tools)
        self._tools_by_name = {tool.name: tool for tool in tools}
        self._server_name = server_name
        self._server_version = server_version
        self._transport = StdioTransport(
            max_message_bytes=max_message_bytes,
            max_response_bytes=max_response_bytes,
        )
        self._initialized = False
        self._ready = False

    def serve(
        self,
        *,
        stdin: BinaryIO | None = None,
        stdout: BinaryIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        """Process complete newline-delimited messages until EOF or a fatal frame."""

        input_stream = stdin if stdin is not None else sys.stdin.buffer
        output_stream = stdout if stdout is not None else sys.stdout.buffer
        error_stream = stderr if stderr is not None else sys.stderr

        while True:
            try:
                frame = self._transport.read_frame(input_stream)
            except StdioMessageLimitError:
                self._write(
                    self._error(None, -32600, "message exceeds the configured size limit"),
                    output_stream,
                    error_stream,
                )
                return
            if frame is None:
                return

            response = self._handle_line(frame, error_stream)
            if response is not None and not self._write(response, output_stream, error_stream):
                return

    def _handle_line(self, line: bytes, stderr: TextIO) -> dict[str, Any] | None:
        try:
            text = line.decode("utf-8", errors="strict")
            message = json.loads(text, parse_constant=self._reject_non_json_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            return self._error(None, -32700, "Parse error")

        if not isinstance(message, dict):
            return self._error(None, -32600, "Invalid Request")
        request_id = message.get("id")
        has_id = "id" in message
        valid_id = type(request_id) in (str, int)
        if isinstance(request_id, str):
            try:
                request_id.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                valid_id = False
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return self._error(request_id if valid_id else None, -32600, "Invalid Request")
        if has_id and not valid_id:
            return self._error(None, -32600, "Invalid Request")

        method = message["method"]
        params = message.get("params")
        if not has_id:
            self._handle_notification(method, params)
            return None

        if method == "initialize":
            return self._initialize(request_id, params)
        if method == "ping":
            if params is not None and not self._valid_params(params, {"_meta"}):
                return self._error(request_id, -32602, "Invalid params")
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method not in {"tools/list", "tools/call"}:
            return self._error(request_id, -32601, "Method not found")
        if not self._ready:
            return self._error(request_id, -32600, "Server is not initialized")
        if method == "tools/list":
            return self._list_tools(request_id, params)
        return self._call_tool(request_id, params, stderr)

    def _initialize(self, request_id: str | int, params: Any) -> dict[str, Any]:
        if self._initialized:
            return self._error(request_id, -32600, "Server is already initialized")
        if not self._valid_params(
            params, {"_meta", "protocolVersion", "capabilities", "clientInfo"}
        ):
            return self._error(request_id, -32602, "Invalid params")
        if not isinstance(params.get("protocolVersion"), str):
            return self._error(request_id, -32602, "Invalid protocol version")
        if not isinstance(params.get("capabilities"), dict):
            return self._error(request_id, -32602, "Invalid client capabilities")
        client_info = params.get("clientInfo")
        if not isinstance(client_info, dict) or not all(
            isinstance(client_info.get(key), str) for key in ("name", "version")
        ):
            return self._error(request_id, -32602, "Invalid client information")

        self._initialized = True
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self._server_name, "version": self._server_version},
            },
        }

    def _handle_notification(self, method: str, params: Any) -> None:
        if (
            method == "notifications/initialized"
            and self._initialized
            and (params is None or self._valid_params(params, {"_meta"}))
        ):
            self._ready = True
        # Cancellation is cooperative. All current handlers return promptly and render
        # only enqueues a background web job, so late/unknown cancellations are harmless.
        # Unknown notifications are intentionally ignored as required for JSON-RPC.

    def _list_tools(self, request_id: str | int, params: Any) -> dict[str, Any]:
        if params is not None and not self._valid_params(params, {"_meta", "cursor"}):
            return self._error(request_id, -32602, "Invalid params")
        if isinstance(params, dict) and "cursor" in params:
            if not isinstance(params["cursor"], str):
                return self._error(request_id, -32602, "Invalid params")
            return self._error(request_id, -32602, "Invalid cursor")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.input_schema,
                    }
                    for tool in self._tools
                ]
            },
        }

    def _call_tool(
        self, request_id: str | int, params: Any, stderr: TextIO
    ) -> dict[str, Any]:
        if not self._valid_params(params, {"_meta", "name", "arguments"}):
            return self._error(request_id, -32602, "Invalid params")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return self._error(request_id, -32602, "Invalid params")
        tool = self._tools_by_name.get(name)
        if tool is None:
            return self._error(request_id, -32602, f"Unknown tool: {name}")

        try:
            value = tool.handler(arguments)
        except MCPToolError as error:
            message = str(error).encode("utf-8", errors="replace").decode("utf-8")
            message = message[:MAX_TOOL_ERROR_CHARS]
            self._log(stderr, f"tool call failed: {name} code={error.code}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": message}],
                    "structuredContent": {"error_code": error.code, "message": message},
                    "isError": True,
                },
            }
        except Exception:
            self._log(stderr, f"tool handler failed: {name}")
            return self._error(request_id, -32603, "Tool execution failed")
        if not isinstance(value, dict):
            self._log(stderr, f"tool handler returned a non-object: {name}")
            return self._error(request_id, -32603, "Tool execution failed")
        try:
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            text.encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError):
            self._log(stderr, f"tool handler returned non-JSON data: {name}")
            return self._error(request_id, -32603, "Tool execution failed")
        self._log(stderr, f"tool call succeeded: {name}")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "structuredContent": value,
                "isError": False,
            },
        }

    @staticmethod
    def _valid_params(params: Any, allowed: set[str]) -> bool:
        return (
            isinstance(params, dict)
            and set(params).issubset(allowed)
            and ("_meta" not in params or isinstance(params["_meta"], dict))
        )

    @staticmethod
    def _reject_non_json_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant: {value}")

    @staticmethod
    def _error(request_id: str | int | None, code: int, message: str) -> dict[str, Any]:
        response: dict[str, Any] = {"jsonrpc": "2.0", "error": {"code": code, "message": message}}
        if request_id is not None:
            response["id"] = request_id
        return response

    def _write(self, response: dict[str, Any], stdout: BinaryIO, stderr: TextIO) -> bool:
        try:
            self._transport.write_message(response, stdout)
            return True
        except StdioMessageLimitError:
            return self._write_fallback(
                response, -32603, "Response exceeds the configured size limit", stdout, stderr
            )
        except StdioSerializationError:
            return self._write_fallback(
                response, -32603, "Protocol response could not be serialized", stdout, stderr
            )
        except StdioWriteError:
            self._log(stderr, "could not write protocol response")
            return False

    def _write_fallback(
        self,
        original: dict[str, Any],
        code: int,
        message: str,
        stdout: BinaryIO,
        stderr: TextIO,
    ) -> bool:
        """Write a bounded JSON-RPC error replacing an invalid server response."""

        request_id = original.get("id")
        fallback = self._error(
            request_id if type(request_id) in (str, int) else None, code, message
        )
        try:
            self._transport.write_message(fallback, stdout)
        except StdioFrameError:
            self._log(stderr, "could not write protocol response")
            return False
        return True

    @staticmethod
    def _log(stderr: TextIO, message: str) -> None:
        try:
            stderr.write(message + "\n")
            stderr.flush()
        except (OSError, ValueError):
            pass
