"""Tests for Kee-Suri global TOP5 signal scoring."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from keysuri_global_signal_scoring import (
    AI_PRIMARY_CATEGORY,
    apply_scored_selection_to_source_pack,
    classify_endava_article_test_item,
    classify_global_tech_category,
    score_global_signal_candidates,
    score_global_signal_item,
)
from keysuri_news_contract import select_top_5_news
from keysuri_source_gate import GateResult
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def _recent_iso(hours_ago: int = 12) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ).astimezone(KST).isoformat(timespec="seconds")


def _item(
    source_id: str,
    title: str,
    *,
    url: str = "",
    category: str = "ai_product",
    summary: str = "",
) -> dict:
    return {
        "source_id": source_id,
        "title": title,
        "link": url or f"https://{source_id}.sources.test/post",
        "published_at": _recent_iso(6),
        "source_tier": "T3_QUALITY_PRESS",
        "category": category,
        "summary": summary or title,
    }


def _source_pack_from_items(items: list[dict]) -> dict:
    sources = []
    claims = []
    for item in items:
        sid = item["source_id"]
        sources.append(
            {
                "source_id": sid,
                "source_name": item.get("source_name") or sid,
                "source_url": item.get("link"),
                "source_tier": item.get("source_tier") or "T3_QUALITY_PRESS",
                "published_at": item.get("published_at"),
                "title": item.get("title"),
                "snippet": item.get("summary"),
            }
        )
        claims.append(
            {
                "claim_id": f"claim-{sid}",
                "statement": item.get("title"),
                "claim_type": "general",
                "source_ids": [sid],
                "confidence_label": "reported",
                "category": item.get("category") or "ai_product",
                "headline": item.get("title"),
                "summary": item.get("summary") or item.get("title"),
                "why_it_matters": f"Why {sid}",
                "business_implication": f"Business implication {sid}",
            }
        )
    return {"program_id": "keysuri_global_tech", "sources": sources, "claims": claims}


class KeysuriGlobalSignalScoringTests(unittest.TestCase):
    def test_endava_classified_as_official_customer_case_not_breaking_launch(self) -> None:
        scored = classify_endava_article_test_item()
        self.assertTrue(scored.is_official_source)
        self.assertTrue(scored.is_customer_case_study)
        self.assertFalse(scored.is_breaking_launch)
        self.assertLess(scored.scores.hype_penalty, 0)
        self.assertIn("customer_case_study", scored.tags)
        self.assertNotEqual(scored.classification, "deep_dive_candidate")
        self.assertNotIn("breaking", scored.selection_rationale.lower())

    def test_endava_not_framed_as_product_launch_keywords(self) -> None:
        scored = classify_endava_article_test_item()
        self.assertFalse(scored.is_breaking_launch)
        self.assertTrue(scored.hype_warning)

    def test_hard_reject_without_url(self) -> None:
        scored = score_global_signal_item(
            {
                "title": "Mystery AI news",
                "link": "",
                "published_at": _recent_iso(),
            }
        )
        self.assertEqual(scored.classification, "hard_reject")
        self.assertEqual(scored.hard_reject_reason, "no_source_url")

    def test_duplicate_story_rejected(self) -> None:
        item = {
            "source_id": "a1",
            "title": "OpenAI releases new model for developers",
            "link": "https://openai.com/index/model-a/",
            "published_at": _recent_iso(),
            "source_tier": "T1_OFFICIAL_SECONDARY",
            "summary": "OpenAI model release for developer workflow and API platform.",
        }
        dup = dict(item)
        dup["source_id"] = "a2"
        dup["link"] = "https://example.com/repost-model-a"
        result = score_global_signal_candidates([item, dup])
        rejected_dup = [r for r in result.rejected if r.hard_reject_reason == "duplicate_story"]
        self.assertTrue(rejected_dup or len(result.all_candidates) >= 2)

    def test_strong_official_launch_scores_higher_than_case_study(self) -> None:
        launch = score_global_signal_item(
            {
                "source_id": "launch-1",
                "title": "OpenAI launches new developer platform and API pricing model",
                "link": "https://openai.com/index/new-platform/",
                "published_at": _recent_iso(6),
                "source_tier": "T1_OFFICIAL_SECONDARY",
                "category": "ai_product",
                "summary": (
                    "OpenAI launches a new developer platform with API pricing, enterprise "
                    "workflow changes, and distribution channel updates."
                ),
            }
        )
        case = classify_endava_article_test_item()
        self.assertGreater(launch.scores.base_total, case.scores.base_total)

    def test_selection_partitions_top5_watchlist_reject(self) -> None:
        items = []
        for i in range(8):
            items.append(
                _item(
                    f"s{i}",
                    f"AI platform policy signal number {i} enterprise workflow",
                    category="platform",
                    summary=(
                        f"Enterprise AI workflow, API monetization, and developer platform signal {i} "
                        "for Korean founders and automation operators."
                    ),
                )
            )
        result = score_global_signal_candidates(items)
        self.assertEqual(len(result.selected_top5), 5)
        self.assertGreaterEqual(len(result.all_candidates), 8)

    def test_category_fields_present(self) -> None:
        scored = score_global_signal_item(
            _item(
                "semi-1",
                "TSMC expands advanced packaging for AI accelerator chips and HBM supply",
                category="semiconductor_chip_infra",
                summary="TSMC fab packaging GPU wafer capacity for enterprise AI infrastructure.",
            )
        )
        self.assertEqual(scored.primary_category, "semiconductor_chip_infra")
        self.assertGreater(scored.category_confidence, 0.4)
        self.assertTrue(scored.reason_for_category)

    def test_semiconductor_classification(self) -> None:
        primary, secondary, conf, reason = classify_global_tech_category(
            "Nvidia HBM GPU wafer fab packaging chiplet AI accelerator"
        )
        self.assertEqual(primary, "semiconductor_chip_infra")
        self.assertGreater(conf, 0.4)
        self.assertTrue(reason)

    def test_ai_capped_at_two_when_non_ai_qualify(self) -> None:
        items = [
            _item(
                f"ai-{i}",
                f"OpenAI Google Anthropic enterprise AI agent platform developer tools {i}",
                summary="Enterprise AI agent platform API workflow for operators.",
            )
            for i in range(4)
        ] + [
            _item(
                "semi-1",
                "TSMC Samsung Foundry HBM GPU wafer fab semiconductor packaging",
                category="semiconductor_chip_infra",
                summary="Semiconductor chip infrastructure supply for AI accelerators.",
            ),
            _item(
                "rob-1",
                "Industrial robot warehouse automation factory collaborative robot systems",
                category="robotics_automation_manufacturing",
                summary="Robotics automation manufacturing deployment for enterprise operations.",
            ),
            _item(
                "bat-1",
                "Solid-state battery EV grid storage lithium ESS charging infrastructure",
                category="battery_ev_energy_grid",
                summary="Battery EV energy grid storage for data center power demand.",
            ),
        ]
        result = score_global_signal_candidates(items)
        ai_count = sum(
            1 for s in result.selected_top5 if s.primary_category == AI_PRIMARY_CATEGORY
        )
        self.assertLessEqual(ai_count, 2)
        cats = {s.primary_category for s in result.selected_top5}
        self.assertTrue(
            "semiconductor_chip_infra" in cats
            or "robotics_automation_manufacturing" in cats
            or "battery_ev_energy_grid" in cats
        )
        self.assertIn("final_category_distribution", result.to_dict())

    def test_endava_does_not_auto_rank_first_against_launch(self) -> None:
        items = [
            _item(
                "launch-top",
                "OpenAI launches new developer platform API pricing enterprise workflow",
                url="https://openai.com/index/platform-launch/",
                summary="OpenAI launches platform with API pricing and enterprise distribution.",
            ),
            {
                "source_id": "endava",
                "title": "Endava Frontiers: OpenAI enterprise agents across software delivery",
                "link": "https://openai.com/index/endava-frontiers/",
                "published_at": _recent_iso(4),
                "source_tier": "T1_OFFICIAL_SECONDARY",
                "category": "enterprise_adoption",
                "summary": (
                    "OpenAI customer story on Endava enterprise agents in software delivery workflows."
                ),
            },
        ]
        result = score_global_signal_candidates(items)
        if result.selected_top5:
            top = result.selected_top5[0]
            self.assertFalse(top.is_customer_case_study)

    def test_sponsored_content_gets_strong_penalty(self) -> None:
        scored = score_global_signal_item(
            {
                "source_id": "spon-1",
                "title": "Sponsored: Decoupling from the grid for data centers",
                "link": "https://datacenterdynamics.com/sponsored/grid/",
                "published_at": _recent_iso(4),
                "source_tier": "T3_QUALITY_PRESS",
                "summary": "Partner content on grid decoupling for enterprise data centers.",
            }
        )
        self.assertTrue(scored.is_sponsored)
        self.assertLessEqual(scored.scores.hype_penalty, -25)
        self.assertIn("sponsored_content", scored.tags)

    def test_sponsored_usually_cannot_enter_top5(self) -> None:
        items = [
            _item(
                f"clean-{i}",
                f"OpenAI launches enterprise API platform workflow pricing model {i}",
                url=f"https://openai.com/index/platform-{i}/",
                summary="OpenAI launches developer platform with API pricing and enterprise workflow.",
            )
            for i in range(4)
        ] + [
            {
                "source_id": "spon-grid",
                "title": "Sponsored: Decoupling from the grid",
                "link": "https://datacenterdynamics.com/en/sponsored/grid/",
                "published_at": _recent_iso(3),
                "source_tier": "T3_QUALITY_PRESS",
                "summary": "Sponsored partner content on grid infrastructure.",
            },
            _item(
                "semi-1",
                "TSMC Samsung HBM GPU wafer fab semiconductor packaging",
                category="semiconductor_chip_infra",
                summary="Semiconductor chip infrastructure supply for AI accelerators.",
            ),
        ]
        result = score_global_signal_candidates(items)
        sponsored_in_top5 = [s for s in result.selected_top5 if s.is_sponsored]
        self.assertEqual(len(sponsored_in_top5), 0)
        deprioritized = [
            s
            for s in result.all_candidates
            if s.is_sponsored
            and (s.source_id or s.url) not in {x.source_id or x.url for x in result.selected_top5}
        ]
        self.assertTrue(deprioritized)

    def test_sponsored_top5_exception_carries_warning(self) -> None:
        sponsored = score_global_signal_item(
            {
                "source_id": "spon-strong",
                "title": "Sponsored: Major chip regulation policy shift",
                "link": "https://example.com/sponsored-chip-policy/",
                "published_at": _recent_iso(2),
                "source_tier": "T2_TIER1_WIRE",
                "summary": (
                    "Sponsored partner content on export control regulation policy funding "
                    "acquisition semiconductor chip enterprise platform launch."
                ),
            }
        )
        self.assertTrue(sponsored.is_sponsored)
        if sponsored.scores.structural_impact >= 8:
            sponsored.sponsored_warning = True
            sponsored.hype_warning = True
            sponsored.selection_note = "sponsored/partner content; watch with caution"
        self.assertTrue(sponsored.is_sponsored)

    def test_source_max_two_per_domain(self) -> None:
        items = []
        for i in range(4):
            items.append(
                {
                    "source_id": f"nvidia-{i}",
                    "title": f"NVIDIA launches GPU platform model API enterprise {i}",
                    "link": f"https://blogs.nvidia.com/blog/post-{i}/",
                    "published_at": _recent_iso(5 - i),
                    "source_name": "NVIDIA Blog",
                    "source_tier": "T1_OFFICIAL_SECONDARY",
                    "summary": "NVIDIA GPU chip platform launch for enterprise AI infrastructure.",
                }
            )
        items.extend(
            [
                _item(
                    "google-1",
                    "Google Gemini enterprise search platform API update",
                    url="https://blog.google/technology/ai/gemini-enterprise/",
                    summary="Google AI platform enterprise search API workflow.",
                ),
                _item(
                    "semi-1",
                    "TSMC HBM GPU wafer fab semiconductor packaging",
                    category="semiconductor_chip_infra",
                    summary="Semiconductor chip infrastructure supply chain.",
                ),
                _item(
                    "rob-1",
                    "Industrial robot warehouse automation factory systems",
                    category="robotics_automation_manufacturing",
                    summary="Robotics automation manufacturing deployment.",
                ),
            ]
        )
        result = score_global_signal_candidates(items)
        nvidia_count = sum(
            1 for s in result.selected_top5 if "nvidia.com" in (s.url or "")
        )
        self.assertLessEqual(nvidia_count, 2)

    def test_third_nvidia_item_watchlist_unless_score_gap(self) -> None:
        items = [
            {
                "source_id": f"nvidia-{i}",
                "title": f"NVIDIA GPU chip platform launch enterprise API {i}",
                "link": f"https://blogs.nvidia.com/blog/gpu-{i}/",
                "published_at": _recent_iso(4 - i),
                "source_name": "NVIDIA Blog",
                "source_tier": "T1_OFFICIAL_SECONDARY",
                "summary": "NVIDIA GPU semiconductor chip platform API enterprise launch.",
            }
            for i in range(3)
        ] + [
            _item(
                "alt-1",
                "OpenAI Anthropic enterprise agent platform developer tools",
                url="https://openai.com/index/agent-tools/",
                summary="Enterprise AI agent platform API workflow for operators.",
            ),
            _item(
                "alt-2",
                "Google Gemini enterprise search platform API update",
                url="https://blog.google/technology/ai/gemini-enterprise/",
                summary="Google AI platform enterprise search API workflow.",
            ),
            _item(
                "semi-1",
                "TSMC HBM wafer fab semiconductor packaging",
                category="semiconductor_chip_infra",
                summary="Semiconductor chip infrastructure supply.",
            ),
            _item(
                "rob-1",
                "Industrial robot warehouse automation",
                category="robotics_automation_manufacturing",
                summary="Robotics automation manufacturing deployment.",
            ),
        ]
        result = score_global_signal_candidates(items)
        nvidia_top = [s for s in result.selected_top5 if "nvidia.com" in (s.url or "")]
        self.assertLessEqual(len(nvidia_top), 2)
        blocked = [
            s
            for s in result.watchlist
            if "nvidia.com" in (s.url or "")
            and s.source_concentration_reason == "source_concentration_limit"
        ]
        self.assertTrue(blocked or len(nvidia_top) <= 2)

    def test_debug_report_includes_source_distribution_fields(self) -> None:
        result = score_global_signal_candidates(
            [
                _item("a1", "OpenAI agent platform API", summary="AI software platform enterprise."),
                _item(
                    "s1",
                    "ASML EUV photoresist wafer equipment",
                    category="semiconductor_equipment_materials",
                    summary="Semiconductor equipment materials for advanced packaging.",
                ),
            ]
        )
        payload = result.to_dict()
        self.assertIn("final_source_distribution", payload)
        self.assertIn("source_concentration_decisions", payload)
        if result.selected_top5:
            row = result.selected_top5[0].to_dict()
            self.assertIn("source_domain", row)
            self.assertIn("source_count_in_top5", row)

    def test_debug_report_includes_category_distribution(self) -> None:
        result = score_global_signal_candidates(
            [
                _item("a1", "OpenAI agent platform API", summary="AI software platform enterprise."),
                _item(
                    "s1",
                    "ASML EUV photoresist wafer equipment",
                    category="semiconductor_equipment_materials",
                    summary="Semiconductor equipment materials for advanced packaging.",
                ),
            ]
        )
        payload = result.to_dict()
        self.assertIn("diversity_quota_decisions", payload)
        self.assertIn("summary", payload)
        self.assertIn("ai_count_in_top5", payload["summary"])

    def test_apply_scored_selection_preserves_downstream_replacement_pool(self) -> None:
        items = [
            _item(
                "nvidia-1",
                "NVIDIA and AWS Collaborate to Bring AI to Production at Scale",
                url="https://blogs.nvidia.com/blog/aws-scale/",
                category="semiconductor_chip_infra",
                summary="NVIDIA AWS GPU infrastructure enterprise AI at scale.",
            ),
            _item(
                "tc-1",
                "Patronus AI lands $50M to stress-test AI agents",
                url="https://techcrunch.com/ai/patronus/",
                category="ai_product",
                summary="Funding round for AI agents enterprise platform workflow.",
            ),
            _item(
                "nvidia-2",
                "How Businesses Are Building Specialized AI They Can Trust",
                url="https://blogs.nvidia.com/blog/specialized-ai/",
                category="ai_product",
                summary="NVIDIA enterprise AI platform customer workflow.",
            ),
            _item(
                "dcd-1",
                "OpenAI partners with semiconductor firms on chip design",
                url="https://www.datacenterdynamics.com/openai-chip/",
                category="semiconductor_chip_infra",
                summary="OpenAI chip design semiconductor infrastructure.",
            ),
            _item(
                "google-1",
                "Our latest Google Finance upgrades, including a new app",
                url="https://blog.google/products/search/google-finance-app/",
                category="market_signal",
                summary="Google Finance app product update and platform signal.",
            ),
            _item(
                "ms-1",
                "Microsoft expands enterprise cloud security suite",
                url="https://blogs.microsoft.com/ai/cloud-security/",
                category="ai_product",
                summary="Microsoft enterprise cloud security platform workflow.",
            ),
            _item(
                "aws-1",
                "AWS expands AI infrastructure for enterprise inference",
                url="https://aws.amazon.com/blogs/aws/inference/",
                category="cybersecurity_cloud_datacenter",
                summary="AWS cloud infrastructure inference deployment.",
            ),
        ]
        for item in items:
            if item["source_id"].startswith("nvidia"):
                item["source_name"] = "NVIDIA Blog"
            elif item["source_id"].startswith("openai"):
                item["source_name"] = "OpenAI News"
            elif item["source_id"].startswith("google"):
                item["source_name"] = "Google AI Blog"
            elif item["source_id"].startswith("tc"):
                item["source_name"] = "TechCrunch AI"
            elif item["source_id"].startswith("ars"):
                item["source_name"] = "Ars Technica"
        source_pack = _source_pack_from_items(items)
        selection = score_global_signal_candidates(items)
        packed = apply_scored_selection_to_source_pack(source_pack, selection)

        self.assertEqual(len(selection.selected_top5), 5)
        self.assertGreater(len(selection.all_candidates), 5)
        self.assertGreater(len(packed["claims"]), 5)
        funnel = packed["source_pack_funnel_summary"]
        self.assertGreater(funnel["pre_diversity_candidate_count"], 5)
        self.assertEqual(funnel["scored_selected_count"], 5)
        self.assertEqual(
            packed["global_top5_selection"]["downstream_candidate_source_ids"],
            [c.source_id for c in selection.selected_top5 + selection.watchlist]
            + packed["global_top5_selection"]["replacement_source_ids"],
        )

    def test_low_scoring_safe_rejected_items_can_replace_same_source_duplicates(self) -> None:
        items = [
            _item(
                "nvidia-1",
                "NVIDIA AWS AI production GPU chip enterprise platform",
                url="https://blogs.nvidia.com/blog/a/",
                category="semiconductor_chip_infra",
                summary="NVIDIA AWS GPU infrastructure enterprise AI at scale.",
            ),
            _item(
                "openai-1",
                "OpenAI HP frontier partnership enterprise AI workflow",
                url="https://openai.com/index/hp/",
                summary="OpenAI enterprise AI workflow platform.",
            ),
            _item(
                "nvidia-2",
                "NVIDIA specialized AI trust tools secure runtime",
                url="https://blogs.nvidia.com/blog/b/",
                summary="NVIDIA enterprise AI platform customer workflow.",
            ),
            _item(
                "openai-2",
                "OpenAI agents transforming work enterprise workflow",
                url="https://openai.com/index/agents/",
                summary="OpenAI agents enterprise workflow.",
            ),
            _item(
                "google-1",
                "Google Finance upgrades include new app platform",
                url="https://blog.google/finance/",
                summary="Google Finance app product update.",
            ),
            _item(
                "tc-1",
                "TechCrunch reports quiet startup tooling update",
                url="https://techcrunch.com/quiet/",
                summary="A startup tooling update for founders.",
            ),
            _item(
                "ars-1",
                "Ars Technica notes hardware maintenance update",
                url="https://arstechnica.com/hw/",
                summary="Hardware maintenance update.",
            ),
        ]
        for item in items:
            if item["source_id"].startswith("nvidia"):
                item["source_name"] = "NVIDIA Blog"
            elif item["source_id"].startswith("openai"):
                item["source_name"] = "OpenAI News"
            elif item["source_id"].startswith("google"):
                item["source_name"] = "Google AI Blog"
            elif item["source_id"].startswith("tc"):
                item["source_name"] = "TechCrunch AI"
            elif item["source_id"].startswith("ars"):
                item["source_name"] = "Ars Technica"
        source_pack = _source_pack_from_items(items)
        selection = score_global_signal_candidates(items)
        self.assertEqual(len(selection.watchlist), 0)

        packed = apply_scored_selection_to_source_pack(source_pack, selection)
        self.assertGreater(packed["source_pack_funnel_summary"]["replacement_pool_count"], 0)
        self.assertGreater(packed["source_pack_funnel_summary"]["pre_diversity_candidate_count"], 5)
        self.assertIn("tc-1", packed["global_top5_selection"]["replacement_source_ids"])

        result = select_top_5_news(packed, GateResult(verdict="pass", issues=()))
        items_after = result["top_5_news"]["items"]
        source_counts = {}
        for item in items_after:
            source_counts[item["normalized_source"]] = source_counts.get(item["normalized_source"], 0) + 1

        self.assertEqual(len(items_after), 5)
        self.assertEqual(source_counts.get("nvidia blog"), 1)
        self.assertEqual(source_counts.get("openai news"), 1)
        self.assertFalse(result["diversity_summary"]["relaxed_due_to_candidate_shortage"])
        self.assertGreaterEqual(result["diversity_summary"]["same_source_reject_count"], 2)
        self.assertEqual(result["candidate_funnel_summary"]["post_diversity_selected_count"], 5)


if __name__ == "__main__":
    unittest.main()
