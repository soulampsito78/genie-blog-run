from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from sent_news_log_store import (
    append_or_upsert_sent_news,
    load_sent_news_log,
    recent_sent_news_log,
    save_sent_news_log,
)


def _selected(title: str, url: str = "https://example.com/a") -> dict:
    return {
        "title": title,
        "url": url,
        "source": "Example",
        "topic_key": "topic",
        "summary": "Short summary",
    }


class SentNewsLogStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self.tmp.name) / "sent_news_log.json"
        self.env = mock.patch.dict(os.environ, {"GENIE_SENT_NEWS_LOG_PATH": str(self.log_path)}, clear=False)
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_briefing_type_logs_are_separated(self) -> None:
        now = datetime(2026, 6, 25, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        append_or_upsert_sent_news(
            run_id="r1",
            briefing_type="today_genie",
            selected_items=[_selected("Today")],
            now=now,
        )
        append_or_upsert_sent_news(
            run_id="r2",
            briefing_type="keysuri_global_tech",
            selected_items=[_selected("Global", "https://example.com/b")],
            now=now,
        )
        self.assertEqual(len(recent_sent_news_log("today_genie", now=now)), 1)
        self.assertEqual(len(recent_sent_news_log("keysuri_global_tech", now=now)), 1)

    def test_same_run_id_does_not_append_duplicate(self) -> None:
        now = datetime(2026, 6, 25, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        append_or_upsert_sent_news(
            run_id="same-run",
            briefing_type="today_genie",
            selected_items=[_selected("First")],
            now=now,
        )
        append_or_upsert_sent_news(
            run_id="same-run",
            briefing_type="today_genie",
            selected_items=[_selected("First")],
            now=now,
        )
        self.assertEqual(len(load_sent_news_log()), 1)

    def test_prunes_items_older_than_five_days(self) -> None:
        now = datetime(2026, 6, 25, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        old = now - timedelta(days=6)
        save_sent_news_log(
            [
                {
                    "run_id": "old",
                    "briefing_type": "today_genie",
                    "sent_at": old.isoformat(),
                    "canonical_url": "https://example.com/old",
                    "title": "Old",
                }
            ]
        )
        result = append_or_upsert_sent_news(
            run_id="new",
            briefing_type="today_genie",
            selected_items=[_selected("New", "https://example.com/new")],
            now=now,
        )
        self.assertEqual(result["pruned_count"], 1)
        self.assertEqual([row["run_id"] for row in load_sent_news_log()], ["new"])


if __name__ == "__main__":
    unittest.main()
