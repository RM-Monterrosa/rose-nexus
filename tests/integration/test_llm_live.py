"""Optional live integration with the local model.

Skipped automatically when the tunnel is down, so the default suite never needs
the model. Run explicitly with ROSE_LLM_ENABLED=true.
"""

import os
import unittest
import urllib.request

from rose_nexus.ai.client import InferenceClient
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


if __name__ == "__main__":
    unittest.main()
