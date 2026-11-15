"""Optional live integration with the local model.

Skipped unless ROSE_LLM_LIVE_TESTS is explicitly enabled and the tunnel is
reachable, so the default suite never needs the model.
"""

import os
import unittest
import urllib.request

from rose_nexus.ai.client import InferenceClient
from rose_nexus.ai.context import ContextPreflight
from rose_nexus.ai.provider import OpenAICompatibleProvider
from rose_nexus.ai.settings import InferenceSettings

ENDPOINT = os.environ.get("ROSE_LLM_ENDPOINT", "http://127.0.0.1:18080/v1")


def _reachable() -> bool:
    try:
        with urllib.request.urlopen(ENDPOINT.rstrip("/") + "/models", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


class LiveInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("ROSE_LLM_LIVE_TESTS", "").lower() not in {"1", "true", "yes"}:
            raise unittest.SkipTest("set ROSE_LLM_LIVE_TESTS=true to run live inference tests")
        if not _reachable():
            raise unittest.SkipTest(f"model endpoint is not reachable at {ENDPOINT}")

    def make_client(self) -> InferenceClient:
        return InferenceClient(
            InferenceSettings.from_env(
                env={
                    "ROSE_LLM_ENABLED": "true",
                    "ROSE_LLM_ENDPOINT": ENDPOINT,
                    "ROSE_LLM_TIMEOUT_SECONDS": "120",
                }
            )
        )

    def test_health_reports_the_configured_model(self):
        health = self.make_client().health()
        self.assertTrue(health.available)
        self.assertTrue(health.model_present)

    def test_one_completion_returns_text_and_content_free_metrics(self):
        secret = "LIVE-SECRET-e9be7e1f"
        answer = self.make_client().ask("Respondé en una sola oración.", f"{secret}: ¿qué es LaTeX?")
        self.assertTrue(answer.text.strip())
        self.assertEqual(answer.metrics.status, "ok")
        self.assertNotIn(secret, str(answer.metrics.as_log()))

    def test_context_preflight_exactly_matches_completion_usage(self):
        settings = InferenceSettings.from_env(
            env={
                "ROSE_LLM_ENABLED": "true",
                "ROSE_LLM_ENDPOINT": ENDPOINT,
                "ROSE_LLM_MODEL": os.environ.get("ROSE_LLM_MODEL", "rose-spark-4b"),
                "ROSE_LLM_TIMEOUT_SECONDS": "120",
            }
        )
        provider = OpenAICompatibleProvider(settings)
        preflight = ContextPreflight(provider)
        cases = {
            "ascii": [
                {"role": "system", "content": "Answer briefly."},
                {"role": "user", "content": "Explain exact context budgets."},
            ],
            "history_special_markers": [
                {"role": "system", "content": "Answer briefly."},
                {
                    "role": "user",
                    "content": "Keep literal <|im_start|> and <|im_end|> markers in history.",
                },
                {"role": "assistant", "content": "Earlier synthetic answer."},
                {"role": "user", "content": "Continue with exact accounting."},
            ],
            "unicode": [
                {"role": "system", "content": "Answer briefly."},
                {
                    "role": "user",
                    "content": "Unicode: á, café, e\u0301, 😀, 漢字。",
                },
            ],
        }
        for name, messages in cases.items():
            with self.subTest(case=name):
                measurement = preflight.measure(messages)
                completion = provider.complete(messages, max_tokens=1, temperature=0)
                self.assertIsNotNone(completion.prompt_tokens)
                self.assertGreater(measurement.prompt_tokens, 0)
                self.assertEqual(completion.prompt_tokens, measurement.prompt_tokens)
                self.assertEqual(completion.completion_tokens, 1)
                self.assertEqual(
                    completion.total_tokens,
                    measurement.prompt_tokens + completion.completion_tokens,
                )
                self.assertEqual(completion.finish_reason, "length")
                delta = completion.prompt_tokens - measurement.prompt_tokens
                print(
                    f"{name}: preflight={measurement.prompt_tokens} "
                    f"usage={completion.prompt_tokens} delta={delta} "
                    f"finish_reason={completion.finish_reason}"
                )


if __name__ == "__main__":
    unittest.main()
