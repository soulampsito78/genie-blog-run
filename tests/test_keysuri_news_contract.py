"""Tests for Kee-Suri Global/Korea TOP 5 news contract."""
from __future__ import annotations

import unittest

from keysuri_news_contract import (
    KEYSURI_TOP_NEWS_COUNT,
    NEWS_SCOPE_GLOBAL,
    NEWS_SCOPE_KOREA,
    SECTION_TOP5_GLOBAL,
    SECTION_TOP5_KOREA,
    expected_news_scope_for_program,
    expected_top5_heading_for_program,
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
