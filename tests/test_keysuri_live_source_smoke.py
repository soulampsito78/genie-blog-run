"""Tests for Kee-Suri live source-pack smoke helpers."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from keysuri_live_source_smoke import (
    SAMPLE_MARKER_PATTERNS,
    build_live_source_pack,
    run_keysuri_live_source_smoke,
    scan_sample_markers,
    FetchedFeedItem,
)
from keysuri_renderer import render_keysuri_owner_review_html

_REPO = Path(__file__).resolve().parent.parent


def _fake_items(count: int = 5) -> list[FetchedFeedItem]:
    items: list[FetchedFeedItem] = []
    for idx in range(1, count + 1):
        items.append(
            FetchedFeedItem(
                feed_id=f"feed-{idx}",
                feed_name=f"Publisher {idx}",
                feed_url=f"https://publisher{idx}.example.org/feed/",
                source_tier="T3_QUALITY_PRESS",
                default_category="market_signal",
                title=f"Live tech headline {idx} from public feed",
                link=f"https://news.publisher{idx}.org/articles/live-tech-{idx}",
                published_at="2026-06-08T12:00:00+09:00",
                summary=f"Summary for live tech headline {idx}.",
            )
        )
    return items


class KeysuriLiveSourceSmokeTests(unittest.TestCase):
    def test_sample_marker_gate_blocks_example_com(self) -> None:
        hits = scan_sample_markers("Visit https://example.com/source/global-ai-official")
        codes = {h.code for h in hits}
        self.assertIn("example_com", codes)

    def test_sample_marker_gate_blocks_fixture_ids(self) -> None:
        hits = scan_sample_markers("source_ids: global-t0-ai-official, global-t2-market-wire")
        codes = {h.code for h in hits}
        self.assertTrue({"fixture_source_id_global_t0", "fixture_source_id_market_wire"} & codes)

    def test_live_renderer_output_has_no_sample_markers(self) -> None:
        pack = build_live_source_pack("keysuri_global_tech", _fake_items())
        from keysuri_prompt_input import build_keysuri_prompt_input

        prompt_input = build_keysuri_prompt_input("keysuri_global_tech", pack)
        html = render_keysuri_owner_review_html(prompt_input, preview_mode="live_smoke")
        hits = scan_sample_markers(json.dumps(pack), html)
        self.assertEqual(hits, [], hits)
        self.assertIn("Live source smoke preview", html)
        self.assertNotIn("No live fetch", html)
        self.assertNotIn("No Gemini call", html)

    def test_no_send_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(10)

            def _fetch(feed, **kwargs):
                pick = items[(hash(feed["feed_id"]) % len(items))]
                unique = FetchedFeedItem(
                    feed_id=feed["feed_id"],
                    feed_name=feed["feed_name"],
                    feed_url=feed["feed_url"],
                    source_tier=feed["source_tier"],
                    default_category=feed["default_category"],
                    title=f"{pick.title} ({feed['feed_id']})",
                    link=f"{pick.link}/{feed['feed_id']}",
                    published_at=pick.published_at,
                    summary=pick.summary,
                )
                return [unique]

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch):
                result = run_keysuri_live_source_smoke(
                    allow_network=True,
                    out_dir=Path(tmpdir),
                    repo_root=_REPO,
                )
        self.assertFalse(result.send_attempted)
        self.assertEqual(result.send_block_reason, "send_not_requested")

    def test_send_requires_confirm(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(10)

            def _fetch(feed, **kwargs):
                pick = items[(hash(feed["feed_id"]) % len(items))]
                unique = FetchedFeedItem(
                    feed_id=feed["feed_id"],
                    feed_name=feed["feed_name"],
                    feed_url=feed["feed_url"],
                    source_tier=feed["source_tier"],
                    default_category=feed["default_category"],
                    title=f"{pick.title} ({feed['feed_id']})",
                    link=f"{pick.link}/{feed['feed_id']}",
                    published_at=pick.published_at,
                    summary=pick.summary,
                )
                return [unique]

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch):
                result = run_keysuri_live_source_smoke(
                    allow_network=True,
                    send=True,
                    send_confirm=None,
                    recipients=["soulampsito@gmail.com"],
                    out_dir=Path(tmpdir),
                    repo_root=_REPO,
                )
        self.assertFalse(result.send_success)
        self.assertEqual(result.send_block_reason, "confirm_send_missing")

    def test_build_live_source_pack_rejects_fixture_like_urls(self) -> None:
        bad = _fake_items(1)[0]
        bad.link = "https://example.com/bad"
        with self.assertRaises(ValueError):
            build_live_source_pack("keysuri_global_tech", [bad] * 5)

    def test_sample_marker_patterns_are_non_empty(self) -> None:
        self.assertGreaterEqual(len(SAMPLE_MARKER_PATTERNS), 8)


if __name__ == "__main__":
    unittest.main()
