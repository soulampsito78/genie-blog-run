"""Tests for Kee-Suri prompt profiles (TOP 5 news contract + fixed labels)."""
from __future__ import annotations

import unittest

from keysuri_news_contract import NEWS_SCOPE_GLOBAL, NEWS_SCOPE_KOREA
from keysuri_private_briefing import (
    SECTION_CLOSING,
    SECTION_DEEP_DIVE,
    SECTION_ONE_LINE,
    SECTION_TOP5_GLOBAL,
    SECTION_TOP5_KOREA,
)
from keysuri_prompt_profiles import (
    KEYSURI_GLOBAL_TECH_V1,
    KEYSURI_KOREA_TECH_V1,
    get_keysuri_prompt_profile,
)


class KeysuriPromptProfileTests(unittest.TestCase):
    def test_global_profile_news_scope_global(self) -> None:
        text = get_keysuri_prompt_profile("keysuri_global_tech_v1")
        self.assertIn(f'news_scope = "{NEWS_SCOPE_GLOBAL}"', text)
        self.assertIn(SECTION_TOP5_GLOBAL, text)

    def test_korea_profile_news_scope_korea(self) -> None:
        text = get_keysuri_prompt_profile("keysuri_korea_tech_v1")
        self.assertIn(f'news_scope = "{NEWS_SCOPE_KOREA}"', text)
        self.assertIn(SECTION_TOP5_KOREA, text)

    def test_global_profile_forbids_korea_heading(self) -> None:
        text = get_keysuri_prompt_profile("keysuri_global_tech_v1")
        self.assertIn("국내 테크 TOP 5", text)
        self.assertIn("출력 금지", text)

    def test_korea_profile_forbids_global_heading(self) -> None:
        text = get_keysuri_prompt_profile("keysuri_korea_tech_v1")
        self.assertIn("글로벌 테크 TOP 5", text)
        self.assertIn("출력 금지", text)

    def test_both_profiles_forbid_top3(self) -> None:
        self.assertIn("TOP 3", KEYSURI_GLOBAL_TECH_V1)
        self.assertIn("TOP 3", KEYSURI_KOREA_TECH_V1)

    def test_global_profile_fixed_korean_labels(self) -> None:
        text = get_keysuri_prompt_profile("keysuri_global_tech_v1")
        self.assertIn(SECTION_DEEP_DIVE, text)
        self.assertIn(SECTION_ONE_LINE, text)
        self.assertIn(SECTION_CLOSING, text)
        self.assertIn("review_required", text)

    def test_korea_profile_fixed_korean_labels(self) -> None:
        text = get_keysuri_prompt_profile("keysuri_korea_tech_v1")
        self.assertIn(SECTION_DEEP_DIVE, text)
        self.assertIn(SECTION_ONE_LINE, text)
        self.assertIn(SECTION_CLOSING, text)

    def test_profiles_forbid_renamed_labels(self) -> None:
        self.assertIn("심층 분석", KEYSURI_GLOBAL_TECH_V1)
        self.assertIn("핵심 요약", KEYSURI_GLOBAL_TECH_V1)
        self.assertIn('generic "TOP 5" 금지', KEYSURI_KOREA_TECH_V1)

    def test_profiles_forbid_unsupported_content(self) -> None:
        for text in (KEYSURI_GLOBAL_TECH_V1, KEYSURI_KOREA_TECH_V1):
            self.assertIn("fake sources", text)
            self.assertIn("Naver paste body", text)
            self.assertIn("attachment package", text)


if __name__ == "__main__":
    unittest.main()
