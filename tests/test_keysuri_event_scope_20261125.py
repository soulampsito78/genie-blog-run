import copy
from unittest.mock import patch

import pytest

from keysuri_duplicate_repair import plan_duplicate_repair
from keysuri_news_contract import select_top_5_news
from keysuri_prompt_input import build_keysuri_prompt_input
from keysuri_source_gate import GateResult
from news_event_identity import event_identity, same_event


def parent():
    sources, claims, items = [], [], []
    for i in range(1, 7):
        summary = f"국내 로봇 기업{i}가 새로운 공정 검사 기술을 공급했다."
        if i == 3:
            summary = "킨드레드 벤처스가 지난 23일 서울에서 'AI 웨이브: 서울 2026'을 열고 기술을 논의했다."
        if i == 4:
            summary = "Kindred Ventures가 SBVA와 함께 23일 서울에서 'AI Wave: Seoul 2026'을 개최했다."
        source = {"source_id": f"s{i}", "source_url": f"https://outlet{i}.example/article/{i}",
                  "source_name": f"매체{i}", "source_tier": "T3_QUALITY_PRESS",
                  "published_at": "2026-11-25T16:00:00+09:00", "fetched_at": "2026-11-25T17:30:00+09:00",
                  "title": f"국내 로봇 기술{i}", "snippet": summary}
        claim = {"claim_id": f"n{i}", "headline": f"국내 로봇 기술{i}", "statement": summary,
                 "summary": summary, "source_ids": [f"s{i}"], "claim_type": "general",
                 "confidence_label": "reported", "category": "korea_robotics_manufacturing",
                 "why_it_matters": "생산라인 검사 기술이 개선된다.", "business_implication": "로봇 공급 계약 범위를 확인한다.",
                 "korea_tech_scope_status": "strong_tech", "selection_score": 60}
        sources.append(source)
        claims.append(claim)
        items.append({"rank": i, "news_id": f"n{i}", "source_ids": [f"s{i}"],
                      "headline": claim["headline"], "summary": summary,
                      "published_at": source["published_at"], "url": source["source_url"]})
    pack = {"program_id": "keysuri_korea_tech", "generated_at": "2026-11-25T17:30:00+09:00",
            "sources": sources[:5], "claims": claims[:5], "backfill_sources": sources[5:], "backfill_claims": claims[5:]}
    return {"program_id": "keysuri_korea_tech", "selected_items": items[:5], "regen_source_pack_snapshot": pack,
            "regen_prompt_input_snapshot": {"program_id": "keysuri_korea_tech", "prompt_status": "ready_for_generation",
                                           "source_pack": pack, "top_5_news": {"items": items[:5]}}}


def test_different_headlines_urls_and_languages_form_one_dated_event():
    p = parent()["selected_items"]
    assert same_event(p[2], p[3])
    other = copy.deepcopy(p[3]); other["summary"] = other["summary"].replace("23일", "24일")
    assert not same_event(p[2], other)
    other["summary"] = other["summary"].replace("Kindred Ventures", "Another Organizer")
    assert not event_identity(other)
    undated = copy.deepcopy(p[2]); undated.pop("published_at")
    assert not event_identity(undated)


def test_explicit_event_identity_does_not_confuse_same_name_other_date_or_organizer():
    a = {"event_name": "Industry Summit", "event_date": "2026-11-23", "event_organizer": "one"}
    assert same_event(a, dict(a))
    assert not same_event(a, dict(a, event_date="2026-11-24"))
    assert not same_event(a, dict(a, event_organizer="two"))
    assert not event_identity(dict(a, event_date="2026-02-30"))


def test_actual_prompt_entry_point_deduplicates_before_backfill_to_five():
    pack = parent()["regen_source_pack_snapshot"]
    with patch("keysuri_prompt_input.recent_sent_news_log", return_value=[]), patch(
            "keysuri_prompt_input.recent_owner_review_exposure_log_with_status", return_value={"items": [], "read_ok": True}):
        result = build_keysuri_prompt_input("keysuri_korea_tech", pack, gate_result=GateResult("pass", []))
    ids = [i["news_id"] for i in result["top_5_news"]["items"]]
    assert len(ids) == 5 and "n3" in ids and "n4" not in ids and "n6" in ids
    assert result["candidate_funnel_summary"]["same_event_removed_count"] == 1


def test_proven_duplicates_cannot_return_through_soft_exposure_backfill():
    p = parent(); pack = p["regen_source_pack_snapshot"]
    pack["backfill_claims"] = []; pack["backfill_sources"] = []
    result = select_top_5_news(pack, GateResult("pass", []), sent_log_rows=[], exposure_log_rows=[p["selected_items"][3]])
    assert result["verdict"] == "hold"


def test_targeted_plan_preserves_four_and_merges_source_support_without_editing_parent():
    p = parent(); before = copy.deepcopy(p)
    working, fields = plan_duplicate_repair(p, sent_rows=[])
    assert p == before
    assert [i["news_id"] for i in working["selected_items"]] == ["n1", "n2", "n3", "n5", "n6"]
    assert working["selected_items"][2]["source_ids"] == ["s3", "s4"]
    assert fields["reissue_same_event_removed_ids"] == ["n4"]
    assert fields["reissue_targeted_replacement_ids"] == ["n6"]
    assert working["regen_source_pack_snapshot"]["korea_top5_selection"]["selected_source_ids"] == ["s1", "s2", "s3", "s5", "s6"]


@pytest.mark.parametrize("defect", ["below_floor", "unverified", "irrelevant", "already_sent", "no_backfill"])
def test_targeted_plan_never_bypasses_qualification_or_sent_history(defect):
    p = parent(); pack = p["regen_source_pack_snapshot"]; sent = []
    if defect == "below_floor": pack["backfill_claims"][0]["selection_score"] = 44
    if defect == "unverified": pack["backfill_claims"][0]["confidence_label"] = "unverified"
    if defect == "irrelevant": pack["backfill_claims"][0]["korea_tech_scope_status"] = "unknown"
    if defect == "already_sent": sent = [{"url": pack["backfill_sources"][0]["source_url"]}]
    if defect == "no_backfill": pack["backfill_claims"] = []
    with pytest.raises(ValueError, match="qualified_pool_exhausted"):
        plan_duplicate_repair(p, sent_rows=sent)


def test_existing_body_reissue_entry_point_uses_targeted_pool_and_editorial_note():
    import keysuri_service_full_run as service
    p = parent()
    with patch.object(service, "_saved_top_image_reference", return_value=(service.Path("/tmp/unused"), {})), patch.object(
            service, "_saved_korea_bottom_image_path", return_value=None), patch.object(
            service, "recent_sent_news_log", return_value=[]), patch.object(
            service, "_regenerate_keysuri_text_from_frozen_parent", return_value=(None, None, {}, "test_stop_before_any_paid_call")) as generate, patch.object(
            service, "run_keysuri_live_source_smoke") as collect:
        result = service.run_keysuri_text_only_reissue("parent", parent_meta=p, send_owner_email=False,
                                                      reissue_reason_code="뉴스 중복 이슈", reissue_reason_note="프로젝트 합산 수주 범위 유지")
    assert result["error"] == "test_stop_before_any_paid_call"
    assert [i["news_id"] for i in generate.call_args.args[1]["selected_items"]] == ["n1", "n2", "n3", "n5", "n6"]
    assert generate.call_args.kwargs["editorial_instruction"] == "프로젝트 합산 수주 범위 유지"
    collect.assert_not_called()


def test_old_parent_body_cannot_become_a_targeted_child_after_generation_fallback():
    import keysuri_service_full_run as service
    p = parent()
    with patch.object(service, "_saved_top_image_reference", return_value=(service.Path("/tmp/unused"), {})), patch.object(
            service, "_saved_korea_bottom_image_path", return_value=None), patch.object(
            service, "recent_sent_news_log", return_value=[]), patch.object(
            service, "_regenerate_keysuri_text_from_frozen_parent", return_value=(p["regen_prompt_input_snapshot"],
                {"top_5_news": {"items": p["selected_items"]}}, {}, None)), patch.object(
            service, "_adjudicate_and_send_owner_surface") as send:
        result = service.run_keysuri_text_only_reissue("parent", parent_meta=p, send_owner_email=False,
                                                      reissue_reason_code="뉴스 중복 이슈")
    assert result["error"] == "targeted_duplicate_repair_identity_mismatch"
    send.assert_not_called()


