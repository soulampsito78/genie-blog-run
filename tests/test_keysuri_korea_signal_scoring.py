"""Tests for Kee-Suri Korea TOP5 signal scoring."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from keysuri_korea_signal_scoring import (
    AI_PRIMARY_CATEGORY,
    INDUSTRIAL_CATEGORIES,
    POLICY_CAPITAL_CATEGORIES,
    build_korea_selection_debug_report,
    classify_korea_tech_category,
    score_korea_signal_candidates,
    score_korea_tech_item,
    select_korea_top5,
)
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def _recent_iso(hours_ago: int = 6) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ).astimezone(KST).isoformat(timespec="seconds")


def _item(
    source_id: str,
    title: str,
    *,
    url: str = "",
    category: str = "korea_big_company_strategy",
    summary: str = "",
    feed_id: str = "",
    source_tier: str = "T3_QUALITY_PRESS",
) -> dict:
    return {
        "source_id": source_id,
        "title": title,
        "link": url or f"https://news.korea-test.co.kr/articles/{source_id}",
        "published_at": _recent_iso(6),
        "source_tier": source_tier,
        "category": category,
        "default_category": category,
        "summary": summary or title,
        "source_name": "Korea Test Press",
        "feed_id": feed_id or source_id.split("-")[0],
    }


class KeysuriKoreaSignalScoringTests(unittest.TestCase):
    def test_semiconductor_classification(self) -> None:
        primary, _, conf, reason = classify_korea_tech_category(
            "삼성전자 SK하이닉스 HBM DRAM 메모리 반도체 증설"
        )
        self.assertEqual(primary, "korea_semiconductor")
        self.assertGreater(conf, 0.4)
        self.assertTrue(reason)

    def test_ai_enterprise_classification(self) -> None:
        primary, _, conf, _ = classify_korea_tech_category(
            "국내 기업 AI 도입 LLM AICC 생성형 AI 파일럿"
        )
        self.assertEqual(primary, "korea_ai_enterprise")
        self.assertGreater(conf, 0.4)

    def test_robotics_classification(self) -> None:
        primary, _, _, _ = classify_korea_tech_category(
            "스마트팩토리 협동로봇 AMR 물류로봇 제조 자동화"
        )
        self.assertEqual(primary, "korea_robotics_manufacturing")

    def test_battery_classification(self) -> None:
        primary, _, _, _ = classify_korea_tech_category(
            "LG에너지솔루션 2차전지 ESS 전고체 배터리 EV 충전"
        )
        self.assertEqual(primary, "korea_battery_energy")

    def test_policy_classification(self) -> None:
        primary, _, _, _ = classify_korea_tech_category(
            "과기정통부 정책 규제 법안 조달 입찰 공공"
        )
        self.assertEqual(primary, "korea_policy_regulation")

    def test_startup_investment_classification(self) -> None:
        primary, _, _, _ = classify_korea_tech_category(
            "스타트업 시리즈A 투자 M&A TIPS VC 라운드"
        )
        self.assertEqual(primary, "korea_startup_investment")

    def test_ai_capped_at_two_when_non_ai_qualify(self) -> None:
        items = [
            _item(
                f"ai-{i}",
                f"국내 기업 AI 도입 LLM AICC 생성형 AI 에이전트 플랫폼 {i}",
                category="korea_ai_enterprise",
                summary=(
                    "삼성·네이버 등 국내 기업 AI 도입, LLM AICC 파일럿, "
                    "입찰·정책 일정 확인 필요."
                ),
            )
            for i in range(4)
        ] + [
            _item(
                "semi-1",
                "SK하이닉스 HBM DRAM 반도체 증설 투자 수주",
                category="korea_semiconductor",
                summary="국내 반도체 HBM 증설, 삼성·SK 공급망 투자 수주 일정.",
            ),
            _item(
                "rob-1",
                "두산로보틱스 스마트팩토리 협동로봇 자동화 공장",
                category="korea_robotics_manufacturing",
                summary="국내 스마트팩토리 로봇 자동화, 수주·입찰 일정.",
            ),
            _item(
                "bat-1",
                "LG에너지솔루션 2차전지 ESS 배터리 EV 투자",
                category="korea_battery_energy",
                summary="국내 배터리 ESS EV 투자 규제 리스크 기회.",
            ),
        ]
        result = score_korea_signal_candidates(items)
        ai_count = sum(1 for s in result.selected_top5 if s.is_ai_category)
        self.assertLessEqual(ai_count, 2)
        self.assertIn("final_category_distribution", result.to_dict())

    def test_industrial_mandatory_slot(self) -> None:
        items = [
            _item(
                f"plat-{i}",
                f"네이버 카카오 클라우드 SaaS 플랫폼 API 마켓플레이스 {i}",
                category="korea_platform_cloud_saas",
                summary="국내 플랫폼 클라우드 SaaS API, 입찰·파트너 일정.",
            )
            for i in range(6)
        ] + [
            _item(
                "semi-must",
                "삼성전자 SK하이닉스 HBM 반도체 증설 투자 수주",
                category="korea_semiconductor",
                summary="국내 반도체 HBM 증설 투자, 조달·수주 일정 확인.",
            ),
        ]
        result = score_korea_signal_candidates(items)
        industrial_selected = [
            s for s in result.selected_top5 if s.primary_category in INDUSTRIAL_CATEGORIES
        ]
        self.assertGreaterEqual(len(industrial_selected), 1)

    def test_policy_capital_mandatory_slot(self) -> None:
        items = [
            _item(
                f"cons-{i}",
                f"스마트폰 단말 출시 모빌리티 OTT 디바이스 {i}",
                category="korea_consumer_mobility",
                summary="국내 소비자 테크 단말 출시, 요금제 일정.",
            )
            for i in range(6)
        ] + [
            _item(
                "policy-must",
                "과기정통부 정책 규제 법안 조달 입찰 공고",
                category="korea_policy_regulation",
                summary="국내 정책 규제 조달 입찰, 마감 일정 확인.",
            ),
        ]
        result = score_korea_signal_candidates(items)
        policy_selected = [
            s
            for s in result.selected_top5
            if s.primary_category in POLICY_CAPITAL_CATEGORIES
        ]
        self.assertGreaterEqual(len(policy_selected), 1)

    def test_source_concentration_blocks_third_same_feed(self) -> None:
        items = []
        for i in range(2):
            items.append(
                _item(
                    f"feed-a-{i}",
                    f"삼성전자 반도체 HBM 투자 수주 증설 {i}",
                    category="korea_semiconductor",
                    summary="국내 반도체 HBM 투자 수주, 입찰 일정.",
                    feed_id="yna-industry",
                    url=f"https://yna.co.kr/industry/{i}",
                    source_tier="T2_TIER1_WIRE",
                )
            )
        items.append(
            _item(
                "feed-a-2",
                "삼성전자 반도체 HBM 투자 수주 증설 2",
                category="korea_semiconductor",
                summary="국내 반도체 HBM 투자 수주.",
                feed_id="yna-industry",
                url="https://yna.co.kr/industry/2",
                source_tier="T4_AGGREGATOR_BLOG",
            )
        )
        items.extend(
            [
                _item(
                    "alt-1",
                    "LG에너지솔루션 2차전지 ESS 배터리 EV 투자 규제 리스크",
                    category="korea_battery_energy",
                    feed_id="mk-tech",
                    url="https://mk.co.kr/tech/battery-1",
                    source_tier="T2_TIER1_WIRE",
                ),
                _item(
                    "alt-2",
                    "과기정통부 정책 규제 조달 입찰 공고 마감",
                    category="korea_policy_regulation",
                    feed_id="etnews-policy",
                    url="https://etnews.com/policy-1",
                    source_tier="T2_TIER1_WIRE",
                ),
                _item(
                    "alt-3",
                    "두산로보틱스 스마트팩토리 협동로봇 자동화 수주",
                    category="korea_robotics_manufacturing",
                    feed_id="robot-news",
                    url="https://robotnews.kr/factory-1",
                    source_tier="T2_TIER1_WIRE",
                ),
            ]
        )
        result = score_korea_signal_candidates(items)
        yna_count = sum(1 for s in result.selected_top5 if s.feed_id == "yna-industry")
        self.assertLessEqual(yna_count, 2)
        blocked = [
            s
            for s in result.watchlist
            if s.feed_id == "yna-industry" and s.reason_not_selected == "source_concentration_limit"
        ]
        self.assertTrue(blocked or yna_count <= 2)

    def test_pr_hype_penalty_and_flag(self) -> None:
        scored = score_korea_tech_item(
            _item(
                "pr-1",
                "보도자료: 협력 강화 파트너십 체결 고객사례",
                category="korea_platform_cloud_saas",
                summary="보도자료 기반 협력 강화 파트너십 체결, customer story.",
            )
        )
        self.assertLess(scored.scores.pr_hype_penalty, 0)
        self.assertTrue(scored.pr_hype_warning or scored.press_release_only)
        self.assertIn("pr_hype_penalty", scored.scores.to_dict())

    def test_domestic_relevance_boost(self) -> None:
        domestic = score_korea_tech_item(
            _item(
                "dom-1",
                "삼성전자 SK하이닉스 국내 반도체 공급망 투자 수주",
                category="korea_semiconductor",
                summary="국내 삼성·SK 반도체 공급망 투자, 조달 입찰 일정.",
            )
        )
        generic_item = _item(
            "gen-1",
            "Generic platform API update for overseas vendors",
            category="korea_platform_cloud_saas",
            summary="Platform API update for enterprise workflow in Silicon Valley.",
            url="https://example.com/platform-update",
        )
        generic_item["source_name"] = "Overseas Tech Wire"
        generic = score_korea_tech_item(generic_item)
        self.assertGreater(domestic.scores.domestic_relevance_boost, generic.scores.domestic_relevance_boost)

    def test_stock_only_hard_reject(self) -> None:
        stock = score_korea_tech_item(
            _item(
                "stock-1",
                "코스피 장중 급등 주가 상한가 마감",
                summary="코스닥 주가 급등 급락 장중 마감.",
            )
        )
        tech = score_korea_tech_item(
            _item(
                "tech-1",
                "SK하이닉스 HBM 반도체 증설 투자 수주",
                category="korea_semiconductor",
                summary="국내 반도체 HBM 투자 수주 일정.",
            )
        )
        self.assertEqual(stock.hard_reject_reason, "stock_only_no_tech_signal")
        self.assertGreater(tech.scores.base_score, stock.scores.base_score)

    def test_debug_report_shape(self) -> None:
        result = score_korea_signal_candidates(
            [
                _item(
                    "a1",
                    "삼성전자 SK하이닉스 HBM 반도체 증설",
                    category="korea_semiconductor",
                ),
                _item(
                    "a2",
                    "과기정통부 정책 규제 조달 입찰",
                    category="korea_policy_regulation",
                ),
            ]
        )
        payload = result.to_dict()
        self.assertIn("selected_top5", payload)
        self.assertIn("watchlist", payload)
        self.assertIn("final_category_distribution", payload)
        self.assertIn("final_source_distribution", payload)
        self.assertIn("source_concentration_decisions", payload)
        self.assertIn("summary", payload)
        self.assertIn("ai_count_in_top5", payload["summary"])
        if result.selected_top5:
            row = result.selected_top5[0].to_dict()
            self.assertIn("category_display_label", row)
            self.assertIn("owner_action_line", row)
            self.assertIn("next_day_impact_line", row)
            self.assertIn("selection_reason_tags", row)

    def test_build_korea_selection_debug_report(self) -> None:
        scored = score_korea_tech_item(
            _item("x1", "삼성 반도체 HBM 투자", category="korea_semiconductor")
        )
        report = build_korea_selection_debug_report([scored], [scored], [])
        self.assertIn("selected_top5", report)
        self.assertEqual(report.get("policy"), "keysuri_korea_top5_selection_v1")

    def test_score_output_fields(self) -> None:
        scored = score_korea_tech_item(
            _item(
                "fields-1",
                "국내 기업 AI 도입 LLM AICC",
                category="korea_ai_enterprise",
                summary="삼성 네이버 국내 AI 도입, 입찰 일정.",
            )
        )
        row = scored.to_dict()
        for key in (
            "score",
            "base_score",
            "final_score",
            "primary_category",
            "category_display_label",
            "category_confidence",
            "reason_for_category",
            "reason_for_selection",
            "is_ai_category",
            "is_industrial_category",
            "is_policy_or_capital_category",
        ):
            self.assertIn(key, row)
        self.assertEqual(scored.primary_category, AI_PRIMARY_CATEGORY)
        self.assertTrue(scored.is_ai_category)

    def test_select_korea_top5_returns_distributions(self) -> None:
        pool = [
            score_korea_tech_item(_item(f"s{i}", f"삼성 반도체 HBM {i}", category="korea_semiconductor"))
            for i in range(6)
        ]
        selected, decisions, _, dist, _, _ = select_korea_top5(pool)
        self.assertLessEqual(len(selected), 5)
        self.assertTrue(decisions)
        self.assertIsInstance(dist, dict)


if __name__ == "__main__":
    unittest.main()
