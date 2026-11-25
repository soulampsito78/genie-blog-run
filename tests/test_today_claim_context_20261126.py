from copy import deepcopy

import pytest

from product_surface_contract import prepare_final_customer_copy, PRODUCT_SURFACE_DIAGNOSTIC_KEY
from prompts import build_full_prompt, build_top3_extraction_prompt
from today_claim_context import (
    SESSION_CAUSALITY, PERSON_SCOPE, DOMESTIC_APPLICATION, CONSENSUS_SCOPE,
)


def runtime(kind, **facts):
    return {"target_date": "2026-11-26", "top_market_news": [
        {"news_id": "selected", "headline": "Selected source", "url": "https://example.com/selected"}
    ], "primary_claim_context": [{
        "news_id": "selected", "source_url": "https://example.com/primary",
        "source_sha256": "a" * 64, "observed_at": "2026-11-26T06:09:00+09:00",
        "facts": {"kind": kind, **facts},
    }]}


def inspect(text, source, *, market=False):
    payload = {"market_setup": text} if market else {
        "key_watchpoints": [{"news_id": "selected", "headline": "확인할 소식", "detail": text}]
    }
    original = deepcopy(payload)
    result = prepare_final_customer_copy("today_genie", payload, source_input=source)
    diagnostic = result.pop(PRODUCT_SURFACE_DIAGNOSTIC_KEY)
    assert result == original  # No substantive editing or invented QA evidence.
    assert payload == original
    return diagnostic["issue_codes"]


def economic():
    return runtime("economic_release", released_at="2026-11-25T08:30:00-05:00",
                   consensus_relation="inline", market_sessions=[
                       {"names": ["코스피", "코스닥"], "closed_at": "2026-11-25T15:30:00+09:00"},
                       {"names": ["니케이"], "closed_at": "2026-11-25T15:30:00+09:00"},
                   ])


def test_same_calendar_date_does_not_mean_same_market_information_set():
    bad = "코스피와 니케이가 하락했습니다. 이는 PCE 3.8% 발표가 작용한 결과입니다."
    assert SESSION_CAUSALITY in inspect(bad, economic(), market=True)


def test_economic_indicator_alias_does_not_hide_the_causal_scope_problem():
    bad = "코스피와 니케이가 동반 하락했습니다. 이는 연준의 선호 인플레이션 지표 발표가 작용한 결과입니다."
    assert SESSION_CAUSALITY in inspect(bad, economic(), market=True)


def test_explicit_asia_close_before_us_release_does_not_flag_us_session_analysis():
    good = "아시아 증시는 PCE 발표 이전에 마감했습니다. 이후 미국 증시는 PCE 발표 영향으로 혼조세였습니다."
    assert SESSION_CAUSALITY not in inspect(good, economic(), market=True)


def test_qualifier_does_not_clear_an_explicitly_contradictory_causal_claim():
    bad = "코스피는 PCE 발표 영향으로 급락했습니다. 아시아는 PCE 발표 이전에 마감했습니다."
    assert SESSION_CAUSALITY in inspect(bad, economic(), market=True)


def test_rss_timestamp_cannot_replace_the_release_clock():
    source = economic()
    source["top_market_news"][0]["published_at"] = "2026-11-25T01:00:00+09:00"
    assert SESSION_CAUSALITY in inspect("코스피는 PCE 발표 영향으로 하락했습니다.", source, market=True)


@pytest.mark.parametrize("text", ["엔비디아 관련 불확실성을 해소했습니다.", "황 CEO 관련 법적 리스크 해소는 기술주에 긍정적입니다."])
def test_personal_assurance_does_not_prove_company_wide_clearance(text):
    assert PERSON_SCOPE in inspect(text, runtime("personal_investigation"))


def test_attributed_personal_statement_and_explicit_limitation_are_allowed():
    text = "밴스는 황 개인이 조사 대상이 아니라고 들었다고 전했습니다. 회사 전체의 법적 리스크 해소를 의미하지 않습니다."
    assert PERSON_SCOPE not in inspect(text, runtime("personal_investigation"))


@pytest.mark.parametrize("text", [
    "미국은 14개 경제권에 관세를 제안했습니다.",
    "한국산에 최대 15% 관세를 제안했으며 아직 미확정입니다.",
])
def test_korea_application_and_net_exceptions_must_survive_card_compression(text):
    assert DOMESTIC_APPLICATION in inspect(text, runtime("tariff_proposal", economies=["Korea"], maximum_rate=15))


def test_complete_domestic_proposal_scope_is_allowed():
    text = "한국산 최대 15% 관세 검토는 기존 MFN·301조 관세를 감안하며 일부 상품 예외가 있는 제안으로 아직 미확정입니다."
    assert DOMESTIC_APPLICATION not in inspect(text, runtime("tariff_proposal", economies=["Korea"], maximum_rate=15))


def test_a_different_selected_article_cannot_lend_its_primary_annotation():
    source = runtime("tariff_proposal", economies=["Korea"], maximum_rate=15)
    source["primary_claim_context"][0]["news_id"] = "unselected"
    assert DOMESTIC_APPLICATION not in inspect("14개 경제권에 관세를 제안했습니다.", source)


def test_inflation_acceleration_is_not_a_consensus_beat():
    assert CONSENSUS_SCOPE in inspect("PCE 물가는 예상치를 웃도는 상승률을 기록했습니다.", economic())
    assert CONSENSUS_SCOPE not in inspect("PCE 전년 대비 3.8%는 시장 예상에 부합했습니다.", economic())


def test_core_pce_beat_cannot_be_borrowed_by_headline_and_is_not_false_flagged():
    good = "10월 전체 PCE는 전년 대비 3.8%로 예상 3.8%에 부합했습니다. 근원 PCE는 3.3%로 예상 3.2%를 웃돌았습니다."
    assert CONSENSUS_SCOPE not in inspect(good, economic())
    bad = "전체 PCE는 예상치를 웃돌았습니다. 근원 PCE도 예상보다 높았습니다."
    assert CONSENSUS_SCOPE in inspect(bad, economic())


def test_conditional_tariff_alternative_cannot_be_replaced_by_a_market_decimal():
    source = runtime("tariff_proposal", economies=["Korea"], maximum_rate=15, conditional_rate=25)
    base = "한국산 최대 15% 관세 제안은 기존 MFN·301조 관세를 반영하며 일부 예외가 있는 미확정안입니다."
    assert DOMESTIC_APPLICATION in inspect(base + " 지수는 -0.25%였습니다.", source)
    assert DOMESTIC_APPLICATION not in inspect(base + " 협의·약속이 불충분하다고 판단할 경우 최대 25% 대안도 제안했습니다.", source)


def test_unenriched_rss_does_not_silently_certify_risky_assertions():
    source = {"target_date": "2026-11-26", "top_market_news": [{"news_id": "selected",
        "headline": "U.S. PCE inflation rises", "url": "https://example.test/pce"}]}
    assert SESSION_CAUSALITY in inspect("코스피와 니케이 하락은 PCE 발표가 작용한 결과입니다.", source, market=True)
    source["top_market_news"][0]["headline"] = "USTR proposes tariffs on trading partner economies"
    assert DOMESTIC_APPLICATION in inspect("14개 경제권에 관세를 제안했습니다.", source)


def test_an_unrelated_negative_sentence_cannot_clear_broad_legal_clearance():
    assert PERSON_SCOPE in inspect("회사의 결론이 아닙니다. 엔비디아 관련 불확실성을 해소했습니다.", runtime("personal_investigation"))


@pytest.mark.parametrize("builder", [build_top3_extraction_prompt,
    lambda source: build_full_prompt("today_genie", source, today_genie_main_briefing=True)])
def test_both_actual_prompt_layers_receive_the_same_scope_constraints(builder):
    source = economic()
    before = deepcopy(source)
    prompt = builder(source)
    assert "[TODAY_CLAIM_CONTEXT" in prompt
    assert "after a market closes cannot explain" in prompt
    assert "company-wide legal clearance" in prompt
    assert "domestic applicability" in prompt
    assert "2026-11-25T08:30:00-05:00" in prompt
    assert source == before
