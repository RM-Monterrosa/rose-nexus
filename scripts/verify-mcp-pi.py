#!/usr/bin/env python3
"""Opt-in local Pi discovery and content-free MCP workflow measurement."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = (
    "render_document",
    "get_document_status",
    "list_branding_profiles",
    "get_document_metadata",
)


def _frame(message: dict[str, Any]) -> bytes:
    """Serialize one compact newline-delimited JSON-RPC message."""

    return json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"


class StdioProbe:
    """Small synchronous client used only by this local verification script."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process
        self.next_id = 1

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], float, int]:
        request_id = self.next_id
        self.next_id += 1
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params
        payload = _frame(message)
        started = time.perf_counter()
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(payload)
        self.process.stdin.flush()
        raw = self.process.stdout.readline()
        elapsed_ms = (time.perf_counter() - started) * 1000
        if not raw:
            raise RuntimeError("MCP server closed stdout before returning a response")
        response = json.loads(raw)
        if "error" in response:
            raise RuntimeError(f"MCP request failed with code {response['error'].get('code')}")
        return response["result"], elapsed_ms, len(raw)

    def notify(self, method: str) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(_frame({"jsonrpc": "2.0", "method": method}))
        self.process.stdin.flush()


def _create_probe_store(base: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, str, str]:
    """Create one disposable local account and source document for the probe."""

    from rose_nexus.web.db import connect, migrate
    from rose_nexus.web.models import Document, User
    from rose_nexus.web.repository import Repository
    from rose_nexus.web.storage import Storage

    database = base / "rose-nexus.sqlite3"
    storage_root = base / "storage"
    connection = connect(database)
    migrate(connection)
    repository = Repository(connection)
    user = repository.create_user(
        User("pi-probe-user", "pi-probe", "opaque-probe-hash", "2026-11-15T00:00:00Z")
    )
    source_bytes = b"# MCP Pi probe\n\nDisposable fixture; no personal content.\n"
    original = Storage(storage_root).save_original(source_bytes)
    document = repository.create_document(
        Document(
            "pi-probe-document",
            user.id,
            "default",
            "pi-probe.md",
            original.sha256,
            len(source_bytes),
            "2026-11-15T00:00:00Z",
        )
    )
    connection.close()
    return database, storage_root, user.username, document.id


def _pi_environment(agent_dir: pathlib.Path) -> dict[str, str]:
    """Isolate Pi configuration and disable unrelated network activity."""

    environment = os.environ.copy()
    environment.update(
        {
            "PI_CODING_AGENT_DIR": str(agent_dir),
            "PI_OFFLINE": "1",
            "PI_SKIP_VERSION_CHECK": "1",
            "PI_TELEMETRY": "0",
        }
    )
    return environment


def _verify_pi_discovery(
    server_environment: dict[str, str], agent_dir: pathlib.Path
) -> dict[str, Any]:
    """Ask the installed Pi CLI to connect and inspect direct MCP exposure."""

    pi = shutil.which("pi")
    if pi is None:
        raise RuntimeError("Pi executable is not available on PATH")
    version = subprocess.run(
        [pi, "--version"],
        capture_output=True,
        text=True,
        check=True,
        env=_pi_environment(agent_dir),
    ).stdout.strip()
    config = {
        "mcpServers": {
            "rose-documents": {
                "command": "python",
                "args": ["-m", "rose_nexus.mcp"],
                "cwd": ".",
                "env": {
                    "PYTHONPATH": "backend",
                    "ROSE_MCP_USERNAME": "${ROSE_MCP_USERNAME}",
                    "ROSE_MCP_WORKER_MODE": "serialized",
                },
                "timeout": 60,
                "exposure": "direct",
                "description": "Controlled rendering and owner-scoped document status.",
            }
        }
    }
    (agent_dir / "mcp.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    started = time.perf_counter()
    process_environment = _pi_environment(agent_dir)
    process_environment.update(server_environment)
    result = subprocess.run(
        [pi, "mcp", "list", "--json"],
        cwd=ROOT,
        env=process_environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    if result.returncode != 0:
        raise RuntimeError("Pi MCP discovery failed; inspect the captured diagnostic output")
    payload = json.loads(result.stdout)
    servers = payload.get("servers", [])
    server = next((item for item in servers if item.get("name") == "rose-documents"), None)
    if server is None or server.get("state") != "connected":
        raise RuntimeError("Pi did not connect to rose-documents")
    if server.get("exposure") != "direct" or set(server.get("tools", [])) != set(TOOLS):
        raise RuntimeError("Pi did not discover the expected four direct tools")
    return {
        "pi_version": version,
        "state": server["state"],
        "exposure": server["exposure"],
        "tool_count": len(server["tools"]),
        "discovery_ms": round(elapsed_ms, 3),
    }


def verify() -> dict[str, Any]:
    """Run Pi's MCP discovery and measure direct-service versus stdio calls."""

    from rose_nexus.core.config import Settings
    from rose_nexus.web.db import connect
    from rose_nexus.web.document_service import (
        get_document_metadata,
        get_document_status,
        list_brand_profiles,
        submit_render,
    )
    from rose_nexus.web.models import User
    from rose_nexus.web.repository import Repository
    with tempfile.TemporaryDirectory(prefix="rose-mcp-pi-verify-") as temporary:
        base = pathlib.Path(temporary)
        agent_dir = base / "pi-agent"
        agent_dir.mkdir()
        database, storage_root, username, document_id = _create_probe_store(base)
        settings = Settings(branding_dir=ROOT / "branding", output_dir=base / "conversion-output")
        server_environment = {
            "PYTHONPATH": str(ROOT / "backend"),
            "ROSE_MCP_USERNAME": username,
            "ROSE_MCP_WORKER_MODE": "serialized",
            "ROSE_DB_PATH": str(database),
            "ROSE_STORAGE_DIR": str(storage_root),
            "ROSE_BRANDING_DIR": str(settings.branding_dir),
            "ROSE_OUTPUT_DIR": str(settings.output_dir),
        }
        pi_metrics = _verify_pi_discovery(server_environment, agent_dir)

        connection = connect(database)
        repository = Repository(connection)
        principal = repository.get_user_by_username(username)
        assert principal is not None
        child_environment = os.environ.copy()
        child_environment.update(server_environment)
        process = subprocess.Popen(
            [sys.executable, "-m", "rose_nexus.mcp"],
            cwd=ROOT,
            env=child_environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        workflows: dict[str, Any] = {}
        try:
            client = StdioProbe(process)
            initialize, initialize_ms, initialize_bytes = client.request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "rose-mcp-probe", "version": "1"},
                },
            )
            client.notify("notifications/initialized")
            listed, list_ms, list_bytes = client.request("tools/list")
            if initialize.get("protocolVersion") != "2025-11-25":
                raise RuntimeError("MCP protocol negotiation failed")
            if {tool["name"] for tool in listed["tools"]} != set(TOOLS):
                raise RuntimeError("MCP server tool contract changed")
            _ping, ping_ms, ping_bytes = client.request("ping")
            workflows["tools_list"] = {
                "roundtrip_ms": round(list_ms, 3),
                "response_bytes": list_bytes,
                "tool_count": len(listed["tools"]),
            }
            workflows["ping_protocol_baseline"] = {
                "roundtrip_ms": round(ping_ms, 3),
                "response_bytes": ping_bytes,
            }
            workflows["initialize"] = {
                "roundtrip_ms": round(initialize_ms, 3),
                "response_bytes": initialize_bytes,
            }

            def call_tool(
                name: str, arguments: dict[str, Any]
            ) -> tuple[dict[str, Any], float, int]:
                result, elapsed_ms, response_bytes = client.request(
                    "tools/call", {"name": name, "arguments": arguments}
                )
                if result.get("isError"):
                    error = result.get("structuredContent", {}).get("error_code", "tool_error")
                    raise RuntimeError(f"MCP workflow failed with code {error}")
                return result["structuredContent"], elapsed_ms, response_bytes

            direct_started = time.perf_counter()
            profiles = list_brand_profiles(settings)
            direct_profiles_ms = (time.perf_counter() - direct_started) * 1000
            mcp_profiles, mcp_profiles_ms, profiles_bytes = call_tool(
                "list_branding_profiles", {}
            )
            workflows["list_branding_profiles"] = {
                "direct_ms": round(direct_profiles_ms, 3),
                "mcp_roundtrip_ms": round(mcp_profiles_ms, 3),
                "estimated_extra_ms": round(mcp_profiles_ms - direct_profiles_ms, 3),
                "response_bytes": profiles_bytes,
                "profile_count": len(mcp_profiles["profiles"]),
            }

            direct_started = time.perf_counter()
            get_document_metadata(
                repository=repository, user=principal, document_id=document_id
            )
            direct_metadata_ms = (time.perf_counter() - direct_started) * 1000
            metadata, mcp_metadata_ms, metadata_bytes = call_tool(
                "get_document_metadata", {"document_id": document_id}
            )
            workflows["get_document_metadata"] = {
                "direct_ms": round(direct_metadata_ms, 3),
                "mcp_roundtrip_ms": round(mcp_metadata_ms, 3),
                "estimated_extra_ms": round(mcp_metadata_ms - direct_metadata_ms, 3),
                "response_bytes": metadata_bytes,
                "metadata_field_count": len(metadata),
            }

            class RecordingRunner:
                def submit(self, job_id: str) -> None:
                    del job_id

            direct_started = time.perf_counter()
            submit_render(
                repository=repository,
                runner=RecordingRunner(),  # type: ignore[arg-type]
                settings=settings,
                user=principal,
                document_id=document_id,
                brand="invering",
                output_format="tex",
            )
            direct_render_ms = (time.perf_counter() - direct_started) * 1000
            render_result, mcp_render_ms, render_bytes = call_tool(
                "render_document",
                {
                    "source_id": document_id,
                    "branding_profile": "invering",
                    "output_format": "tex",
                },
            )
            job_id = render_result["job_id"]
            workflows["render_document"] = {
                "direct_enqueue_ms": round(direct_render_ms, 3),
                "mcp_roundtrip_ms": round(mcp_render_ms, 3),
                "estimated_extra_ms": round(mcp_render_ms - direct_render_ms, 3),
                "response_bytes": render_bytes,
                "state_returned": render_result["status"],
            }

            deadline = time.perf_counter() + 30
            status: dict[str, Any] | None = None
            status_ms = 0.0
            status_bytes = 0
            while time.perf_counter() < deadline:
                status, status_ms, status_bytes = call_tool(
                    "get_document_status", {"job_id": job_id}
                )
                if status["status"] not in {"pending", "running"}:
                    break
                time.sleep(0.05)
            if status is None or status["status"] != "completed":
                raise RuntimeError("TeX-only MCP render did not complete successfully")
            direct_started = time.perf_counter()
            get_document_status(repository=repository, user=principal, job_id=job_id)
            direct_status_ms = (time.perf_counter() - direct_started) * 1000
            workflows["get_document_status"] = {
                "direct_ms": round(direct_status_ms, 3),
                "mcp_roundtrip_ms": round(status_ms, 3),
                "estimated_extra_ms": round(status_ms - direct_status_ms, 3),
                "response_bytes": status_bytes,
                "final_state": status["status"],
                "artifact_count": len(status["artifacts"]),
            }
        finally:
            if process.stdin is not None:
                process.stdin.close()
            try:
                process.wait(timeout=100)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
            connection.close()

        return {
            "pi": pi_metrics,
            "protocol_version": "2025-11-25",
            "worker_mode": "serialized",
            "workflows": workflows,
            "note": (
                "One local sample per workflow; timing deltas are observations, "
                "not model or GPU performance claims."
            ),
        }


def main() -> int:
    """Print only numeric and categorical verification evidence."""

    try:
        report = verify()
    except Exception as error:
        print(f"error: {error.__class__.__name__}: MCP Pi verification failed", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
