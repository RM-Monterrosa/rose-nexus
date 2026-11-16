"""Conformance tests for the narrow JSON-RPC MCP stdio server."""

from __future__ import annotations

import io
import json
import unittest
from typing import Any
from unittest.mock import patch

import rose_nexus.mcp.server as server_module
from rose_nexus.mcp.server import MCPStdioServer, MCPTool, MCPToolError
from rose_nexus.mcp.stdio import StdioFrameError, StdioTransport


def message(value: dict[str, Any]) -> bytes:
    """Encode one transport message."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def initialized(version: str = "2025-11-25") -> list[dict[str, Any]]:
    """Return a minimal client handshake and ready notification."""

    return [
        {
            "jsonrpc": "2.0",
            "id": "init-1",
            "method": "initialize",
            "params": {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]


def echo(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return the test input as structured output."""

    return {"echo": arguments.get("text", "")}


def fail(_arguments: dict[str, Any]) -> dict[str, Any]:
    """Raise an expected business-level tool error."""

    raise MCPToolError("document not found")


def make_server(*, max_message_bytes: int = 64 * 1024) -> MCPStdioServer:
    return MCPStdioServer(
        tools=(
            MCPTool(
                name="echo",
                description="Return text unchanged.",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
                handler=echo,
            ),
            MCPTool(
                name="fail",
                description="Raise a business-level failure.",
                input_schema={"type": "object", "additionalProperties": False},
                handler=fail,
            ),
        ),
        max_message_bytes=max_message_bytes,
    )


def run_server(data: bytes, *, server: MCPStdioServer | None = None):
    stdin = io.BytesIO(data)
    stdout = io.BytesIO()
    stderr = io.StringIO()
    (server or make_server()).serve(stdin=stdin, stdout=stdout, stderr=stderr)
    raw = stdout.getvalue()
    responses = [json.loads(line) for line in raw.splitlines()]
    return responses, raw, stderr.getvalue()


class StdioTransportTests(unittest.TestCase):
    def test_read_frame_preserves_utf8_and_accepts_exact_size_limit(self) -> None:
        frame = "café".encode("utf-8")
        transport = StdioTransport(max_message_bytes=len(frame))

        self.assertEqual(transport.read_frame(io.BytesIO(frame + b"\n")), frame)

    def test_read_frame_returns_none_for_eof_and_incomplete_final_frame(self) -> None:
        transport = StdioTransport()

        self.assertIsNone(transport.read_frame(io.BytesIO(b"")))
        self.assertIsNone(transport.read_frame(io.BytesIO(b'{"jsonrpc":"2.0"}')))

    def test_read_frame_rejects_oversized_complete_and_incomplete_frames(self) -> None:
        transport = StdioTransport(max_message_bytes=4)

        with self.assertRaises(StdioFrameError):
            transport.read_frame(io.BytesIO(b"12345\n"))
        with self.assertRaises(StdioFrameError):
            transport.read_frame(io.BytesIO(b"12345"))

    def test_write_message_is_compact_utf8_and_newline_terminated(self) -> None:
        class FlushTrackingBuffer(io.BytesIO):
            flushed = False

            def flush(self) -> None:
                self.flushed = True
                super().flush()

        output = FlushTrackingBuffer()
        StdioTransport().write_message({"text": "olá"}, output)

        self.assertEqual(output.getvalue(), b'{"text":"ol\xc3\xa1"}\n')
        self.assertTrue(output.flushed)

    def test_write_message_rejects_invalid_json_and_oversized_response(self) -> None:
        transport = StdioTransport(max_response_bytes=4)

        with self.assertRaises(StdioFrameError):
            transport.write_message({"value": float("nan")}, io.BytesIO())
        with self.assertRaises(StdioFrameError):
            transport.write_message({"text": "too long"}, io.BytesIO())

    def test_server_uses_the_shared_stdio_transport(self) -> None:
        calls = 0

        def transport_factory(**kwargs: int) -> StdioTransport:
            nonlocal calls
            calls += 1
            return StdioTransport(**kwargs)

        with patch.object(
            server_module, "StdioTransport", side_effect=transport_factory, create=True
        ):
            responses, _raw, _stderr = run_server(
                message({"jsonrpc": "2.0", "id": 1, "method": "ping"})
            )

        self.assertEqual(calls, 1)
        self.assertEqual(responses[0]["result"], {})


class McpStdioTests(unittest.TestCase):
    def test_initialize_negotiates_supported_version_and_advertises_tools(self) -> None:
        messages = initialized("unsupported-version")
        responses, _raw, stderr = run_server(message(messages[0]) + message(messages[1]))

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], "init-1")
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-11-25")
        self.assertIn("tools", responses[0]["result"]["capabilities"])
        self.assertEqual(stderr, "")

    def test_supported_version_is_echoed_and_notifications_have_no_response(self) -> None:
        messages = initialized()
        messages.extend(
            [
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": "done"},
                },
                {"jsonrpc": "2.0", "method": "notifications/custom"},
            ]
        )
        responses, _raw, _stderr = run_server(b"".join(map(message, messages)))

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-11-25")

    def test_ping_is_allowed_before_initialize_and_returns_empty_result(self) -> None:
        responses, _raw, _stderr = run_server(
            message({"jsonrpc": "2.0", "id": 4, "method": "ping"})
        )

        self.assertEqual(responses, [{"jsonrpc": "2.0", "id": 4, "result": {}}])

    def test_other_requests_require_initialize_and_initialized(self) -> None:
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            *initialized()[:1],
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            *initialized()[1:],
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        ]
        responses, _raw, _stderr = run_server(b"".join(map(message, messages)))

        self.assertEqual([response.get("id") for response in responses], [1, "init-1", 2, 3])
        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertEqual(responses[2]["error"]["code"], -32600)
        self.assertIn("tools", responses[-1]["result"])

    def test_tools_list_returns_static_complete_set_without_cursor(self) -> None:
        messages = initialized() + [{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        responses, _raw, _stderr = run_server(b"".join(map(message, messages)))
        listed = responses[-1]["result"]

        self.assertEqual([tool["name"] for tool in listed["tools"]], ["echo", "fail"])
        self.assertNotIn("nextCursor", listed)
        self.assertEqual(listed["tools"][0]["inputSchema"]["type"], "object")

    def test_tools_list_rejects_cursor_when_static_result_has_no_pages(self) -> None:
        messages = initialized() + [
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"cursor": "unknown"}}
        ]
        responses, _raw, _stderr = run_server(b"".join(map(message, messages)))

        self.assertEqual(responses[-1]["error"]["code"], -32602)

    def test_tools_call_returns_structured_and_text_content(self) -> None:
        messages = initialized() + [
            {
                "jsonrpc": "2.0",
                "id": "call-1",
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "olá"}},
            }
        ]
        responses, _raw, _stderr = run_server(b"".join(map(message, messages)))
        result = responses[-1]["result"]

        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], {"echo": "olá"})
        self.assertEqual(json.loads(result["content"][0]["text"]), {"echo": "olá"})

    def test_unknown_tool_is_protocol_error_and_execution_error_is_tool_result(self) -> None:
        messages = initialized() + [
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "missing"}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "fail", "arguments": {}},
            },
        ]
        responses, _raw, _stderr = run_server(b"".join(map(message, messages)))

        self.assertEqual(responses[-2]["error"]["code"], -32602)
        self.assertTrue(responses[-1]["result"]["isError"])
        self.assertEqual(responses[-1]["result"]["content"][0]["text"], "document not found")

    def test_invalid_json_and_unknown_method_use_jsonrpc_errors(self) -> None:
        data = b"{not-json}\n\xff\n" + message({"jsonrpc": "2.0", "id": 5, "method": "unknown"})
        responses, raw, stderr = run_server(data)

        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertNotIn("id", responses[0])
        self.assertEqual(responses[1]["error"]["code"], -32700)
        self.assertEqual(responses[2]["error"]["code"], -32601)
        self.assertEqual(raw.count(b"\n"), 3)
        self.assertEqual(stderr, "")

    def test_malformed_request_does_not_echo_invalid_id(self) -> None:
        responses, _raw, _stderr = run_server(
            message({"jsonrpc": "2.0", "id": None, "method": "ping"})
        )

        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertNotIn("id", responses[0])

    def test_surrogate_request_id_is_rejected_without_crashing(self) -> None:
        data = b'{"jsonrpc":"2.0","id":"\\ud800","method":"ping"}\n'
        responses, _raw, _stderr = run_server(data)

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertNotIn("id", responses[0])

    def test_oversized_line_is_rejected_and_server_stops(self) -> None:
        server = make_server(max_message_bytes=64)
        oversized = b"x" * 65 + b"\n" + message(
            {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        )
        responses, raw, _stderr = run_server(oversized, server=server)

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertLessEqual(len(raw), 256)

    def test_oversized_response_is_replaced_by_a_bounded_protocol_error(self) -> None:
        server = MCPStdioServer(tools=(), max_response_bytes=120)
        request = message(initialized()[0])
        responses, raw, _stderr = run_server(request, server=server)

        self.assertEqual(responses[0]["error"]["code"], -32603)
        self.assertLessEqual(len(raw.rstrip(b"\n")), 120)

    def test_incomplete_unterminated_line_is_not_processed_on_eof(self) -> None:
        responses, _raw, _stderr = run_server(message(initialized()[0]).rstrip(b"\n"))

        self.assertEqual(responses, [])

    def test_protocol_output_is_one_utf8_jsonrpc_message_per_line(self) -> None:
        messages = initialized() + [
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "olá"}},
            },
            {"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 8, "method": "ping"},
        ]
        responses, raw, _stderr = run_server(b"".join(map(message, messages)))

        self.assertEqual(raw.count(b"\n"), len(responses))
        self.assertEqual(len(responses), 4)
        self.assertIn("olá".encode("utf-8"), raw)
        for line in raw.splitlines():
            self.assertEqual(json.loads(line)["jsonrpc"], "2.0")


if __name__ == "__main__":
    unittest.main()
