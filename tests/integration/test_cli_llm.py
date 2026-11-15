"""Subprocess integration tests for the local inference CLI commands."""

import json
import math
import os
import pathlib
import socket
import statistics
import subprocess
import sys
import tempfile
import unittest

from tests.ai.fake_server import FakeLlmServer

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
MODEL = "rose-spark-4b"


def run_cli(*arguments, env_extra=None):
    """Run the public CLI with an isolated Rose environment."""
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("ROSE_")
    }
    environment["PYTHONPATH"] = str(BACKEND)
    environment.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "rose_nexus.cli", *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
        check=False,
    )


def llm_env(server, **overrides):
    """Point inference at a fake server without using ambient credentials."""
    environment = {
        "ROSE_LLM_ENABLED": "true",
        "ROSE_LLM_ENDPOINT": server.endpoint,
        "ROSE_LLM_MODEL": MODEL,
        "ROSE_LLM_TIMEOUT_SECONDS": "5",
        "ROSE_LLM_CONNECT_TIMEOUT_SECONDS": "2",
    }
    environment.update(overrides)
    return environment


class LlmCommandTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeLlmServer(content="Fake answer.")
        self.server.__enter__()

    def tearDown(self):
        self.server.__exit__(None, None, None)

    def test_health_human_and_json_do_not_require_enabled_inference(self):
        environment = llm_env(self.server, ROSE_LLM_ENABLED="false")
        human = run_cli("llm", "health", env_extra=environment)
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertEqual(human.stderr, "")
        self.assertEqual(len(human.stdout.splitlines()), 1)
        self.assertIn(MODEL, human.stdout)
        self.assertIn("latency", human.stdout)
        self.assertIn("available", human.stdout)
        self.assertIn("model_present", human.stdout)

        machine = run_cli("llm", "health", "--json", env_extra=environment)
        self.assertEqual(machine.returncode, 0, machine.stderr)
        self.assertEqual(machine.stderr, "")
        payload = json.loads(machine.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["health"]["available"])
        self.assertTrue(payload["health"]["model_present"])
        self.assertEqual(payload["health"]["model"], MODEL)
        self.assertIsInstance(payload["health"]["latency_ms"], (int, float))

    def test_health_unreachable_keeps_exit_four_and_clean_stderr(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        endpoint = f"http://127.0.0.1:{port}/v1"
        environment = llm_env(self.server, ROSE_LLM_ENDPOINT=endpoint)
        result = run_cli("llm", "health", "--json", env_extra=environment)
        self.assertEqual(result.returncode, 4)
        self.assertEqual(result.stdout, "")
        self.assertIn("inference_unavailable", result.stderr)

    def test_ask_prints_only_answer_and_content_free_metrics(self):
        secret_prompt = "unique-prompt-secret-7c9154b3"
        fake_api_key = "fake-api-key-not-for-logging"
        environment = llm_env(self.server, ROSE_LLM_API_KEY=fake_api_key)
        result = run_cli(
            "llm", "ask", "--prompt", secret_prompt, env_extra=environment
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Fake answer.\n")
        lines = result.stderr.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("metrics: "))
        metrics = json.loads(lines[0].removeprefix("metrics: "))
        self.assertEqual(metrics["prompt_tokens"], 22)
        self.assertEqual(metrics["completion_tokens"], 2)
        self.assertNotIn(secret_prompt, result.stdout)
        self.assertNotIn(secret_prompt, result.stderr)
        self.assertNotIn(fake_api_key, result.stdout)
        self.assertNotIn(fake_api_key, result.stderr)

    def test_ask_json_has_answer_metrics_and_no_stderr(self):
        result = run_cli(
            "llm",
            "ask",
            "--prompt",
            "json-question",
            "--system",
            "Answer briefly.",
            "--max-tokens",
            "32",
            "--temperature",
            "0.1",
            "--json",
            env_extra=llm_env(self.server),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["answer"], "Fake answer.")
        self.assertEqual(payload["metrics"]["total_tokens"], 24)
        self.assertEqual(self.server.last_payload["max_tokens"], 32)
        self.assertEqual(self.server.last_payload["temperature"], 0.1)

    def test_ask_requires_exactly_one_prompt_source(self):
        for arguments in ((), ("--prompt", "one", "--prompt-file", "unused.txt")):
            with self.subTest(arguments=arguments):
                before = self.server.request_count
                result = run_cli("llm", "ask", *arguments, env_extra=llm_env(self.server))
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("invalid_input", result.stderr)
                self.assertEqual(self.server.request_count, before)

    def test_ask_rejects_oversized_prompt_file_without_echoing_it(self):
        secret_prompt = b"oversized-prompt-secret-1bc40d93"
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "prompt.txt"
            path.write_bytes(secret_prompt + b"x" * (65537 - len(secret_prompt)))
            before = self.server.request_count
            result = run_cli(
                "llm",
                "ask",
                "--prompt-file",
                str(path),
                env_extra=llm_env(self.server),
            )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("prompt_too_large", result.stderr)
        self.assertNotIn(secret_prompt.decode(), result.stdout)
        self.assertNotIn(secret_prompt.decode(), result.stderr)
        self.assertEqual(self.server.request_count, before)

    def test_ask_rejects_rendered_prompt_over_budget_without_completion_or_echo(self):
        secret_prompt = "over-budget-prompt-secret-0a0b3c19"
        fake_api_key = "fake-api-key-not-for-logging"
        self.server.prompt_tokens = 100_000
        before = self.server.request_count
        result = run_cli(
            "llm",
            "ask",
            "--prompt",
            secret_prompt,
            env_extra=llm_env(self.server, ROSE_LLM_API_KEY=fake_api_key),
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("prompt_too_long", result.stderr)
        self.assertIn(
            "Prompt budget exceeded: 100000 prompt tokens + 512 generation tokens "
            "= 100512, but the context limit is 8192",
            result.stderr,
        )
        self.assertNotIn(secret_prompt, result.stdout)
        self.assertNotIn(secret_prompt, result.stderr)
        self.assertNotIn(fake_api_key, result.stdout)
        self.assertNotIn(fake_api_key, result.stderr)
        self.assertNotIn("Unicode á € 😀", result.stdout + result.stderr)
        self.assertEqual(self.server.request_count, before)

    def test_ask_warns_when_generation_reaches_max_tokens(self):
        secret_prompt = "length-finish-prompt-secret-ed735c21"
        fake_api_key = "fake-api-key-not-for-logging"
        self.server.finish_reason = "length"
        environment = llm_env(self.server, ROSE_LLM_API_KEY=fake_api_key)
        result = run_cli(
            "llm", "ask", "--prompt", secret_prompt, env_extra=environment
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Fake answer.\n")
        self.assertIn(
            "warning: generation reached max_tokens; answer may be incomplete",
            result.stderr.splitlines(),
        )
        metric_lines = [
            line for line in result.stderr.splitlines() if line.startswith("metrics: ")
        ]
        self.assertEqual(len(metric_lines), 1)
        metrics = json.loads(metric_lines[0].removeprefix("metrics: "))
        self.assertEqual(metrics["finish_reason"], "length")
        self.assertEqual(metrics["prompt_tokens"], 22)
        self.assertEqual(metrics["completion_tokens"], 2)
        self.assertNotIn(secret_prompt, result.stdout)
        self.assertNotIn(secret_prompt, result.stderr)
        self.assertNotIn(fake_api_key, result.stdout)
        self.assertNotIn(fake_api_key, result.stderr)

        machine = run_cli(
            "llm", "ask", "--prompt", secret_prompt, "--json", env_extra=environment
        )
        self.assertEqual(machine.returncode, 0, machine.stderr)
        self.assertEqual(machine.stderr, "")
        payload = json.loads(machine.stdout)
        self.assertEqual(set(payload), {"ok", "answer", "metrics"})
        self.assertEqual(payload["answer"], "Fake answer.")
        self.assertEqual(payload["metrics"]["finish_reason"], "length")
        self.assertNotIn(secret_prompt, machine.stdout)
        self.assertNotIn(secret_prompt, machine.stderr)
        self.assertNotIn(fake_api_key, machine.stdout)
        self.assertNotIn(fake_api_key, machine.stderr)
        self.assertEqual(self.server.request_count, 2)

    def test_ask_disabled_reports_inference_disabled(self):
        environment = llm_env(self.server)
        del environment["ROSE_LLM_ENABLED"]
        before = self.server.request_count
        result = run_cli("llm", "ask", "--prompt", "disabled", env_extra=environment)
        self.assertEqual(result.returncode, 4)
        self.assertEqual(result.stdout, "")
        self.assertIn("inference_disabled", result.stderr)
        self.assertEqual(self.server.request_count, before)

    def test_bench_prints_one_row_per_run_and_median_summary(self):
        result = run_cli("llm", "bench", env_extra=llm_env(self.server))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        lines = result.stdout.strip().splitlines()
        self.assertEqual(
            lines[0].split(),
            ["run", "wall_ms", "prompt_tokens", "completion_tokens", "tok_s", "finish_reason"],
        )
        rows = [line.split() for line in lines[1:] if line[:1].isdigit()]
        self.assertEqual(len(rows), 3)
        self.assertEqual([int(row[0]) for row in rows], [1, 2, 3])
        for row in rows:
            self.assertEqual(row[2:4], ["22", "2"])
            self.assertEqual(row[5], "stop")
        summary_lines = [line for line in lines if line.startswith("summary:")]
        self.assertEqual(len(summary_lines), 1)
        summary = dict(
            item.split("=", 1) for item in summary_lines[0].removeprefix("summary:").split()
        )
        self.assertEqual(summary["runs"], "3")
        self.assertEqual(summary["failures"], "0")
        self.assertAlmostEqual(
            float(summary["wall_median_ms"]),
            statistics.median(float(row[1]) for row in rows),
        )
        self.assertAlmostEqual(
            float(summary["tok_s_median"]),
            statistics.median(float(row[4]) for row in rows),
        )

    def test_bench_json_has_documented_runs_and_summary(self):
        result = run_cli(
            "llm", "bench", "--runs", "2", "--json", env_extra=llm_env(self.server)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["runs"]), 2)
        self.assertEqual(
            set(payload["summary"]),
            {"runs", "failures", "wall_median_ms", "tok_s_median"},
        )
        self.assertEqual(payload["summary"]["runs"], 2)
        self.assertEqual(payload["summary"]["failures"], 0)
        self.assertTrue(math.isfinite(payload["summary"]["wall_median_ms"]))
        self.assertTrue(math.isfinite(payload["summary"]["tok_s_median"]))
        self.assertEqual(payload["runs"][0]["prompt_tokens"], 22)
        self.assertEqual(payload["runs"][0]["completion_tokens"], 2)

    def test_bench_rejects_run_counts_outside_the_supported_range(self):
        for runs in (0, 21):
            with self.subTest(runs=runs):
                before = self.server.request_count
                result = run_cli(
                    "llm",
                    "bench",
                    "--runs",
                    str(runs),
                    env_extra=llm_env(self.server),
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("invalid_input", result.stderr)
                self.assertEqual(self.server.request_count, before)

    def test_endpoint_and_model_overrides_beat_environment(self):
        environment = llm_env(
            self.server,
            ROSE_LLM_ENDPOINT="http://127.0.0.1:1/v1",
            ROSE_LLM_MODEL="wrong-model",
        )
        result = run_cli(
            "llm",
            "health",
            "--endpoint",
            self.server.endpoint,
            "--model",
            MODEL,
            env_extra=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(MODEL, result.stdout)

    def test_existing_commands_remain_available(self):
        for arguments in (("--version",), ("brands", "--json"), ("doctor", "--json")):
            with self.subTest(arguments=arguments):
                result = run_cli(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
