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

    def test_korea_schema_example_contains_news_scope(self) -> None:
        from keysuri_private_briefing import keysuri_output_schema_example
        schema = keysuri_output_schema_example("keysuri_korea_tech")
        self.assertIn("news_scope", schema["top_5_news"])
        self.assertEqual(schema["top_5_news"]["news_scope"], NEWS_SCOPE_KOREA)


class KeysuriNewsContractValidationTests(unittest.TestCase):
    def test_missing_korea_news_scope_is_repaired(self) -> None:
        block = _top5_block("keysuri_korea_tech")
        del block["news_scope"]  # Remove news_scope
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertFalse(any(i["code"] == "top_5_news_scope_missing" for i in issues))
        self.assertEqual(block["news_scope"], NEWS_SCOPE_KOREA)
        self.assertTrue(block.get("_repaired_news_scope"))

    def test_missing_global_news_scope_fails(self) -> None:
        block = _top5_block("keysuri_global_tech")
        del block["news_scope"]
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertTrue(any(i["code"] == "top_5_news_scope_missing" for i in issues))
        self.assertNotIn("_repaired_news_scope", block)
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


class KeysuriNewsSelectionDiversityTests(unittest.TestCase):
    """Source/url hydration + intra-briefing same-source cap at selection."""

    def _pack(self) -> dict:
        sources = [
            {"source_id": "s-nvidia", "source_name": "NVIDIA Blog",
             "source_url": "https://blogs.nvidia.com/blog/aws-scale/", "source_tier": "T2_TIER1_WIRE"},
            {"source_id": "s-tc", "source_name": "TechCrunch AI",
             "source_url": "https://techcrunch.com/patronus/", "source_tier": "T2_TIER1_WIRE"},
            {"source_id": "s-dc", "source_name": "Datacenter Dynamics",
             "source_url": "https://www.datacenterdynamics.com/openai-chip/", "source_tier": "T2_TIER1_WIRE"},
            {"source_id": "s-goog", "source_name": "Google AI Blog",
             "source_url": "https://blog.google/finance-app/", "source_tier": "T2_TIER1_WIRE"},
            {"source_id": "s-reuters", "source_name": "Reuters",
             "source_url": "https://www.reuters.com/msft-cloud/", "source_tier": "T2_TIER1_WIRE"},
        ]
        specs = [
            ("c1", "s-nvidia", "NVIDIA and AWS Collaborate to Bring AI to Production at Scale"),
            ("c2", "s-tc", "Patronus AI lands $50M to stress-test AI agents"),
            ("c3", "s-nvidia", "How Businesses Are Building Specialized AI They Can Trust"),
            ("c4", "s-dc", "OpenAI partners with semiconductor firms on chip design"),
            ("c5", "s-goog", "Our latest Google Finance upgrades, including a new app"),
            ("c6", "s-reuters", "Microsoft expands enterprise cloud security suite"),
        ]
        claims = [
            {
                "claim_id": cid,
                "headline": headline,
                "statement": headline,
                "claim_type": "general",
                "source_ids": [sid],
                "confidence_label": "reported",
                "news_category": "startup",
                "business_implication": f"Biz impl {cid}",
            }
            for cid, sid, headline in specs
        ]
        return {"program_id": "keysuri_global_tech", "sources": sources, "claims": claims}

    def test_source_url_metadata_hydrated_onto_items(self) -> None:
        result = select_top_5_news(self._pack(), GateResult(verdict="pass", issues=()))
        items = result["top_5_news"]["items"]
        for item in items:
            self.assertTrue(item["source"], f"source empty for {item['news_id']}")
            self.assertTrue(item["url"], f"url empty for {item['news_id']}")
            self.assertTrue(item["canonical_url"], f"canonical_url empty for {item['news_id']}")
            self.assertTrue(item["normalized_source"], f"normalized_source empty for {item['news_id']}")
            self.assertNotEqual(item["source_domain"], "")
        nvidia = next(it for it in items if it["news_id"] == "c1")
        self.assertEqual(nvidia["source"], "NVIDIA Blog")
        self.assertEqual(nvidia["normalized_source"], "nvidia blog")
        self.assertEqual(nvidia["canonical_url"], "https://blogs.nvidia.com/blog/aws-scale")
        self.assertEqual(nvidia["source_domain"], "blogs.nvidia.com")

    def test_two_same_source_items_collapse_to_one_with_replacement(self) -> None:
        result = select_top_5_news(self._pack(), GateResult(verdict="pass", issues=()))
        items = result["top_5_news"]["items"]
        ids = [it["news_id"] for it in items]
        self.assertEqual(len(items), 5)
        nvidia_items = [it for it in items if it["normalized_source"] == "nvidia blog"]
        self.assertEqual(len(nvidia_items), 1)
        self.assertIn("c1", ids)
        self.assertNotIn("c3", ids)  # second NVIDIA Blog post replaced by c6
        self.assertIn("c6", ids)
        self.assertEqual([it["rank"] for it in items], [1, 2, 3, 4, 5])

    def test_non_nvidia_same_source_rejects_and_promotes_replacement(self) -> None:
        pack = self._pack()
        for src in pack["sources"]:
            if src["source_id"] == "s-nvidia":
                src["source_name"] = "OpenAI Blog"
                src["source_url"] = "https://openai.com/blog/agent-platform/"
        pack["claims"][0]["headline"] = "OpenAI ships new agent platform"
        pack["claims"][0]["statement"] = "OpenAI ships new agent platform"
        pack["claims"][2]["headline"] = "OpenAI updates developer model router"
        pack["claims"][2]["statement"] = "OpenAI updates developer model router"
        pack["claims"][3]["headline"] = "Datacenter firms expand AI chip design capacity"
        pack["claims"][3]["statement"] = "Datacenter firms expand AI chip design capacity"

        result = select_top_5_news(pack, GateResult(verdict="pass", issues=()))
        items = result["top_5_news"]["items"]
        ids = [it["news_id"] for it in items]
        self.assertEqual(len(items), 5)
        self.assertEqual([it for it in items if it["normalized_source"] == "openai blog"][0]["news_id"], "c1")
        self.assertNotIn("c3", ids)
        self.assertIn("c6", ids)
        rejected = [r for r in result["diversity_rejected_items"] if r["news_id"] == "c3"]
        self.assertEqual(rejected[0]["rejected_reason"], "same_source_cap")

    def test_non_nvidia_entity_rejects_and_promotes_replacement(self) -> None:
        pack = self._pack()
        pack["sources"].append(
            {
                "source_id": "s-meta",
                "source_name": "Meta AI Blog",
                "source_url": "https://ai.meta.com/blog/dataset/",
                "source_tier": "T2_TIER1_WIRE",
            }
        )
        specs = [
            ("c1", "s-tc", "OpenAI ships new agent platform"),
            ("c2", "s-dc", "Open AI updates developer model router"),
            ("c3", "s-goog", "Google Finance upgrades arrive with a new app"),
            ("c4", "s-reuters", "Microsoft expands enterprise cloud security suite"),
            ("c5", "s-nvidia", "Apple updates developer AI tools"),
            ("c6", "s-meta", "Meta open-sources enterprise AI dataset"),
        ]
        for claim, (_cid, sid, headline) in zip(pack["claims"], specs):
            claim["source_ids"] = [sid]
            claim["headline"] = headline
            claim["statement"] = headline

        result = select_top_5_news(pack, GateResult(verdict="pass", issues=()))
        ids = [it["news_id"] for it in result["top_5_news"]["items"]]
        self.assertEqual(len(ids), 5)
        self.assertIn("c1", ids)
        self.assertNotIn("c2", ids)
        self.assertIn("c6", ids)
        rejected = [r for r in result["diversity_rejected_items"] if r["news_id"] == "c2"]
        self.assertEqual(rejected[0]["rejected_reason"], "entity_cap")
        self.assertEqual(rejected[0]["collided_entity"], "openai")

    def test_diversity_summary_recorded(self) -> None:
        result = select_top_5_news(self._pack(), GateResult(verdict="pass", issues=()))
        summary = result["diversity_summary"]
        self.assertTrue(summary["selected_after_diversity_gate"])
        self.assertEqual(summary["same_source_reject_count"], 1)
        self.assertEqual(summary["selected_count"], 5)
        self.assertFalse(summary["relaxed_due_to_candidate_shortage"])
        rejected = result["diversity_rejected_items"]
        c3_rej = [r for r in rejected if r["news_id"] == "c3"]
        self.assertEqual(c3_rej[0]["rejected_reason"], "same_source_cap")
        self.assertEqual(c3_rej[0]["collided_with"]["news_id"], "c1")

    def test_scored_downstream_pool_promotes_watchlist_replacement(self) -> None:
        pack = self._pack()
        pack["global_top5_selection"] = {
            "selected_source_ids": ["s-nvidia", "s-tc", "s-nvidia", "s-dc", "s-goog"],
            "watchlist_source_ids": ["s-reuters"],
            "downstream_candidate_source_ids": [
                "s-nvidia",
                "s-tc",
                "s-nvidia",
                "s-dc",
                "s-goog",
                "s-reuters",
            ],
        }
        pack["source_pack_funnel_summary"] = {
            "scored_candidate_count": 24,
            "scored_selected_count": 5,
            "scored_watchlist_count": 2,
            "scored_rejected_count": 17,
            "replacement_pool_count": 2,
        }

        result = select_top_5_news(pack, GateResult(verdict="pass", issues=()))
        items = result["top_5_news"]["items"]
        ids = [it["news_id"] for it in items]

        self.assertEqual(len(items), 5)
        self.assertIn("c6", ids)
        self.assertNotIn("c3", ids)
        self.assertEqual(len([it for it in items if it["normalized_source"] == "nvidia blog"]), 1)
        self.assertFalse(result["diversity_summary"]["relaxed_due_to_candidate_shortage"])
        self.assertEqual(result["candidate_funnel_summary"]["scored_candidate_count"], 24)
        self.assertGreater(result["candidate_funnel_summary"]["pre_diversity_candidate_count"], 5)
        self.assertEqual(result["candidate_funnel_summary"]["post_diversity_selected_count"], 5)
        self.assertEqual(result["candidate_funnel_summary"]["diversity_rejected_count"], 1)

    def test_scored_downstream_pool_keeps_relax_visible_when_replacement_missing(self) -> None:
        pack = self._pack()
        pack["sources"] = pack["sources"][:5]
        pack["claims"] = pack["claims"][:5]
        pack["global_top5_selection"] = {
            "selected_source_ids": ["s-nvidia", "s-tc", "s-nvidia", "s-dc", "s-goog"],
            "downstream_candidate_source_ids": ["s-nvidia", "s-tc", "s-nvidia", "s-dc", "s-goog"],
        }

        result = select_top_5_news(pack, GateResult(verdict="pass", issues=()))
        items = result["top_5_news"]["items"]

        self.assertEqual(len(items), 5)
        self.assertTrue(result["diversity_summary"]["relaxed_due_to_candidate_shortage"])
        relaxed = [it for it in items if it.get("diversity_relaxed")]
        self.assertEqual(relaxed[0]["news_id"], "c3")
        self.assertEqual(relaxed[0]["diversity_relaxed_from"], "same_source_cap")


if __name__ == "__main__":
    unittest.main()
