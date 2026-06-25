from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keysuri_prompt_input import build_keysuri_prompt_input
from main import apply_today_genie_sent_news_dedup
from orchestrator import OrchestrationResult, build_run_artifact_metadata
from publishing_policy import PublishingDecision

_REPO = Path(__file__).resolve().parent.parent


def _decision() -> PublishingDecision:
    return PublishingDecision(
        send_email=True,
        create_naver_draft=False,
        auto_publish=False,
        require_review=True,
        suppress_external=False,
    )


class SentNewsDedupWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ,
            {"GENIE_SENT_NEWS_LOG_PATH": str(Path(self.tmp.name) / "sent_news_log.json")},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_today_genie_artifact_metadata_keeps_dedup_fields(self) -> None:
        runtime_input = apply_today_genie_sent_news_dedup(
            {
                "top_market_news": [
                    {"headline": "One", "url": "https://example.com/1", "source": "A", "topic_key": "one"},
                    {"headline": "Two", "url": "https://example.com/2", "source": "A", "topic_key": "two"},
                    {"headline": "Three", "url": "https://example.com/3", "source": "A", "topic_key": "three"},
                ]
            }
        )
        result = OrchestrationResult(
            decision=_decision(),
            reason_summary="ok",
            response_status=200,
            mode="today_genie",
            response_data={
                "validation_result": "pass",
                "workflow_status": "validated",
                "runtime_input": runtime_input,
            },
        )
        meta = build_run_artifact_metadata(
            result,
            run_id="20260625_090000_today_genie_aabbcc07",
            email_sent=True,
        )
        self.assertTrue(meta["used_dedup_gate"])
        self.assertEqual(meta["required_count"], 3)
        self.assertEqual(meta["selected_count"], 3)

    def test_keysuri_global_prompt_input_keeps_dedup_fields(self) -> None:
        pack = json.loads((_REPO / "ops" / "feeds" / "keysuri_global_sources.sample.json").read_text(encoding="utf-8"))
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        self.assertTrue(result["used_dedup_gate"])
        self.assertEqual(result["required_count"], 5)
        self.assertEqual(result["selected_count"], 5)

    def test_keysuri_korea_prompt_input_keeps_dedup_fields(self) -> None:
        pack = json.loads((_REPO / "ops" / "feeds" / "keysuri_korea_sources.sample.json").read_text(encoding="utf-8"))
        result = build_keysuri_prompt_input("keysuri_korea_tech", pack)
        self.assertTrue(result["used_dedup_gate"])
        self.assertEqual(result["required_count"], 5)
        self.assertEqual(result["selected_count"], 5)


if __name__ == "__main__":
    unittest.main()
