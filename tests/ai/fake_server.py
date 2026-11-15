"""Configurable loopback HTTP server for inference tests."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FakeLlmServer:
    """Serve configurable OpenAI-compatible responses on an ephemeral port."""

    def __init__(
        self,
        behavior: str = "success",
        *,
        health_shape: str = "openai",
        model: str = "rose-spark-4b",
        content: str = "A measured answer.",
        delay_seconds: float = 0.0,
        error_body: str = "inference failed",
        redirect_endpoint: str | None = None,
    ) -> None:
        self.behavior = behavior
        self.health_shape = health_shape
        self.model = model
        self.content = content
        self.delay_seconds = delay_seconds
        self.error_body = error_body
        self.redirect_endpoint = redirect_endpoint
        self.max_simultaneous = 0
        self.request_count = 0
        self.last_payload: dict[str, Any] | None = None
        self.last_headers: dict[str, str] = {}
        self.request_started = threading.Event()
        self._active = 0
        self._state_lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def endpoint(self) -> str:
        """Return the versioned API endpoint for this server."""
        host, port = self._server.server_address
        return f"http://{host}:{port}/v1"

    def __enter__(self) -> "FakeLlmServer":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            """Handle model discovery and chat completion requests."""

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                if self.path != "/v1/models":
                    self._send(404, b"not found", "text/plain; charset=utf-8")
                    return
                if fake.behavior == "http_500":
                    self._send(
                        500,
                        fake.error_body.encode("utf-8"),
                        "text/plain; charset=utf-8",
                    )
                    return
                if fake.behavior == "invalid_json":
                    self._send(200, b"{not-json", "application/json")
                    return
                if fake.health_shape == "llama":
                    payload: dict[str, Any] = {"models": [{"name": fake.model}]}
                elif fake.health_shape == "missing_model":
                    payload = {"data": [{"id": "another-model"}]}
                else:
                    payload = {"data": [{"id": fake.model}]}
                self._send_json(200, payload)

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                if self.path != "/v1/chat/completions":
                    self._send(404, b"not found", "text/plain; charset=utf-8")
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                with fake._state_lock:
                    fake.request_count += 1
                    fake._active += 1
                    fake.max_simultaneous = max(fake.max_simultaneous, fake._active)
                    try:
                        fake.last_payload = json.loads(raw_body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        fake.last_payload = None
                    fake.last_headers = dict(self.headers.items())
                fake.request_started.set()
                try:
                    if fake.delay_seconds:
                        time.sleep(fake.delay_seconds)
                    self._respond_to_completion()
                finally:
                    with fake._state_lock:
                        fake._active -= 1

            def _respond_to_completion(self) -> None:
                if fake.behavior == "http_500":
                    self._send(
                        500,
                        fake.error_body.encode("utf-8"),
                        "text/plain; charset=utf-8",
                    )
                    return
                if fake.behavior == "invalid_json":
                    self._send(200, b"{not-json", "application/json")
                    return
                if fake.behavior == "redirect":
                    self.send_response(302)
                    target = fake.redirect_endpoint or fake.endpoint
                    self.send_header("Location", target + "/chat/completions")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if fake.behavior == "oversized":
                    payload = {
                        "object": "chat.completion",
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "x" * (2 * 1024 * 1024 + 1),
                                },
                                "finish_reason": "stop",
                            }
                        ],
                    }
                    self._send_json(200, payload)
                    return

                message: dict[str, Any] = {
                    "role": "assistant",
                    "content": fake.content,
                }
                if fake.behavior == "non_string_content":
                    message["content"] = {"text": fake.content}
                choices = [] if fake.behavior == "missing_choices" else [
                    {"message": message, "finish_reason": "stop"}
                ]
                payload = {
                    "object": "chat.completion",
                    "choices": choices,
                }
                if fake.behavior not in {"no_usage", "no_usage_no_timings"}:
                    usage = {
                        "prompt_tokens": 22,
                        "completion_tokens": 2,
                        "total_tokens": 24,
                    }
                    if fake.behavior == "usage_without_total":
                        del usage["total_tokens"]
                    payload["usage"] = usage
                if fake.behavior == "timings_without_speed":
                    payload["timings"] = {
                        "prompt_per_second": 100.0,
                    }
                elif fake.behavior != "no_usage_no_timings":
                    payload["timings"] = {"predicted_per_second": 71.4}
                self._send_json(200, payload)

            def _send_json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self._send(status, body, "application/json")

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    # Timeout tests intentionally disconnect before a delayed reply.
                    pass

            def log_message(self, *_: object) -> None:
                """Keep test output free of HTTP request logs."""

        return Handler
