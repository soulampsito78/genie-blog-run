"""Tests for Kee-Suri Global/Korea TOP 5 news contract."""
from __future__ import annotations

import unittest

from keysuri_generation_prompt import parse_keysuri_generated_response
from keysuri_news_contract import (
    GLOBAL_NEWS_CATEGORIES,
    KOREA_CATEGORY_DISPLAY_LABELS,
    KOREA_NEWS_CATEGORIES,
    KEYSURI_TOP_NEWS_COUNT,
    NEWS_SCOPE_GLOBAL,
    NEWS_SCOPE_KOREA,
    SECTION_TOP5_GLOBAL,
    SECTION_TOP5_KOREA,
    expected_news_scope_for_program,
    expected_top5_heading_for_program,
    get_news_categories_for_program,
    select_top_5_news,
    validate_news_scope_matches_program,
    validate_top_5_news_block,
)
from keysuri_source_gate import GateResult


def _news_item(rank: int, **overrides) -> dict:
    base = {
        "rank": rank,
        "news_id": f"news-{rank}",
        "headline": f"Headline {rank}",
        "category": "ai_product",
        "summary": f"Summary {rank}",
        "why_it_matters": f"Why {rank}",
        "business_implication": f"Biz {rank}",
        "source_ids": ["src-1"],
        "confidence_label": "reported",
    }
    base.update(overrides)
    return base


def _top5_block(program_id: str, *, scope: str | None = None, heading: str | None = None) -> dict:
    scope_val = scope or expected_news_scope_for_program(program_id)
    heading_val = heading or expected_top5_heading_for_program(program_id)
    return {
        "news_scope": scope_val,
        "section_heading": heading_val,
        "items": [_news_item(i) for i in range(1, KEYSURI_TOP_NEWS_COUNT + 1)],
    }


class KeysuriNewsContractScopeTests(unittest.TestCase):
    def test_expected_scope_global(self) -> None:
        self.assertEqual(expected_news_scope_for_program("keysuri_global_tech"), NEWS_SCOPE_GLOBAL)

    def test_expected_scope_korea(self) -> None:
        self.assertEqual(expected_news_scope_for_program("keysuri_korea_tech"), NEWS_SCOPE_KOREA)

    def test_expected_heading_global(self) -> None:
        self.assertEqual(expected_top5_heading_for_program("keysuri_global_tech"), SECTION_TOP5_GLOBAL)

    def test_expected_heading_korea(self) -> None:
        self.assertEqual(expected_top5_heading_for_program("keysuri_korea_tech"), SECTION_TOP5_KOREA)


class KeysuriNewsContractValidationTests(unittest.TestCase):
    def test_global_program_korea_scope_fails(self) -> None:
        block = _top5_block("keysuri_global_tech", scope=NEWS_SCOPE_KOREA)
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertTrue(any(i["code"] == "top_5_news_scope_wrong" for i in issues))

    def test_korea_program_global_scope_fails(self) -> None:
        block = _top5_block("keysuri_korea_tech", scope=NEWS_SCOPE_GLOBAL)
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertTrue(any(i["code"] == "top_5_news_scope_wrong" for i in issues))

    def test_global_output_korea_heading_fails(self) -> None:
        block = _top5_block("keysuri_global_tech", heading=SECTION_TOP5_KOREA)
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertTrue(any(i["code"] == "top_5_news_heading_wrong" for i in issues))

    def test_korea_output_global_heading_fails(self) -> None:
        block = _top5_block("keysuri_korea_tech", heading=SECTION_TOP5_GLOBAL)
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertTrue(any(i["code"] == "top_5_news_heading_wrong" for i in issues))

    def test_generic_top5_fails(self) -> None:
        block = _top5_block("keysuri_global_tech", heading="TOP 5")
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertTrue(any("heading" in i["code"] for i in issues))

    def test_fewer_than_five_items_fails(self) -> None:
        block = _top5_block("keysuri_global_tech")
        block["items"] = block["items"][:4]
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertTrue(any(i["code"] == "top_5_news_items_too_few" for i in issues))

    def test_more_than_five_items_fails(self) -> None:
        block = _top5_block("keysuri_global_tech")
        block["items"].append(_news_item(6, news_id="news-6"))
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertTrue(any(i["code"] == "top_5_news_items_too_many" for i in issues))

    def test_invalid_rank_fails(self) -> None:
        block = _top5_block("keysuri_global_tech")
        block["items"][0]["rank"] = 9
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertTrue(any(i["code"] == "top_5_news_item_rank_invalid" for i in issues))

    def test_duplicate_rank_fails(self) -> None:
        block = _top5_block("keysuri_global_tech")
        block["items"][1]["rank"] = 1
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertTrue(any(i["code"] == "top_5_news_item_rank_duplicate" for i in issues))

    def test_missing_source_ids_fails(self) -> None:
        block = _top5_block("keysuri_global_tech")
        block["items"][0]["source_ids"] = []
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertTrue(any(i["code"] == "top_5_news_item_source_ids_missing" for i in issues))

    def test_unknown_category_fails(self) -> None:
        block = _top5_block("keysuri_global_tech")
        block["items"][0]["category"] = "not_a_category"
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertTrue(any(i["code"] == "top_5_news_item_category_unknown" for i in issues))

    def test_global_category_still_validates(self) -> None:
        block = _top5_block("keysuri_global_tech")
        block["items"][0]["category"] = "semiconductor_chip_infra"
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertFalse(any(i["code"] == "top_5_news_item_category_unknown" for i in issues))

    def test_korea_semiconductor_valid_for_korea_program(self) -> None:
        block = _top5_block("keysuri_korea_tech")
        block["items"][0]["category"] = "korea_semiconductor"
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertFalse(any(i["code"] == "top_5_news_item_category_unknown" for i in issues))

    def test_global_to_korea_translation_valid_for_korea_program(self) -> None:
        block = _top5_block("keysuri_korea_tech")
        block["items"][1]["category"] = "global_to_korea_translation"
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertFalse(any(i["code"] == "top_5_news_item_category_unknown" for i in issues))

    def test_korea_startup_investment_valid_for_korea_program(self) -> None:
        block = _top5_block("keysuri_korea_tech")
        block["items"][2]["category"] = "korea_startup_investment"
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertFalse(any(i["code"] == "top_5_news_item_category_unknown" for i in issues))

    def test_korea_big_company_strategy_valid_for_korea_program(self) -> None:
        block = _top5_block("keysuri_korea_tech")
        block["items"][3]["category"] = "korea_big_company_strategy"
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertFalse(any(i["code"] == "top_5_news_item_category_unknown" for i in issues))

    def test_korea_category_rejected_for_global_program(self) -> None:
        block = _top5_block("keysuri_global_tech")
        block["items"][0]["category"] = "korea_semiconductor"
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertTrue(any(i["code"] == "top_5_news_item_category_unknown" for i in issues))

    def test_all_korea_categories_have_display_labels(self) -> None:
        for slug in KOREA_NEWS_CATEGORIES:
            self.assertIn(slug, KOREA_CATEGORY_DISPLAY_LABELS)
            self.assertTrue(KOREA_CATEGORY_DISPLAY_LABELS[slug].strip())

    def test_get_news_categories_for_program_korea_includes_legacy_global(self) -> None:
        allowed = get_news_categories_for_program("keysuri_korea_tech")
        self.assertIn("korea_semiconductor", allowed)
        self.assertIn("policy", allowed)
        self.assertNotIn("korea_semiconductor", get_news_categories_for_program("keysuri_global_tech"))

    def test_plain_list_fails(self) -> None:
        issues = validate_top_5_news_block("keysuri_global_tech", [])
        self.assertTrue(any(i["code"] == "top_5_news_must_be_object" for i in issues))

    def test_source_pack_program_mismatch(self) -> None:
        issues = validate_news_scope_matches_program(
            "keysuri_global_tech",
            source_pack={"program_id": "keysuri_korea_tech"},
            top_5_news=_top5_block("keysuri_global_tech"),
        )
        self.assertTrue(any(i["code"] == "source_pack_program_mismatch" for i in issues))


class KeysuriKoreaCategoryParseTests(unittest.TestCase):
    def test_parsed_korea_gemini_like_response_accepts_korea_categories(self) -> None:
        categories = [
            "korea_semiconductor",
            "korea_semiconductor",
            "global_to_korea_translation",
            "korea_startup_investment",
            "korea_big_company_strategy",
        ]
        items = []
        for rank, category in enumerate(categories, start=1):
            items.append(
                {
                    "rank": rank,
                    "news_id": f"claim-live-korea-{rank}",
                    "headline": f"Korea headline {rank}",
                    "category": category,
                    "summary": f"Summary {rank}",
                    "why_it_matters": f"Why {rank}",
                    "business_implication": f"Biz {rank}",
                    "source_ids": [f"live-src-{rank}"],
                    "confidence_label": "reported",
                }
            )
        raw = {
            "program_id": "keysuri_korea_tech",
            "generated_status": "generated_review_required",
            "operational_status": "review_required",
            "news_scope": "korea",
            "section_heading": "국내 테크 TOP 5",
            "top_5_news": {
                "news_scope": "korea",
                "section_heading": "국내 테크 TOP 5",
                "items": items,
            },
            "deep_dive": {
                "section_heading": "키수리의 딥-다이브",
                "body": "한국 기업·정책으로 읽으면 오늘 국내 반도체와 AI 흐름이 핵심입니다.",
                "confirmed_facts": ["Fact one"],
                "key_implications": ["Domestic supply-chain read-through"],
                "interpretation": "Domestic interpretation.",
                "owner_impact": "Owner impact.",
                "uncertainty": [],
                "source_ids": ["live-src-1"],
                "confidence_label": "reported",
            },
            "one_line_checkpoint": {
                "section_heading": "원-라인 체크포인트",
                "body": "Checkpoint line.",
            },
            "closing_sources": {
                "section_heading": "마무리 및 출처 리스트",
                "closing_message": "퇴근 전 메모로 정리했습니다.",
                "source_list": [
                    {
                        "source_id": "live-src-1",
                        "label": "더lec",
                        "source_name": "더lec",
                        "source_url": "https://example.com/1",
                    }
                ],
            },
        }
        import json

        prompt_input = {
            "program_id": "keysuri_korea_tech",
            "top_5_news": raw["top_5_news"],
            "source_pack": {"program_id": "keysuri_korea_tech", "claims": [], "sources": []},
        }
        result = parse_keysuri_generated_response(
            json.dumps(raw, ensure_ascii=False),
            "keysuri_korea_tech",
            prompt_input,
        )
        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        self.assertFalse(
            any(i.get("code") == "top_5_news_item_category_unknown" for i in (result.get("issues") or []))
        )


class KeysuriNewsSelectionTests(unittest.TestCase):
    def _pack_with_claims(self, n: int, *, business_implication: bool = True) -> dict:
        claims = []
        for i in range(n):
            claim = {
                "claim_id": f"c{i + 1}",
                "statement": f"Statement {i + 1}",
                "claim_type": "general",
                "source_ids": ["src-t2"],
                "confidence_label": "reported",
                "news_category": "startup",
            }
            if business_implication:
                claim["business_implication"] = f"Biz impl {i + 1}"
            claims.append(claim)
        return {
            "program_id": "keysuri_global_tech",
            "sources": [
                {
                    "source_id": "src-t2",
                    "source_name": "Example Wire",
                    "source_url": "https://example.com/source/wire",
                    "source_tier": "T2_TIER1_WIRE",
                    "fetched_at": "2026-06-04T10:00:00+09:00",
                }
            ],
            "claims": claims,
        }

    def test_blocked_gate_raises(self) -> None:
        gate = GateResult(verdict="block", issues=())
        with self.assertRaises(ValueError):
            select_top_5_news(self._pack_with_claims(5), gate)

    def test_insufficient_candidates_hold(self) -> None:
        gate = GateResult(verdict="pass", issues=())
        result = select_top_5_news(self._pack_with_claims(3), gate)
        self.assertEqual(result["verdict"], "hold")
        self.assertTrue(
            any(i["code"] == "insufficient_top_news_candidates" for i in result["issues"])
        )

    def test_missing_business_implication_hold(self) -> None:
        gate = GateResult(verdict="pass", issues=())
        result = select_top_5_news(self._pack_with_claims(5, business_implication=False), gate)
        self.assertEqual(result["verdict"], "hold")
        self.assertTrue(
            any(i["code"] == "business_implication_missing" for i in result["issues"])
        )

    def test_five_qualified_candidates_pass(self) -> None:
        gate = GateResult(verdict="pass", issues=())
        result = select_top_5_news(self._pack_with_claims(5), gate)
        self.assertEqual(result["verdict"], "pass")
        top5 = result["top_5_news"]
        self.assertEqual(top5["news_scope"], NEWS_SCOPE_GLOBAL)
        self.assertEqual(top5["section_heading"], SECTION_TOP5_GLOBAL)
        self.assertEqual(len(top5["items"]), 5)
        self.assertEqual([item["rank"] for item in top5["items"]], [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
