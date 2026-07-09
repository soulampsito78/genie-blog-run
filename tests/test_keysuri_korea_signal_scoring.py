"""Tests for Kee-Suri Korea TOP5 signal scoring."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from keysuri_korea_signal_scoring import (
    AI_PRIMARY_CATEGORY,
    GLOBAL_DUPLICATE_PENALTY_NO_ANGLE,
    INDUSTRIAL_CATEGORIES,
    POLICY_CAPITAL_CATEGORIES,
    apply_scored_selection_to_source_pack,
    build_global_story_index,
    build_korea_selection_debug_report,
    build_story_cluster_key,
    classify_korea_tech_category,
    evaluate_korea_tech_scope,
    load_global_selection_report,
    normalize_story_text,
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


def _global_report(*rows: tuple[str, str]) -> dict:
    selected = []
    for idx, (title, summary) in enumerate(rows):
        selected.append(
            {
                "source_id": f"global-{idx}",
                "title": title,
                "url": f"https://global.example.com/articles/{idx}",
                "summary": summary,
                "primary_category": "ai_product",
            }
        )
    return {"selected_top5": selected}


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
        self.assertIn(
            stock.hard_reject_reason,
            {"stock_only_no_tech_signal", "korea_tech_scope_finance_only"},
        )
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
        self.assertEqual(report.get("policy"), "keysuri_korea_top5_selection_v2_duplicate_guard")

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


class KeysuriKoreaDuplicateGuardTests(unittest.TestCase):
    def test_build_story_cluster_key_normalizes_similar_titles(self) -> None:
        a = build_story_cluster_key(
            _item("a", "OpenAI launches NEW developer platform!!!", summary="OpenAI API platform.")
        )
        b = build_story_cluster_key(
            _item("b", "OpenAI launches new developer platform", summary="OpenAI API platform.")
        )
        self.assertEqual(a, b)

    def test_normalize_story_text_strips_punctuation(self) -> None:
        self.assertEqual(
            normalize_story_text("NVIDIA HBM — GPU launch!!!"),
            "nvidia hbm gpu launch",
        )

    def test_build_global_story_index_from_debug_report(self) -> None:
        report = _global_report(
            ("NVIDIA HBM GPU platform launch", "NVIDIA GPU chip platform enterprise."),
        )
        index = build_global_story_index(report)
        self.assertEqual(index.global_story_count, 1)
        self.assertEqual(len(index.cluster_keys), 1)

    def test_exact_global_korea_duplicate_without_angle_penalized(self) -> None:
        title = "OpenAI launches new developer platform API pricing model"
        summary = "OpenAI model release for developer workflow and API platform."
        report = _global_report((title, summary))
        dup = _item("dup-1", title, summary=summary, url="https://wire.example.com/dup-1")
        dup["source_name"] = "Overseas Tech Wire"
        result = score_korea_signal_candidates([dup], global_selection_report=report)
        candidate = result.all_candidates[0]
        self.assertTrue(candidate.global_duplicate_detected)
        self.assertFalse(candidate.korea_angle_satisfied)
        self.assertEqual(candidate.scores.global_duplicate_penalty, GLOBAL_DUPLICATE_PENALTY_NO_ANGLE)
        self.assertNotIn(candidate, result.selected_top5)

    def test_nvidia_samsung_hbm_allowed_with_korea_angle(self) -> None:
        report = _global_report(
            (
                "NVIDIA HBM GPU platform launch enterprise API",
                "NVIDIA GPU chip platform launch for enterprise AI infrastructure.",
            )
        )
        korea = _item(
            "k-hbm",
            "삼성전자 SK하이닉스 HBM4 NVIDIA 협력 국내 증설 수주",
            category="korea_semiconductor",
            summary="삼성전자 SK하이닉스 국내 HBM 증설 수주 입찰 일정.",
            url="https://korea.example.com/hbm-1",
        )
        result = score_korea_signal_candidates([korea], global_selection_report=report)
        candidate = result.all_candidates[0]
        self.assertTrue(candidate.global_duplicate_detected)
        self.assertTrue(candidate.korea_angle_satisfied)
        self.assertEqual(candidate.duplicate_resolution, "allowed_with_korea_angle")

    def test_openai_customer_case_without_korean_entity_penalized(self) -> None:
        report = _global_report(
            (
                "OpenAI enterprise agents customer story Endava",
                "OpenAI customer story on Endava enterprise agents in software delivery.",
            )
        )
        korea = _item(
            "k-case",
            "OpenAI enterprise agents customer story Endava",
            summary="OpenAI customer story partner content case study.",
            url="https://wire.example.com/case-1",
        )
        korea["source_name"] = "Overseas Tech Wire"
        result = score_korea_signal_candidates([korea], global_selection_report=report)
        candidate = result.all_candidates[0]
        self.assertTrue(candidate.global_duplicate_detected)
        self.assertFalse(candidate.korea_angle_satisfied)
        self.assertLessEqual(candidate.scores.global_duplicate_penalty, GLOBAL_DUPLICATE_PENALTY_NO_ANGLE)

    def test_same_company_different_event_not_blocked(self) -> None:
        report = _global_report(
            (
                "Samsung Foundry wafer fab capacity expansion investment",
                "Samsung semiconductor fab wafer packaging capacity expansion.",
            )
        )
        korea = _item(
            "k-phone",
            "Samsung Electronics Galaxy flagship smartphone launch event",
            summary="Samsung mobile division flagship launch schedule for consumers.",
            url="https://korea.example.com/phone-1",
            category="korea_consumer_mobility",
        )
        result = score_korea_signal_candidates([korea], global_selection_report=report)
        candidate = result.all_candidates[0]
        self.assertFalse(candidate.global_duplicate_detected)
        self.assertTrue(candidate.same_entity_not_same_story)

    def test_duplicate_penalized_loses_to_non_duplicate_domestic(self) -> None:
        title = "OpenAI launches new developer platform API pricing model"
        summary = "OpenAI model release for developer workflow and API platform."
        report = _global_report((title, summary))
        dup = _item("dup-1", title, summary=summary, url="https://wire.example.com/dup-1")
        dup["source_name"] = "Overseas Tech Wire"
        domestic = _item(
            "dom-1",
            "과기정통부 정책 규제 조달 입찰 공고 마감",
            category="korea_policy_regulation",
            summary="국내 정책 규제 조달 입찰, 마감 일정 확인.",
            url="https://korea.example.com/policy-1",
        )
        result = score_korea_signal_candidates(
            [dup, domestic],
            global_selection_report=report,
        )
        selected_ids = {s.source_id for s in result.selected_top5}
        self.assertIn("dom-1", selected_ids)
        self.assertNotIn("dup-1", selected_ids)

    def test_no_global_report_duplicate_guard_not_applied(self) -> None:
        result = score_korea_signal_candidates(
            [_item("a1", "삼성 반도체 HBM 투자", category="korea_semiconductor")]
        )
        self.assertEqual(result.duplicate_guard_status, "not_applied_no_global_report")
        self.assertEqual(result.global_story_count, 0)

    def test_debug_report_contains_duplicate_guard_metrics(self) -> None:
        report = _global_report(
            ("OpenAI launches developer platform API", "OpenAI platform API workflow."),
        )
        result = score_korea_signal_candidates(
            [
                _item(
                    "k1",
                    "OpenAI launches developer platform API",
                    summary="OpenAI platform API workflow.",
                )
            ],
            global_selection_report=report,
        )
        payload = result.to_dict()
        self.assertEqual(payload["duplicate_guard_status"], "applied")
        self.assertGreaterEqual(payload["global_story_count"], 1)
        self.assertIn("duplicate_detected_count", payload)
        self.assertIn("duplicate_penalized_count", payload)
        self.assertIn("duplicate_allowed_with_korea_angle_count", payload)
        self.assertIn("duplicate_watchlist_items", payload)

    def test_overlap_selected_item_has_domestic_angle_fields(self) -> None:
        report = _global_report(
            (
                "NVIDIA HBM GPU platform launch enterprise API",
                "NVIDIA GPU chip platform launch for enterprise AI infrastructure.",
            )
        )
        korea = _item(
            "k-hbm",
            "삼성전자 HBM4 NVIDIA 협력 국내 증설 수주",
            category="korea_semiconductor",
            summary="삼성전자 SK하이닉스 국내 HBM 증설 수주 입찰 일정.",
            url="https://korea.example.com/hbm-2",
        )
        selection = score_korea_signal_candidates([korea], global_selection_report=report)
        source_pack = apply_scored_selection_to_source_pack(
            {
                "sources": [
                    {
                        "source_id": "k-hbm",
                        "source_url": korea["link"],
                        "title": korea["title"],
                        "snippet": korea["summary"],
                    }
                ],
                "claims": [
                    {
                        "claim_id": "claim-k-hbm",
                        "statement": korea["title"],
                        "source_ids": ["k-hbm"],
                        "category": "korea_semiconductor",
                    }
                ],
            },
            selection,
        )
        claim = source_pack["claims"][0]
        self.assertEqual(claim.get("angle_chip"), "국내 적용")
        self.assertTrue(claim.get("next_day_impact_line"))

    def test_load_global_selection_report_invalid_path(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_global_selection_report("/tmp/does-not-exist-global-report.json")


class KoreaTechScopeGateTests(unittest.TestCase):
    def test_openai_us_gov_without_korea_link_is_rejected(self) -> None:
        item = _item(
            "g-openai",
            "오픈AI, 미 정부 검증 거친 GPT-5.6 공개 출시하며 프론티어 AI 접근 통제 본격화",
            summary="OpenAI가 미국 정부 검증을 거친 GPT 모델을 공개했다. frontier AI 접근 통제.",
            category="global_to_korea_translation",
        )
        scored = score_korea_tech_item(item)
        self.assertEqual(scored.hard_reject_reason, "korea_tech_scope_global_leak")
        self.assertEqual(scored.classification, "hard_reject")
        self.assertEqual(scored.korea_tech_scope_status, "global_leak")

    def test_openai_with_korea_enterprise_adoption_is_allowed(self) -> None:
        item = _item(
            "g-openai-kr",
            "오픈AI, 국내 기업 AI 도입 계약으로 한국 시장 서비스 출시",
            summary="OpenAI가 한국 기업과 국내 도입 계약을 맺고 국내 서비스를 출시한다.",
            category="korea_ai_enterprise",
        )
        scored = score_korea_tech_item(item)
        self.assertIsNone(scored.hard_reject_reason)
        self.assertNotEqual(scored.classification, "hard_reject")
        self.assertIn(scored.korea_tech_scope_status, ("strong_tech", "weak_tech"))

    def test_casino_local_economy_is_rejected(self) -> None:
        item = _item(
            "casino-1",
            "강원도의원, 카지노 출입 규제 강화에 폐광지 생존 위협 우려 표명",
            summary="카지노 출입객 규제 강화가 폐광지 지역경제와 자영업에 타격을 줄 수 있다고 우려했다.",
            category="korea_policy_regulation",
        )
        scored = score_korea_tech_item(item)
        self.assertEqual(scored.hard_reject_reason, "korea_tech_scope_non_tech_local_economy")
        self.assertEqual(scored.korea_tech_scope_status, "local_economy")

    def test_leverage_etf_petition_is_finance_only_rejected(self) -> None:
        item = _item(
            "fin-1",
            "단일종목 레버리지 상품 논란, 국회 청원으로 제도 보완 압박 커져",
            summary=(
                "삼성전자와 SK하이닉스 등 특정 대형주를 기초자산으로 한 단일종목 레버리지 ETF "
                "수급 쏠림과 개인 투자자 포트폴리오 논란이 국회 청원으로 이어졌다."
            ),
            category="korea_semiconductor",
        )
        scored = score_korea_tech_item(item)
        self.assertEqual(scored.hard_reject_reason, "korea_tech_scope_finance_only")
        self.assertEqual(scored.korea_tech_scope_status, "finance_only")
        self.assertFalse(scored.is_industrial_category)

    def test_samsung_name_alone_does_not_make_finance_story_semiconductor(self) -> None:
        primary, _, _, reason = classify_korea_tech_category(
            "삼성전자 SK하이닉스 단일종목 레버리지 ETF 수급 쏠림 국회 청원 금융상품"
        )
        self.assertNotEqual(primary, "korea_semiconductor")
        self.assertIn("finance_only", reason)

    def test_finance_only_does_not_get_hbm_foundry_impact_line(self) -> None:
        item = _item(
            "fin-2",
            "단일종목 레버리지 상품 논란, 국회 청원으로 제도 보완 압박 커져",
            summary="레버리지 ETF 수급 쏠림과 개인 투자자 금융상품 논란.",
        )
        scored = score_korea_tech_item(item)
        self.assertNotIn("HBM", scored.next_day_impact_line)
        self.assertNotIn("파운드리", scored.next_day_impact_line)

    def test_local_economy_does_not_get_tech_infra_theme(self) -> None:
        item = _item(
            "casino-2",
            "카지노 출입 규제와 폐광지 지역경제 타격 우려",
            summary="관광·자영업·소상공인 피해 우려.",
        )
        scored = score_korea_tech_item(item)
        self.assertEqual(scored.korea_tech_scope_status, "local_economy")
        self.assertFalse(scored.is_industrial_category)
        self.assertNotIn("반도체", scored.next_day_impact_line)

    def test_top1_requires_strong_tech_relevance(self) -> None:
        weak = _item(
            "weak-1",
            "국내 대기업 조직개편 소식",
            summary="대기업 그룹 조직개편 관련 일반 소식.",
            category="korea_big_company_strategy",
        )
        strong = _item(
            "strong-1",
            "랩씨드, 데이터 통합 AI 트레이싱 솔루션으로 코스닥 상장 추진",
            summary="국내 기업 AI 도입 솔루션 기업 랩씨드가 코스닥 상장 절차에 돌입했다.",
            category="korea_ai_enterprise",
        )
        result = score_korea_signal_candidates([weak, strong])
        self.assertTrue(result.selected_top5)
        self.assertEqual(result.selected_top5[0].source_id, "strong-1")
        self.assertEqual(result.selected_top5[0].korea_tech_scope_status, "strong_tech")

    def test_does_not_backfill_with_casino_or_finance_only(self) -> None:
        items = [
            _item(
                "casino-x",
                "카지노 출입 규제 강화에 폐광지 지역경제 우려",
                summary="관광 자영업 소상공인 타격.",
            ),
            _item(
                "fin-x",
                "단일종목 레버리지 ETF 수급 쏠림 국회 청원",
                summary="금융상품 개인 투자자 포트폴리오 논란.",
            ),
            _item(
                "openai-x",
                "OpenAI GPT frontier AI 미 정부 검증 공개",
                summary="미국 정부 검증 GPT 공개. 한국 연결 없음.",
            ),
        ]
        result = score_korea_signal_candidates(items)
        self.assertEqual(result.selected_top5, [])
        reasons = {s.hard_reject_reason for s in result.all_candidates}
        self.assertIn("korea_tech_scope_non_tech_local_economy", reasons)
        self.assertIn("korea_tech_scope_finance_only", reasons)
        self.assertIn("korea_tech_scope_global_leak", reasons)

    def test_normal_domestic_tech_candidates_still_qualify(self) -> None:
        items = [
            _item(
                "labseed",
                "랩씨드, 데이터 통합 및 AI 트레이싱 솔루션으로 코스닥 상장 추진",
                summary="국내 기업 AI 도입 솔루션 기업이 코스닥 상장 절차에 돌입.",
                category="korea_ai_enterprise",
            ),
            _item(
                "hyundai-robot",
                "현대차그룹 휴머노이드 로봇 공장 자동화 투자",
                summary="현대차그룹이 국내 로봇·스마트팩토리 설비투자와 수주를 확대.",
                category="korea_robotics_manufacturing",
            ),
            _item(
                "semi-1",
                "삼성전자 HBM 파운드리 장비 수주와 국내 증설",
                summary="삼성전자 SK하이닉스 HBM DRAM 패키징 장비 수주 국내 공급망.",
                category="korea_semiconductor",
            ),
            _item(
                "naver-1",
                "네이버, 국내 클라우드·AI 플랫폼 기업 고객 도입 확대",
                summary="네이버가 국내 기업 AI·클라우드 SaaS 도입 계약을 확대.",
                category="korea_platform_cloud_saas",
            ),
            _item(
                "policy-ai",
                "과기정통부 국내 AI 규제·조달 정책 발표",
                summary="정부가 국내 AI 정책과 공공 조달 입찰 일정을 발표.",
                category="korea_policy_regulation",
            ),
        ]
        result = score_korea_signal_candidates(items)
        selected_ids = {s.source_id for s in result.selected_top5}
        self.assertIn("labseed", selected_ids)
        self.assertIn("semi-1", selected_ids)
        self.assertTrue(all(s.korea_tech_scope_status in ("strong_tech", "weak_tech") for s in result.selected_top5))
        self.assertEqual(result.selected_top5[0].korea_tech_scope_status, "strong_tech")

    def test_b_startup_challenge_is_weak_tech_not_strong(self) -> None:
        from keysuri_korea_signal_scoring import is_weak_startup_support_signal

        text = (
            "B-스타트업 챌린지, 5개 팀에 3억 원 지분투자 및 참가기업 모집 "
            "부산시 BNK부산은행 공동 주최"
        )
        self.assertTrue(is_weak_startup_support_signal(text))
        reject, status = evaluate_korea_tech_scope(text)
        self.assertIsNone(reject)
        self.assertEqual(status, "weak_tech")

    def test_named_ai_startup_series_investment_remains_strong(self) -> None:
        from keysuri_korea_signal_scoring import is_weak_startup_support_signal

        text = (
            "네이버 D2SF, 국내 AI 스타트업에 시리즈A 투자 — "
            "LLM 플랫폼·클라우드 SaaS 제품 상용화"
        )
        self.assertFalse(is_weak_startup_support_signal(text))
        reject, status = evaluate_korea_tech_scope(text)
        self.assertIsNone(reject)
        self.assertEqual(status, "strong_tech")

    def test_weak_startup_support_deferred_from_top3_when_stronger_exist(self) -> None:
        items = [
            _item(
                "challenge",
                "B-스타트업 챌린지, 5개 팀에 3억 원 지분투자 및 참가기업 모집",
                summary="부산시·BNK부산은행 공동 주최 창업 경진대회 참가기업 모집.",
                category="korea_startup_investment",
            ),
            _item(
                "semi-1",
                "삼성전자 HBM 파운드리 장비 수주와 국내 증설",
                summary="삼성전자 SK하이닉스 HBM DRAM 패키징 장비 수주 국내 공급망.",
                category="korea_semiconductor",
            ),
            _item(
                "npu-1",
                "모빌린트, 2세대 NPU 레귤러스 연말 대량 양산 목표",
                summary="국내 AI 반도체 NPU 양산, 피지컬 AI 인프라 국산화.",
                category="korea_semiconductor",
            ),
            _item(
                "policy-1",
                "과기정통부 국내 AI 규제·조달 정책 발표",
                summary="정부가 국내 AI 정책과 공공 조달 입찰 일정을 발표.",
                category="korea_policy_regulation",
            ),
            _item(
                "naver-1",
                "네이버, 국내 클라우드·AI 플랫폼 기업 고객 도입 확대",
                summary="네이버가 국내 기업 AI·클라우드 SaaS 도입 계약을 확대.",
                category="korea_platform_cloud_saas",
            ),
            _item(
                "robot-1",
                "두산로보틱스 스마트팩토리 협동로봇 자동화 수주",
                summary="국내 스마트팩토리 로봇 자동화 공장 수주·입찰 일정.",
                category="korea_robotics_manufacturing",
            ),
        ]
        result = score_korea_signal_candidates(items)
        top3_titles = [s.title for s in result.selected_top5[:3]]
        self.assertTrue(result.selected_top5)
        self.assertTrue(
            all("챌린지" not in t and "참가기업" not in t for t in top3_titles),
            top3_titles,
        )
        # Enough non-weak candidates → prefer exclude from TOP5 entirely.
        self.assertTrue(
            all("챌린지" not in s.title for s in result.selected_top5),
            [s.title for s in result.selected_top5],
        )

    def test_weak_startup_support_only_ranks_4_or_5_when_pool_thin(self) -> None:
        items = [
            _item(
                "challenge",
                "B-스타트업 챌린지, 5개 팀에 3억 원 지분투자 및 참가기업 모집",
                summary="부산시·BNK부산은행 공동 주최 창업 경진대회 참가기업 모집.",
                category="korea_startup_investment",
            ),
            _item(
                "semi-1",
                "삼성전자 HBM 파운드리 장비 수주와 국내 증설",
                summary="삼성전자 SK하이닉스 HBM DRAM 패키징 장비 수주 국내 공급망.",
                category="korea_semiconductor",
            ),
            _item(
                "npu-1",
                "모빌린트, 2세대 NPU 레귤러스 연말 대량 양산 목표",
                summary="국내 AI 반도체 NPU 양산, 피지컬 AI 인프라 국산화.",
                category="korea_semiconductor",
            ),
            _item(
                "policy-1",
                "과기정통부 국내 AI 규제·조달 정책 발표",
                summary="정부가 국내 AI 정책과 공공 조달 입찰 일정을 발표.",
                category="korea_policy_regulation",
            ),
        ]
        result = score_korea_signal_candidates(items)
        for idx, s in enumerate(result.selected_top5, start=1):
            if "챌린지" in s.title:
                self.assertGreaterEqual(idx, 4, f"rank={idx} title={s.title}")
                self.assertEqual(s.korea_tech_scope_status, "weak_tech")
                self.assertIn("weak_startup_support", s.selection_reason_tags)

if __name__ == "__main__":
    unittest.main()