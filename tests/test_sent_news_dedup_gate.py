from __future__ import annotations

import unittest

from sent_news_dedup_gate import (
    canonicalize_url,
    normalize_title,
    run_sent_news_dedup_gate,
)


def _item(idx: int, **overrides):
    data = {
        "title": f"Fresh AI headline {idx}",
        "url": f"https://example.com/news/{idx}",
        "source": "Example",
        "topic_key": f"topic-{idx}",
        "summary": f"Summary {idx}",
    }
    data.update(overrides)
    return data


def _item_without_topic(idx: int, **overrides):
    data = _item(idx, **overrides)
    data.pop("topic_key", None)
    return data


class SentNewsDedupGateTests(unittest.TestCase):
    def test_canonical_url_removes_tracking(self) -> None:
        self.assertEqual(
            canonicalize_url("HTTPS://Example.COM/path/?utm_source=x&a=1#frag"),
            "https://example.com/path?a=1",
        )

    def test_normalized_title_removes_noise(self) -> None:
        self.assertEqual(normalize_title("[속보] AI 투자 확대!!!"), "ai 투자 확대")

    def test_recent_log_canonical_url_duplicate_rejected(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="today_genie",
            candidates=[_item(1, url="https://example.com/a?utm_source=x"), _item(2)],
            sent_log_last_5_days=[_item(9, url="https://example.com/a")],
            required_count=1,
        )
        self.assertEqual(result["rejected_items"][0]["rejected_reason"], "recent_log_canonical_url_duplicate")

    def test_recent_log_normalized_title_duplicate_rejected(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="today_genie",
            candidates=[_item(1, title="[단독] Same Title"), _item(2)],
            sent_log_last_5_days=[_item(9, title="Same Title")],
            required_count=1,
        )
        self.assertEqual(result["rejected_items"][0]["rejected_reason"], "recent_log_normalized_title_duplicate")

    def test_recent_log_source_similar_title_duplicate_rejected(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="today_genie",
            candidates=[_item(1, source="Wire", title="OpenAI launches enterprise agent platform"), _item(2)],
            sent_log_last_5_days=[_item(9, source="Wire", title="OpenAI launches enterprise agents platform")],
            required_count=1,
        )
        self.assertEqual(result["rejected_items"][0]["rejected_reason"], "recent_log_source_similar_title_duplicate")

    def test_recent_log_topic_key_duplicate_rejected(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="keysuri_global_tech",
            candidates=[_item(1, topic_key="chips"), _item(2)],
            sent_log_last_5_days=[_item(9, topic_key="chips")],
            required_count=1,
        )
        self.assertEqual(result["rejected_items"][0]["rejected_reason"], "recent_log_topic_key_duplicate")

    def test_same_category_does_not_count_as_topic_duplicate(self) -> None:
        candidates = [
            _item_without_topic(
                idx,
                category="ai_product",
                title=f"Different headline {idx}",
                url=f"https://example.com/different/{idx}",
                source=f"Source {idx}",
            )
            for idx in range(1, 6)
        ]
        result = run_sent_news_dedup_gate(
            briefing_type="keysuri_global_tech",
            candidates=candidates,
            sent_log_last_5_days=[],
            required_count=5,
        )
        self.assertEqual(len(result["selected_items"]), 5)
        self.assertEqual(result["rejected_items"], [])

    def test_missing_topic_key_uses_url_title_source_only(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="keysuri_global_tech",
            candidates=[
                _item_without_topic(1, category="policy", title="Policy headline", url="https://example.com/a"),
                _item_without_topic(2, category="policy", title="Funding headline", url="https://example.com/b"),
            ],
            sent_log_last_5_days=[
                _item_without_topic(9, category="policy", title="Old unrelated headline", url="https://example.com/old")
            ],
            required_count=2,
        )
        self.assertEqual(len(result["selected_items"]), 2)
        self.assertNotIn("recent_log_topic_key_duplicate", result["dedup_summary"]["rejected_by_reason"])

    def test_selected_internal_duplicate_rejected(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="keysuri_korea_tech",
            candidates=[_item(1, title="Same"), _item(2, title="Same", url="https://example.com/other"), _item(3)],
            sent_log_last_5_days=[],
            required_count=2,
        )
        reasons = [item["rejected_reason"] for item in result["rejected_items"]]
        self.assertIn("selected_normalized_title_duplicate", reasons)

    def test_next_candidate_promoted_to_fill_required_count(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="keysuri_global_tech",
            candidates=[
                _item(1, url="https://dup.example/a"),
                _item(2, title="Semiconductor capex expands"),
                _item(3, title="Cloud security spending rises"),
            ],
            sent_log_last_5_days=[_item(9, url="https://dup.example/a")],
            required_count=2,
        )
        self.assertEqual([item["title"] for item in result["selected_items"]], ["Semiconductor capex expands", "Cloud security spending rises"])
        self.assertTrue(result["dedup_summary"]["filled_required_count"])

    def test_insufficient_fresh_candidates_records_shortfall(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="keysuri_korea_tech",
            candidates=[_item(1)],
            sent_log_last_5_days=[],
            required_count=2,
        )
        self.assertEqual(result["dedup_summary"]["selected_count"], 1)
        self.assertEqual(result["dedup_summary"]["reason"], "insufficient_fresh_candidates")


if __name__ == "__main__":
    unittest.main()
