"""Startup tests for the supervised standalone MCP stdio process."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rose_nexus.core.errors import RoseNexusError
from rose_nexus.mcp.runtime import serve_stdio
from rose_nexus.web.db import connect, migrate
from rose_nexus.web.models import Document, User
from rose_nexus.web.repository import Repository
from rose_nexus.web.storage import Storage


ROOT = Path(__file__).resolve().parents[2]


def protocol_input() -> bytes:
    """Build initialization followed by a tools/list request."""

    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "runtime-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    return b"".join(
        json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        for message in messages
    )


class MCPRuntimeTests(unittest.TestCase):
    """Verify startup is explicitly configured and reuses an existing web store."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rose-mcp-runtime-")
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "web.sqlite3"
        self.storage_root = self.root / "storage"
        self.storage = Storage(self.storage_root)
        connection = connect(self.database_path)
        migrate(connection)
        repository = Repository(connection)
        user = repository.create_user(
            User(
                "runtime-user",
                "runtime",
                "opaque-test-hash",
                datetime(2026, 11, 15, tzinfo=timezone.utc).isoformat(),
            )
        )
        data = b"# Runtime fixture\n"
        original = self.storage.save_original(data)
        repository.create_document(
            Document(
                "runtime-document",
                user.id,
                "default",
                "runtime.md",
                original.sha256,
                len(data),
                "2026-11-15T00:00:00Z",
            )
        )
        connection.close()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def environment(self) -> dict[str, str]:
        return {
            "ROSE_MCP_USERNAME": "runtime",
            "ROSE_MCP_WORKER_MODE": "serialized",
            "ROSE_DB_PATH": str(self.database_path),
            "ROSE_STORAGE_DIR": str(self.storage_root),
            "ROSE_BRANDING_DIR": str(ROOT / "branding"),
            "ROSE_OUTPUT_DIR": str(self.root / "conversion-output"),
        }

    def test_server_starts_against_existing_store_and_advertises_four_tools(self) -> None:
        stdout = io.BytesIO()
        stderr = io.StringIO()
        serve_stdio(
            environment=self.environment(),
            stdin=io.BytesIO(protocol_input()),
            stdout=stdout,
            stderr=stderr,
        )
        responses = [json.loads(line) for line in stdout.getvalue().splitlines()]

        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(
            [tool["name"] for tool in responses[1]["result"]["tools"]],
            [
                "render_document",
                "get_document_status",
                "list_branding_profiles",
                "get_document_metadata",
            ],
        )
        self.assertEqual(stderr.getvalue(), "")

    def test_runtime_requires_explicit_serial_worker_mode(self) -> None:
        environment = self.environment()
        del environment["ROSE_MCP_WORKER_MODE"]
        stdout = io.BytesIO()
        stderr = io.StringIO()

        with self.assertRaises(RoseNexusError) as caught:
            serve_stdio(
                environment=environment,
                stdin=io.BytesIO(b""),
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(caught.exception.code, "mcp_worker_mode_required")
        self.assertEqual(stdout.getvalue(), b"")

    def test_module_entrypoint_keeps_startup_errors_off_stdout(self) -> None:
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(ROOT / "backend"),
        }
        result = subprocess.run(
            [sys.executable, "-m", "rose_nexus.mcp"],
            cwd=ROOT,
            env=environment,
            input=b"",
            capture_output=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"mcp_username_required", result.stderr)

    def test_runtime_requires_an_existing_configured_user(self) -> None:
        environment = self.environment()
        environment["ROSE_MCP_USERNAME"] = "absent-user"
        stdout = io.BytesIO()
        stderr = io.StringIO()

        with self.assertRaises(RoseNexusError) as caught:
            serve_stdio(
                environment=environment,
                stdin=io.BytesIO(b""),
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(caught.exception.code, "mcp_principal_not_found")
        self.assertEqual(stdout.getvalue(), b"")


if __name__ == "__main__":
    unittest.main()
