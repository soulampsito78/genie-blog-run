"""Tests for Kee-Suri offline owner-review HTML renderer."""
from __future__ import annotations

import json
import re
import unittest
from copy import deepcopy
from pathlib import Path

from keysuri_news_contract import SECTION_TOP5_GLOBAL, SECTION_TOP5_KOREA
from keysuri_generated_briefing import (
    GENERATED_STATUS_REQUIRED,
    load_keysuri_generated_briefing_fixture,
)
from keysuri_private_briefing import SECTION_CLOSING, SECTION_DEEP_DIVE, SECTION_ONE_LINE
from keysuri_renderer import (
    GENERATION_PENDING_LABEL,
    IDENTITY_TITLE,
    load_keysuri_prompt_input_fixture,
    render_keysuri_owner_review_html,
    render_keysuri_top5_section,
)

_REPO = Path(__file__).resolve().parent.parent


def _load_fixture(name: str) -> dict:
    return load_keysuri_prompt_input_fixture(str(_REPO / "ops" / "feeds" / name))


class KeysuriRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.global_html = render_keysuri_owner_review_html(
            _load_fixture("keysuri_global_prompt_input.sample.json")
        )
        self.korea_html = render_keysuri_owner_review_html(
            _load_fixture("keysuri_korea_prompt_input.sample.json")
        )

    def test_renders_complete_html(self) -> None:
        self.assertIn("<!DOCTYPE html>", self.global_html)
        self.assertIn("</html>", self.global_html)
        self.assertIn("<body>", self.global_html)

    def test_identity_title_present(self) -> None:
        self.assertIn("테크 비서 키수리", self.global_html)
        self.assertIn(IDENTITY_TITLE, self.global_html)

    def test_forbidden_anchor_identity_absent(self) -> None:
        for bad in ("테크 앵커", "뉴스 앵커", "아나운서"):
            with self.subTest(term=bad):
                self.assertNotIn(bad, self.global_html)
                self.assertNotIn(bad, self.korea_html)

    def test_private_tech_wording(self) -> None:
        self.assertIn("프라이빗 테크", self.global_html)

    def test_footer_markers(self) -> None:
        for marker in (
            "Owner Review Preview",
            "No email sent",
            "No live fetch",
            "No Gemini call",
            "review_required",
            "Private Tech Secretary Preview",
        ):
            self.assertIn(marker, self.global_html)

    def test_global_top5_heading(self) -> None:
        self.assertIn(SECTION_TOP5_GLOBAL, self.global_html)
        self.assertIn('class="top5-section-heading"', self.global_html)
        self.assertIn(f">{SECTION_TOP5_GLOBAL}</h2>", self.global_html)

    def test_korea_top5_heading(self) -> None:
        self.assertIn(SECTION_TOP5_KOREA, self.korea_html)
        self.assertIn(f">{SECTION_TOP5_KOREA}</h2>", self.korea_html)

    def test_global_does_not_use_korea_as_active_top5_heading(self) -> None:
        self.assertNotRegex(
            self.global_html,
            r'<h2[^>]*class="top5-section-heading"[^>]*>\s*' + re.escape(SECTION_TOP5_KOREA),
        )

    def test_korea_does_not_use_global_as_active_top5_heading(self) -> None:
        self.assertNotRegex(
            self.korea_html,
            r'<h2[^>]*class="top5-section-heading"[^>]*>\s*' + re.escape(SECTION_TOP5_GLOBAL),
        )

    def test_exactly_five_news_cards_global(self) -> None:
        self.assertEqual(len(re.findall(r'class="news-card"', self.global_html)), 5)

    def test_exactly_five_news_cards_korea(self) -> None:
        self.assertEqual(len(re.findall(r'class="news-card"', self.korea_html)), 5)

    def test_source_gate_and_selection_audit(self) -> None:
        self.assertIn("source_gate_result", self.global_html)
        self.assertIn("top_5_selection_result", self.global_html)
        self.assertIn("Source Gate / TOP 5 Selection Audit", self.global_html)

    def test_generation_pending_placeholders(self) -> None:
        self.assertIn("generation_pending", self.global_html)
        self.assertIn("Gemini 호출 전", self.global_html)
        self.assertIn("최종 문안 아님", self.global_html)
        self.assertIn("키수리의 딥-다이브", self.global_html)

    def test_escapes_unsafe_html(self) -> None:
        pack = deepcopy(_load_fixture("keysuri_global_prompt_input.sample.json"))
        top = pack["top_5_news"]
        top["items"][0]["headline"] = '<script>alert("x")</script>'
        top["items"][0]["summary"] = "<img onerror=alert(1)>"
        section = render_keysuri_top5_section(pack)
        self.assertNotIn("<script>", section)
        self.assertIn("&lt;script&gt;", section)
        self.assertNotIn("<img onerror", section)

    def test_no_external_assets(self) -> None:
        for html in (self.global_html, self.korea_html):
            self.assertNotIn("<script", html.lower())
            self.assertNotIn("http://", html)
            self.assertNotIn("https://", html)
            self.assertNotIn("tracking", html.lower())

    def test_scheduler_active_only_three_programs(self) -> None:
        self.assertIn("Today_Geenee", self.global_html)
        self.assertIn("06:30 KST", self.global_html)
        self.assertIn("Kee-Suri Global Tech", self.global_html)
        self.assertIn("12:30 KST", self.global_html)
        self.assertIn("Kee-Suri Korea Tech", self.global_html)
        self.assertIn("18:30 KST", self.global_html)

    def test_tomorrow_geenee_not_rendered(self) -> None:
        for html in (self.global_html, self.korea_html):
            self.assertNotIn("Tomorrow_Geenee", html)
            self.assertNotIn("tomorrow_genie", html)
            self.assertNotIn("Tomorrow_Geenee", html)
            # No 18:00-only tomorrow slot
            self.assertNotRegex(html, r"18:00\s*KST")


class KeysuriRendererFixtureLoaderTests(unittest.TestCase):
    def test_load_fixture(self) -> None:
        data = _load_fixture("keysuri_global_prompt_input.sample.json")
        self.assertEqual(data["program_id"], "keysuri_global_tech")


def _load_generated(name: str) -> dict:
    return load_keysuri_generated_briefing_fixture(
        str(_REPO / "ops" / "feeds" / name)
    )


class KeysuriRendererGeneratedModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.global_prompt = _load_fixture("keysuri_global_prompt_input.sample.json")
        self.global_gen = _load_generated("keysuri_global_generated_briefing.sample.json")
        self.global_html = render_keysuri_owner_review_html(
            self.global_prompt, self.global_gen
        )

    def test_placeholder_mode_still_has_generation_pending(self) -> None:
        html = render_keysuri_owner_review_html(self.global_prompt)
        self.assertIn(GENERATION_PENDING_LABEL, html)
        self.assertIn("badge-pending", html)

    def test_generated_mode_no_generation_pending_placeholders(self) -> None:
        self.assertNotRegex(
            self.global_html,
            r'<section class="card placeholder-section"',
        )
        self.assertNotIn(GENERATION_PENDING_LABEL, self.global_html)
        self.assertNotIn("Gemini 호출 전 · 최종 문안 아님", self.global_html)

    def test_generated_mode_renders_deep_dive_body(self) -> None:
        body = self.global_gen["deep_dive"]["body"]
        self.assertIn(SECTION_DEEP_DIVE, self.global_html)
        self.assertIn(body[:40], self.global_html)

    def test_generated_mode_renders_one_line_body(self) -> None:
        body = self.global_gen["one_line_checkpoint"]["body"]
        self.assertIn(SECTION_ONE_LINE, self.global_html)
        self.assertIn(body[:30], self.global_html)

    def test_generated_mode_renders_closing_sources(self) -> None:
        self.assertIn(SECTION_CLOSING, self.global_html)
        self.assertIn("source-card", self.global_html)
        self.assertIn(
            self.global_gen["closing_sources"]["closing_message"][:30],
            self.global_html,
        )

    def test_generated_mode_shows_generated_review_required(self) -> None:
        self.assertIn(GENERATED_STATUS_REQUIRED, self.global_html)
        self.assertIn("badge-generated", self.global_html)

    def test_generated_mode_keeps_owner_review_preview(self) -> None:
        self.assertIn("Owner Review Preview", self.global_html)

    def test_generated_mode_keeps_offline_footer(self) -> None:
        for marker in ("No email sent", "No live fetch", "No Gemini call"):
            self.assertIn(marker, self.global_html)

    def test_generated_mode_escapes_unsafe_text(self) -> None:
        bad_gen = deepcopy(self.global_gen)
        bad_gen["deep_dive"]["body"] = '<script>alert("x")</script>'
        html = render_keysuri_owner_review_html(self.global_prompt, bad_gen)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_generated_mode_rejects_invalid_briefing(self) -> None:
        bad_gen = deepcopy(self.global_gen)
        bad_gen["deep_dive"]["body"] = ""
        with self.assertRaises(ValueError) as ctx:
            render_keysuri_owner_review_html(self.global_prompt, bad_gen)
        self.assertIn("Invalid generated briefing", str(ctx.exception))

    def test_generated_html_identity_guard(self) -> None:
        for bad in ("테크 앵커", "뉴스 앵커", "아나운서"):
            self.assertNotIn(bad, self.global_html)

    def test_generated_html_retired_guard(self) -> None:
        self.assertNotIn("Tomorrow_Geenee", self.global_html)
        self.assertNotIn("tomorrow_genie", self.global_html)
        self.assertNotRegex(self.global_html, r"18:00\s*KST")


if __name__ == "__main__":
    unittest.main()
