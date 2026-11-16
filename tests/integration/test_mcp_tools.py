"""Security and contract tests for the rose-documents MCP tools."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from rose_nexus.core.config import Settings
from rose_nexus.mcp.server import MCPStdioServer
from rose_nexus.mcp.tools import MCPToolRateLimiter, create_document_tools
from rose_nexus.web.db import connect, migrate
from rose_nexus.web.document_service import submit_render
from rose_nexus.web.models import Document, User
from rose_nexus.web.repository import Repository
from rose_nexus.web.storage import Storage


ROOT = Path(__file__).resolve().parents[2]
CREATED_AT = "2026-11-15T12:00:00Z"


def encode_messages(messages: list[dict[str, Any]]) -> bytes:
    """Encode requests as newline-delimited UTF-8 JSON-RPC frames."""

    return b"".join(
        json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
        for message in messages
    )


def run_server(
    server: MCPStdioServer, messages: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str]:
    """Run one finite client exchange and decode its protocol responses."""

    stdout = io.BytesIO()
    stderr = io.StringIO()
    server.serve(stdin=io.BytesIO(encode_messages(messages)), stdout=stdout, stderr=stderr)
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    return responses, stderr.getvalue()


def initialize_requests() -> list[dict[str, Any]]:
    """Return a valid minimal MCP initialization exchange."""

    return [
        {
            "jsonrpc": "2.0",
            "id": "init",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "mcp-tools-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]


def tool_request(request_id: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build one MCP tools/call request."""

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


class RecordingRunner:
    """Record enqueued jobs without starting a worker."""

    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)


class MCPDocumentToolTests(unittest.TestCase):
    """Exercise MCP tools against isolated web services and owner-scoped rows."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rose-mcp-tools-")
        self.root = Path(self.temporary.name)
        self.connection = connect(self.root / "web.sqlite3")
        migrate(self.connection)
        self.repository = Repository(self.connection)
        self.storage = Storage(self.root / "storage")
        self.settings = Settings(
            branding_dir=ROOT / "branding",
            output_dir=self.root / "conversion-output",
        )
        self.runner = RecordingRunner()
        self.alice = self.repository.create_user(
            User("user-alice", "alice", "opaque-test-hash", CREATED_AT)
        )
        self.bob = self.repository.create_user(
            User("user-bob", "bob", "opaque-test-hash", CREATED_AT)
        )
        self.alice_document = self.add_document("alice-document", self.alice, "private-name.md")
        self.bob_document = self.add_document("bob-document", self.bob, "other-user.txt")

    def tearDown(self) -> None:
        self.connection.close()
        self.temporary.cleanup()

    def add_document(self, document_id: str, user: User, filename: str) -> Document:
        data = b"# Private source\n"
        source = self.storage.save_original(data)
        return self.repository.create_document(
            Document(
                document_id,
                user.id,
                "default",
                filename,
                source.sha256,
                len(data),
                CREATED_AT,
            )
        )

    def make_server(
        self,
        *,
        principal: User | None = None,
        limiter: MCPToolRateLimiter | None = None,
        render_limiter: MCPToolRateLimiter | None = None,
    ) -> MCPStdioServer:
        """Bind all handlers to the supplied trusted principal, never tool arguments."""

        tools = create_document_tools(
            repository=self.repository,
            runner=self.runner,
            settings=self.settings,
            principal=principal or self.alice,
            rate_limiter=limiter,
            render_rate_limiter=render_limiter,
        )
        return MCPStdioServer(tools=tools)

    def call_tool(
        self,
        server: MCPStdioServer,
        request_id: int,
        name: str,
        arguments: dict[str, Any],
        *,
        initialize: bool = False,
    ) -> tuple[dict[str, Any], str]:
        messages = [tool_request(request_id, name, arguments)]
        if initialize:
            messages = initialize_requests() + messages
        responses, stderr = run_server(server, messages)
        return responses[-1], stderr

    def test_exposes_exact_four_tools_with_closed_schemas_and_no_principal_input(self) -> None:
        tools = create_document_tools(
            repository=self.repository,
            runner=self.runner,
            settings=self.settings,
            principal=self.alice,
        )
        by_name = {tool.name: tool for tool in tools}

        self.assertEqual(
            set(by_name),
            {
                "render_document",
                "get_document_status",
                "list_branding_profiles",
                "get_document_metadata",
            },
        )
        for tool in tools:
            self.assertEqual(tool.input_schema["type"], "object")
            self.assertFalse(tool.input_schema["additionalProperties"])
            serialized = json.dumps(tool.input_schema)
            for forbidden in ("user_id", "principal", "filesystem", "path"):
                self.assertNotIn(forbidden, serialized)
        self.assertEqual(
            by_name["render_document"].input_schema["required"],
            ["source_id", "branding_profile", "output_format"],
        )
        self.assertEqual(by_name["list_branding_profiles"].input_schema["properties"], {})

    def test_render_returns_the_owned_web_job_id(self) -> None:
        server = self.make_server()
        response, _stderr = self.call_tool(
            server,
            2,
            "render_document",
            {
                "source_id": self.alice_document.id,
                "branding_profile": "invering",
                "output_format": "tex",
            },
            initialize=True,
        )

        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["status"], "pending")
        job_id = result["structuredContent"]["job_id"]
        job = self.repository.get_job(job_id, self.alice.id)
        self.assertEqual(job.document_id, self.alice_document.id)
        self.assertEqual(job.user_id, self.alice.id)
        self.assertEqual(self.runner.submitted, [job_id])

    def test_foreign_document_is_hidden_and_creates_no_job(self) -> None:
        response, _stderr = self.call_tool(
            self.make_server(),
            2,
            "render_document",
            {
                "source_id": self.bob_document.id,
                "branding_profile": "invering",
                "output_format": "pdf",
            },
            initialize=True,
        )

        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error_code"], "document_not_found")
        self.assertEqual(result["structuredContent"]["message"], "document not found")
        self.assertEqual(self.repository.list_jobs(), [])
        self.assertEqual(self.runner.submitted, [])

    def test_status_and_metadata_are_scoped_to_the_bound_principal(self) -> None:
        alice_job = submit_render(
            repository=self.repository,
            runner=self.runner,
            settings=self.settings,
            user=self.alice,
            document_id=self.alice_document.id,
            brand="invering",
            output_format="tex",
        )["job_id"]
        bob_job = submit_render(
            repository=self.repository,
            runner=self.runner,
            settings=self.settings,
            user=self.bob,
            document_id=self.bob_document.id,
            brand="invering",
            output_format="tex",
        )["job_id"]
        server = self.make_server()
        status, _stderr = self.call_tool(
            server, 2, "get_document_status", {"job_id": alice_job}, initialize=True
        )
        metadata, _stderr = self.call_tool(
            server, 3, "get_document_metadata", {"document_id": self.alice_document.id}
        )
        foreign_status, _stderr = self.call_tool(
            server, 4, "get_document_status", {"job_id": bob_job}
        )
        foreign_metadata, _stderr = self.call_tool(
            server, 5, "get_document_metadata", {"document_id": self.bob_document.id}
        )

        self.assertEqual(status["result"]["structuredContent"]["job_id"], alice_job)
        self.assertEqual(metadata["result"]["structuredContent"]["filename"], "private-name.md")
        self.assertTrue(foreign_status["result"]["isError"])
        self.assertEqual(
            foreign_status["result"]["structuredContent"]["error_code"], "job_not_found"
        )
        self.assertTrue(foreign_metadata["result"]["isError"])
        self.assertEqual(
            foreign_metadata["result"]["structuredContent"]["error_code"],
            "document_not_found",
        )

    def test_arguments_are_strictly_bounded_and_cannot_override_principal(self) -> None:
        response, _stderr = self.call_tool(
            self.make_server(),
            2,
            "render_document",
            {
                "source_id": self.alice_document.id,
                "branding_profile": "invering",
                "output_format": "tex",
                "user_id": self.bob.id,
            },
            initialize=True,
        )

        self.assertTrue(response["result"]["isError"])
        self.assertEqual(response["result"]["structuredContent"]["error_code"], "invalid_input")
        self.assertEqual(self.repository.list_jobs(), [])
        self.assertEqual(self.runner.submitted, [])

    def test_malformed_scalar_types_are_rejected_as_invalid_input(self) -> None:
        server = self.make_server()
        calls = (
            {
                "source_id": self.alice_document.id,
                "branding_profile": "invering",
                "output_format": [],
            },
            {
                "source_id": "\ud800",
                "branding_profile": "invering",
                "output_format": "tex",
            },
        )
        for request_id, arguments in enumerate(calls, start=2):
            response, _stderr = self.call_tool(
                server,
                request_id,
                "render_document",
                arguments,
                initialize=request_id == 2,
            )
            result = response["result"]
            self.assertTrue(result["isError"])
            self.assertEqual(result["structuredContent"]["error_code"], "invalid_input")
        self.assertEqual(self.repository.list_jobs(), [])

    def test_shared_rate_limit_is_deterministic_and_recovers_after_window(self) -> None:
        now = [100.0]
        limiter = MCPToolRateLimiter(
            max_calls=2, window_seconds=10.0, clock=lambda: now[0]
        )
        server = self.make_server(limiter=limiter)
        first, _stderr = self.call_tool(
            server, 2, "list_branding_profiles", {}, initialize=True
        )
        second, _stderr = self.call_tool(server, 3, "list_branding_profiles", {})
        limited, _stderr = self.call_tool(server, 4, "get_document_metadata", {})

        self.assertFalse(first["result"]["isError"])
        self.assertFalse(second["result"]["isError"])
        self.assertTrue(limited["result"]["isError"])
        self.assertEqual(limited["result"]["structuredContent"]["error_code"], "rate_limited")
        now[0] = 110.0
        recovered, _stderr = self.call_tool(server, 5, "list_branding_profiles", {})
        self.assertFalse(recovered["result"]["isError"])

    def test_render_has_a_separate_resource_rate_limit(self) -> None:
        now = [200.0]
        server = self.make_server(
            limiter=MCPToolRateLimiter(max_calls=10, clock=lambda: now[0]),
            render_limiter=MCPToolRateLimiter(max_calls=1, clock=lambda: now[0]),
        )
        arguments = {
            "source_id": self.alice_document.id,
            "branding_profile": "invering",
            "output_format": "tex",
        }
        first, _stderr = self.call_tool(
            server, 2, "render_document", arguments, initialize=True
        )
        limited, _stderr = self.call_tool(server, 3, "render_document", arguments)

        self.assertFalse(first["result"]["isError"])
        self.assertTrue(limited["result"]["isError"])
        self.assertEqual(limited["result"]["structuredContent"]["error_code"], "rate_limited")
        self.assertEqual(len(self.runner.submitted), 1)

    def test_stderr_trace_contains_no_tool_arguments_or_results(self) -> None:
        response, stderr = self.call_tool(
            self.make_server(),
            2,
            "get_document_metadata",
            {"document_id": self.alice_document.id},
            initialize=True,
        )

        self.assertFalse(response["result"]["isError"])
        self.assertIn("tool call succeeded: get_document_metadata", stderr)
        self.assertNotIn(self.alice_document.id, stderr)
        self.assertNotIn("private-name.md", stderr)


if __name__ == "__main__":
    unittest.main()
