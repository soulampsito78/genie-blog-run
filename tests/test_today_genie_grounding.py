"""Unit tests for today_genie_grounding shared helper."""
from __future__ import annotations

import unittest

from today_genie_grounding import (
    anchor_phrase_for_headline,
    extract_market_entities,
    headline_grounding_anchors,
    headline_topic_tokens,
    inject_headline_grounding_into_detail,
    missing_required_anchors,
    text_covers_headline_entities,
)

SP_NASDAQ_HEADLINE = (
    "S&P 500 and Nasdaq close at new records, lifted by tech rally"
)


class TodayGenieGroundingHelperTests(unittest.TestCase):
    def test_sp500_nasdaq_headline_extracts_primary_entities(self) -> None:
        entities = extract_market_entities(SP_NASDAQ_HEADLINE)
        self.assertIn("sp500", entities)
        self.assertIn("nasdaq", entities)

    def test_korean_text_with_canonical_names_passes_coverage(self) -> None:
        text = "원문 지표 기준: S&P 500·Nasdaq 신기록, 기술주 강세. 미국 지수가 강세를 이어갔습니다."
        self.assertTrue(text_covers_headline_entities(text, SP_NASDAQ_HEADLINE))

    def test_korean_generic_us_market_fails_coverage(self) -> None:
        text = "미국 증시가 사상 최고치를 경신하며 마감했습니다."
        self.assertFalse(text_covers_headline_entities(text, SP_NASDAQ_HEADLINE))

    def test_korean_aliases_pass_coverage(self) -> None:
        text = "에스앤피500과 나스닥이 신기록을 경신했습니다."
        self.assertTrue(text_covers_headline_entities(text, SP_NASDAQ_HEADLINE))

    def test_missing_required_anchors_lists_canonical_terms(self) -> None:
        text = "미국 증시가 강세를 보였습니다."
        missing = missing_required_anchors(text, SP_NASDAQ_HEADLINE)
        self.assertIn("S&P 500", missing)
        self.assertIn("Nasdaq", missing)

    def test_anchor_phrase_includes_canonical_market_names(self) -> None:
        phrase = anchor_phrase_for_headline(SP_NASDAQ_HEADLINE)
        self.assertIn("S&P 500", phrase)
        self.assertIn("Nasdaq", phrase)
        self.assertIn("관련 보도입니다", phrase)
        self.assertNotIn("원문 지표 기준:", phrase)

    def test_headline_grounding_anchors_for_image_prompts(self) -> None:
        anchors = headline_grounding_anchors(SP_NASDAQ_HEADLINE)
        self.assertIn("S&P 500", anchors)
        self.assertIn("Nasdaq", anchors)

    def test_nikkei_mideast_ai_headline_still_grounded(self) -> None:
        headline = "Japan's Nikkei scales record peak on Mideast, AI optimism"
        entities = extract_market_entities(headline)
        self.assertIn("nikkei", entities)
        self.assertIn("mideast", entities)
        self.assertIn("ai", entities)
        text = "원문 지표 기준: Nikkei 신기록, 중동, AI. 일본 증시가 강세입니다."
        self.assertTrue(text_covers_headline_entities(text, headline))

    def test_seoul_shares_kospi_equivalence(self) -> None:
        headline = "Seoul shares close at new high on tech rally, Mideast optimism"
        text = "코스피가 기술주 강세 속 신기록을 경신했습니다."
        self.assertTrue(text_covers_headline_entities(text, headline))

    def test_topic_tokens_for_political_headline(self) -> None:
        headline = "Trump nominates Todd Blanche for attorney general amid controversy over DOJ fund"
        tokens = headline_topic_tokens(headline)
        self.assertIn("Trump", tokens)
        self.assertIn("Todd Blanche", tokens)

    def test_non_market_headline_injects_nothing_into_korean_detail(self) -> None:
        """No canonical market entity: leave the prose alone.

        Splicing English headline tokens into Korean reader copy produced the
        2026-09-07 internal keyword fragment ("U.S. Energy Secretary Wright·Iran
        관련."). The article is bound to the card by news_id, so grounding does
        not need — and must not use — a token dump on the customer surface.
        """
        headline = "Trump nominates Todd Blanche for attorney general amid controversy over DOJ fund"
        detail = "트럼프 행정부가 법무장관 후보를 지명하며 정치적 논란이 이어지고 있습니다."
        out = inject_headline_grounding_into_detail(detail, headline)
        self.assertEqual(out, detail)
        self.assertNotIn("원문 키워드", out)
        self.assertNotIn("원문 헤드라인 기준", out)
        for banned in ("Trump", "Todd", "Blanche", "DOJ"):
            self.assertNotIn(banned, out)

    def test_spacex_ipo_headline_does_not_dump_stopwords(self) -> None:
        headline = "SpaceX IPO Stock Could Face Further Delays"
        detail = "스페이스X 상장 관련 관측이 이어지고 있습니다."
        out = inject_headline_grounding_into_detail(detail, headline)
        self.assertEqual(out, detail)
        self.assertNotIn("원문 키워드", out)
        self.assertNotIn("원문 헤드라인 기준", out)
        for banned in ("SpaceX", "Could", "Face", "Further", "Stock"):
            self.assertNotIn(banned, out)

    def test_market_entity_headline_still_gets_a_canonical_korean_anchor(self) -> None:
        """Canonical index names remain legitimate grounded Korean reader copy."""
        detail = "미국 증시가 강세로 마감했습니다."
        out = inject_headline_grounding_into_detail(detail, SP_NASDAQ_HEADLINE)
        self.assertIn("S&P 500", out)
        self.assertIn("Nasdaq", out)
        self.assertIn(detail, out)


if __name__ == "__main__":
    unittest.main()
