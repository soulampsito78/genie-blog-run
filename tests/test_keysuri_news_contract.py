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
from keysuri_news_contract import is_korea_tech_irrelevant_headline


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
        self.assertEqual(schema["top_5_news"]["news_scope"], NEWS_SCOPE_KOREA)


class KeysuriKoreaTechRelevanceTests(unittest.TestCase):
    def test_irrelevant_foreign_accidents_rejected(self) -> None:
        self.assertTrue(is_korea_tech_irrelevant_headline("태국에서 11세 소년이 트럭으로 승려 들이받아 9명 사망"))
        self.assertTrue(is_korea_tech_irrelevant_headline("미국에서 총기 난사 사건으로 다수 사상자 발생"))
        self.assertTrue(is_korea_tech_irrelevant_headline("일본 지진으로 여성 부상자 속출"))

    def test_tech_anchored_news_accepted(self) -> None:
        # Has tech anchors so even if it has accident words (unlikely but possible), it's accepted
        self.assertFalse(is_korea_tech_irrelevant_headline("삼성전자, AI 반도체로 혁신", "미국 시장 진출"))
        self.assertFalse(is_korea_tech_irrelevant_headline("엔비디아 주가 폭락, 국내 반도체 소부장 타격"))
        self.assertFalse(is_korea_tech_irrelevant_headline("정부, 전력 인프라 확충... 데이터센터 화재 방지"))
        
    def test_general_tech_news_accepted(self) -> None:
        self.assertFalse(is_korea_tech_irrelevant_headline("네이버 클라우드, 사우디에 기업용 플랫폼 수출"))
        self.assertFalse(is_korea_tech_irrelevant_headline("카카오모빌리티 자율주행 택시 서비스 개시"))
        self.assertFalse(is_korea_tech_irrelevant_headline("테슬라 로보택시 공개, 국내 배터리 업계 영향은"))

    def test_validate_top_5_news_block_rejects_irrelevant_item(self) -> None:
        block = _top5_block("keysuri_korea_tech")
        block["items"][0]["headline"] = "태국에서 11세 소년이 트럭으로 승려 들이받아 9명 사망"
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertTrue(any(i["code"] == "korea_tech_top5_irrelevant_item" for i in issues))


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


class KeysuriKoreaExposureDedupBackfillTests(unittest.TestCase):
    """Scheduled Korea runs must not 500 just because an earlier same-day
    owner-review exposed the same news. Customer-sent items stay a hard block;
    owner-review-exposure items are a soft duplicate that a scheduled run may
    controlled-backfill (fresh watchlist first, then re-injected exposure dupes).
    """

    _SCHEDULED = "scheduled_service_full_run"

    def _claim(self, cid: str) -> dict:
        return {
            "claim_id": cid,
            "statement": f"Korea tech statement {cid}",
            "claim_type": "general",
            "source_ids": [f"s-{cid}"],
            "confidence_label": "reported",
            "primary_category": "korea_semiconductor",
            "category": "korea_semiconductor",
            "headline": f"Korea headline {cid}",
            "summary": f"Summary {cid}",
            "why_it_matters": f"Why {cid}",
            "business_implication": f"Biz impl {cid}",
        }

    def _source(self, cid: str) -> dict:
        return {
            "source_id": f"s-{cid}",
            "source_name": f"Outlet {cid}",
            "source_url": f"https://korea-{cid}.example.com/news/{cid}",
            "source_tier": "T2_TIER1_WIRE",
            "fetched_at": "2026-07-01T10:00:00+09:00",
        }

    def _pack(self, selected, backfill=()) -> dict:
        return {
            "program_id": "keysuri_korea_tech",
            "generated_at": "2026-07-01T10:00:00+09:00",
            "sources": [self._source(c) for c in selected],
            "claims": [self._claim(c) for c in selected],
            "backfill_sources": [self._source(c) for c in backfill],
            "backfill_claims": [self._claim(c) for c in backfill],
        }

    def _log_row(self, cid: str) -> dict:
        return {
            "title": f"Korea headline {cid}",
            "url": f"https://korea-{cid}.example.com/news/{cid}",
            "source": f"Outlet {cid}",
        }

    def _gate(self) -> GateResult:
        return GateResult(verdict="pass", issues=())

    def test_scheduled_run_backfills_from_fresh_watchlist_first(self) -> None:
        # All 5 selected are owner-review-exposure duplicates, but 5 fresh
        # watchlist candidates are available -> recover with FRESH items, no
        # exposure re-injection.
        pack = self._pack(["a1", "a2", "a3", "a4", "a5"], backfill=["b1", "b2", "b3", "b4", "b5"])
        exposure = [self._log_row(c) for c in ["a1", "a2", "a3", "a4", "a5"]]
        result = select_top_5_news(
            pack,
            self._gate(),
            exposure_log_rows=exposure,
            trigger_source=self._SCHEDULED,
        )
        self.assertEqual(result["verdict"], "pass")
        ids = [it["news_id"] for it in result["top_5_news"]["items"]]
        self.assertEqual(len(ids), 5)
        self.assertTrue(all(i.startswith("b") for i in ids), ids)
        self.assertFalse(result["exposure_backfill_used"])
        self.assertNotIn(
            "keysuri_korea_exposure_dedup_backfill_used",
            result.get("internal_issue_codes") or [],
        )
        funnel = result["candidate_funnel_summary"]
        self.assertEqual(funnel["dedup_removed_by_exposure_log_count"], 5)
        self.assertEqual(funnel["dedup_removed_by_sent_log_count"], 0)
        self.assertEqual(funnel["fresh_backfill_used_count"], 5)
        self.assertEqual(funnel["final_selected_count"], 5)

    def test_scheduled_run_reinjects_exposure_dupes_when_no_fresh_pool(self) -> None:
        # 5 selected are exposure duplicates and there is no fresh watchlist ->
        # controlled backfill re-injects the exposure dupes and marks the run.
        pack = self._pack(["a1", "a2", "a3", "a4", "a5"])
        exposure = [self._log_row(c) for c in ["a1", "a2", "a3", "a4", "a5"]]
        result = select_top_5_news(
            pack,
            self._gate(),
            exposure_log_rows=exposure,
            trigger_source=self._SCHEDULED,
        )
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(len(result["top_5_news"]["items"]), 5)
        self.assertTrue(result["exposure_backfill_used"])
        self.assertIn(
            "keysuri_korea_exposure_dedup_backfill_used",
            result.get("internal_issue_codes") or [],
        )
        funnel = result["candidate_funnel_summary"]
        self.assertEqual(funnel["exposure_backfill_used_count"], 5)
        self.assertEqual(funnel["final_selected_count"], 5)

    def test_sent_log_customer_dupes_are_never_backfilled(self) -> None:
        # Customer-sent items are a hard block: even a scheduled run holds rather
        # than re-injecting them, and no fresh pool exists to recover from.
        pack = self._pack(["a1", "a2", "a3", "a4", "a5"])
        sent = [self._log_row(c) for c in ["a1", "a2", "a3", "a4", "a5"]]
        result = select_top_5_news(
            pack,
            self._gate(),
            sent_log_rows=sent,
            trigger_source=self._SCHEDULED,
        )
        self.assertEqual(result["verdict"], "hold")
        self.assertFalse(result.get("exposure_backfill_used"))
        funnel = result["candidate_funnel_summary"]
        self.assertEqual(funnel["dedup_removed_by_sent_log_count"], 5)
        self.assertEqual(funnel["dedup_removed_by_exposure_log_count"], 0)
        self.assertEqual(funnel["hold_reason"], "insufficient_fresh_candidates_after_dedup")

    def test_sent_dupe_blocks_backfill_even_with_fresh_watchlist(self) -> None:
        # One selected item is customer-sent; the fresh watchlist backfills only
        # the non-sent gap, and the customer-sent item is never re-added.
        pack = self._pack(["a1", "a2", "a3", "a4", "a5"], backfill=["b1"])
        sent = [self._log_row("a1")]
        result = select_top_5_news(
            pack,
            self._gate(),
            sent_log_rows=sent,
            trigger_source=self._SCHEDULED,
        )
        self.assertEqual(result["verdict"], "pass")
        ids = [it["news_id"] for it in result["top_5_news"]["items"]]
        self.assertNotIn("a1", ids)
        self.assertIn("b1", ids)
        self.assertEqual(len(ids), 5)

    def test_manual_run_holds_on_exposure_dupes_without_backfill(self) -> None:
        # Non-scheduled (manual/QA) run keeps exposure items as a hard block so the
        # operator sees the true dedup state -> hold, no re-injection.
        pack = self._pack(["a1", "a2", "a3", "a4", "a5"])
        exposure = [self._log_row(c) for c in ["a1", "a2", "a3", "a4", "a5"]]
        result = select_top_5_news(
            pack,
            self._gate(),
            exposure_log_rows=exposure,
            trigger_source="manual_admin_review",
        )
        self.assertEqual(result["verdict"], "hold")
        self.assertFalse(result.get("exposure_backfill_used"))

    def test_hold_funnel_has_all_diagnostic_fields(self) -> None:
        pack = self._pack(["a1", "a2", "a3", "a4", "a5"])
        exposure = [self._log_row(c) for c in ["a1", "a2", "a3"]]
        sent = [self._log_row(c) for c in ["a4", "a5"]]
        result = select_top_5_news(
            pack,
            self._gate(),
            sent_log_rows=sent,
            exposure_log_rows=exposure,
            trigger_source="manual_admin_review",
        )
        self.assertEqual(result["verdict"], "hold")
        funnel = result["candidate_funnel_summary"]
        for key in (
            "candidate_count_before_dedup",
            "sent_log_read_count",
            "exposure_log_read_count",
            "recent_combined_log_count",
            "dedup_removed_count",
            "dedup_removed_by_sent_log_count",
            "dedup_removed_by_exposure_log_count",
            "candidate_count_after_dedup",
            "final_selected_count",
            "hold_reason",
        ):
            self.assertIn(key, funnel)
        self.assertEqual(funnel["dedup_removed_by_sent_log_count"], 2)
        self.assertEqual(funnel["dedup_removed_by_exposure_log_count"], 3)

    def test_healthy_path_unchanged_when_no_recent_logs(self) -> None:
        # No dedup rows at all: identical to legacy behaviour (no backfill fields
        # firing), exactly five selected.
        pack = self._pack(["a1", "a2", "a3", "a4", "a5"], backfill=["b1", "b2"])
        result = select_top_5_news(pack, self._gate(), trigger_source=self._SCHEDULED)
        self.assertEqual(result["verdict"], "pass")
        ids = [it["news_id"] for it in result["top_5_news"]["items"]]
        self.assertEqual(len(ids), 5)
        self.assertTrue(all(i.startswith("a") for i in ids), ids)
        self.assertFalse(result["exposure_backfill_used"])
        self.assertEqual(result["candidate_funnel_summary"]["fresh_backfill_used_count"], 0)


class KeysuriKoreaMarketSignalFieldContractTests(unittest.TestCase):
    """Korea-only OPTIONAL market_lens/market_impact fields on TOP5 items."""

    def _korea_block_with_item_fields(self, **fields) -> dict:
        block = _top5_block("keysuri_korea_tech")
        block["items"][0].update(fields)
        return block

    def test_absent_fields_stay_valid(self) -> None:
        issues = validate_top_5_news_block("keysuri_korea_tech", _top5_block("keysuri_korea_tech"))
        self.assertEqual(issues, [])

    def test_valid_market_lens_list_accepted(self) -> None:
        block = self._korea_block_with_item_fields(
            market_lens=["주식", "채권/금리", "정책"],
            market_impact="정책 발표와 실제 예산·조달 일정은 분리해서 봐야 합니다.",
        )
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertEqual(issues, [])

    def test_valid_market_lens_string_form_accepted(self) -> None:
        block = self._korea_block_with_item_fields(market_lens="주식 · 채권/금리")
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertEqual(issues, [])

    def test_empty_market_lens_values_fall_back_without_blocking(self) -> None:
        for empty_value in ("", "   ", [], [""], ["  "]):
            with self.subTest(empty_value=empty_value):
                block = self._korea_block_with_item_fields(market_lens=empty_value)
                issues = validate_top_5_news_block("keysuri_korea_tech", block)
                codes = {i["code"] for i in issues}
                self.assertNotIn("top_5_news_item_market_lens_empty", codes)
                self.assertEqual(issues, [])

    def test_unknown_market_lens_value_falls_back_without_blocking(self) -> None:
        block = self._korea_block_with_item_fields(market_lens=["주식", "부동산"])
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        codes = {i["code"] for i in issues}
        self.assertNotIn("top_5_news_item_market_lens_unknown", codes)
        self.assertEqual(issues, [])

    def test_market_lens_investment_alias_normalizes_to_stock(self) -> None:
        for value in ("투자", ["투자"], ["투자자"], ["개인 투자자"]):
            with self.subTest(value=value):
                block = self._korea_block_with_item_fields(market_lens=value)
                issues = validate_top_5_news_block("keysuri_korea_tech", block)
                self.assertEqual(issues, [], issues)

    def test_market_lens_policy_finance_alias_normalizes(self) -> None:
        block = self._korea_block_with_item_fields(market_lens=["정책금융"])
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertEqual(issues, [])

    def test_market_lens_subcontractor_alias_normalizes(self) -> None:
        block = self._korea_block_with_item_fields(market_lens=["소부장"])
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertEqual(issues, [])

    def test_normalize_korea_market_lens_values_maps_investment_aliases(self) -> None:
        from keysuri_news_contract import normalize_korea_market_lens_values

        for raw in ("투자", ["투자"], ["투자자"], ["개인 투자자"]):
            with self.subTest(raw=raw):
                normalized, repairs = normalize_korea_market_lens_values(raw)
                self.assertEqual(normalized, ["주식"])
                self.assertTrue(repairs)

    def test_normalize_korea_market_lens_values_unknown_non_dangerous_fallback(self) -> None:
        from keysuri_news_contract import normalize_korea_market_lens_values

        normalized, repairs = normalize_korea_market_lens_values(["부동산"])
        self.assertEqual(normalized, ["산업"])
        self.assertEqual(repairs, ["부동산->산업"])

    def test_dangerous_market_lens_sell_term_rejected(self) -> None:
        block = self._korea_block_with_item_fields(market_lens=["매도"])
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        codes = {i["code"] for i in issues}
        self.assertIn("top_5_news_item_market_lens_forbidden", codes)

    def test_dangerous_market_lens_score_term_rejected(self) -> None:
        for value in ("점수", "총점"):
            with self.subTest(value=value):
                block = self._korea_block_with_item_fields(market_lens=[value])
                issues = validate_top_5_news_block("keysuri_korea_tech", block)
                codes = {i["code"] for i in issues}
                self.assertIn("top_5_news_item_market_lens_forbidden", codes)

    def test_market_lens_wrong_type_rejected(self) -> None:
        block = self._korea_block_with_item_fields(market_lens={"lens": "주식"})
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        codes = {i["code"] for i in issues}
        self.assertIn("top_5_news_item_market_lens_invalid", codes)

    def test_dangerous_market_lens_terms_rejected(self) -> None:
        for value in ("매수", "강력추천", "총점"):
            with self.subTest(value=value):
                block = self._korea_block_with_item_fields(market_lens=[value])
                issues = validate_top_5_news_block("keysuri_korea_tech", block)
                codes = {i["code"] for i in issues}
                self.assertIn("top_5_news_item_market_lens_forbidden", codes)

    def test_market_impact_investment_directive_phrase_rejected(self) -> None:
        block = self._korea_block_with_item_fields(market_impact="지금 사라. 내일 팔아라.")
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        codes = {i["code"] for i in issues}
        self.assertIn("top_5_news_item_market_impact_directive", codes)

    def test_market_impact_buy_sell_directive_rejected(self) -> None:
        block = self._korea_block_with_item_fields(
            market_impact="이 종목은 내일 매수하시는 것이 좋습니다."
        )
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        codes = {i["code"] for i in issues}
        self.assertIn("top_5_news_item_market_impact_directive", codes)

    def test_market_impact_score_terms_rejected(self) -> None:
        block = self._korea_block_with_item_fields(market_impact="총점 95점으로 강력추천합니다.")
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        codes = {i["code"] for i in issues}
        self.assertIn("top_5_news_item_market_impact_directive", codes)

    def test_market_impact_empty_string_falls_back_without_blocking(self) -> None:
        block = self._korea_block_with_item_fields(market_impact="   ")
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        self.assertEqual(issues, [])

    def test_market_impact_wrong_type_rejected(self) -> None:
        block = self._korea_block_with_item_fields(market_impact=[])
        issues = validate_top_5_news_block("keysuri_korea_tech", block)
        codes = {i["code"] for i in issues}
        self.assertIn("top_5_news_item_market_impact_invalid", codes)

    def test_global_program_ignores_market_fields(self) -> None:
        block = _top5_block("keysuri_global_tech")
        block["items"][0]["market_lens"] = ["부동산"]
        block["items"][0]["market_impact"] = "매수 추천."
        issues = validate_top_5_news_block("keysuri_global_tech", block)
        self.assertEqual(issues, [])

    def test_lens_parser_keeps_bond_rate_label_intact(self) -> None:
        from keysuri_news_contract import parse_korea_market_lens_values

        self.assertEqual(
            parse_korea_market_lens_values("주식 · 채권/금리, 환율"),
            ["주식", "채권/금리", "환율"],
        )

    def test_repair_korea_market_lens_fields_maps_investment_alias(self) -> None:
        from keysuri_news_contract import repair_korea_market_lens_fields_in_top5

        block = self._korea_block_with_item_fields(market_lens=["투자"])
        repaired, notes = repair_korea_market_lens_fields_in_top5(block)
        self.assertEqual(repaired["items"][0]["market_lens"], ["주식"])
        self.assertTrue(notes)


class GlobalTechLowSignalGateTests(unittest.TestCase):
    """Global TOP5 must reject evergreen explainers, culture soft stories, and empty recaps."""

    def _low(self, headline: str, summary: str = ""):
        from keysuri_news_contract import is_global_tech_low_signal_headline

        return is_global_tech_low_signal_headline(headline, summary)

    def test_vhf_explainer_rejected(self) -> None:
        low, reason = self._low("VHF 전파: 모든 RF 엔지니어가 알아야 할 핵심 지식")
        self.assertTrue(low)
        self.assertEqual(reason, "global_evergreen_explainer")

    def test_english_understanding_explainer_rejected(self) -> None:
        low, reason = self._low("Understanding VHF propagation for RF engineers")
        self.assertTrue(low)
        self.assertEqual(reason, "global_evergreen_explainer")

    def test_guide_and_tutorial_rejected(self) -> None:
        for headline in (
            "클라우드 컴퓨팅 입문 가이드",
            "A beginner tutorial: guide to Kubernetes networking",
            "What is quantum computing and why it matters",
        ):
            with self.subTest(headline=headline):
                low, reason = self._low(headline)
                self.assertTrue(low)
                self.assertEqual(reason, "global_evergreen_explainer")

    def test_policy_guideline_revision_not_flagged_as_guide(self) -> None:
        low, _ = self._low("정부, AI 데이터센터 전력 가이드라인 개정")
        self.assertFalse(low)

    def test_netflix_binge_culture_rejected(self) -> None:
        low, reason = self._low(
            "넷플릭스가 만든 '몰아보기' 문화, 이제는 한계를 맞이했을 수 있습니다"
        )
        self.assertTrue(low)
        self.assertEqual(reason, "global_consumer_culture_story")

    def test_english_binge_soft_story_rejected(self) -> None:
        low, reason = self._low("Binge-watching culture may finally be fading")
        self.assertTrue(low)
        self.assertEqual(reason, "global_consumer_culture_story")

    def test_culture_story_with_ad_tier_pricing_rescued(self) -> None:
        low, _ = self._low("넷플릭스, 몰아보기 감소에 광고 요금제 개편")
        self.assertFalse(low)

    def test_ai_ransomware_with_actor_tool_impact_accepted(self) -> None:
        low, _ = self._low(
            "AI 기반 랜섬웨어 공격, 여전히 인간의 개입이 필요했습니다",
            "공격 그룹이 AI 도구로 침투 후 수동으로 암호화를 실행했습니다.",
        )
        self.assertFalse(low)

    def test_icml_recap_without_concrete_change_rejected(self) -> None:
        low, reason = self._low("오픈 모델이 AI 연구를 이끄는 방식: ICML 2026의 시사점")
        self.assertTrue(low)
        self.assertEqual(reason, "global_corporate_recap_no_concrete_change")

    def test_icml_recap_with_concrete_release_accepted(self) -> None:
        low, _ = self._low(
            "ICML 2026의 시사점: 새 오픈소스 벤치마크와 70B 모델 공개"
        )
        self.assertFalse(low)

    def test_subsea_cable_infra_accepted(self) -> None:
        low, _ = self._low(
            "일본 IPS, 오사카 인근 와카야마에 1억 4,100만 달러 규모 해저 케이블 착륙국 건설 계획"
        )
        self.assertFalse(low)

    def test_gate_is_source_agnostic(self) -> None:
        """TechCrunch consumer culture and IEEE evergreen explainers are still rejected."""
        low_tc, _ = self._low(
            "TechCrunch: streaming habits and pop culture in 2026"
        )
        self.assertTrue(low_tc)
        low_ieee, _ = self._low(
            "IEEE Spectrum: the basics every RF engineer needs to know"
        )
        self.assertTrue(low_ieee)

    def test_unexplained_incident_not_flagged_as_explainer(self) -> None:
        """'explained' must match on a word boundary, not inside 'unexplained'."""
        low, reason = self._low("Unexplained cloud outage disrupts API traffic")
        self.assertFalse(low, reason)

    def test_explained_as_word_still_rejected(self) -> None:
        """A real explainer using the word 'explained' is still rejected."""
        low, reason = self._low("explained VHF propagation basics")
        self.assertTrue(low)
        self.assertEqual(reason, "global_evergreen_explainer")
        low2, reason2 = self._low("Understanding VHF propagation for RF engineers")
        self.assertTrue(low2)
        self.assertEqual(reason2, "global_evergreen_explainer")

    def test_explainer_token_still_matches_on_boundary(self) -> None:
        low, reason = self._low("AI model explainer article for newcomers")
        self.assertTrue(low)
        self.assertEqual(reason, "global_evergreen_explainer")


class GlobalTechSelectionGateIntegrationTests(unittest.TestCase):
    """Low-signal gate applies in select_top_5_news for both main pool and backfill."""

    def _claim(self, cid: str, headline: str) -> dict:
        return {
            "claim_id": cid,
            "statement": headline,
            "headline": headline,
            "summary": f"{headline} 관련 요약.",
            "claim_type": "general",
            "source_ids": [f"s-{cid}"],
            "confidence_label": "reported",
            "news_category": "startup",
            "business_implication": f"Biz impl {cid}",
        }

    def _source(self, cid: str) -> dict:
        return {
            "source_id": f"s-{cid}",
            "source_name": f"Outlet {cid}",
            "source_url": f"https://global-{cid}.example.com/news/{cid}",
            "source_tier": "T2_TIER1_WIRE",
            "fetched_at": "2026-07-07T10:00:00+09:00",
        }

    def _good_headlines(self, n: int) -> list:
        pool = [
            "오픈AI, 신규 에이전트 API 정식 출시",
            "AWS, 서울 리전 GPU 클러스터 증설 발표",
            "EU, AI 플랫폼 규제 초안 확정",
            "TSMC, 2나노 파운드리 양산 계약 수주",
            "일본 IPS, 해저 케이블 착륙국 건설 계획",
            "구글, 검색 API 정책 변경 공지",
        ]
        return pool[:n]

    def test_explainer_claim_excluded_from_global_top5(self) -> None:
        good = [
            self._claim(f"good-{i}", h) for i, h in enumerate(self._good_headlines(5), 1)
        ]
        bad = self._claim("bad-explainer", "VHF 전파: 모든 RF 엔지니어가 알아야 할 핵심 지식")
        claims = [bad] + good
        pack = {
            "program_id": "keysuri_global_tech",
            "sources": [self._source(c["claim_id"]) for c in claims],
            "claims": claims,
        }
        result = select_top_5_news(pack, GateResult(verdict="pass", issues=()))
        self.assertEqual(result["verdict"], "pass")
        ids = [item["news_id"] for item in result["top_5_news"]["items"]]
        self.assertNotIn("bad-explainer", ids)
        self.assertEqual(len(ids), 5)

    def test_backfill_cannot_bypass_global_gate(self) -> None:
        # 5 fresh candidates, one removed by cross-day dedup -> backfill pool is
        # consulted; a low-signal backfill claim must be skipped, a good one used.
        good = [
            self._claim(f"good-{i}", h) for i, h in enumerate(self._good_headlines(5), 1)
        ]
        backfill = [
            self._claim("bf-culture", "넷플릭스가 만든 몰아보기 문화, 한계를 맞았습니다"),
            self._claim("bf-good", "MS, 클라우드 보안 취약점 긴급 패치 공개"),
        ]
        pack = {
            "program_id": "keysuri_global_tech",
            "sources": [self._source(c["claim_id"]) for c in good],
            "claims": good,
            "backfill_claims": backfill,
            "backfill_sources": [self._source(c["claim_id"]) for c in backfill],
        }
        sent = [
            {
                "title": good[4]["headline"],
                "url": "https://global-good-5.example.com/news/good-5",
                "source": "Outlet good-5",
            }
        ]
        result = select_top_5_news(
            pack, GateResult(verdict="pass", issues=()), sent_log_rows=sent
        )
        self.assertEqual(result["verdict"], "pass", result.get("issues"))
        ids = [item["news_id"] for item in result["top_5_news"]["items"]]
        self.assertNotIn("bf-culture", ids)
        self.assertIn("bf-good", ids)

    def test_korea_selection_not_affected_by_global_gate(self) -> None:
        """A tech-anchored explainer-style headline still qualifies for Korea Tech."""
        claims = []
        for i in range(1, 6):
            claim = self._claim(f"k{i}", f"국내 반도체 공급망 뉴스 {i}")
            claim["news_category"] = "korea_semiconductor"
            claims.append(claim)
        claims[0]["headline"] = "반도체 기초 개념 이해하기: 알아야 할 핵심 지식"
        claims[0]["statement"] = claims[0]["headline"]
        pack = {
            "program_id": "keysuri_korea_tech",
            "sources": [self._source(c["claim_id"]) for c in claims],
            "claims": claims,
        }
        result = select_top_5_news(pack, GateResult(verdict="pass", issues=()))
        self.assertEqual(result["verdict"], "pass", result.get("issues"))
        ids = [item["news_id"] for item in result["top_5_news"]["items"]]
        self.assertIn("k1", ids)


if __name__ == "__main__":
    unittest.main()
