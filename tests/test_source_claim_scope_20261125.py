import pytest

from product_surface_contract import prepare_final_customer_copy, PRODUCT_SURFACE_DIAGNOSTIC_KEY
from prompts import build_full_prompt, build_top3_extraction_prompt
from source_claim_scope import CLAIM_SCOPE_UNVERIFIED, EVENT_DESTINATION_UNVERIFIED
from temporal_context_diagnostic import build_role_evidence_from_source_headings
from keysuri_generation_prompt import build_keysuri_generation_prompt, build_keysuri_generation_prompt_compact


def test_actual_nov25_named_person_return_does_not_require_literal_ceo_token():
    data = {"key_watchpoints": [{"headline": "젠슨 황의 백악관 복귀", "detail": "복귀 소식입니다."}]}
    result = prepare_final_customer_copy("today_genie", data, source_input={})
    assert EVENT_DESTINATION_UNVERIFIED in result[PRODUCT_SURFACE_DIAGNOSTIC_KEY]["issue_codes"]


def source_input(title, snippet="", source_id="source-last"):
    # The selected source is deliberately beyond the compact prompt's former
    # first-eight cutoff. Unselected sources must not inflate its text budget.
    sources = [{"source_id": f"unused-{i}", "snippet": "unrelated"} for i in range(12)]
    sources.append({"source_id": source_id, "source_url": "https://example.com/article",
                    "title": title, "snippet": snippet})
    item = {"news_id": "selected-id", "source_ids": [source_id], "headline": title}
    return {"program_id": "keysuri_global_tech", "news_scope": "global",
            "source_pack": {"sources": sources, "claims": []},
            "top_5_news": {"items": [item]}}


def inspect(text, original, *, lead=False):
    item = {"news_id": "selected-id", "headline": "검수 대상 기사", "summary": text}
    payload = {"top_5_news": {"items": [item]}}
    if lead:
        item["summary"] = "거래의 기술적 영향을 살펴봅니다."
        payload["briefing_display"] = {"opening_lead": text}
    prepared = prepare_final_customer_copy("keysuri_global_tech", payload, source_input=original)
    diagnostic = prepared.pop(PRODUCT_SURFACE_DIAGNOSTIC_KEY)
    assert prepared == payload  # QA must never rewrite substantive copy.
    return diagnostic


@pytest.mark.parametrize("lead", [False, True])
def test_company_object_completion_and_reported_price_cannot_be_upgraded(lead):
    original = source_input("Amazon's Decart acquisition", "A decision to acquire Decart for a reported $7.5 billion.")
    result = inspect("아마존은 소프트웨어 기업 데카르트를 75억 달러에 인수했습니다.", original, lead=lead)
    assert CLAIM_SCOPE_UNVERIFIED in result["issue_codes"]
    assert result["customer_surface_status"] == "PRODUCT_REVIEW_REQUIRED"


def test_source_bound_technology_agreement_and_unknown_close_stay_unmodified():
    original = source_input("Technology purchase agreement", "An agreement to purchase DOS technology; closing conditions remain.")
    result = inspect("아마존은 DOS 기술 매입 계약을 체결했으며 거래 종결은 미확인입니다.", original)
    assert CLAIM_SCOPE_UNVERIFIED not in result["issue_codes"]


def test_a_later_unknown_clause_does_not_hide_an_earlier_completion_assertion():
    original = source_input("Technology purchase agreement", "An agreement pending closing.")
    result = inspect("인수를 완료했지만 거래 종결은 미확인입니다.", original)
    assert CLAIM_SCOPE_UNVERIFIED in result["issue_codes"]


def test_reported_price_does_not_contaminate_an_unrelated_small_running_cost():
    original = source_input("Acquisition report", "A reported $7.5 billion transaction.")
    assert CLAIM_SCOPE_UNVERIFIED not in inspect("실행당 비용은 0.04달러입니다.", original, lead=True)["issue_codes"]


@pytest.mark.parametrize("bad", ["1만5천 개 저장소에 AI를 전면 도입했습니다.",
                                      "코드 리뷰 자동화에 성공했습니다.",
                                      "AI 에이전트를 성공적으로 이식했습니다."])
def test_repository_coverage_does_not_prove_workflow_or_universal_success(bad):
    original = source_input("Coding agents across 15,000 repositories")
    assert CLAIM_SCOPE_UNVERIFIED in inspect(bad, original)["issue_codes"]


def test_merge_request_and_negative_autonomy_qualification_are_allowed():
    original = source_input("Coding agents across 15,000 repositories")
    result = inspect("1만5천여 저장소에서 취약 의존성을 점검하고 수정안을 병합 요청으로 반환합니다. 전체 자동 배포가 아닙니다.", original)
    assert CLAIM_SCOPE_UNVERIFIED not in result["issue_codes"]


def test_unrelated_source_cannot_supply_selected_card_completion_evidence():
    original = source_input("Technology purchase agreement", "Agreement pending closing.")
    original["source_pack"]["sources"][0]["snippet"] = "completed the acquisition of the startup"
    assert CLAIM_SCOPE_UNVERIFIED in inspect("소프트웨어 기업을 인수 완료했습니다.", original)["issue_codes"]


def test_acquiring_a_startups_technology_is_not_acquiring_the_company():
    original = source_input("Technology transaction", "An agreement to acquire the startup's technology and hire its team.")
    assert CLAIM_SCOPE_UNVERIFIED in inspect("소프트웨어 스타트업을 인수하기로 합의했습니다.", original)["issue_codes"]


@pytest.mark.parametrize("builder", [build_keysuri_generation_prompt, build_keysuri_generation_prompt_compact])
def test_real_prompt_entry_points_keep_selected_evidence_after_source_eight(builder):
    original = source_input("Selected exact title", "Reported purchase, pending closing; selected-source-only-evidence.")
    prompt = builder(original)
    assert "selected-source-only-evidence" in prompt
    assert "RSS_METADATA_ONLY" in prompt
    assert "Repository coverage is not successful universal deployment" in prompt


def test_ceo_return_cannot_borrow_white_house_destination_from_washington_context():
    data = {"key_watchpoints": [{"headline": "기업 대표 복귀", "detail": "트럼프 대통령이 젠슨 황 엔비디아 CEO의 백악관 복귀를 원했습니다."}]}
    source = {"target_date": "2026-11-25", "top_market_news": [{"headline": "Trump wanted Jensen Huang back. Now the president is alone in Washington"}]}
    prepared = prepare_final_customer_copy("today_genie", data, source_input=source)
    assert EVENT_DESTINATION_UNVERIFIED in prepared[PRODUCT_SURFACE_DIAGNOSTIC_KEY]["issue_codes"]
    prepared.pop(PRODUCT_SURFACE_DIAGNOSTIC_KEY)
    assert prepared == data
    data["key_watchpoints"][0]["detail"] = "엔비디아 이사회는 젠슨 황을 엔비디아 CEO로 복귀시켰다고 발표했습니다."
    prepared = prepare_final_customer_copy("today_genie", data, source_input=source)
    assert EVENT_DESTINATION_UNVERIFIED not in prepared[PRODUCT_SURFACE_DIAGNOSTIC_KEY]["issue_codes"]


def test_unrelated_white_house_source_cannot_clear_a_bound_ceo_card():
    from today_genie_top3_assembly import canonical_news_id
    article = {"headline": "Trump wanted Jensen Huang back. Now the president is alone in Washington", "url": "https://example.com/ceo"}
    data = {"key_watchpoints": [{"news_id": canonical_news_id(article), "headline": "기업 대표 복귀", "detail": "젠슨 황 엔비디아 CEO의 백악관 복귀를 원했습니다."}]}
    source = {"target_date": "2026-11-25", "top_market_news": [article,
        {"headline": "A former advisor returned to the White House", "url": "https://example.com/unrelated"}]}
    result = prepare_final_customer_copy("today_genie", data, source_input=source)
    assert EVENT_DESTINATION_UNVERIFIED in result[PRODUCT_SURFACE_DIAGNOSTIC_KEY]["issue_codes"]


@pytest.mark.parametrize("day", ["2026-11-24", "2026-11-25"])
def test_daily_role_rule_reaches_both_prompts_and_current_mismatch_remains_blocked(day):
    evidence = build_role_evidence_from_source_headings(day,
        ["President Donald J. Trump", "Vice President JD Vance"],
        observed_at=day + "T06:00:00+09:00", source_sha256="a" * 64)
    source = {"target_date": day, "current_role_evidence": evidence, "top_market_news": []}
    for prompt in (build_top3_extraction_prompt(source), build_full_prompt("today_genie", source)):
        assert "당일 공식 근거에 따른 현재 직함은 '트럼프 대통령'" in prompt
    bad = {"risk_check": [{"detail": "트럼프 전 대통령과 엔비디아 관련 뉴스가 시장에 영향을 줍니다."}]}
    result = prepare_final_customer_copy("today_genie", bad, source_input=source)
    assert "customer_surface_current_office_role_mismatch" in result[PRODUCT_SURFACE_DIAGNOSTIC_KEY]["issue_codes"]
    old = {"summary": "2017년 당시 트럼프 전 대통령의 발언을 회고합니다."}
    result = prepare_final_customer_copy("today_genie", old, source_input=source)
    assert "customer_surface_current_office_role_mismatch" not in result[PRODUCT_SURFACE_DIAGNOSTIC_KEY]["issue_codes"]


def test_stale_role_evidence_cannot_supply_current_title_binding():
    source = {"target_date": "2026-11-25", "current_role_evidence": build_role_evidence_from_source_headings(
        "2026-11-24", ["President Donald J. Trump", "Vice President JD Vance"],
        observed_at="2026-11-24T06:00:00+09:00", source_sha256="a" * 64)}
    assert "당일 공식 근거에 따른 현재 직함은" not in build_top3_extraction_prompt(source)


@pytest.mark.parametrize("code", [CLAIM_SCOPE_UNVERIFIED, EVENT_DESTINATION_UNVERIFIED])
def test_missing_source_evidence_cannot_trigger_another_automatic_paid_regeneration(code):
    from auto_remediation import classify_issue_codes
    scope, blocking, unknown = classify_issue_codes([code])
    assert scope is None
    assert blocking == [code]
    assert unknown == []


@pytest.mark.parametrize("text,bad", [
    ("브릴스의 올해 누적 수주액은 46억8000만원입니다.", True),
    ("올해 디와이에이와 완료했거나 진행 중인 17개 프로젝트의 합산 수주액은 46억8000만원입니다.", False),
])
def test_customer_copy_boundary_keeps_order_counterparty_project_scope(text, bad):
    source = {"source_pack": {"sources": [{"source_id": "s", "title": "로봇 공급", "snippet": "디와이에이 생산라인 공급. 올해 누적 수주액 46억8000만원(17건)."}]},
              "top_5_news": {"items": [{"news_id": "n", "source_ids": ["s"]}]}}
    payload = {"top_5_news": {"items": [{"news_id": "n", "headline": "로봇 공급", "summary": text}]}}
    prepared = prepare_final_customer_copy("keysuri_korea_tech", payload, source_input=source)
    diagnostic = prepared.pop(PRODUCT_SURFACE_DIAGNOSTIC_KEY)
    assert prepared == payload
    assert (CLAIM_SCOPE_UNVERIFIED in diagnostic["issue_codes"]) is bad
