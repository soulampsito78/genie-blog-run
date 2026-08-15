from __future__ import annotations

import copy
import unittest

from keysuri_briefing_content_enricher import enrich_korea_top5_item_content
from keysuri_korea_signal_scoring import (
    CATEGORY_KO_LABELS,
    classify_korea_tech_category,
)
from keysuri_quality_adjudication import (
    CUSTOMER_WARNING_CONFIRMATION,
    EDITORIAL_READY,
    EDITORIAL_REVIEW,
    OWNER_SEND_WARNING,
    SAFETY_SAFE,
    SAFETY_UNSAFE,
    adjudicate_keysuri_owner_surface,
    run_keysuri_graded_validation_no_send_proof,
)


DEEPX_SOURCE_SUMMARY = (
    "국산 온디바이스 AI 반도체(NPU) ‘DX-M1’이 양산 1년 만에 글로벌 9개 "
    "국가·지역에서 77건, 1,300만달러 이상의 상업용 구매주문(PO)을 확보했다. "
    "전체 주문의 62%가 최근 4개월에 집중돼 수주 속도도 빨라지는 흐름이다. "
    "초저전력 AI 반도체 기업 딥엑스(DEEPX)는 이 같은 내용의 DX-M1 양산 "
    "1년 실적을 공개했다."
)

# Sanitized production-derived item from run
# 20260815_114119_keysuri_korea_tech_ba60b2f4.
DEEPX_BROKEN_ITEM = {
    "rank": 3,
    "news_id": "claim-live-platum-sanitized",
    "korean_title": (
        "딥엑스, 온디바이스 AI 반도체 NPU 양산 1년 만에 9개국서 77건 수주"
    ),
    "what_happened": (
        "국내 온디바이스 AI 반도체 기업 딥엑스가 NPU 'DX-M1' 양산 1년 만에 "
        "9개 국가·지역에서 77건 1,300만 달러 이상의 상업용 구매주문(PO)을 "
        "확보했습니다. 특히 최근 4개월간 전체 주문의 62%가 집중되며 수주 "
        "속도가 빨라지고 있습니다."
    ),
    "why_now": (
        "국내 AI 반도체 스타트업의 글로벌 시장 성과는 국내 기술력의 경쟁력을 "
        "입증하며 온디바이스 AI 시장의 성장 가능성을 보여줍니다. 이는 국내 "
        "시스템 반도체 생태계 전반에 긍정적인 신호로 작용합니다."
    ),
    "owner_angle": (
        "딥엑스의 실제 납품 및 양산 규모 확대 여부를 지속적으로 확인해야 합니다. "
        "특히 국내 반도체 소부장 기업들의 수혜 여부만 이어서 보면 됩니다. "
        "내일은 배터리·에너지 관련 파트너·고객·입찰 움직임만 좁혀 보면 됩니다."
    ),
    "next_watch": (
        "딥엑스의 추가 수주 발표 및 실제 매출액 증가 추이.; 온디바이스 AI "
        "반도체 시장의 글로벌 경쟁 동향.; 파운드리, 패키징, 테스트 등 후공정 "
        "협력사들의 수주 물량 변화."
    ),
    "selection_reason": (
        "배터리·에너지 관점에서 오늘 한국에서 의미 있는 신호로 선정했습니다."
    ),
    "category": "korea_battery_energy",
    "primary_category": "korea_battery_energy",
    "category_label_ko": "국내 배터리 / EV / 에너지",
    "owner_action_line": (
        "내일 국내 배터리 / EV / 에너지 관련 파트너·고객·입찰·정책 일정을 "
        "점검하세요."
    ),
}


OTHER_LIVE_ITEMS = [
    {
        "rank": 1,
        "korean_title": "무역 장벽 속 에너지 기술 시장 성장, 2035년 2.6조 달러 전망",
        "what_happened": "태양광, 풍력, 배터리, 전기차 등 핵심 에너지 기술 시장이 성장했습니다.",
        "selection_reason": "배터리·에너지 관점에서 의미 있는 신호로 선정했습니다.",
        "owner_angle": "에너지 시장과 국내 배터리 기업의 수주를 확인합니다.",
        "next_watch": "태양광·풍력·배터리 기업의 투자 계획을 확인합니다.",
        "primary_category": "korea_battery_energy",
        "category_label_ko": "국내 배터리 / EV / 에너지",
    },
    {
        "rank": 2,
        "korean_title": "산업부·현대차그룹·육군, 로봇·피지컬 AI 국방 적용 확대 MOU 체결",
        "what_happened": "민간 피지컬 AI 기술과 국방 로봇의 실증을 추진합니다.",
        "selection_reason": "대기업 기술 전략 관점에서 의미 있는 신호로 선정했습니다.",
        "owner_angle": "로봇·피지컬 AI 실증과 국방 조달 일정을 확인합니다.",
        "next_watch": "로봇 도입 로드맵과 예산을 확인합니다.",
        "primary_category": "korea_big_company_strategy",
        "category_label_ko": "국내 대기업 테크 전략",
    },
    {
        "rank": 4,
        "korean_title": "사이오닉에이아이, 금융 규제산업용 AI 에이전트 개발",
        "what_happened": "금융 문서의 근거를 추적하는 온프레미스 AI 에이전트를 개발합니다.",
        "selection_reason": "정책·공공 인프라 관점에서 의미 있는 신호로 선정했습니다.",
        "owner_angle": "금융권 도입과 규제 가이드라인을 확인합니다.",
        "next_watch": "파일럿 테스트와 정부 지원 성과를 확인합니다.",
        "primary_category": "korea_policy_regulation",
        "category_label_ko": "국내 정책 / 규제 / 공공",
    },
    {
        "rank": 5,
        "korean_title": "경남·부산·울산, 창업-BuS 연합 IR 개최",
        "what_happened": "지역 스타트업 13개사가 연합 IR과 정책자금 상담에 참여했습니다.",
        "selection_reason": "스타트업 투자 관점에서 의미 있는 신호로 선정했습니다.",
        "owner_angle": "후속 투자 유치와 지역 협력 기회를 확인합니다.",
        "next_watch": "투자 유치 성과와 추가 지원 정책을 확인합니다.",
        "primary_category": "korea_startup_investment",
        "category_label_ko": "국내 스타트업 / 투자 / M&A",
    },
]


def _adjudicate(item: dict):
    return adjudicate_keysuri_owner_surface(
        program_id="keysuri_korea_tech",
        subject="[운영자 검토] 한국 테크 브리핑",
        email_html="<html><body><p>한국 테크 브리핑</p></body></html>",
        structured_briefing={"top_5_news": {"items": [item]}},
    )


class KeysuriKoreaCrossFieldContextTests(unittest.TestCase):
    def test_01_root_cause_deepx_classifies_as_semiconductor(self) -> None:
        category, secondary, confidence, reason = classify_korea_tech_category(
            DEEPX_SOURCE_SUMMARY
        )
        self.assertEqual(category, "korea_semiconductor")
        self.assertNotEqual(category, "korea_battery_energy")
        self.assertGreater(confidence, 0.45)
        self.assertIn("keyword_hits", reason)
        self.assertNotIn("korea_battery_energy", secondary)

    def test_02_exact_broken_surface_is_safe_review(self) -> None:
        result = _adjudicate(copy.deepcopy(DEEPX_BROKEN_ITEM))
        self.assertEqual(result["safety_verdict"], SAFETY_SAFE)
        self.assertEqual(result["editorial_verdict"], EDITORIAL_REVIEW)
        self.assertEqual(result["owner_delivery_behavior"], OWNER_SEND_WARNING)
        self.assertEqual(
            result["customer_approval_policy"], CUSTOMER_WARNING_CONFIRMATION
        )
        self.assertEqual(
            result["review_issue_codes"],
            ["keysuri_cross_field_context_mismatch"],
        )

    def test_03_producer_repair_is_same_item_aligned_and_idempotent(self) -> None:
        category, _, _, _ = classify_korea_tech_category(DEEPX_SOURCE_SUMMARY)
        meta = {
            "statement": "딥엑스 NPU, 양산 1년 만에 9개국서 수주 77건",
            "summary": DEEPX_SOURCE_SUMMARY,
            "source_name": "공개 기술 매체",
            "primary_category": category,
            "category_label_ko": CATEGORY_KO_LABELS[category],
            "category_display_label": CATEGORY_KO_LABELS[category],
            "owner_action_line": (
                "내일 국내 반도체 / 장비 / 소재 관련 파트너·고객·입찰·정책 "
                "일정을 점검하세요."
            ),
            "next_day_impact_line": "내일 국내 반도체 공급망과 양산 일정을 확인하세요.",
        }
        once = enrich_korea_top5_item_content(copy.deepcopy(DEEPX_BROKEN_ITEM), meta=meta)
        twice = enrich_korea_top5_item_content(copy.deepcopy(once), meta=meta)
        self.assertEqual(once, twice)
        self.assertEqual(once["primary_category"], "korea_semiconductor")
        for field in (
            "selection_reason",
            "why_it_matters",
            "owner_angle",
            "business_implication",
            "next_watch",
            "owner_action_line",
        ):
            self.assertNotIn("배터리", str(once.get(field) or ""), field)
        self.assertIn("반도체", once["selection_reason"])
        self.assertIn("반도체", once["owner_angle"])
        repaired_result = _adjudicate(once)
        self.assertEqual(repaired_result["safety_verdict"], SAFETY_SAFE)
        self.assertEqual(repaired_result["editorial_verdict"], EDITORIAL_READY)

    def test_04_other_four_live_items_have_no_cross_item_leakage(self) -> None:
        result = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 한국 테크 브리핑",
            email_html="<html><body><p>TOP5</p></body></html>",
            structured_briefing={
                "top_5_news": {"items": copy.deepcopy(OTHER_LIVE_ITEMS)}
            },
        )
        self.assertEqual(result["safety_verdict"], SAFETY_SAFE)
        self.assertEqual(result["editorial_verdict"], EDITORIAL_READY)
        self.assertNotIn(
            "keysuri_cross_field_context_mismatch", result["issue_codes"]
        )

    def test_05_energy_and_robotics_controls_remain_aligned(self) -> None:
        energy, _, _, _ = classify_korea_tech_category(
            "태양광 풍력 배터리 전기차 ESS 에너지 기술 시장 확대"
        )
        robotics, _, _, _ = classify_korea_tech_category(
            "국내 로봇 피지컬 AI 스마트팩토리 자동화 실증 확대"
        )
        self.assertEqual(energy, "korea_battery_energy")
        self.assertEqual(robotics, "korea_robotics_manufacturing")

    def test_06_unsupported_claim_still_holds(self) -> None:
        result = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="제목",
            email_html="<html><body>본문</body></html>",
            extra_findings=[{"issue_code": "unsupported_claim", "field": "top5[0]"}],
        )
        self.assertEqual(result["safety_verdict"], SAFETY_UNSAFE)

    def test_07_deployed_no_send_proof_contract_includes_deepx(self) -> None:
        proof = run_keysuri_graded_validation_no_send_proof()
        self.assertTrue(proof["ok"])
        cases = {row["name"]: row for row in proof["cases"]}
        self.assertEqual(
            cases["deepx_original_wrong_domain"]["editorial_verdict"],
            EDITORIAL_REVIEW,
        )
        self.assertEqual(
            cases["deepx_after_producer_repair"]["editorial_verdict"],
            EDITORIAL_READY,
        )
        self.assertEqual(proof["side_effects"]["model"], 0)
        self.assertEqual(proof["side_effects"]["image"], 0)
        self.assertEqual(proof["side_effects"]["smtp"], 0)
        self.assertEqual(proof["side_effects"]["customer"], 0)


if __name__ == "__main__":
    unittest.main()
