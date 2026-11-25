import copy
import pytest

from keysuri_temporal_scope import TEMPORAL_SCOPE_UNVERIFIED
from keysuri_korea_longform_ux import build_korea_evening_memo
from product_surface_contract import prepare_final_customer_copy, PRODUCT_SURFACE_DIAGNOSTIC_KEY


def source(kind="forecast_revision"):
    return {"target_date": "2026-11-25", "primary_event_time_evidence": [{
        "news_id": "selected", "event_kind": kind,
        "event_date": "2026-10-23" if kind == "forecast_revision" else "2027-01-06",
        "outcome_date": "2027-03-31" if kind == "forecast_revision" else "2027-01-06",
        "source_url": "https://www.fanuc.co.jp/en/ir/announce/" if kind == "forecast_revision" else "https://www.ces.tech/plan-your-visit/dates-and-hours/",
        "source_sha256": "a" * 64, "observed_at": "2026-11-25T18:05:00+09:00",
        "event_names": ["화낙"] if kind == "forecast_revision" else ["CES"],
    }]}


def inspect(text, original, *, watch="", memo=False):
    item = {"news_id": "selected", "headline": "검수할 신호", "summary": text, "next_watch": watch}
    payload = {"top_5_news": {"items": [item]}}
    if memo:
        payload["closing_sources"] = {"evening_memo": build_korea_evening_memo([item])}
    before = copy.deepcopy(payload)
    prepared = prepare_final_customer_copy("keysuri_korea_tech", payload, source_input=original)
    diagnostics = prepared.pop(PRODUCT_SURFACE_DIAGNOSTIC_KEY)
    assert prepared == before
    return diagnostics


@pytest.mark.parametrize("publication_date", ["2026-11-25", "2026-11-26"])
def test_republished_article_cannot_turn_october_forecast_into_new_november_event(publication_date):
    original = source(); original["source_pack"] = {"generated_at": publication_date, "sources": [{"published_at": publication_date}]}
    result = inspect("화낙의 연매출은 사상 첫 1조 엔 돌파 전망입니다.", original)
    assert TEMPORAL_SCOPE_UNVERIFIED in result["issue_codes"]


def test_forecast_with_actual_asof_date_is_allowed_as_background():
    result = inspect("화낙이 10월 23일 공시한 기존 전망은 연매출 1조137억 엔입니다.", source())
    assert TEMPORAL_SCOPE_UNVERIFIED not in result["issue_codes"]


def test_new_article_does_not_make_future_ces_a_tomorrow_outcome():
    result = inspect("삼성의 휴머노이드 공개는 증권사 전망입니다.", source("exhibition"), watch="CES에서 공개 여부와 구체적인 사양 확인")
    assert TEMPORAL_SCOPE_UNVERIFIED in result["issue_codes"]


def test_tomorrow_can_monitor_an_official_future_event_notice():
    result = inspect("삼성의 휴머노이드 공개는 증권사 전망입니다.", source("exhibition"), watch="삼성전자 또는 CES가 공개 여부와 브리핑 일정을 공식 예고하는지 확인")
    assert TEMPORAL_SCOPE_UNVERIFIED not in result["issue_codes"]


def test_actual_evening_memo_builder_copies_future_watch_under_tomorrow_label():
    result = inspect("삼성의 휴머노이드 공개는 증권사 전망입니다.", source("exhibition"), watch="CES에서 공개 여부와 사양 확인", memo=True)
    findings = [f for f in result["findings"] if f["code"] == TEMPORAL_SCOPE_UNVERIFIED]
    assert any("closing_sources.evening_memo.action_lines" in f["path"] for f in findings)


def test_future_financial_outcome_is_not_assumed_to_be_available_tomorrow():
    result = inspect("화낙의 10월 23일 기존 전망입니다.", source(), watch="화낙 실제 연매출 달성 여부와 상세 실적 발표 확인")
    assert TEMPORAL_SCOPE_UNVERIFIED in result["issue_codes"]


def test_unrelated_or_generated_date_annotation_cannot_supply_evidence():
    original = source(); original["primary_event_time_evidence"][0]["news_id"] = "other-article"
    assert TEMPORAL_SCOPE_UNVERIFIED not in inspect("매출 1조 엔 전망입니다.", original)["issue_codes"]
    original = source(); original["primary_event_time_evidence"][0]["source_sha256"] = "missing"
    assert TEMPORAL_SCOPE_UNVERIFIED not in inspect("매출 1조 엔 전망입니다.", original)["issue_codes"]


def test_date_evidence_dependency_cannot_start_another_automatic_paid_call():
    from auto_remediation import classify_issue_codes
    scope, blocking, unknown = classify_issue_codes([TEMPORAL_SCOPE_UNVERIFIED])
    assert scope is None and blocking == [TEMPORAL_SCOPE_UNVERIFIED] and unknown == []
