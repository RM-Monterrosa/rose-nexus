"""Standalone supervised MCP process reusing the local web document services."""

from __future__ import annotations

import os
import pathlib
import sqlite3
import sys
from collections.abc import Mapping
from typing import BinaryIO, TextIO

from ..core.config import Settings
from ..core.errors import InputValidationError, RoseNexusError
from ..web.db import connect
from ..web.jobs import JobRunner
from ..web.repository import Repository
from ..web.storage import Storage
from .server import MCPStdioServer
from .tools import create_document_tools


def serve_stdio(
    *,
    environment: Mapping[str, str] | None = None,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    stderr: TextIO | None = None,
) -> None:
    """Run the local stdio server for one explicitly configured web principal.

    The serialized-worker opt-in is deliberate: this initial implementation uses
    a process-local job queue and must not run alongside the web worker.
    """

    source = os.environ if environment is None else environment
    username = (source.get("ROSE_MCP_USERNAME") or "").strip()
    if not username:
        raise InputValidationError(
            "ROSE_MCP_USERNAME must select an existing local account",
            code="mcp_username_required",
        )
    if source.get("ROSE_MCP_WORKER_MODE") != "serialized":
        raise InputValidationError(
            "serialized worker mode must be explicitly enabled; "
            "stop the web worker before starting MCP",
            code="mcp_worker_mode_required",
        )

    settings = Settings.from_env(source)
    database_path = pathlib.Path(
        source.get("ROSE_DB_PATH") or settings.output_dir / "rose-nexus.db"
    )
    storage_root = pathlib.Path(
        source.get("ROSE_STORAGE_DIR") or settings.output_dir / "storage"
    )
    if not database_path.is_file():
        raise InputValidationError(
            "the configured web database does not exist", code="mcp_database_missing"
        )
    if not storage_root.is_dir():
        raise InputValidationError(
            "the configured web storage directory does not exist",
            code="mcp_storage_missing",
        )

    connection = connect(database_path)
    runner: JobRunner | None = None
    try:
        repository = Repository(connection)
        principal = repository.get_user_by_username(username)
        if principal is None:
            raise InputValidationError(
                "the configured local user does not exist", code="mcp_principal_not_found"
            )
        runner = JobRunner(repository, Storage(storage_root), settings)
        runner.start()
        server = MCPStdioServer(
            tools=create_document_tools(
                repository=repository,
                runner=runner,
                settings=settings,
                principal=principal,
            )
        )
        server.serve(stdin=stdin, stdout=stdout, stderr=stderr)
    finally:
        if runner is not None:
            runner.stop(timeout=max(5.0, settings.compile_timeout_seconds + 5.0))
        connection.close()


def main() -> int:
    """Start the configured stdio server and keep diagnostics off stdout."""

    try:
        serve_stdio()
    except RoseNexusError as error:
        print(f"error: {error.code}: {error.message}", file=sys.stderr)
        return error.exit_code
    except sqlite3.Error:
        print("error: mcp_database_unavailable: could not open the web database", file=sys.stderr)
        return 2
    except OSError:
        print("error: mcp_storage_unavailable: could not access web storage", file=sys.stderr)
        return 2
    return 0
