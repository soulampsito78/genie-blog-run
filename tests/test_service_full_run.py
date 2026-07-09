"""Tests: service-level full runs with generated images (Unit 6p)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from admin_store import (
    artifact_email_path,
    load_run_artifact,
    load_run_email_html,
    save_run_artifact,
)
from fastapi.testclient import TestClient
from internal_jobs import create_keysuri_owner_review_job
from keysuri_live_source_smoke import PROGRAM_GLOBAL, PROGRAM_KOREA, LiveSourceSmokeResult
from main import app
from orchestrator import OrchestrationResult
from publishing_policy import PublishingDecision
from service_full_run_contract import (
    IMAGE_SOURCE_GENERATED,
    IMAGE_SOURCE_REGISTRY,
    IMAGE_SOURCE_STATIC,
    ServiceImageOutcome,
    is_smoke_only_image_source,
    service_image_passes,
)
from service_image_api import invoke_vertex_image_generation
from today_genie_service_full_run import (
    generate_today_genie_service_images,
    run_today_genie_service_full_run,
)

_TOKEN = "unit-test-internal-token"


def _minimal_contract_preview_document(
    *,
    body_inner: str | None = None,
    theme_class: str = "premium-briefing theme-global",
) -> str:
    inner = body_inner or (
        '<header class="premium-hero" id="premium-hero">'
        '<h1 class="hero-title">키수리 글로벌 테크 브리핑</h1>'
        '<img src="cid:keysuri_topshot_global_20260611" class="top-shot-hero"/>'
        "</header>"
    )
    return (
        '<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"/>'
        "<style>.premium-briefing.theme-global{--g-accent:#3f7ecb;}</style>"
        f"</head><body class=\"{theme_class}\"><div class=\"briefing-shell\">{inner}</div></body></html>"
    )
_MINIMAL_TODAY_DATA = {
    "title": "오늘의 지니",
    "summary": "국내 증시는 장전 변동성에 주목합니다.",
    "greeting": "안녕하세요.",
    "closing_message": "오늘도 신중한 접근이 필요합니다.",
    "image_briefing_mood_state": "mixed_cautious",
    "image_mood_basis": "신중한 장전 분위기",
    "image_prompt_studio": "Professional Korean financial anchor in studio with market screens.",
    "image_prompt_outdoor": "Same anchor outdoors on Seoul morning street, smart casual.",
    "key_watchpoints": [{"headline": "코스피", "detail": "외국인 수급을 확인합니다."}],
    "risk_check": [{"risk": "환율", "detail": "원/달러 변동성을 봅니다."}],
    "hashtags": ["#코스피"],
    "channel_drafts": {"email_subject": "오늘의 지니 장전 브리핑"},
}
_RUNTIME_INPUT = {"target_date": "2026-06-08", "top_market_news": [{"headline": "OpenAI IPO filing"}]}


def _mock_generate(_path: Path) -> Path:
    _path.parent.mkdir(parents=True, exist_ok=True)
    _path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
    return _path


def _mock_keysuri_watermark(source: Path, target: Path) -> Path:
    src = Path(source)
    dst = Path(target)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes() + b"MirAI:ON")
    return dst.resolve()


def _pass_today_orchestration_result() -> OrchestrationResult:
    return OrchestrationResult(
        decision=PublishingDecision(
            send_email=True,
            create_naver_draft=False,
            auto_publish=False,
            require_review=True,
            suppress_external=False,
            send_customer_email=False,
        ),
        reason_summary="ok",
        response_status=200,
        mode="today_genie",
        response_data={
            "validation_result": "pass",
            "workflow_status": "validated",
            "runtime_input": _RUNTIME_INPUT,
            "data": _MINIMAL_TODAY_DATA,
        },
    )


def _fake_keysuri_smoke(program_id: str, **_kwargs) -> LiveSourceSmokeResult:
    return LiveSourceSmokeResult(
        ok=True,
        program_id=program_id,
        source_pack_path=str(Path(__file__).resolve().parents[1] / "output" / "keysuri_preview" / "pack.json"),
        html_path="/tmp/smoke.html",
        fetched_item_count=5,
        feed_urls_used=["https://example.com/feed"],
        sample_marker_pass=True,
        called_gemini=True,
        use_gemini=True,
        contract_preview=True,
        parse_status="parsed_valid",
        raw_response_path="/tmp/raw.txt",
        preview_overall_status="PASS_OWNER_REVIEW_READY",
        validation_status="PASS",
        side_effects={"called_gemini": True, "called_image_api": False},
    )


def _reissue_parent_top5_items() -> list[dict]:
    out = []
    for idx in range(1, 6):
        out.append(
            {
                "rank": idx,
                "news_id": f"parent-{idx}",
                "headline": f"Parent Signal {idx}",
                "korean_title": f"부모 신호 {idx}",
                "category": "market_signal",
                "summary": f"Parent summary {idx}",
                "why_it_matters": f"Parent why {idx}",
                "business_implication": f"Parent business implication {idx}",
                "source_ids": [f"parent-{idx}"],
                "source_name": f"Parent Source {idx}",
                "source_url": f"https://example.com/parent-{idx}",
                "canonical_url": f"https://example.com/parent-{idx}",
                "confidence_label": "reported",
            }
        )
    return out


def _generated_briefing_with_top_count(items: list[dict], program_id: str = PROGRAM_GLOBAL) -> dict:
    news_scope = "korea" if program_id == PROGRAM_KOREA else "global"
    section_heading = "국내 테크 TOP 5" if program_id == PROGRAM_KOREA else "글로벌 테크 TOP 5"
    source_list = [
        {
            "source_id": "parent-1",
            "label": "Parent Source 1",
            "url": "https://example.com/parent-1",
        }
    ]
    return {
        "program_id": program_id,
        "operational_status": "review_required",
        "generated_status": "generated_review_required",
        "news_scope": news_scope,
        "section_heading": section_heading,
        "top_5_news": {
            "news_scope": news_scope,
            "section_heading": section_heading,
            "items": items,
        },
        "deep_dive": {
            "section_heading": "키수리의 딥-다이브",
            "body": "Global operators should watch infrastructure and platform signals.",
            "key_implications": ["Infrastructure signal", "Platform pressure"],
            "source_ids": ["parent-1"],
            "confidence_label": "reported",
        },
        "one_line_checkpoint": {
            "section_heading": "원-라인 체크포인트",
            "body": "Watch the parent-selected signals without changing the source set.",
        },
        "closing_sources": {
            "section_heading": "마무리 및 출처 리스트",
            "closing_message": "Source list remains grounded in the parent selection.",
            "source_list": source_list,
        },
        "briefing_display": {
            "opening_lead": "주인님, 오늘은 부모 선택 신호를 기준으로 재발행합니다.",
            "closing_message": "오늘 신호는 여기까지 정리했습니다.",
        },
    }


def _live_reselection_items(prefix: str = "live") -> list[dict]:
    """Fresh, parent-disjoint candidate selection for reissue reselection tests."""
    out = []
    for idx in range(1, 6):
        out.append(
            {
                "rank": idx,
                "news_id": f"{prefix}-{idx}",
                "headline": f"Live Signal {idx}",
                "korean_title": f"라이브 신호 {idx}",
                "category": "market_signal",
                "summary": f"Live summary {idx}",
                "why_it_matters": f"Live why {idx}",
                "business_implication": f"Live business implication {idx}",
                "source_ids": [f"{prefix}-src-{idx}"],
                "source_name": f"Live Source {idx}",
                "source_url": f"https://example.com/{prefix}-{idx}",
                "canonical_url": f"https://example.com/{prefix}-{idx}",
                "confidence_label": "reported",
            }
        )
    return out


def _live_reselection_items_with_raw_english_ellipsis(prefix: str = "live-raw") -> list[dict]:
    live_items = _live_reselection_items(prefix=prefix)
    for idx, item in enumerate(live_items, start=1):
        item["headline"] = f"AI labor report maps job shifts {idx}"
        item["summary"] = "…report maps how AI could reshape jobs across the EU.. highlighting…"
        item["why_it_matters"] = "Operators should read the raw claim.. before market open…"
        item["business_implication"] = "This affects enterprise AI planning across several teams."
    return live_items


def _briefing_for_live_items(items: list[dict], program_id: str = PROGRAM_GLOBAL) -> dict:
    """A contract-valid briefing whose deep_dive/closing reference the given items'
    sources, so grafting these items as TOP5 validates."""
    news_scope = "korea" if program_id == PROGRAM_KOREA else "global"
    section_heading = "국내 테크 TOP 5" if program_id == PROGRAM_KOREA else "글로벌 테크 TOP 5"
    sids = [it["source_ids"][0] for it in items]
    return {
        "program_id": program_id,
        "operational_status": "review_required",
        "generated_status": "generated_review_required",
        "news_scope": news_scope,
        "section_heading": section_heading,
        "top_5_news": {"news_scope": news_scope, "section_heading": section_heading, "items": items},
        "deep_dive": {
            "section_heading": "키수리의 딥-다이브",
            "body": "Live operators should watch fresh infrastructure and platform signals.",
            "key_implications": ["Fresh signal", "Platform pressure"],
            "source_ids": sids,
            "confidence_label": "reported",
        },
        "one_line_checkpoint": {
            "section_heading": "원-라인 체크포인트",
            "body": "Watch the freshly reselected signals.",
        },
        "closing_sources": {
            "section_heading": "마무리 및 출처 리스트",
            "closing_message": "Source list grounded in the fresh live selection.",
            "source_list": [{"source_id": s, "label": f"Live Source {i+1}", "url": items[i]["canonical_url"]} for i, s in enumerate(sids)],
        },
        "briefing_display": {
            "opening_lead": "주인님, 오늘은 새로 수집한 신호를 기준으로 재발행합니다.",
            "closing_message": "오늘 신호는 여기까지 정리했습니다.",
        },
    }


def _live_smoke_result_for_pack(source_pack_path: str, program_id: str = PROGRAM_GLOBAL):
    return LiveSourceSmokeResult(
        ok=True,
        program_id=program_id,
        source_pack_path=source_pack_path,
        html_path="",
        fetched_item_count=7,
        feed_urls_used=[],
        sample_marker_pass=True,
        called_gemini=False,
        parse_status=None,
        generated_briefing=None,
    )


class KeysuriOwnerEmailDeliveryFieldsTests(unittest.TestCase):
    def test_success_masks_recipients_and_keeps_domains_and_hashes(self) -> None:
        from keysuri_service_full_run import _owner_email_delivery_fields

        trace = {
            "envelope_to": [
                "tera9003@daum.net",
                "tomato3593@gmail.com",
                "tera9003@daum.net",
                "a@naver.com",
            ],
            "mime_html_sha256": "html-sha",
            "mime_html_bytes_len": 1234,
            "inline_input_hashes": [
                {
                    "path": str(Path(__file__).resolve()),
                    "cid": "keysuri_topshot_korea_20260623",
                    "filename": "/tmp/top.jpg",
                    "sha256": "top-sha",
                }
            ],
        }
        with patch("keysuri_service_full_run.email_sender.last_send_trace", return_value=trace):
            with patch("keysuri_service_full_run.email_sender.last_send_diagnostic", return_value=""):
                fields = _owner_email_delivery_fields(
                    smtp_attempted=True,
                    email_sent=True,
                    subject="[운영자 검토] Kee-Suri Korea Tech",
                )

        self.assertEqual(fields["owner_email_delivery_status"], "smtp_accepted")
        self.assertEqual(fields["owner_email_recipient_count"], 3)
        self.assertEqual(fields["owner_email_recipient_domains"], ["daum.net", "gmail.com", "naver.com"])
        self.assertEqual(
            fields["owner_email_recipients_masked"],
            ["te***03@daum.net", "to***93@gmail.com", "a***@naver.com"],
        )
        self.assertEqual(fields["owner_email_mime_html_sha256"], "html-sha")
        self.assertEqual(fields["owner_email_mime_html_bytes_len"], 1234)
        self.assertEqual(fields["owner_email_inline_image_hashes"][0]["cid"], "keysuri_topshot_korea_20260623")
        self.assertEqual(fields["owner_email_inline_image_hashes"][0]["filename"], "top.jpg")
        blob = json.dumps(fields, ensure_ascii=False)
        self.assertNotIn("tera9003@daum.net", blob)
        self.assertNotIn("tomato3593@gmail.com", blob)

    def test_failure_records_failed_status_and_sanitized_diagnostic(self) -> None:
        from keysuri_service_full_run import _owner_email_delivery_fields

        trace = {
            "envelope_to": ["kha6210@hanmail.com"],
            "mime_html_sha256": "",
            "mime_html_bytes_len": 0,
            "inline_input_hashes": [],
        }
        diagnostic = (
            "SMTPAuthenticationError: password=rawpass token=rawtoken "
            "recipient kha6210@hanmail.com rejected"
        )
        with patch.dict(os.environ, {"SMTP_PASSWORD": "rawpass", "GENIE_INTERNAL_JOB_TOKEN": "rawtoken"}, clear=False):
            with patch("keysuri_service_full_run.email_sender.last_send_trace", return_value=trace):
                with patch("keysuri_service_full_run.email_sender.last_send_diagnostic", return_value=diagnostic):
                    fields = _owner_email_delivery_fields(
                        smtp_attempted=True,
                        email_sent=False,
                        subject="[운영자 검토] Kee-Suri Korea Tech",
                    )

        self.assertEqual(fields["owner_email_delivery_status"], "failed")
        self.assertEqual(fields["owner_email_recipient_count"], 1)
        self.assertEqual(fields["owner_email_recipients_masked"], ["kh***10@hanmail.com"])
        self.assertIn("password=[redacted]", fields["owner_email_send_diagnostic"])
        self.assertIn("token=[redacted]", fields["owner_email_send_diagnostic"])
        self.assertNotIn("rawpass", fields["owner_email_send_diagnostic"])
        self.assertNotIn("rawtoken", fields["owner_email_send_diagnostic"])
        self.assertNotIn("kha6210@hanmail.com", json.dumps(fields, ensure_ascii=False))

    def test_not_sent_does_not_read_stale_send_trace(self) -> None:
        from keysuri_service_full_run import _owner_email_delivery_fields

        with patch("keysuri_service_full_run.email_sender.last_send_trace") as trace_reader:
            with patch("keysuri_service_full_run.email_sender.last_send_diagnostic") as diag_reader:
                fields = _owner_email_delivery_fields(
                    smtp_attempted=False,
                    email_sent=False,
                    subject="[운영자 검토] Kee-Suri Korea Tech",
                )

        trace_reader.assert_not_called()
        diag_reader.assert_not_called()
        self.assertEqual(fields["owner_email_delivery_status"], "not_sent")
        self.assertFalse(fields["owner_email_smtp_attempted"])
        self.assertIsNone(fields["owner_email_sent_at_kst"])
        self.assertEqual(fields["owner_email_recipient_count"], 0)
        self.assertEqual(fields["owner_email_send_diagnostic"], "")


class KeysuriReissueTop5RepairTests(unittest.TestCase):
    def _live_items_with_raw_english_ellipsis(self) -> list[dict]:
        return _live_reselection_items_with_raw_english_ellipsis()

    def test_live_reissue_raw_english_ellipsis_fallback_is_sanitized(self) -> None:
        from keysuri_service_full_run import _repair_reissue_top5_from_live_selection
        from keysuri_visible_text_quality import validate_and_repair_keysuri_visible_text_quality

        live_items = self._live_items_with_raw_english_ellipsis()
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []},
            "top_5_news": {"news_scope": "global", "section_heading": "글로벌 테크 TOP 5", "items": live_items},
        }
        # Gemini returns only a partial TOP5; the remaining visible prose must be
        # clean Korean fallback, never raw claim snippets.
        partial_gemini = _briefing_for_live_items(live_items[:2])

        repaired_prompt, repaired_briefing, fields, err = _repair_reissue_top5_from_live_selection(
            generated_briefing=partial_gemini,
            prompt_input=prompt_input,
            program_id=PROGRAM_GLOBAL,
            parent={},
        )

        self.assertIsNone(err)
        self.assertIsNotNone(repaired_prompt)
        self.assertEqual(fields["reissue_top5_repair_source"], "reissue_live_selected_items")
        self.assertTrue(fields["reissue_visible_text_sanitized"])
        self.assertTrue(fields["reissue_top5_clean_korean_fallback_used"])
        self.assertEqual(fields["reissue_text_quality_gate_before"], "block")
        self.assertEqual(fields["reissue_text_quality_gate_after"], "pass")
        repaired_items = repaired_briefing["top_5_news"]["items"]
        self.assertEqual(len(repaired_items), 5)
        rendered = json.dumps(repaired_items, ensure_ascii=False)
        self.assertNotIn("…", rendered)
        self.assertNotIn("..", rendered)
        self.assertNotIn("report maps how AI could reshape jobs", rendered)
        _payload, quality = validate_and_repair_keysuri_visible_text_quality(repaired_briefing)
        self.assertFalse(quality.get("visible_text_ellipsis_blocked"))

    def test_live_reissue_valid_gemini_korean_is_preserved(self) -> None:
        from keysuri_service_full_run import _repair_reissue_top5_from_live_selection

        live_items = self._live_items_with_raw_english_ellipsis()
        gemini_items = []
        for idx, live in enumerate(live_items, start=1):
            item = dict(live)
            item["headline"] = f"제미나이 한국어 제목 {idx}"
            item["korean_title"] = f"제미나이 한국어 제목 {idx}"
            item["summary"] = f"제미나이가 정리한 한국어 요약 {idx}입니다."
            item["why_it_matters"] = f"주요 시장 흐름을 판단하는 데 필요한 한국어 이유 {idx}입니다."
            item["business_implication"] = f"주인님이 점검할 실행 포인트 {idx}입니다."
            gemini_items.append(item)
        gemini_briefing = _briefing_for_live_items(gemini_items)
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []},
            "top_5_news": {"news_scope": "global", "section_heading": "글로벌 테크 TOP 5", "items": live_items},
        }

        repaired_prompt, repaired_briefing, fields, err = _repair_reissue_top5_from_live_selection(
            generated_briefing=gemini_briefing,
            prompt_input=prompt_input,
            program_id=PROGRAM_GLOBAL,
            parent={},
        )

        self.assertIsNone(err)
        self.assertIsNotNone(repaired_prompt)
        repaired_items = repaired_briefing["top_5_news"]["items"]
        self.assertEqual([it["summary"] for it in repaired_items], [it["summary"] for it in gemini_items])
        self.assertEqual([it["why_it_matters"] for it in repaired_items], [it["why_it_matters"] for it in gemini_items])
        self.assertFalse(fields["reissue_visible_text_sanitized"])
        self.assertFalse(fields["reissue_top5_clean_korean_fallback_used"])
        # Grounding still comes from the live selection.
        self.assertEqual(
            [it["canonical_url"] for it in repaired_items],
            [it["canonical_url"] for it in live_items],
        )
        self.assertEqual(
            [it["source_ids"] for it in repaired_items],
            [it["source_ids"] for it in live_items],
        )

    def test_live_reissue_partial_gemini_preserves_clean_items_and_fills_fallback(self) -> None:
        from keysuri_service_full_run import _repair_reissue_top5_from_live_selection

        live_items = self._live_items_with_raw_english_ellipsis()
        partial_items = []
        for idx, live in enumerate(live_items[:2], start=1):
            item = dict(live)
            item["headline"] = f"부분 제미나이 제목 {idx}"
            item["summary"] = f"부분 제미나이 요약 {idx}입니다."
            item["why_it_matters"] = f"부분 제미나이 이유 {idx}입니다."
            item["business_implication"] = f"부분 제미나이 실행 포인트 {idx}입니다."
            partial_items.append(item)
        partial_gemini = _briefing_for_live_items(partial_items)
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []},
            "top_5_news": {"news_scope": "global", "section_heading": "글로벌 테크 TOP 5", "items": live_items},
        }

        _repaired_prompt, repaired_briefing, fields, err = _repair_reissue_top5_from_live_selection(
            generated_briefing=partial_gemini,
            prompt_input=prompt_input,
            program_id=PROGRAM_GLOBAL,
            parent={},
        )

        self.assertIsNone(err)
        repaired_items = repaired_briefing["top_5_news"]["items"]
        self.assertEqual(repaired_items[0]["summary"], "부분 제미나이 요약 1입니다.")
        self.assertEqual(repaired_items[1]["summary"], "부분 제미나이 요약 2입니다.")
        self.assertIn("최신 발표를 바탕으로", repaired_items[2]["summary"])
        self.assertTrue(fields["reissue_top5_clean_korean_fallback_used"])
        self.assertTrue(fields["reissue_visible_text_sanitized"])
        self.assertEqual([it["news_id"] for it in repaired_items], [it["news_id"] for it in live_items])
        self.assertEqual([it["canonical_url"] for it in repaired_items], [it["canonical_url"] for it in live_items])

    def test_body_and_image_reissue_repairs_top5_from_parent_selection(self) -> None:
        from keysuri_service_full_run import _repair_reissue_top5_from_raw_text

        parent_items = _reissue_parent_top5_items()
        parent = {"selected_items": parent_items}
        generated = _generated_briefing_with_top_count(parent_items[:2])
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []},
            "top_5_news": generated["top_5_news"],
        }

        repaired_prompt, repaired_briefing, fields, err = _repair_reissue_top5_from_raw_text(
            raw_text=json.dumps(generated, ensure_ascii=False),
            prompt_input=prompt_input,
            parent=parent,
            program_id=PROGRAM_GLOBAL,
        )

        self.assertIsNone(err)
        self.assertTrue(fields["reissue_top5_repaired_from_parent"])
        self.assertEqual(fields["reissue_top5_original_count"], 2)
        self.assertEqual(fields["reissue_top5_repaired_count"], 5)
        repaired_items = repaired_briefing["top_5_news"]["items"]
        self.assertEqual(len(repaired_items), 5)
        self.assertEqual([it["news_id"] for it in repaired_items], [it["news_id"] for it in parent_items])
        self.assertEqual(
            [it["canonical_url"] for it in repaired_items],
            [it["canonical_url"] for it in parent_items],
        )
        self.assertEqual(
            [it["news_id"] for it in repaired_prompt["top_5_news"]["items"]],
            [it["news_id"] for it in parent_items],
        )

    def test_body_only_reissue_regen_uses_live_selection_not_parent(self) -> None:
        from keysuri_service_full_run import _regenerate_keysuri_text_from_source_pack

        parent_items = _reissue_parent_top5_items()
        parent = {"selected_items": parent_items}
        live_items = _live_reselection_items()
        source_pack = {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []}
        live_prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": source_pack,
            "top_5_news": {
                "news_scope": "global",
                "section_heading": "글로벌 테크 TOP 5",
                "items": live_items,
            },
            "sent_log_read_count": 3,
            "exposure_log_read_count": 2,
        }
        # Gemini truncates TOP5 to 2 — final must still be the fresh live 5.
        gemini_short = _briefing_for_live_items(live_items[:2])

        with patch(
            "keysuri_service_full_run.build_keysuri_prompt_input",
            return_value=json.loads(json.dumps(live_prompt_input)),
        ), patch(
            "keysuri_service_full_run.build_keysuri_generation_prompt", return_value="PROMPT"
        ), patch(
            "keysuri_service_full_run.enrich_generated_briefing_content",
            side_effect=lambda briefing, *_a, **_k: briefing,
        ), patch(
            "keysuri_service_full_run.validate_and_repair_keysuri_visible_text_quality",
            side_effect=lambda payload, **_k: (payload, {"visible_text_ellipsis_blocked": False}),
        ):
            repaired_prompt, repaired_briefing, fields, err = _regenerate_keysuri_text_from_source_pack(
                PROGRAM_GLOBAL,
                source_pack,
                parent=parent,
                text_caller=MagicMock(return_value=json.dumps(gemini_short, ensure_ascii=False)),
                extra_recent_log=[{"canonical_url": parent_items[0]["canonical_url"]}],
            )

        self.assertIsNone(err)
        self.assertTrue(fields["reissue_reselection_enabled"])
        self.assertEqual(fields["reissue_top5_repair_source"], "reissue_live_selected_items")
        self.assertFalse(fields["reissue_top5_repaired_from_parent"])
        self.assertEqual(fields["reissue_top5_original_count"], 2)
        self.assertEqual(fields["reissue_top5_repaired_count"], 5)
        items = repaired_briefing["top_5_news"]["items"]
        self.assertEqual(len(items), 5)
        self.assertEqual([it["news_id"] for it in items], [it["news_id"] for it in live_items])
        # Final selection must NOT overlap the parent run's items.
        parent_urls = {it["canonical_url"] for it in parent_items}
        self.assertTrue(all(it["canonical_url"] not in parent_urls for it in items))

    def test_reissue_top5_repair_requires_parent_selection(self) -> None:
        from keysuri_service_full_run import _repair_reissue_top5_from_raw_text

        generated = _generated_briefing_with_top_count(_reissue_parent_top5_items()[:2])
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []},
            "top_5_news": generated["top_5_news"],
        }

        repaired_prompt, repaired_briefing, fields, err = _repair_reissue_top5_from_raw_text(
            raw_text=json.dumps(generated, ensure_ascii=False),
            prompt_input=prompt_input,
            parent={"selected_items": _reissue_parent_top5_items()[:4]},
            program_id=PROGRAM_GLOBAL,
        )

        self.assertIsNone(repaired_prompt)
        self.assertIsNone(repaired_briefing)
        # Parent cannot supply 5 authoritative items and has no validated snapshot:
        # safe failure, but the attempt is still recorded for internal tracing.
        self.assertTrue(fields["reissue_top5_repair_attempted"])
        self.assertFalse(fields["reissue_top5_repaired_from_parent"])
        self.assertEqual(err, "reissue_parent_selected_items_missing_or_invalid")

    def test_body_and_image_repair_falls_back_to_parent_snapshot(self) -> None:
        """Real-artifact shape: broken Gemini output but parent has a validated
        snapshot → repair must complete from the parent snapshot, not safe-fail."""
        from keysuri_service_full_run import _repair_reissue_top5_from_raw_text

        parent_items = _reissue_parent_top5_items()
        # Parent persists both selected_items and the previously validated briefing.
        snapshot = _generated_briefing_with_top_count(parent_items)
        parent = {
            "selected_items": parent_items,
            "regen_generated_briefing_snapshot": snapshot,
        }
        # Gemini returned only 2 items AND an invalid generated_status, so grafting
        # the parent TOP5 onto the Gemini output still fails the contract.
        broken_gemini = _generated_briefing_with_top_count(parent_items[:2])
        broken_gemini["generated_status"] = "WRONG_STATUS"
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []},
        }

        repaired_prompt, repaired_briefing, fields, err = _repair_reissue_top5_from_raw_text(
            raw_text=json.dumps(broken_gemini, ensure_ascii=False),
            prompt_input=prompt_input,
            parent=parent,
            program_id=PROGRAM_GLOBAL,
        )

        self.assertIsNone(err)
        self.assertTrue(fields["reissue_top5_repaired_from_parent"])
        self.assertEqual(fields["reissue_top5_original_count"], 2)
        self.assertEqual(fields["reissue_top5_repaired_count"], 5)
        self.assertEqual(fields["reissue_top5_repair_source"], "parent_generated_briefing_snapshot")
        repaired_items = repaired_briefing["top_5_news"]["items"]
        self.assertEqual(len(repaired_items), 5)
        self.assertEqual([it["news_id"] for it in repaired_items], [it["news_id"] for it in parent_items])
        # Snapshot items carry the full display fields (korean_title) for rendering.
        self.assertTrue(all("korean_title" in it for it in repaired_items))

    def test_repair_unparseable_raw_recovers_from_parent_snapshot(self) -> None:
        """Even when the raw Gemini text is unparseable, a parent with a validated
        snapshot must still complete the reissue."""
        from keysuri_service_full_run import _repair_reissue_top5_from_raw_text

        parent_items = _reissue_parent_top5_items()
        parent = {
            "selected_items": parent_items,
            "regen_generated_briefing_snapshot": _generated_briefing_with_top_count(parent_items),
        }
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []},
        }

        repaired_prompt, repaired_briefing, fields, err = _repair_reissue_top5_from_raw_text(
            raw_text="this is not json at all",
            prompt_input=prompt_input,
            parent=parent,
            program_id=PROGRAM_GLOBAL,
        )

        self.assertIsNone(err)
        self.assertEqual(len(repaired_briefing["top_5_news"]["items"]), 5)
        self.assertEqual(fields["reissue_top5_repair_source"], "parent_generated_briefing_snapshot")

    def test_repair_records_diagnostics_when_no_parent_base_validates(self) -> None:
        """Parent has 5 selected_items but no validated snapshot and the Gemini
        output cannot be salvaged → safe failure with traceable repair metadata."""
        from keysuri_service_full_run import _repair_reissue_top5_from_parent_selection

        parent_items = _reissue_parent_top5_items()
        parent = {"selected_items": parent_items}  # no regen_generated_briefing_snapshot
        broken_gemini = _generated_briefing_with_top_count(parent_items[:2])
        # deep_dive references a source absent from both the pack and the parent TOP5.
        broken_gemini["deep_dive"]["source_ids"] = ["unknown-orphan-source"]
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []},
        }

        repaired_prompt, repaired_briefing, fields, err = _repair_reissue_top5_from_parent_selection(
            generated_briefing=broken_gemini,
            prompt_input=prompt_input,
            parent=parent,
            program_id=PROGRAM_GLOBAL,
        )

        self.assertIsNone(repaired_prompt)
        self.assertIsNone(repaired_briefing)
        self.assertEqual(err, "reissue_top5_parent_repair_validation_failed")
        self.assertTrue(fields["reissue_top5_repair_attempted"])
        self.assertFalse(fields["reissue_top5_repaired_from_parent"])
        self.assertEqual(fields["reissue_top5_original_count"], 2)
        self.assertTrue(fields["reissue_top5_repair_failed_sections"])  # safe issue codes recorded


class KeysuriBodyOnlyReissueExhaustedPoolTests(unittest.TestCase):
    """body_only reissue must not raise an uncaught ValueError when the reselect
    candidate pool is exhausted (every parent-selected source excluded)."""

    def test_regen_from_source_pack_exhausted_pool_returns_safe_error(self) -> None:
        from keysuri_service_full_run import _regenerate_keysuri_text_from_source_pack

        source_pack = {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []}
        # Depleted pool: build_keysuri_prompt_input returns top_5_news=None.
        depleted = {"program_id": PROGRAM_GLOBAL, "top_5_news": None}
        with patch("keysuri_service_full_run.build_keysuri_prompt_input", return_value=dict(depleted)):
            prompt_input, briefing, fields, err = _regenerate_keysuri_text_from_source_pack(
                PROGRAM_GLOBAL,
                source_pack,
                parent={"selected_items": _reissue_parent_top5_items()},
                text_caller=MagicMock(return_value="{}"),
            )
        self.assertIsNone(prompt_input)
        self.assertIsNone(briefing)
        self.assertEqual(err, "text_only_reselect_candidate_pool_exhausted")

    def test_regen_from_source_pack_empty_top5_items_returns_safe_error(self) -> None:
        from keysuri_service_full_run import _regenerate_keysuri_text_from_source_pack

        source_pack = {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []}
        depleted = {"program_id": PROGRAM_GLOBAL, "top_5_news": {"items": []}}
        with patch("keysuri_service_full_run.build_keysuri_prompt_input", return_value=dict(depleted)):
            prompt_input, briefing, fields, err = _regenerate_keysuri_text_from_source_pack(
                PROGRAM_GLOBAL,
                source_pack,
                parent={"selected_items": _reissue_parent_top5_items()},
                text_caller=MagicMock(return_value="{}"),
            )
        self.assertIsNone(prompt_input)
        self.assertEqual(err, "text_only_reselect_candidate_pool_exhausted")

    def test_text_only_reissue_insufficient_live_pool_does_not_raise(self) -> None:
        from keysuri_service_full_run import run_keysuri_text_only_reissue

        parent = {
            "program_id": PROGRAM_GLOBAL,
            "mode": "keysuri_global_tech",
            "selected_items": _reissue_parent_top5_items(),
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as _sp:
            json.dump({"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []}, _sp)
            sp_path = _sp.name
        # Live pool yields fewer than 5 fresh candidates after exclusion.
        depleted = {"program_id": PROGRAM_GLOBAL, "top_5_news": {"items": _live_reselection_items()[:3]}}
        with patch(
            "keysuri_service_full_run.build_keysuri_prompt_input", return_value=dict(depleted)
        ):
            result = run_keysuri_text_only_reissue(
                "20260629_120000_keysuri_global_tech_deadbeef",
                parent_meta=parent,
                send_owner_email=True,
                text_caller=MagicMock(return_value="{}"),
                send_fn=MagicMock(return_value=True),
                smoke_runner=lambda **_kw: _live_smoke_result_for_pack(sp_path),
            )
        # Graceful safe failure (ok=False), never a raised ValueError, never parent reuse.
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "reissue_live_candidate_pool_insufficient")


class KeysuriReissueCandidateExpansionTests(unittest.TestCase):
    """Reissue must remove parent/sent/exposure HARD-duplicates from the candidate
    pool BEFORE TOP5 selection, so the diversity gate fills 5 fresh items with
    backfill instead of being left short after post-selection dedup."""

    @staticmethod
    def _claim(cid, url, title, source="example.com"):
        return {
            "claim_id": cid,
            "headline": title,
            "title": title,
            "canonical_url": url,
            "url": url,
            "source_name": source,
            "source_ids": [cid],
        }

    def test_filter_hard_duplicate_claims_removes_hard_keeps_soft(self) -> None:
        from keysuri_service_full_run import _filter_hard_duplicate_claims

        pack = {
            "program_id": PROGRAM_GLOBAL,
            "claims": [
                self._claim("c1", "https://nvidia.com/a", "NVIDIA ships chip", "blogs.nvidia.com"),
                self._claim("c2", "https://openai.com/b", "OpenAI launches model", "openai.com"),
                self._claim("c3", "https://nvidia.com/c", "NVIDIA opens lab", "blogs.nvidia.com"),
                self._claim("c4", "https://techcrunch.com/d", "Startup raises round", "techcrunch.com"),
            ],
        }
        # Exclude c1 by canonical_url and c2 by exact title.
        exclusion_rows = [
            {"canonical_url": "https://nvidia.com/a", "title": "irrelevant"},
            {"canonical_url": "https://other.com/x", "title": "OpenAI launches model"},
        ]
        filtered, kept = _filter_hard_duplicate_claims(pack, exclusion_rows)
        ids = [c["claim_id"] for c in filtered["claims"]]
        self.assertEqual(kept, 2)
        self.assertNotIn("c1", ids)  # hard canonical_url duplicate removed
        self.assertNotIn("c2", ids)  # hard title duplicate removed
        # c3 (same NVIDIA *source* but different article) is SOFT — kept for the
        # diversity gate to weigh, never hard-removed.
        self.assertIn("c3", ids)
        self.assertIn("c4", ids)

    def test_prepare_reissue_prefilters_pool_and_reports_diagnostics(self) -> None:
        from keysuri_service_full_run import _prepare_keysuri_reissue_prompt_input

        parent_items = _reissue_parent_top5_items()  # canonical_url example.com/parent-N
        parent = {"selected_items": parent_items}
        pack = {
            "program_id": PROGRAM_GLOBAL,
            "claims": (
                [self._claim(f"p{i}", parent_items[i]["canonical_url"], parent_items[i]["headline"]) for i in range(3)]
                + [self._claim(f"f{i}", f"https://fresh.com/{i}", f"Fresh story {i}") for i in range(7)]
            ),
        }
        live_items = _live_reselection_items()
        captured = {}

        def _fake_build(pid, sp, extra_recent_log=None):
            captured["pack"] = sp
            captured["extra"] = extra_recent_log
            return {
                "program_id": PROGRAM_GLOBAL,
                "source_pack": sp,
                "top_5_news": {"items": live_items},
                "sent_log_read_count": 0,
                "exposure_log_read_count": 0,
            }

        with patch("keysuri_service_full_run.build_keysuri_prompt_input", side_effect=_fake_build), patch(
            "keysuri_service_full_run.recent_sent_news_log", return_value=[]
        ), patch(
            "keysuri_service_full_run.recent_owner_review_exposure_log_with_status",
            return_value={"items": [], "read_ok": True},
        ):
            prompt_input, parent_rows, diag, err = _prepare_keysuri_reissue_prompt_input(
                PROGRAM_GLOBAL, pack, parent
            )

        self.assertIsNone(err)
        # The 3 parent-duplicate claims were removed before selection; 7 fresh kept.
        kept_ids = [c["claim_id"] for c in captured["pack"]["claims"]]
        self.assertEqual(len(kept_ids), 7)
        self.assertTrue(all(cid.startswith("f") for cid in kept_ids))
        self.assertEqual(diag["reissue_candidate_raw_count"], 10)
        self.assertEqual(diag["reissue_candidate_after_hard_exclusion_count"], 7)
        self.assertEqual(diag["reissue_excluded_parent_items_count"], 5)
        self.assertEqual(diag["reissue_candidate_final_count"], 5)
        self.assertTrue(diag["reissue_hard_exclude_before_scoring"])
        self.assertTrue(diag["reissue_hard_exclude_reinsertion_blocked"])
        self.assertEqual(diag["reissue_hard_excluded_parent_count"], 3)
        self.assertEqual(diag["reissue_hard_excluded_total_count"], 3)

    def test_prepare_reissue_prefilters_source_map_url_before_selection(self) -> None:
        from keysuri_service_full_run import _prepare_keysuri_reissue_prompt_input

        parent_url = "https://openai.com/index/how-agents-are-transforming-work"
        parent = {
            "selected_items": [
                {
                    "headline": "How agents are transforming work",
                    "canonical_url": parent_url,
                    "source_name": "OpenAI News",
                }
            ]
        }
        pack = {
            "program_id": PROGRAM_GLOBAL,
            "sources": [
                {
                    "source_id": "dup-src",
                    "source_name": "OpenAI News",
                    "source_url": parent_url + "?utm_source=rss",
                    "title": "How agents are transforming work",
                },
                *[
                    {
                        "source_id": f"fresh-src-{i}",
                        "source_name": "Fresh Source",
                        "source_url": f"https://fresh.example.com/{i}",
                        "title": f"Fresh story {i}",
                    }
                    for i in range(6)
                ],
            ],
            "claims": [
                {
                    "claim_id": "dup-claim",
                    "headline": "How agents are transforming work",
                    "statement": "How agents are transforming work",
                    "source_ids": ["dup-src"],
                },
                *[
                    {
                        "claim_id": f"fresh-claim-{i}",
                        "headline": f"Fresh story {i}",
                        "statement": f"Fresh story {i}",
                        "source_ids": [f"fresh-src-{i}"],
                    }
                    for i in range(6)
                ],
            ],
            "global_top5_selection": {
                "selected_source_ids": ["dup-src", "fresh-src-0", "fresh-src-1"],
                "downstream_candidate_source_ids": [
                    "dup-src",
                    "fresh-src-0",
                    "fresh-src-1",
                    "fresh-src-2",
                    "fresh-src-3",
                    "fresh-src-4",
                ],
                "replacement_source_ids": ["dup-src", "fresh-src-5"],
            },
        }
        captured = {}

        def _fake_build(pid, sp, extra_recent_log=None):
            captured["pack"] = sp
            return {
                "program_id": PROGRAM_GLOBAL,
                "source_pack": sp,
                "top_5_news": {"items": _live_reselection_items()},
                "sent_log_read_count": 0,
                "exposure_log_read_count": 0,
            }

        with patch("keysuri_service_full_run.build_keysuri_prompt_input", side_effect=_fake_build), patch(
            "keysuri_service_full_run.recent_sent_news_log", return_value=[]
        ), patch(
            "keysuri_service_full_run.recent_owner_review_exposure_log_with_status",
            return_value={"items": [], "read_ok": True},
        ):
            prompt_input, _parent_rows, diag, err = _prepare_keysuri_reissue_prompt_input(
                PROGRAM_GLOBAL, pack, parent
            )

        self.assertIsNone(err)
        self.assertIsNotNone(prompt_input)
        kept_claim_ids = [c["claim_id"] for c in captured["pack"]["claims"]]
        self.assertNotIn("dup-claim", kept_claim_ids)
        selection = captured["pack"]["global_top5_selection"]
        self.assertNotIn("dup-src", selection["selected_source_ids"])
        self.assertNotIn("dup-src", selection["downstream_candidate_source_ids"])
        self.assertNotIn("dup-src", selection["replacement_source_ids"])
        self.assertEqual(diag["reissue_candidate_raw_count"], 7)
        self.assertEqual(diag["reissue_candidate_after_hard_exclusion_count"], 6)
        self.assertEqual(diag["reissue_hard_excluded_parent_count"], 1)

    def test_reissue_hard_rows_exclude_owner_review_exposure(self) -> None:
        from keysuri_service_full_run import _prepare_keysuri_reissue_prompt_input

        sent_url = "https://sent.example.com"
        exposure_url = "https://exposure.example.com"
        pack = {
            "program_id": PROGRAM_GLOBAL,
            "claims": [
                self._claim("sent-dup", sent_url, "Sent story"),
                self._claim("exposure-dup", exposure_url, "Exposure story"),
            ],
        }
        captured = {}

        def _fake_build(pid, sp, extra_recent_log=None):
            captured["pack"] = sp
            return {
                "program_id": PROGRAM_GLOBAL,
                "source_pack": sp,
                "top_5_news": {"items": _live_reselection_items()},
                "sent_log_read_count": 1,
                "exposure_log_read_count": 1,
            }

        with patch("keysuri_service_full_run.build_keysuri_prompt_input", side_effect=_fake_build), patch(
            "keysuri_service_full_run.recent_sent_news_log",
            return_value=[{"canonical_url": sent_url, "title": "Sent story", "source": "Sent Source"}],
        ), patch(
            "keysuri_service_full_run.recent_owner_review_exposure_log_with_status",
            return_value={
                "items": [{"canonical_url": exposure_url, "title": "Exposure story", "source": "Exposure Source"}],
                "read_ok": True,
            },
        ):
            prompt_input, _parent_rows, diag, err = _prepare_keysuri_reissue_prompt_input(
                PROGRAM_GLOBAL, pack, {"selected_items": []}
            )

        self.assertIsNone(err)
        self.assertIsNotNone(prompt_input)
        kept_ids = [c["claim_id"] for c in captured["pack"]["claims"]]
        self.assertNotIn("sent-dup", kept_ids)
        self.assertIn("exposure-dup", kept_ids)
        self.assertEqual(diag["reissue_hard_excluded_sent_count"], 1)
        self.assertEqual(diag.get("reissue_hard_excluded_exposure_count", 0), 0)
        self.assertEqual(diag["reissue_hard_excluded_total_count"], 1)

    def test_prepare_reissue_insufficient_after_prefilter_safe_fail(self) -> None:
        from keysuri_service_full_run import _prepare_keysuri_reissue_prompt_input

        parent = {"selected_items": _reissue_parent_top5_items()}
        pack = {"program_id": PROGRAM_GLOBAL, "claims": []}

        # build returns a short selection → prep reports it; caller treats <5 as insufficient.
        def _fake_build(pid, sp, extra_recent_log=None):
            return {"program_id": PROGRAM_GLOBAL, "source_pack": sp, "top_5_news": {"items": _live_reselection_items()[:3]}}

        with patch("keysuri_service_full_run.build_keysuri_prompt_input", side_effect=_fake_build), patch(
            "keysuri_service_full_run.recent_sent_news_log", return_value=[]
        ), patch(
            "keysuri_service_full_run.recent_owner_review_exposure_log_with_status",
            return_value={"items": [], "read_ok": True},
        ):
            prompt_input, parent_rows, diag, err = _prepare_keysuri_reissue_prompt_input(
                PROGRAM_GLOBAL, pack, parent
            )
        # prep itself returns no error, but the live selection is < 5 (caller safe-fails).
        from keysuri_service_full_run import _live_selection_items_from_prompt_input
        self.assertIsNone(_live_selection_items_from_prompt_input(prompt_input))
        self.assertEqual(diag["reissue_candidate_final_count"], 3)


class KeysuriTopImageGcsPersistenceTests(unittest.TestCase):
    """Global top image is persisted to GCS on generation and restored on reissue."""

    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "GENIE_OWNER_REVIEW_SEND": "1",
                "GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com",
                # Keep the *artifact* store local so save/load_run_artifact do not
                # touch real GCS; the persist helper's bucket is patched per-test.
                "GENIE_ADMIN_ARTIFACT_BUCKET": "",
                "GENIE_ARTIFACT_BUCKET": "",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    def test_persist_global_top_image_uploads_and_reports_gcs_fields(self) -> None:
        import keysuri_service_full_run as svc

        repo = Path(__file__).resolve().parents[1]
        top = repo / "output" / "images" / "persist_global_top.jpg"
        top.parent.mkdir(parents=True, exist_ok=True)
        top.write_bytes(b"\xff\xd8\xff" + b"\x10" * 64)
        run_id = "20260630_010101_keysuri_global_tech_aabbccdd"
        uploads: list[tuple] = []

        def _uploader(bucket: str, obj: str, src) -> None:
            uploads.append((bucket, obj, str(src)))

        with patch("keysuri_service_full_run.admin_artifact_bucket_name", return_value="test-bkt"):
            expected_obj = f"{svc.admin_artifact_gcs_prefix()}/{run_id}.images/global_top.jpg"
            fields = svc._persist_global_generated_top_image(run_id, top, upload_fn=_uploader)

        self.assertEqual(fields["top_image_persistence_status"], "persisted")
        self.assertEqual(fields["top_image_gcs_object"], expected_obj)
        self.assertEqual(fields["top_image_gcs_uri"], f"gs://test-bkt/{expected_obj}")
        self.assertEqual(fields["generated_image_watermarked_gcs_uri"], fields["top_image_gcs_uri"])
        self.assertEqual(fields["generated_image_gcs_uri"], fields["top_image_gcs_uri"])
        self.assertEqual(fields["generated_image_gcs_bucket"], "test-bkt")
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0][0], "test-bkt")
        self.assertEqual(uploads[0][1], expected_obj)
        self.assertEqual(uploads[0][2], str(top))

    def test_persist_global_top_image_local_only_without_bucket(self) -> None:
        import keysuri_service_full_run as svc

        repo = Path(__file__).resolve().parents[1]
        top = repo / "output" / "images" / "persist_global_top_nobucket.jpg"
        top.parent.mkdir(parents=True, exist_ok=True)
        top.write_bytes(b"\xff\xd8\xff" + b"\x11" * 64)
        with patch("keysuri_service_full_run.admin_artifact_bucket_name", return_value=None):
            fields = svc._persist_global_generated_top_image("20260630_010101_keysuri_global_tech_aabbccdd", top)
        self.assertEqual(fields["top_image_persistence_status"], "local_only")
        self.assertEqual(fields["top_image_persistence_reason"], "artifact_bucket_not_configured")
        self.assertNotIn("top_image_gcs_uri", fields)

    def test_persist_global_top_image_local_only_when_file_missing(self) -> None:
        import keysuri_service_full_run as svc

        repo = Path(__file__).resolve().parents[1]
        missing = repo / "output" / "images" / "persist_global_top_missing.jpg"
        if missing.exists():
            missing.unlink()
        with patch("keysuri_service_full_run.admin_artifact_bucket_name", return_value="test-bkt"):
            fields = svc._persist_global_generated_top_image("20260630_010101_keysuri_global_tech_aabbccdd", missing)
        self.assertEqual(fields["top_image_persistence_status"], "local_only")
        self.assertEqual(fields["top_image_persistence_reason"], "top_image_local_file_missing")

    def test_saved_top_image_reference_restores_from_gcs_when_local_missing(self) -> None:
        import keysuri_service_full_run as svc

        repo = Path(__file__).resolve().parents[1]
        parent = {
            "run_id": "20260630_010102_keysuri_global_tech_deadbeef",
            "generated_image_path_watermarked": "output/keysuri_preview/image_canary/missing_restore_x.jpg",
            "top_image_gcs_uri": "gs://test-bkt/admin_runs/parent.images/global_top.jpg",
        }
        missing_abs = repo / parent["generated_image_path_watermarked"]
        if missing_abs.exists():
            missing_abs.unlink()
        captured: dict = {}

        def _fake_download(dest, *, bucket_name, object_name):
            captured["bucket"] = bucket_name
            captured["object"] = object_name
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(b"\xff\xd8\xffrestored")
            return None

        with patch("keysuri_service_full_run._download_keysuri_top_image_from_gcs", side_effect=_fake_download):
            path, fields = svc._saved_top_image_reference(parent)

        self.assertIsNotNone(path)
        self.assertTrue(path.is_file())
        self.assertTrue(fields["reissue_body_only_image_gcs_restored"])
        self.assertTrue(fields["reissue_body_only_image_local_file_present"])
        self.assertEqual(fields["reissue_body_only_image_gcs_object"], "admin_runs/parent.images/global_top.jpg")
        self.assertEqual(captured["bucket"], "test-bkt")
        self.assertEqual(captured["object"], "admin_runs/parent.images/global_top.jpg")
        if path is not None and path.exists():
            path.unlink()

    def test_saved_top_image_reference_safe_fail_when_local_and_gcs_missing(self) -> None:
        import keysuri_service_full_run as svc

        repo = Path(__file__).resolve().parents[1]
        # Stale local reference, no GCS reference: dry-run still renders (non-file
        # path returned) but the caller's live-send guard safe-fails.
        stale = {
            "run_id": "20260630_010103_keysuri_global_tech_cafebabe",
            "generated_image_path_watermarked": "output/keysuri_preview/image_canary/missing_restore_y.jpg",
        }
        stale_abs = repo / stale["generated_image_path_watermarked"]
        if stale_abs.exists():
            stale_abs.unlink()
        path, fields = svc._saved_top_image_reference(stale)
        self.assertIsNotNone(path)
        self.assertFalse(fields["reissue_body_only_image_local_file_present"])
        self.assertFalse(fields["reissue_body_only_image_gcs_restored"])

        # No image reference at all: hard safe-fail (None).
        path2, fields2 = svc._saved_top_image_reference(
            {"run_id": "20260630_010104_keysuri_global_tech_0badf00d"}
        )
        self.assertIsNone(path2)
        self.assertFalse(fields2["reissue_body_only_image_reused"])

    def test_saved_top_image_reference_safe_fail_when_gcs_download_fails(self) -> None:
        import keysuri_service_full_run as svc

        repo = Path(__file__).resolve().parents[1]
        parent = {
            "run_id": "20260630_010105_keysuri_global_tech_feedface",
            "generated_image_path_watermarked": "output/keysuri_preview/image_canary/missing_restore_z.jpg",
            "top_image_gcs_uri": "gs://test-bkt/admin_runs/parent.images/global_top.jpg",
        }
        missing_abs = repo / parent["generated_image_path_watermarked"]
        if missing_abs.exists():
            missing_abs.unlink()
        with patch(
            "keysuri_service_full_run._download_keysuri_top_image_from_gcs",
            return_value="top_image_gcs_missing",
        ):
            path, fields = svc._saved_top_image_reference(parent)
        # Falls back to the stale (non-file) reference; live-send guard still fails.
        self.assertFalse(fields["reissue_body_only_image_local_file_present"])
        self.assertFalse(fields["reissue_body_only_image_gcs_restored"])
        self.assertTrue(fields.get("reissue_body_only_image_gcs_restore_attempted"))
        self.assertEqual(fields.get("reissue_body_only_image_gcs_restore_status"), "top_image_gcs_missing")

    def test_body_only_live_send_succeeds_with_gcs_restored_image(self) -> None:
        from keysuri_service_full_run import run_keysuri_text_only_reissue

        repo = Path(__file__).resolve().parents[1]
        parent_id = "20260629_123001_keysuri_global_tech_e70f6567"
        child_id = "20260630_010201_keysuri_global_tech_d0b0d201"
        missing_rel = "output/keysuri_preview/image_canary/gcs_restore_parent_top.jpg"
        missing_abs = repo / missing_rel
        if missing_abs.exists():
            missing_abs.unlink()
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": PROGRAM_GLOBAL,
                "program_id": PROGRAM_GLOBAL,
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "generated_image_path_watermarked": missing_rel,
                "top_image_gcs_uri": "gs://test-bkt/admin_runs/20260629_123001_keysuri_global_tech_e70f6567.images/global_top.jpg",
                "top_image_cid": "keysuri_topshot_global_parent",
                "selected_items": _reissue_parent_top5_items(),
            },
            email_html="<html><body><p>parent body</p></body></html>",
        )
        source_pack = {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as sp_file:
            json.dump(source_pack, sp_file)
            source_pack_path = sp_file.name
        live_items = _live_reselection_items(prefix="gcs-restore-body")
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": source_pack,
            "top_5_news": {"news_scope": "global", "section_heading": "글로벌 테크 TOP 5", "items": live_items},
            "sent_log_read_count": 0,
            "exposure_log_read_count": 0,
        }
        send_fn = MagicMock(return_value=True)
        restored_dest = repo / "output" / "admin_runs" / "keysuri_service_assets" / f"{parent_id}_restored_top.jpg"
        if restored_dest.exists():
            restored_dest.unlink()

        def _fake_download(dest, *, bucket_name, object_name):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(b"\xff\xd8\xffrestored-top")
            return None

        with patch("keysuri_service_full_run.generate_run_id", return_value=child_id), patch(
            "keysuri_service_full_run._download_keysuri_top_image_from_gcs", side_effect=_fake_download
        ), patch(
            "keysuri_service_full_run.build_keysuri_prompt_input", return_value=json.loads(json.dumps(prompt_input))
        ), patch(
            "keysuri_service_full_run.build_keysuri_generation_prompt", return_value="PROMPT"
        ), patch(
            "keysuri_service_full_run.parse_keysuri_generated_response",
            return_value={"parse_status": "parsed_valid", "generated_briefing": _briefing_for_live_items(live_items)},
        ), patch(
            "keysuri_service_full_run.enrich_generated_briefing_content",
            side_effect=lambda briefing, *_args: briefing,
        ), patch(
            "keysuri_service_full_run.build_keysuri_subject_artifact_fields",
            return_value={
                "editorial_subject": "라이브 재발행 검증",
                "email_subject": "라이브 재발행 검증",
                "owner_email_subject": "[운영자 검토] 라이브 재발행 검증",
                "email_preheader": "글로벌 AI·테크 신호 검수 대기",
                "owner_email_preheader": "글로벌 AI·테크 신호 검수 대기",
                "subject_top_headline": "라이브 재발행 검증",
                "subject_source": "top_signal_1_headline",
                "subject_kst_date": "20260629",
                "subject_kst_label": "6월 29일",
                "subject_program_label": "글로벌 테크 브리핑",
                "subject_trigger_label": "admin_text_only_reissue",
            },
        ), patch(
            "keysuri_service_full_run._build_service_contract_fixture",
            return_value={"selected_subject": "라이브 재발행 검증", "preheader": "검수 대기"},
        ), patch(
            "keysuri_service_full_run.render_keysuri_contract_preview_html",
            return_value="<html><body><p>재발행 검수 본문</p></body></html>",
        ), patch(
            "keysuri_service_full_run.build_keysuri_global_gmail_owner_email_html",
            return_value='<html><body><p>재발행 검수 본문</p><img src="cid:keysuri_topshot_global_parent"/></body></html>',
        ), patch(
            "keysuri_service_full_run.email_sender.last_send_trace", return_value={}
        ), patch(
            "keysuri_service_full_run.email_sender.last_send_diagnostic", return_value=""
        ):
            result = run_keysuri_text_only_reissue(
                parent_id,
                trigger_source="admin_text_only_reissue",
                text_caller=MagicMock(return_value="RAW"),
                send_owner_email=True,
                send_fn=send_fn,
                smoke_runner=lambda **_kw: _live_smoke_result_for_pack(source_pack_path),
            )

        self.assertNotEqual(result.get("error"), "text_only_reissue_missing_saved_top_image")
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(result.get("email_sent"))
        send_fn.assert_called_once()
        inline_parts = send_fn.call_args.kwargs["inline_jpeg_parts"]
        self.assertEqual(len(inline_parts), 1)
        self.assertEqual(inline_parts[0][0], str(restored_dest.resolve()))
        child = load_run_artifact(child_id) or {}
        self.assertTrue(child.get("reissue_body_only_image_gcs_restored"))
        self.assertTrue(child.get("reissue_body_only_image_local_file_present"))
        self.assertTrue(child.get("email_sent"))
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        if restored_dest.exists():
            restored_dest.unlink()

    def test_body_only_live_send_safe_fails_when_local_and_gcs_missing(self) -> None:
        from keysuri_service_full_run import run_keysuri_text_only_reissue

        repo = Path(__file__).resolve().parents[1]
        parent_id = "20260629_123001_keysuri_global_tech_e70f6567"
        child_id = "20260630_010202_keysuri_global_tech_d0b0d202"
        missing_rel = "output/keysuri_preview/image_canary/no_gcs_parent_top.jpg"
        missing_abs = repo / missing_rel
        if missing_abs.exists():
            missing_abs.unlink()
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": PROGRAM_GLOBAL,
                "program_id": PROGRAM_GLOBAL,
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "generated_image_path_watermarked": missing_rel,
                "top_image_cid": "keysuri_topshot_global_parent",
                "selected_items": _reissue_parent_top5_items(),
            },
            email_html="<html><body><p>parent body</p></body></html>",
        )
        source_pack = {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as sp_file:
            json.dump(source_pack, sp_file)
            source_pack_path = sp_file.name
        live_items = _live_reselection_items(prefix="no-gcs-body")
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": source_pack,
            "top_5_news": {"news_scope": "global", "section_heading": "글로벌 테크 TOP 5", "items": live_items},
            "sent_log_read_count": 0,
            "exposure_log_read_count": 0,
        }
        send_fn = MagicMock(return_value=True)

        with patch("keysuri_service_full_run.generate_run_id", return_value=child_id), patch(
            "keysuri_service_full_run.build_keysuri_prompt_input", return_value=json.loads(json.dumps(prompt_input))
        ), patch(
            "keysuri_service_full_run.build_keysuri_generation_prompt", return_value="PROMPT"
        ), patch(
            "keysuri_service_full_run.parse_keysuri_generated_response",
            return_value={"parse_status": "parsed_valid", "generated_briefing": _briefing_for_live_items(live_items)},
        ), patch(
            "keysuri_service_full_run.enrich_generated_briefing_content",
            side_effect=lambda briefing, *_args: briefing,
        ):
            result = run_keysuri_text_only_reissue(
                parent_id,
                trigger_source="admin_text_only_reissue",
                text_caller=MagicMock(return_value="RAW"),
                send_owner_email=True,
                send_fn=send_fn,
                smoke_runner=lambda **_kw: _live_smoke_result_for_pack(source_pack_path),
            )

        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "text_only_reissue_missing_saved_top_image")
        send_fn.assert_not_called()

    @patch("keysuri_customer_delivery.send_keysuri_customer_final_email")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_image_path")
    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_image_only_reissue_regenerates_and_persists_global_top_to_gcs(
        self,
        mock_run_id: MagicMock,
        mock_watermark: MagicMock,
        mock_bottom: MagicMock,
        mock_customer_final: MagicMock,
    ) -> None:
        from keysuri_service_full_run import run_keysuri_image_only_reissue

        repo = Path(__file__).resolve().parents[1]
        parent_id = "20260624_183003_keysuri_global_tech_eeff0011"
        child_id = "20260630_010301_keysuri_global_tech_11ab22cd"
        mock_run_id.return_value = child_id
        raw_top = repo / "output" / "images" / "image_only_persist_global_top_raw.jpg"
        raw_top.parent.mkdir(parents=True, exist_ok=True)
        raw_top.write_bytes(b"\xff\xd8\xff" + b"\x47" * 128)
        mock_watermark.side_effect = _mock_keysuri_watermark
        # Parent has NO local top image file — image_only regenerates fresh, so it
        # must not depend on the parent's ephemeral local image.
        parent_html = (
            '<html><body><p id="brief">글로벌 본문 텍스트입니다.</p>'
            '<img src="cid:keysuri_topshot_global_20260624"/>'
            f'<a href="https://example.com/admin/runs/{parent_id}">review</a>'
            "</body></html>"
        )
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "generated_image_path_watermarked": "output/keysuri_preview/image_canary/parent_gone.jpg",
                "owner_email_subject": "[운영자 검토] 클라우드 반도체 공급망 신호: 6월 24일 글로벌 테크 브리핑",
                "owner_email_preheader": "글로벌 AI·테크 신호 검수 대기",
                "email_subject": "클라우드 반도체 공급망 신호: 6월 24일 글로벌 테크 브리핑",
                "subject_top_headline": "클라우드 반도체 공급망 신호",
                "reissue_count": 0,
            },
            email_html=parent_html,
        )

        def _image_runner(program_id: str, **kwargs):
            return ServiceImageOutcome(
                called_image_api=True,
                image_generation_status="generated",
                image_source=IMAGE_SOURCE_GENERATED,
                generated_image_path=str(raw_top.relative_to(repo)),
            )

        send_fn = MagicMock(return_value=True)
        uploads: list[tuple] = []

        def _uploader(bucket: str, obj: str, src) -> None:
            uploads.append((bucket, obj, str(src)))

        with patch("keysuri_service_full_run.admin_artifact_bucket_name", return_value="test-bkt"), patch(
            "keysuri_service_full_run.email_sender.last_send_trace", return_value={}
        ), patch(
            "keysuri_service_full_run.email_sender.last_send_diagnostic", return_value=""
        ):
            result = run_keysuri_image_only_reissue(
                parent_id,
                image_canary_runner=_image_runner,
                send_fn=send_fn,
                image_upload_fn=_uploader,
                reissue_reason_code="이미지 품질 이슈",
                reissue_reason_note="global image only",
            )

        self.assertTrue(result["ok"], result)
        mock_bottom.assert_not_called()
        mock_customer_final.assert_not_called()
        child = load_run_artifact(child_id) or {}
        self.assertEqual(child.get("regen_type"), "image_only")
        self.assertEqual(child.get("program_id"), "keysuri_global_tech")
        self.assertEqual(child.get("top_image_persistence_status"), "persisted")
        expected_obj = f"admin_runs/{child_id}.images/global_top.jpg"
        self.assertEqual(child.get("top_image_gcs_object"), expected_obj)
        self.assertEqual(child.get("top_image_gcs_uri"), f"gs://test-bkt/{expected_obj}")
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0][1], expected_obj)


class KeysuriImageOnlyReissueTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "GENIE_OWNER_REVIEW_SEND": "1",
                "GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com",
                "GENIE_ADMIN_ARTIFACT_BUCKET": "",
                "GENIE_ARTIFACT_BUCKET": "",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    def test_text_only_reissue_dry_run_creates_child_with_sanitized_live_top5(self) -> None:
        from keysuri_service_full_run import run_keysuri_text_only_reissue
        from keysuri_generation_prompt import parse_keysuri_generated_response as real_parse_keysuri_response

        repo = Path(__file__).resolve().parents[1]
        parent_id = "20260629_123001_keysuri_global_tech_e70f6567"
        child_id = "20260629_130001_keysuri_global_tech_d0b0d001"
        top_path = repo / "output" / "images" / "body_only_dry_run_top.jpg"
        top_path.parent.mkdir(parents=True, exist_ok=True)
        top_path.write_bytes(b"\xff\xd8\xff" + b"\x83" * 128)
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": PROGRAM_GLOBAL,
                "program_id": PROGRAM_GLOBAL,
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "generated_image_path_watermarked": str(top_path.relative_to(repo)),
                "top_image_cid": "keysuri_topshot_global_parent",
                "selected_items": _reissue_parent_top5_items(),
            },
            email_html="<html><body><p>parent body</p></body></html>",
        )
        source_pack = {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as sp_file:
            json.dump(source_pack, sp_file)
            source_pack_path = sp_file.name
        live_items = _live_reselection_items_with_raw_english_ellipsis(prefix="dry-body")
        partial_gemini = _briefing_for_live_items(live_items[:2], program_id=PROGRAM_GLOBAL)
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": source_pack,
            "top_5_news": {"news_scope": "global", "section_heading": "글로벌 테크 TOP 5", "items": live_items},
            "sent_log_read_count": 0,
            "exposure_log_read_count": 0,
        }
        send_fn = MagicMock(return_value=True)

        def _parse_reissue_text(raw_text, program_id, parsed_prompt_input):
            if raw_text == "RAW":
                return {"parse_status": "parsed_valid", "generated_briefing": partial_gemini}
            return real_parse_keysuri_response(raw_text, program_id, parsed_prompt_input)

        with patch("keysuri_service_full_run.generate_run_id", return_value=child_id), patch(
            "keysuri_service_full_run.build_keysuri_prompt_input", return_value=json.loads(json.dumps(prompt_input))
        ), patch(
            "keysuri_service_full_run.build_keysuri_generation_prompt", return_value="PROMPT"
        ), patch(
            "keysuri_service_full_run.parse_keysuri_generated_response",
            side_effect=_parse_reissue_text,
        ), patch(
            "keysuri_service_full_run.enrich_generated_briefing_content",
            side_effect=lambda briefing, *_args: briefing,
        ), patch(
            "keysuri_service_full_run.build_keysuri_subject_artifact_fields",
            return_value={
                "editorial_subject": "라이브 재발행 검증",
                "email_subject": "라이브 재발행 검증",
                "owner_email_subject": "[운영자 검토] 라이브 재발행 검증",
                "email_preheader": "글로벌 AI·테크 신호 검수 대기",
                "owner_email_preheader": "글로벌 AI·테크 신호 검수 대기",
                "subject_top_headline": "라이브 재발행 검증",
                "subject_source": "top_signal_1_headline",
                "subject_kst_date": "20260629",
                "subject_kst_label": "6월 29일",
                "subject_program_label": "글로벌 테크 브리핑",
                "subject_trigger_label": "admin_text_only_reissue",
            },
        ), patch(
            "keysuri_service_full_run._build_service_contract_fixture",
            return_value={"selected_subject": "라이브 재발행 검증", "preheader": "검수 대기"},
        ), patch(
            "keysuri_service_full_run.render_keysuri_contract_preview_html",
            return_value="<html><body><p>재발행 검수 본문</p></body></html>",
        ), patch(
            "keysuri_service_full_run.build_keysuri_global_gmail_owner_email_html",
            return_value='<html><body><p>재발행 검수 본문</p><img src="cid:keysuri_topshot_global_parent"/></body></html>',
        ):
            result = run_keysuri_text_only_reissue(
                parent_id,
                trigger_source="admin_text_only_reissue",
                text_caller=MagicMock(return_value="RAW"),
                send_owner_email=False,
                send_fn=send_fn,
                smoke_runner=lambda **_kw: _live_smoke_result_for_pack(source_pack_path),
            )

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["email_sent"])
        send_fn.assert_not_called()
        child = load_run_artifact(child_id) or {}
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        self.assertTrue(child.get("reissue_visible_text_sanitized"))
        self.assertTrue(child.get("reissue_top5_clean_korean_fallback_used"))
        self.assertEqual(child.get("reissue_text_quality_gate_after_enrich"), "pass")
        snap = child.get("regen_generated_briefing_snapshot") or {}
        items = (snap.get("top_5_news") or {}).get("items") or []
        self.assertEqual(len(items), 5)
        self.assertEqual([it.get("news_id") for it in items], [it["news_id"] for it in live_items])
        rendered = json.dumps(items, ensure_ascii=False)
        self.assertNotIn("…", rendered)
        self.assertNotIn("..", rendered)
        self.assertNotIn("report maps how AI could reshape jobs", rendered)

    def test_text_only_reissue_dry_run_reuses_missing_local_parent_image_reference(self) -> None:
        from keysuri_service_full_run import run_keysuri_text_only_reissue

        repo = Path(__file__).resolve().parents[1]
        parent_id = "20260629_123001_keysuri_global_tech_e70f6567"
        child_id = "20260629_130003_keysuri_global_tech_d0b0d003"
        missing_rel = "output/keysuri_preview/image_canary/missing_parent_top_mirai_on_watermarked.jpg"
        missing_abs = repo / missing_rel
        if missing_abs.exists():
            missing_abs.unlink()
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": PROGRAM_GLOBAL,
                "program_id": PROGRAM_GLOBAL,
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "generated_image_path_watermarked": missing_rel,
                "top_image_cid": "keysuri_topshot_global_parent",
                "selected_items": _reissue_parent_top5_items(),
            },
            email_html="<html><body><p>parent body</p></body></html>",
        )
        source_pack = {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as sp_file:
            json.dump(source_pack, sp_file)
            source_pack_path = sp_file.name
        live_items = _live_reselection_items(prefix="dry-body-missing-image")
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": source_pack,
            "top_5_news": {"news_scope": "global", "section_heading": "글로벌 테크 TOP 5", "items": live_items},
            "sent_log_read_count": 0,
            "exposure_log_read_count": 0,
        }
        send_fn = MagicMock(return_value=True)

        with patch("keysuri_service_full_run.generate_run_id", return_value=child_id), patch(
            "keysuri_service_full_run.build_keysuri_prompt_input", return_value=json.loads(json.dumps(prompt_input))
        ), patch(
            "keysuri_service_full_run.build_keysuri_generation_prompt", return_value="PROMPT"
        ), patch(
            "keysuri_service_full_run.parse_keysuri_generated_response",
            return_value={"parse_status": "parsed_valid", "generated_briefing": _briefing_for_live_items(live_items)},
        ), patch(
            "keysuri_service_full_run.enrich_generated_briefing_content",
            side_effect=lambda briefing, *_args: briefing,
        ), patch(
            "keysuri_service_full_run.build_keysuri_subject_artifact_fields",
            return_value={
                "editorial_subject": "라이브 재발행 검증",
                "email_subject": "라이브 재발행 검증",
                "owner_email_subject": "[운영자 검토] 라이브 재발행 검증",
                "email_preheader": "글로벌 AI·테크 신호 검수 대기",
                "owner_email_preheader": "글로벌 AI·테크 신호 검수 대기",
                "subject_top_headline": "라이브 재발행 검증",
                "subject_source": "top_signal_1_headline",
                "subject_kst_date": "20260629",
                "subject_kst_label": "6월 29일",
                "subject_program_label": "글로벌 테크 브리핑",
                "subject_trigger_label": "admin_text_only_reissue",
            },
        ), patch(
            "keysuri_service_full_run._build_service_contract_fixture",
            return_value={"selected_subject": "라이브 재발행 검증", "preheader": "검수 대기"},
        ), patch(
            "keysuri_service_full_run.render_keysuri_contract_preview_html",
            return_value="<html><body><p>재발행 검수 본문</p></body></html>",
        ), patch(
            "keysuri_service_full_run.build_keysuri_global_gmail_owner_email_html",
            return_value='<html><body><p>재발행 검수 본문</p><img src="cid:keysuri_topshot_global_parent"/></body></html>',
        ):
            result = run_keysuri_text_only_reissue(
                parent_id,
                trigger_source="admin_text_only_reissue",
                text_caller=MagicMock(return_value="RAW"),
                send_owner_email=False,
                send_fn=send_fn,
                smoke_runner=lambda **_kw: _live_smoke_result_for_pack(source_pack_path),
            )

        self.assertTrue(result["ok"], result)
        send_fn.assert_not_called()
        child = load_run_artifact(child_id) or {}
        self.assertEqual(child.get("generated_image_path_watermarked"), missing_rel)
        self.assertTrue(child.get("reissue_body_only_image_reused"))
        self.assertEqual(child.get("reissue_body_only_image_source"), "generated_image_path_watermarked")
        self.assertTrue(child.get("reissue_body_only_image_url_present"))
        self.assertFalse(child.get("reissue_body_only_image_local_file_present"))
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        self.assertFalse(child.get("email_sent"))

    def test_text_only_reissue_missing_parent_image_reference_remains_safe_failure(self) -> None:
        from keysuri_service_full_run import run_keysuri_text_only_reissue

        parent_id = "20260629_123001_keysuri_global_tech_00000000"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": PROGRAM_GLOBAL,
                "program_id": PROGRAM_GLOBAL,
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "selected_items": _reissue_parent_top5_items(),
            },
            email_html="<html><body><p>parent body</p></body></html>",
        )
        source_pack = {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as sp_file:
            json.dump(source_pack, sp_file)
            source_pack_path = sp_file.name
        live_items = _live_reselection_items(prefix="dry-body-no-image")
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": source_pack,
            "top_5_news": {"news_scope": "global", "section_heading": "글로벌 테크 TOP 5", "items": live_items},
            "sent_log_read_count": 0,
            "exposure_log_read_count": 0,
        }

        with patch("keysuri_service_full_run.build_keysuri_prompt_input", return_value=json.loads(json.dumps(prompt_input))), patch(
            "keysuri_service_full_run.build_keysuri_generation_prompt", return_value="PROMPT"
        ), patch(
            "keysuri_service_full_run.parse_keysuri_generated_response",
            return_value={"parse_status": "parsed_valid", "generated_briefing": _briefing_for_live_items(live_items)},
        ), patch(
            "keysuri_service_full_run.enrich_generated_briefing_content",
            side_effect=lambda briefing, *_args: briefing,
        ):
            result = run_keysuri_text_only_reissue(
                parent_id,
                text_caller=MagicMock(return_value="RAW"),
                send_owner_email=False,
                send_fn=MagicMock(return_value=True),
                smoke_runner=lambda **_kw: _live_smoke_result_for_pack(source_pack_path),
            )

        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "text_only_reissue_missing_saved_top_image")

    def test_text_and_image_reissue_dry_run_creates_child_with_sanitized_live_top5(self) -> None:
        from keysuri_service_full_run import run_keysuri_text_and_image_reissue

        repo = Path(__file__).resolve().parents[1]
        parent_id = "20260629_123001_keysuri_global_tech_e70f6568"
        child_id = "20260629_130002_keysuri_global_tech_d0b00002"
        raw_top = repo / "output" / "images" / "body_and_image_dry_run_top_raw.jpg"
        raw_top.parent.mkdir(parents=True, exist_ok=True)
        raw_top.write_bytes(b"\xff\xd8\xff" + b"\x84" * 128)
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": PROGRAM_GLOBAL,
                "program_id": PROGRAM_GLOBAL,
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "selected_items": _reissue_parent_top5_items(),
            },
            email_html="<html><body><p>parent body</p></body></html>",
        )
        source_pack = {"program_id": PROGRAM_GLOBAL, "sources": [], "claims": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as sp_file:
            json.dump(source_pack, sp_file)
            source_pack_path = sp_file.name
        live_items = _live_reselection_items_with_raw_english_ellipsis(prefix="dry-both")
        partial_gemini = _briefing_for_live_items(live_items[:2], program_id=PROGRAM_GLOBAL)
        smoke_result = LiveSourceSmokeResult(
            ok=True,
            program_id=PROGRAM_GLOBAL,
            source_pack_path=source_pack_path,
            html_path="",
            fetched_item_count=7,
            feed_urls_used=[],
            sample_marker_pass=True,
            called_gemini=True,
            parse_status="parsed_valid",
            generated_briefing=partial_gemini,
        )
        prompt_input = {
            "program_id": PROGRAM_GLOBAL,
            "source_pack": source_pack,
            "top_5_news": {"news_scope": "global", "section_heading": "글로벌 테크 TOP 5", "items": live_items},
            "sent_log_read_count": 0,
            "exposure_log_read_count": 0,
        }
        image_runner = MagicMock(
            return_value=ServiceImageOutcome(
                called_image_api=True,
                image_generation_status="generated",
                image_source=IMAGE_SOURCE_GENERATED,
                generated_image_path=str(raw_top.relative_to(repo)),
            )
        )
        send_fn = MagicMock(return_value=True)

        with patch("keysuri_service_full_run.generate_run_id", return_value=child_id), patch(
            "keysuri_service_full_run.build_keysuri_prompt_input", return_value=json.loads(json.dumps(prompt_input))
        ), patch(
            "keysuri_service_full_run.enrich_generated_briefing_content",
            side_effect=lambda briefing, *_args: briefing,
        ), patch(
            "keysuri_service_full_run.apply_keysuri_mirai_on_watermark",
            side_effect=_mock_keysuri_watermark,
        ), patch(
            "keysuri_service_full_run.build_keysuri_subject_artifact_fields",
            return_value={
                "editorial_subject": "라이브 전체 재발행 검증",
                "email_subject": "라이브 전체 재발행 검증",
                "owner_email_subject": "[운영자 검토] 라이브 전체 재발행 검증",
                "email_preheader": "글로벌 AI·테크 신호 검수 대기",
                "owner_email_preheader": "글로벌 AI·테크 신호 검수 대기",
                "subject_top_headline": "라이브 전체 재발행 검증",
                "subject_source": "top_signal_1_headline",
                "subject_kst_date": "20260629",
                "subject_kst_label": "6월 29일",
                "subject_program_label": "글로벌 테크 브리핑",
                "subject_trigger_label": "admin_text_and_image_reissue",
            },
        ), patch(
            "keysuri_service_full_run._build_service_contract_fixture",
            return_value={"selected_subject": "라이브 전체 재발행 검증", "preheader": "검수 대기"},
        ), patch(
            "keysuri_service_full_run.render_keysuri_contract_preview_html",
            return_value="<html><body><p>전체 재발행 검수 본문</p></body></html>",
        ), patch(
            "keysuri_service_full_run.build_keysuri_global_gmail_owner_email_html",
            return_value="<html><body><p>전체 재발행 검수 본문</p></body></html>",
        ):
            result = run_keysuri_text_and_image_reissue(
                parent_id,
                smoke_runner=MagicMock(return_value=smoke_result),
                image_canary_runner=image_runner,
                send_owner_email=False,
                send_fn=send_fn,
            )

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["email_sent"])
        send_fn.assert_not_called()
        image_runner.assert_called_once()
        child = load_run_artifact(child_id) or {}
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        self.assertTrue(child.get("image_generation_called"))
        self.assertTrue(child.get("reissue_visible_text_sanitized"))
        self.assertTrue(child.get("reissue_top5_clean_korean_fallback_used"))
        self.assertEqual(child.get("reissue_text_quality_gate_after_enrich"), "pass")
        self.assertNotIn("bottom_image_cid", child)
        snap = child.get("regen_generated_briefing_snapshot") or {}
        items = (snap.get("top_5_news") or {}).get("items") or []
        self.assertEqual(len(items), 5)
        self.assertEqual([it.get("news_id") for it in items], [it["news_id"] for it in live_items])
        rendered = json.dumps(items, ensure_ascii=False)
        self.assertNotIn("…", rendered)
        self.assertNotIn("..", rendered)
        self.assertNotIn("report maps how AI could reshape jobs", rendered)

    @patch("keysuri_customer_delivery.send_keysuri_customer_final_email")
    @patch("keysuri_service_full_run.run_keysuri_live_source_smoke")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_image_path")
    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_image_only_reissue_preserves_text_replaces_images_and_sends_owner_only(
        self,
        mock_run_id: MagicMock,
        mock_watermark: MagicMock,
        mock_bottom: MagicMock,
        mock_prompt_input: MagicMock,
        mock_smoke: MagicMock,
        mock_customer_final: MagicMock,
    ) -> None:
        from keysuri_service_full_run import run_keysuri_image_only_reissue

        repo = Path(__file__).resolve().parents[1]
        parent_id = "20260624_183002_keysuri_korea_tech_aabbccdd"
        child_id = "20260624_190000_keysuri_korea_tech_11223344"
        mock_run_id.return_value = child_id
        raw_top = repo / "output" / "images" / "image_only_regen_top_raw.jpg"
        raw_top.parent.mkdir(parents=True, exist_ok=True)
        raw_top.write_bytes(b"\xff\xd8\xff" + b"\x44" * 128)
        mock_watermark.side_effect = _mock_keysuri_watermark
        bottom_path = repo / "output" / "images" / "image_only_regen_bottom.jpg"
        bottom_path.write_bytes(b"\xff\xd8\xff" + b"\x55" * 128)
        mock_bottom.return_value = (
            bottom_path,
            [],
            {
                "bottom_shot_source": "test_generated",
                "bottom_shot_generation_status": "generated",
                "bottom_shot_image_path": str(bottom_path.relative_to(repo)),
            },
        )
        parent_html = (
            '<html><body>'
            '<span style="display:none">국내 AI·테크 신호 검수 대기</span>'
            '<table><tr><td style="padding:0 0 16px 0;">'
            '<img src="cid:keysuri_topshot_korea_20260624" width="568" /></td></tr>'
            '<tr><td><h1>키수리 국내 테크 브리핑</h1></td></tr></table>'
            '<p id="brief">보존해야 하는 본문 텍스트입니다.</p>'
            '<h2>국내 테크 TOP 5</h2>'
            '<a href="https://www.etnews.com/1">출처1</a>'
            '<h2>키수리의 딥-다이브</h2>'
            '<a href="https://zdnet.co.kr/2">출처2</a>'
            '<img src="cid:keysuri_bottomshot_korea_20260624"/>'
            f'<a href="https://example.com/admin/runs/{parent_id}">review</a>'
            "</body></html>"
        )
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_korea_tech",
                "program_id": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "owner_email_subject": "[운영자 검토] 국내 AI 반도체 정책 점검: 6월 24일 국내 테크 브리핑",
                "owner_email_preheader": "국내 AI·테크 신호 검수 대기 · 주요 신호: 국내 AI 반도체 정책 점검",
                "email_subject": "국내 AI 반도체 정책 점검: 6월 24일 국내 테크 브리핑",
                "email_preheader": "국내 AI·테크 신호 검수 대기 · 주요 신호: 국내 AI 반도체 정책 점검",
                "editorial_subject": "국내 AI 반도체 정책 점검: 6월 24일 국내 테크 브리핑",
                "subject_top_headline": "국내 AI 반도체 정책 점검",
                "reissue_count": 0,
            },
            email_html=parent_html,
        )

        def _image_runner(program_id: str, **kwargs):
            self.assertEqual(program_id, "keysuri_korea_tech")
            self.assertEqual(kwargs.get("run_id"), parent_id)
            self.assertEqual(kwargs.get("subject_top_headline"), "국내 AI 반도체 정책 점검")
            return ServiceImageOutcome(
                called_image_api=True,
                image_generation_status="generated",
                image_source=IMAGE_SOURCE_GENERATED,
                generated_image_path=str(raw_top.relative_to(repo)),
            )

        send_fn = MagicMock(return_value=True)
        trace = {
            "envelope_to": ["owner@example.com"],
            "mime_html_sha256": "html-sha",
            "mime_html_bytes_len": 456,
            "inline_input_hashes": [
                {"path": str(raw_top), "cid": "keysuri_topshot_korea_20260624_regen_11223344", "filename": "top.jpg", "sha256": "top-sha"},
                {"path": str(bottom_path), "cid": "keysuri_bottomshot_korea_20260624_regen_11223344", "filename": "bottom.jpg", "sha256": "bottom-sha"},
            ],
        }
        with patch("keysuri_service_full_run.email_sender.last_send_trace", return_value=trace):
            with patch("keysuri_service_full_run.email_sender.last_send_diagnostic", return_value=""):
                result = run_keysuri_image_only_reissue(
                    parent_id,
                    image_canary_runner=_image_runner,
                    send_fn=send_fn,
                    reissue_reason_code="이미지 품질 이슈",
                    reissue_reason_note="image only",
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["run_id"], child_id)
        self.assertFalse(result["called_gemini"])
        self.assertTrue(result["image_generation_called"])
        mock_smoke.assert_not_called()
        mock_prompt_input.assert_not_called()
        mock_customer_final.assert_not_called()
        send_fn.assert_called_once()
        inline_parts = send_fn.call_args.kwargs["inline_jpeg_parts"]
        self.assertEqual(len(inline_parts), 2)
        self.assertEqual(inline_parts[0][1], "keysuri_topshot_korea_20260624_regen_11223344")
        self.assertEqual(inline_parts[1][1], "keysuri_bottomshot_korea_20260624_regen_11223344")

        child = load_run_artifact(child_id) or {}
        self.assertEqual(child.get("regen_type"), "image_only")
        self.assertEqual(child.get("regen_parent_run_id"), parent_id)
        self.assertTrue(child.get("regen_preserved_text"))
        self.assertTrue(child.get("regen_regenerated_images"))
        self.assertFalse(child.get("text_generation_called"))
        self.assertTrue(child.get("image_generation_called"))
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        self.assertEqual(child.get("owner_review_status"), "pending_review")
        self.assertEqual(child.get("artifact_status"), "emailed")
        self.assertEqual(child.get("owner_email_delivery_status"), "smtp_accepted")
        self.assertTrue(str(child.get("owner_email_subject") or "").startswith("[이미지 재발행][운영자 검토]"))
        self.assertEqual(child.get("reissue_reason_code"), "이미지 품질 이슈")
        self.assertEqual(child.get("reissue_reason_note"), "image only")
        self.assertNotIn("customer_email_subject", child)

        # New: image_only reissue rebuilds the full email with a mobile-Gmail-safe
        # run-unique marker so the body is shown instead of collapsed.
        self.assertTrue(child.get("email_rebuilt_after_image_reissue"))
        self.assertEqual(child.get("reused_body_from_run_id"), parent_id)
        self.assertTrue(child.get("body_content_present"))
        self.assertTrue(child.get("mobile_gmail_safe_layout"))
        self.assertEqual(child.get("rebuilt_email_html_path"), str(artifact_email_path(child_id)))

        child_html = load_run_email_html(child_id) or ""
        self.assertIn("보존해야 하는 본문 텍스트입니다.", child_html)
        self.assertNotIn("cid:keysuri_topshot_korea_20260624\"", child_html)
        self.assertIn("cid:keysuri_topshot_korea_20260624_regen_11223344", child_html)
        self.assertIn("cid:keysuri_bottomshot_korea_20260624_regen_11223344", child_html)
        self.assertIn(child_id, child_html)
        # Marker present and placed after the hero image but before the title.
        self.assertIn("image-only-reissue-marker", child_html)
        self.assertLess(
            child_html.index("cid:keysuri_topshot_korea_20260624_regen_11223344"),
            child_html.index("image-only-reissue-marker"),
        )
        self.assertLess(child_html.index("image-only-reissue-marker"), child_html.index("<h1"))
        parent = load_run_artifact(parent_id) or {}
        self.assertEqual(parent.get("reissue_count", 0), 0)
        self.assertNotIn("regen_type", parent)

    @patch("keysuri_customer_delivery.send_keysuri_customer_final_email")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_image_path")
    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_image_only_reissue_global_regenerates_top_only(
        self,
        mock_run_id: MagicMock,
        mock_watermark: MagicMock,
        mock_bottom: MagicMock,
        mock_customer_final: MagicMock,
    ) -> None:
        from keysuri_service_full_run import run_keysuri_image_only_reissue

        repo = Path(__file__).resolve().parents[1]
        parent_id = "20260624_183003_keysuri_global_tech_aabbccdd"
        child_id = "20260624_190001_keysuri_global_tech_11223344"
        mock_run_id.return_value = child_id
        raw_top = repo / "output" / "images" / "image_only_regen_global_top_raw.jpg"
        raw_top.parent.mkdir(parents=True, exist_ok=True)
        raw_top.write_bytes(b"\xff\xd8\xff" + b"\x46" * 128)
        mock_watermark.side_effect = _mock_keysuri_watermark
        parent_html = (
            '<html><body><p id="brief">글로벌 본문 텍스트입니다.</p>'
            '<img src="cid:keysuri_topshot_global_20260624"/>'
            f'<a href="https://example.com/admin/runs/{parent_id}">review</a>'
            "</body></html>"
        )
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "owner_email_subject": "[운영자 검토] 클라우드 반도체 공급망 신호: 6월 24일 글로벌 테크 브리핑",
                "owner_email_preheader": "글로벌 AI·테크 신호 검수 대기 · 주요 신호: 클라우드 반도체 공급망 신호",
                "email_subject": "클라우드 반도체 공급망 신호: 6월 24일 글로벌 테크 브리핑",
                "subject_top_headline": "클라우드 반도체 공급망 신호",
                "reissue_count": 0,
            },
            email_html=parent_html,
        )

        def _image_runner(program_id: str, **kwargs):
            self.assertEqual(program_id, "keysuri_global_tech")
            self.assertEqual(kwargs.get("run_id"), parent_id)
            return ServiceImageOutcome(
                called_image_api=True,
                image_generation_status="generated",
                image_source=IMAGE_SOURCE_GENERATED,
                generated_image_path=str(raw_top.relative_to(repo)),
            )

        send_fn = MagicMock(return_value=True)
        trace = {
            "envelope_to": ["owner@example.com"],
            "mime_html_sha256": "html-global-sha",
            "mime_html_bytes_len": 345,
            "inline_input_hashes": [
                {
                    "path": str(raw_top),
                    "cid": "keysuri_topshot_global_20260624_regen_11223344",
                    "filename": "top.jpg",
                    "sha256": "top-global-sha",
                }
            ],
        }
        with patch("keysuri_service_full_run.email_sender.last_send_trace", return_value=trace):
            with patch("keysuri_service_full_run.email_sender.last_send_diagnostic", return_value=""):
                result = run_keysuri_image_only_reissue(
                    parent_id,
                    image_canary_runner=_image_runner,
                    send_fn=send_fn,
                    reissue_reason_code="이미지 품질 이슈",
                    reissue_reason_note="global image only",
                )

        self.assertTrue(result["ok"])
        mock_bottom.assert_not_called()
        mock_customer_final.assert_not_called()
        send_fn.assert_called_once()
        inline_parts = send_fn.call_args.kwargs["inline_jpeg_parts"]
        self.assertEqual(len(inline_parts), 1)
        child = load_run_artifact(child_id) or {}
        self.assertEqual(child.get("regen_type"), "image_only")
        self.assertEqual(child.get("program_id"), "keysuri_global_tech")
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        self.assertNotIn("korea_bottom_shot_path", child)

    @patch("keysuri_customer_delivery.send_keysuri_customer_final_email")
    @patch("keysuri_service_full_run.run_keysuri_live_source_smoke")
    @patch("keysuri_service_full_run.generate_run_id")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.build_keysuri_generation_prompt")
    @patch("keysuri_service_full_run.parse_keysuri_generated_response")
    @patch("keysuri_service_full_run.enrich_generated_briefing_content")
    @patch("keysuri_service_full_run.validate_and_repair_keysuri_visible_text_quality")
    @patch("keysuri_service_full_run._build_service_contract_fixture")
    @patch("keysuri_service_full_run.build_keysuri_subject_artifact_fields")
    @patch("keysuri_service_full_run.render_keysuri_contract_preview_html")
    @patch("keysuri_service_full_run.build_keysuri_korea_gmail_owner_email_html")
    @patch("keysuri_service_full_run.validate_keysuri_html_visible_text_quality")
    def test_text_only_reissue_regenerates_text_reuses_images_and_sends_owner_only(
        self,
        mock_validate_html: MagicMock,
        mock_email_html: MagicMock,
        mock_render_preview: MagicMock,
        mock_subject_fields: MagicMock,
        mock_fixture: MagicMock,
        mock_validate_visible: MagicMock,
        mock_enrich: MagicMock,
        mock_parse: MagicMock,
        mock_build_prompt: MagicMock,
        mock_build_input: MagicMock,
        mock_run_id: MagicMock,
        mock_smoke: MagicMock,
        mock_customer_final: MagicMock,
    ) -> None:
        from keysuri_service_full_run import run_keysuri_text_only_reissue

        repo = Path(__file__).resolve().parents[1]
        parent_id = "20260624_183004_keysuri_korea_tech_aabbccdd"
        child_id = "20260624_190002_keysuri_korea_tech_11223344"
        mock_run_id.return_value = child_id
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as _sp:
            json.dump({"program_id": "keysuri_korea_tech", "sources": [], "claims": []}, _sp)
            _sp_path = _sp.name
        mock_smoke.return_value = _live_smoke_result_for_pack(_sp_path, program_id=PROGRAM_KOREA)
        top_path = repo / "output" / "images" / "text_only_saved_top.jpg"
        bottom_path = repo / "output" / "images" / "text_only_saved_bottom.jpg"
        top_path.parent.mkdir(parents=True, exist_ok=True)
        top_path.write_bytes(b"\xff\xd8\xff" + b"\x61" * 128)
        bottom_path.write_bytes(b"\xff\xd8\xff" + b"\x62" * 128)

        parent_snapshot = {"items": [{"headline": "국내 AI 반도체 정책 점검"}]}
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_korea_tech",
                "program_id": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "generated_image_path_watermarked": str(top_path.relative_to(repo)),
                "korea_bottom_shot_path": str(bottom_path.relative_to(repo)),
                "top_image_cid": "keysuri_topshot_korea_parent",
                "bottom_image_cid": "keysuri_bottomshot_korea_parent",
                "owner_email_subject": "[운영자 검토] 기존 제목",
                "owner_email_preheader": "기존 프리헤더",
                "regen_source_pack_snapshot": parent_snapshot,
            },
            email_html="<html><body><p>parent body</p></body></html>",
        )

        live_items = _live_reselection_items(prefix="korea-live")
        mock_build_input.return_value = {
            "program_id": "keysuri_korea_tech",
            "target_date": "2026-06-24",
            "source_pack": {"program_id": "keysuri_korea_tech", "sources": [], "claims": []},
            "top_5_news": {"news_scope": "korea", "section_heading": "국내 테크 TOP 5", "items": live_items},
            "sent_log_read_count": 1,
            "exposure_log_read_count": 1,
        }
        mock_build_prompt.return_value = "PROMPT-BODY"
        text_caller = MagicMock(return_value="RAW-TEXT")
        generated_briefing = _briefing_for_live_items(live_items, program_id=PROGRAM_KOREA)
        mock_parse.return_value = {
            "parse_status": "parsed_valid",
            "generated_briefing": generated_briefing,
        }
        mock_enrich.side_effect = lambda briefing, *_args: briefing
        mock_validate_visible.side_effect = lambda payload, **_kwargs: (payload, {"visible_text_ellipsis_blocked": False})
        mock_fixture.return_value = {
            "selected_subject": "새 제목",
            "preheader": "새 프리헤더",
        }
        mock_subject_fields.return_value = {
            "editorial_subject": "국내 AI 반도체 정책 점검: 6월 24일 국내 테크 브리핑",
            "email_subject": "국내 AI 반도체 정책 점검: 6월 24일 국내 테크 브리핑",
            "owner_email_subject": "[운영자 검토] 국내 AI 반도체 정책 점검: 6월 24일 국내 테크 브리핑",
            "email_preheader": "국내 AI·테크 신호 검수 대기",
            "owner_email_preheader": "국내 AI·테크 신호 검수 대기",
            "subject_top_headline": "국내 AI 반도체 정책 점검",
            "subject_source": "top_signal_1_headline",
            "subject_kst_date": "20260624",
            "subject_kst_label": "6월 24일",
            "subject_program_label": "국내 테크 브리핑",
            "subject_trigger_label": "admin_text_only_reissue",
        }
        mock_render_preview.return_value = "<html><body><p>재생성 본문</p></body></html>"
        mock_email_html.return_value = (
            "<html><body><p>재생성 본문</p>"
            '<img src="cid:keysuri_topshot_korea_parent"/>'
            '<img src="cid:keysuri_bottomshot_korea_parent"/>'
            "</body></html>"
        )
        mock_validate_html.return_value = {}
        send_fn = MagicMock(return_value=True)

        result = run_keysuri_text_only_reissue(
            parent_id,
            text_caller=text_caller,
            send_fn=send_fn,
            reissue_reason_code="제목 수정 요청",
            reissue_reason_note="text only refresh",
        )

        self.assertTrue(result["ok"])
        text_caller.assert_called_once_with("PROMPT-BODY", program_id="keysuri_korea_tech")
        mock_customer_final.assert_not_called()
        send_fn.assert_called_once()
        inline_parts = send_fn.call_args.kwargs["inline_jpeg_parts"]
        self.assertEqual(len(inline_parts), 2)
        self.assertIn(str(top_path.resolve()), inline_parts[0][0])
        self.assertIn(str(bottom_path.resolve()), inline_parts[1][0])
        child = load_run_artifact(child_id) or {}
        self.assertEqual(child.get("regen_type"), "body_only")
        self.assertEqual(child.get("regen_parent_run_id"), parent_id)
        self.assertTrue(child.get("regen_preserved_images"))
        self.assertTrue(child.get("regen_regenerated_text"))
        self.assertFalse(child.get("image_generation_called"))
        self.assertTrue(child.get("text_generation_called"))
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        self.assertEqual(child.get("reissue_reason_code"), "제목 수정 요청")
        self.assertEqual(child.get("generated_image_path"), str(top_path.relative_to(repo)))
        self.assertEqual(child.get("korea_bottom_shot_path"), str(bottom_path.relative_to(repo)))
        child_html = load_run_email_html(child_id) or ""
        self.assertIn("cid:keysuri_topshot_korea_parent", child_html)
        self.assertIn("cid:keysuri_bottomshot_korea_parent", child_html)
        # duplicate_reselect metadata
        self.assertTrue(child.get("duplicate_reselect_called"))
        self.assertTrue(child.get("candidate_pool_reused"))
        self.assertIn("excluded_signal_ids", child)
        self.assertIn("replacement_signal_ids", child)
        # body_only reissue subject must carry the [본문 재발행] prefix exactly once,
        # so Gmail does not thread it against the parent owner-review by subject match.
        owner_subject = str(child.get("owner_email_subject") or "")
        self.assertTrue(owner_subject.startswith("[본문 재발행]"))
        self.assertEqual(owner_subject.count("[본문 재발행]"), 1)
        sent_subject = send_fn.call_args.args[1]
        self.assertEqual(sent_subject, owner_subject)
        parent = load_run_artifact(parent_id) or {}
        self.assertEqual(parent.get("generated_image_path_watermarked"), str(top_path.relative_to(repo)))
        self.assertNotIn("regen_type", parent)

    @patch("keysuri_customer_delivery.send_keysuri_customer_final_email")
    @patch("keysuri_service_full_run.generate_run_id")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.enrich_generated_briefing_content")
    @patch("keysuri_service_full_run.validate_and_repair_keysuri_visible_text_quality")
    @patch("keysuri_service_full_run.build_keysuri_subject_artifact_fields")
    @patch("keysuri_service_full_run.render_keysuri_contract_preview_html")
    @patch("keysuri_service_full_run.build_keysuri_korea_gmail_owner_email_html")
    @patch("keysuri_service_full_run.validate_keysuri_html_visible_text_quality")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_image_path")
    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    def test_text_and_image_reissue_regenerates_text_and_images_owner_only(
        self,
        mock_watermark: MagicMock,
        mock_bottom: MagicMock,
        mock_validate_html: MagicMock,
        mock_email_html: MagicMock,
        mock_render_preview: MagicMock,
        mock_subject_fields: MagicMock,
        mock_validate_visible: MagicMock,
        mock_enrich: MagicMock,
        mock_build_input: MagicMock,
        mock_run_id: MagicMock,
        mock_customer_final: MagicMock,
    ) -> None:
        from keysuri_service_full_run import run_keysuri_text_and_image_reissue

        repo = Path(__file__).resolve().parents[1]
        parent_id = "20260624_183005_keysuri_korea_tech_aabbccdd"
        child_id = "20260624_190003_keysuri_korea_tech_11223344"
        mock_run_id.return_value = child_id
        raw_top = repo / "output" / "images" / "text_and_image_regen_top_raw.jpg"
        raw_top.parent.mkdir(parents=True, exist_ok=True)
        raw_top.write_bytes(b"\xff\xd8\xff" + b"\x71" * 128)
        mock_watermark.side_effect = _mock_keysuri_watermark
        bottom_path = repo / "output" / "images" / "text_and_image_regen_bottom.jpg"
        bottom_path.write_bytes(b"\xff\xd8\xff" + b"\x72" * 128)
        mock_bottom.return_value = (
            bottom_path,
            [],
            {
                "bottom_shot_source": "test_generated",
                "bottom_shot_generation_status": "generated",
                "bottom_shot_image_path": str(bottom_path.relative_to(repo)),
            },
        )
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_korea_tech",
                "program_id": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "selected_items": _reissue_parent_top5_items(),
            },
            email_html="<html><body><p>parent body</p></body></html>",
        )

        # smoke_runner mock: text_and_image fetches fresh sources from scratch
        fresh_source_pack = {"program_id": "keysuri_korea_tech", "sources": [], "claims": []}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as _sp_file:
            json.dump(fresh_source_pack, _sp_file)
            _sp_path = _sp_file.name
        live_items = _live_reselection_items(prefix="korea-live")
        fresh_briefing = _briefing_for_live_items(live_items, program_id=PROGRAM_KOREA)
        smoke_result = LiveSourceSmokeResult(
            ok=True,
            program_id="keysuri_korea_tech",
            source_pack_path=_sp_path,
            html_path="",
            fetched_item_count=7,
            feed_urls_used=[],
            sample_marker_pass=True,
            called_gemini=True,
            parse_status="parsed_valid",
            generated_briefing=fresh_briefing,
        )
        smoke_runner_mock = MagicMock(return_value=smoke_result)

        mock_build_input.return_value = {
            "program_id": "keysuri_korea_tech",
            "target_date": "2026-06-24",
            "source_pack": fresh_source_pack,
            "top_5_news": {"news_scope": "korea", "section_heading": "국내 테크 TOP 5", "items": live_items},
            "sent_log_read_count": 1,
            "exposure_log_read_count": 1,
        }
        mock_enrich.side_effect = lambda briefing, *_args: briefing
        mock_validate_visible.side_effect = lambda payload, **_kwargs: (payload, {"visible_text_ellipsis_blocked": False})
        mock_subject_fields.return_value = {
            "editorial_subject": "배터리 소재와 AI 장비: 6월 24일 국내 테크 브리핑",
            "email_subject": "배터리 소재와 AI 장비: 6월 24일 국내 테크 브리핑",
            "owner_email_subject": "[운영자 검토] 배터리 소재와 AI 장비: 6월 24일 국내 테크 브리핑",
            "email_preheader": "국내 AI·테크 신호 검수 대기",
            "owner_email_preheader": "국내 AI·테크 신호 검수 대기",
            "subject_top_headline": "배터리 소재와 AI 장비",
            "subject_source": "top_signal_1_headline",
            "subject_kst_date": "20260624",
            "subject_kst_label": "6월 24일",
            "subject_program_label": "국내 테크 브리핑",
            "subject_trigger_label": "admin_text_and_image_reissue",
        }
        mock_render_preview.return_value = "<html><body><p>새 본문</p></body></html>"
        mock_email_html.return_value = (
            "<html><body><p>새 본문</p>"
            '<img src="cid:keysuri_topshot_korea_20260624_regen_11223344"/>'
            '<img src="cid:keysuri_bottomshot_korea_20260624_regen_11223344"/>'
            "</body></html>"
        )
        mock_validate_html.return_value = {}
        send_fn = MagicMock(return_value=True)

        image_runner = MagicMock(
            return_value=ServiceImageOutcome(
                called_image_api=True,
                image_generation_status="generated",
                image_source=IMAGE_SOURCE_GENERATED,
                generated_image_path=str(raw_top.relative_to(repo)),
            )
        )

        result = run_keysuri_text_and_image_reissue(
            parent_id,
            smoke_runner=smoke_runner_mock,
            image_canary_runner=image_runner,
            send_fn=send_fn,
            reissue_reason_code="전체 방향 수정 요청",
            reissue_reason_note="regen both",
        )

        self.assertTrue(result["ok"])
        smoke_runner_mock.assert_called_once()  # test 21: smoke_runner called for fresh collection
        image_runner.assert_called_once()
        mock_bottom.assert_called_once()
        mock_customer_final.assert_not_called()  # test 27: customer final blocked
        send_fn.assert_called_once()
        child = load_run_artifact(child_id) or {}
        self.assertEqual(child.get("regen_type"), "body_and_image")
        self.assertEqual(child.get("regen_parent_run_id"), parent_id)
        self.assertTrue(child.get("source_fetch_called"))  # test 22
        self.assertTrue(child.get("candidate_pool_refreshed"))  # test 22
        self.assertTrue(child.get("selected_signals_refreshed"))  # test 23
        self.assertTrue(child.get("regen_regenerated_text"))
        self.assertTrue(child.get("regen_regenerated_images"))
        self.assertTrue(child.get("text_generation_called"))  # test 24
        self.assertTrue(child.get("image_generation_called"))  # test 25
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        self.assertEqual(child.get("reissue_reason_code"), "전체 방향 수정 요청")
        self.assertEqual(child.get("bottom_shot_image_path"), str(bottom_path.relative_to(repo)))
        self.assertEqual(child.get("generated_image_path_raw"), str(raw_top.relative_to(repo)))
        self.assertEqual(child.get("artifact_status"), "emailed")
        # body_and_image reissue subject must carry the [본문·이미지 재발행] prefix
        # exactly once, distinguishing it from the parent owner-review subject.
        owner_subject = str(child.get("owner_email_subject") or "")
        self.assertTrue(owner_subject.startswith("[본문·이미지 재발행]"))
        self.assertEqual(owner_subject.count("[본문·이미지 재발행]"), 1)
        sent_subject = send_fn.call_args.args[1]
        self.assertEqual(sent_subject, owner_subject)
        parent = load_run_artifact(parent_id) or {}
        self.assertNotIn("regen_type", parent)  # test 28: parent artifact not overwritten

    @patch("keysuri_customer_delivery.send_keysuri_customer_final_email")
    @patch("keysuri_service_full_run.generate_run_id")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.enrich_generated_briefing_content")
    @patch("keysuri_service_full_run.validate_and_repair_keysuri_visible_text_quality")
    @patch("keysuri_service_full_run.build_keysuri_subject_artifact_fields")
    @patch("keysuri_service_full_run.render_keysuri_contract_preview_html")
    @patch("keysuri_service_full_run.build_keysuri_korea_gmail_owner_email_html")
    @patch("keysuri_service_full_run.validate_keysuri_html_visible_text_quality")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_image_path")
    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    def test_text_and_image_reissue_recovers_from_parent_snapshot_when_gemini_invalid(
        self,
        mock_watermark: MagicMock,
        mock_bottom: MagicMock,
        mock_validate_html: MagicMock,
        mock_email_html: MagicMock,
        mock_render_preview: MagicMock,
        mock_subject_fields: MagicMock,
        mock_validate_visible: MagicMock,
        mock_enrich: MagicMock,
        mock_build_input: MagicMock,
        mock_run_id: MagicMock,
        mock_customer_final: MagicMock,
    ) -> None:
        """Mirror of the 20260629 production failure: live smoke returns an invalid
        Gemini briefing, but the parent run has a validated snapshot. The reissue
        must complete (new run artifact) from the parent snapshot rather than
        safe-fail, with traceable repair metadata, and must not send to customers."""
        from keysuri_service_full_run import run_keysuri_text_and_image_reissue

        repo = Path(__file__).resolve().parents[1]
        parent_id = "20260629_120000_keysuri_korea_tech_deadbeef"
        child_id = "20260629_193000_keysuri_korea_tech_55667788"
        mock_run_id.return_value = child_id
        raw_top = repo / "output" / "images" / "snapshot_recover_top_raw.jpg"
        raw_top.parent.mkdir(parents=True, exist_ok=True)
        raw_top.write_bytes(b"\xff\xd8\xff" + b"\x73" * 128)
        mock_watermark.side_effect = _mock_keysuri_watermark
        bottom_path = repo / "output" / "images" / "snapshot_recover_bottom.jpg"
        bottom_path.write_bytes(b"\xff\xd8\xff" + b"\x74" * 128)
        mock_bottom.return_value = (
            bottom_path,
            [],
            {
                "bottom_shot_source": "test_generated",
                "bottom_shot_generation_status": "generated",
                "bottom_shot_image_path": str(bottom_path.relative_to(repo)),
            },
        )

        parent_items = _reissue_parent_top5_items()
        parent_snapshot = _generated_briefing_with_top_count(parent_items, program_id=PROGRAM_KOREA)
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_korea_tech",
                "program_id": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "selected_items": parent_items,
                "regen_generated_briefing_snapshot": parent_snapshot,
            },
            email_html="<html><body><p>parent body</p></body></html>",
        )

        fresh_source_pack = {"program_id": "keysuri_korea_tech", "sources": [], "claims": []}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as _sp_file:
            json.dump(fresh_source_pack, _sp_file)
            _sp_path = _sp_file.name
        # Live smoke produced an invalid briefing: only 2 TOP5 items + bad status.
        broken_gemini = _generated_briefing_with_top_count(parent_items[:2], program_id=PROGRAM_KOREA)
        broken_gemini["generated_status"] = "WRONG_STATUS"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as _raw_file:
            _raw_file.write(json.dumps(broken_gemini, ensure_ascii=False))
            _raw_path = _raw_file.name
        smoke_result = LiveSourceSmokeResult(
            ok=True,
            program_id="keysuri_korea_tech",
            source_pack_path=_sp_path,
            html_path="",
            fetched_item_count=5,
            feed_urls_used=[],
            sample_marker_pass=True,
            called_gemini=True,
            parse_status="parsed_invalid",
            generated_briefing=None,
            raw_response_path=_raw_path,
        )
        smoke_runner_mock = MagicMock(return_value=smoke_result)

        live_items = _live_reselection_items(prefix="korea-live")
        mock_build_input.return_value = {
            "program_id": "keysuri_korea_tech",
            "target_date": "2026-06-29",
            "source_pack": fresh_source_pack,
            "top_5_news": {"news_scope": "korea", "section_heading": "국내 테크 TOP 5", "items": live_items},
            "sent_log_read_count": 1,
            "exposure_log_read_count": 1,
        }
        mock_enrich.side_effect = lambda briefing, *_args: briefing
        mock_validate_visible.side_effect = lambda payload, **_kwargs: (payload, {"visible_text_ellipsis_blocked": False})
        mock_subject_fields.return_value = {
            "editorial_subject": "스냅샷 복구: 6월 29일 국내 테크 브리핑",
            "email_subject": "스냅샷 복구: 6월 29일 국내 테크 브리핑",
            "owner_email_subject": "[운영자 검토] 스냅샷 복구: 6월 29일 국내 테크 브리핑",
            "email_preheader": "국내 AI·테크 신호 검수 대기",
            "owner_email_preheader": "국내 AI·테크 신호 검수 대기",
            "subject_top_headline": "스냅샷 복구",
            "subject_source": "top_signal_1_headline",
            "subject_kst_date": "20260629",
            "subject_kst_label": "6월 29일",
            "subject_program_label": "국내 테크 브리핑",
            "subject_trigger_label": "admin_text_and_image_reissue",
        }
        mock_render_preview.return_value = "<html><body><p>복구 본문</p></body></html>"
        mock_email_html.return_value = (
            "<html><body><p>복구 본문</p>"
            '<img src="cid:keysuri_topshot_korea_20260629_regen_55667788"/>'
            '<img src="cid:keysuri_bottomshot_korea_20260629_regen_55667788"/>'
            "</body></html>"
        )
        mock_validate_html.return_value = {}
        send_fn = MagicMock(return_value=True)
        image_runner = MagicMock(
            return_value=ServiceImageOutcome(
                called_image_api=True,
                image_generation_status="generated",
                image_source=IMAGE_SOURCE_GENERATED,
                generated_image_path=str(raw_top.relative_to(repo)),
            )
        )

        result = run_keysuri_text_and_image_reissue(
            parent_id,
            smoke_runner=smoke_runner_mock,
            image_canary_runner=image_runner,
            send_fn=send_fn,
            reissue_reason_code="뉴스 중복 이슈",
            reissue_reason_note="recover from snapshot",
        )

        self.assertTrue(result["ok"])
        mock_customer_final.assert_not_called()  # customer final never sent
        child = load_run_artifact(child_id) or {}
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        self.assertTrue(child.get("reissue_reselection_enabled"))
        self.assertFalse(child.get("reissue_top5_repaired_from_parent"))
        self.assertEqual(child.get("reissue_top5_original_count"), 2)
        self.assertEqual(child.get("reissue_top5_repaired_count"), 5)
        # Final TOP5 comes from the fresh live selection, never the parent snapshot.
        self.assertEqual(child.get("reissue_top5_repair_source"), "reissue_live_selected_items")
        self.assertEqual(child.get("artifact_status"), "emailed")
        snap = child.get("regen_generated_briefing_snapshot") or {}
        child_items = (snap.get("top_5_news") or {}).get("items") or []
        self.assertEqual([it.get("news_id") for it in child_items], [it["news_id"] for it in live_items])
        parent_urls = {it["canonical_url"] for it in parent_items}
        self.assertTrue(all(it.get("canonical_url") not in parent_urls for it in child_items))
        parent = load_run_artifact(parent_id) or {}
        self.assertNotIn("regen_type", parent)  # parent artifact not overwritten

    def test_text_only_reissue_no_parent_snapshot_uses_fresh_live_pool(self) -> None:
        """body_only no longer depends on the parent source-pack snapshot; it
        collects a fresh live pool. With an insufficient fresh pool it returns the
        live-pool safe failure (never the old missing_candidate_pool error, and
        never the parent's duplicate news)."""
        from keysuri_service_full_run import run_keysuri_text_only_reissue

        parent_id = "20260624_200000_keysuri_korea_tech_00000000"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_korea_tech",
                "program_id": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "selected_items": _reissue_parent_top5_items(),
                # deliberately no regen_source_pack_snapshot
            }
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as _sp:
            json.dump({"program_id": "keysuri_korea_tech", "sources": [], "claims": []}, _sp)
            sp_path = _sp.name
        depleted = {"program_id": "keysuri_korea_tech", "top_5_news": {"items": _live_reselection_items()[:2]}}
        with patch("keysuri_service_full_run.build_keysuri_prompt_input", return_value=dict(depleted)):
            result = run_keysuri_text_only_reissue(
                parent_id,
                text_caller=MagicMock(return_value="{}"),
                smoke_runner=lambda **_kw: _live_smoke_result_for_pack(sp_path, program_id=PROGRAM_KOREA),
            )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "reissue_live_candidate_pool_insufficient")

    @patch("keysuri_customer_delivery.send_keysuri_customer_final_email")
    @patch("keysuri_service_full_run.run_keysuri_live_source_smoke")
    @patch("keysuri_service_full_run.generate_run_id")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.build_keysuri_generation_prompt")
    @patch("keysuri_service_full_run.parse_keysuri_generated_response")
    @patch("keysuri_service_full_run.enrich_generated_briefing_content")
    @patch("keysuri_service_full_run.validate_and_repair_keysuri_visible_text_quality")
    @patch("keysuri_service_full_run._build_service_contract_fixture")
    @patch("keysuri_service_full_run.build_keysuri_subject_artifact_fields")
    @patch("keysuri_service_full_run.render_keysuri_contract_preview_html")
    @patch("keysuri_service_full_run.build_keysuri_korea_gmail_owner_email_html")
    @patch("keysuri_service_full_run.validate_keysuri_html_visible_text_quality")
    def test_text_only_reissue_excludes_parent_selected_items(
        self,
        mock_validate_html: MagicMock,
        mock_email_html: MagicMock,
        mock_render_preview: MagicMock,
        mock_subject_fields: MagicMock,
        mock_fixture: MagicMock,
        mock_validate_visible: MagicMock,
        mock_enrich: MagicMock,
        mock_parse: MagicMock,
        mock_build_prompt: MagicMock,
        mock_build_input: MagicMock,
        mock_run_id: MagicMock,
        mock_smoke: MagicMock,
        mock_customer_final: MagicMock,
    ) -> None:
        """body_only feeds the parent's selected_items into the live dedup gate via
        extra_recent_log, so the regenerated TOP5 is fresh and parent-disjoint."""
        from keysuri_service_full_run import run_keysuri_text_only_reissue

        repo = Path(__file__).resolve().parents[1]
        parent_id = "20260624_200100_keysuri_korea_tech_e1e1e1e1"
        child_id = "20260624_200200_keysuri_korea_tech_a2a2a2a2"
        mock_run_id.return_value = child_id

        top_path = repo / "output" / "images" / "exclude_test_top.jpg"
        top_path.parent.mkdir(parents=True, exist_ok=True)
        top_path.write_bytes(b"\xff\xd8\xff" + b"\x91" * 128)

        parent_items = _reissue_parent_top5_items()
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_korea_tech",
                "program_id": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "generated_image_path_watermarked": str(top_path.relative_to(repo)),
                "top_image_cid": "keysuri_topshot_korea_excl",
                "owner_email_subject": "[운영자 검토] 기존",
                "owner_email_preheader": "프리헤더",
                "selected_items": parent_items,
            }
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as _sp:
            json.dump({"program_id": "keysuri_korea_tech", "sources": [], "claims": []}, _sp)
            sp_path = _sp.name
        mock_smoke.return_value = _live_smoke_result_for_pack(sp_path, program_id=PROGRAM_KOREA)

        live_items = _live_reselection_items(prefix="korea-live")
        captured = {}

        def _capture_build_input(pid, sp, extra_recent_log=None):
            captured["extra_recent_log"] = extra_recent_log
            return {
                "program_id": "keysuri_korea_tech",
                "source_pack": sp,
                "top_5_news": {"news_scope": "korea", "section_heading": "국내 테크 TOP 5", "items": live_items},
                "sent_log_read_count": 1,
                "exposure_log_read_count": 1,
            }

        mock_build_input.side_effect = _capture_build_input
        mock_build_prompt.return_value = "PROMPT-EXCL"
        mock_parse.return_value = {
            "parse_status": "parsed_valid",
            "generated_briefing": _briefing_for_live_items(live_items, program_id=PROGRAM_KOREA),
        }
        mock_enrich.side_effect = lambda briefing, *_args: briefing
        mock_validate_visible.side_effect = lambda payload, **_kwargs: (payload, {"visible_text_ellipsis_blocked": False})
        mock_fixture.return_value = {"selected_subject": "로봇 제목", "preheader": "프리헤더"}
        mock_subject_fields.return_value = {
            "editorial_subject": "국내 로봇 산업 성장 가속: 6월 24일 국내 테크 브리핑",
            "email_subject": "국내 로봇 산업 성장 가속: 6월 24일 국내 테크 브리핑",
            "owner_email_subject": "[운영자 검토] 국내 로봇 산업 성장 가속",
            "email_preheader": "국내 AI·테크 신호 검수 대기",
            "owner_email_preheader": "국내 AI·테크 신호 검수 대기",
            "subject_top_headline": "국내 로봇 산업 성장 가속",
            "subject_source": "top_signal_1_headline",
            "subject_kst_date": "20260624",
            "subject_kst_label": "6월 24일",
            "subject_program_label": "국내 테크 브리핑",
            "subject_trigger_label": "admin_text_only_reissue",
        }
        mock_render_preview.return_value = "<html><body><p>재선택 본문</p></body></html>"
        mock_email_html.return_value = "<html><body><p>재선택 본문</p></body></html>"
        mock_validate_html.return_value = {}

        result = run_keysuri_text_only_reissue(
            parent_id,
            text_caller=MagicMock(return_value="RAW-EXCL"),
            send_fn=MagicMock(return_value=True),
        )

        self.assertTrue(result["ok"])
        # Parent selected_items were passed to the live dedup gate as exclusions.
        rows = captured.get("extra_recent_log") or []
        excluded_urls = {str(r.get("canonical_url") or r.get("url")) for r in rows}
        for it in parent_items:
            self.assertIn(it["canonical_url"], excluded_urls)
        # Final selection is the fresh live set, disjoint from the parent.
        child = load_run_artifact(child_id) or {}
        snap = child.get("regen_generated_briefing_snapshot") or {}
        child_items = (snap.get("top_5_news") or {}).get("items") or []
        self.assertEqual(len(child_items), 5)
        parent_urls = {it["canonical_url"] for it in parent_items}
        self.assertTrue(all(it.get("canonical_url") not in parent_urls for it in child_items))
        self.assertEqual(child.get("reissue_top5_repair_source"), "reissue_live_selected_items")


class KeysuriReissueSubjectPrefixTests(unittest.TestCase):
    """Defense-in-depth: distinct subject prefixes per reissue scope so Gmail
    never threads a reissue owner-review against its parent by subject match."""

    def test_body_only_prefix_applied(self) -> None:
        from keysuri_service_full_run import _owner_subject_for_regen

        out = _owner_subject_for_regen(
            {}, "[운영자 검토] 새 헤드라인: 6월 26일 국내 테크 브리핑", "body_only"
        )
        self.assertTrue(out.startswith("[본문 재발행]"))
        self.assertEqual(out.count("[본문 재발행]"), 1)

    def test_body_and_image_prefix_applied(self) -> None:
        from keysuri_service_full_run import _owner_subject_for_regen

        out = _owner_subject_for_regen(
            {}, "[운영자 검토] 새 헤드라인: 6월 26일 글로벌 테크 브리핑", "body_and_image"
        )
        self.assertTrue(out.startswith("[본문·이미지 재발행]"))
        self.assertEqual(out.count("[본문·이미지 재발행]"), 1)

    def test_body_only_prefix_not_duplicated_if_already_present(self) -> None:
        from keysuri_service_full_run import _owner_subject_for_regen

        already_prefixed = "[본문 재발행][운영자 검토] 헤드라인"
        out = _owner_subject_for_regen({}, already_prefixed, "body_only")
        self.assertEqual(out, already_prefixed)
        self.assertEqual(out.count("[본문 재발행]"), 1)

    def test_body_and_image_prefix_not_duplicated_if_already_present(self) -> None:
        from keysuri_service_full_run import _owner_subject_for_regen

        already_prefixed = "[본문·이미지 재발행][운영자 검토] 헤드라인"
        out = _owner_subject_for_regen({}, already_prefixed, "body_and_image")
        self.assertEqual(out, already_prefixed)
        self.assertEqual(out.count("[본문·이미지 재발행]"), 1)

    def test_image_only_policy_unchanged(self) -> None:
        from keysuri_service_full_run import _owner_subject_for_regen

        parent = {"owner_email_subject": "[운영자 검토] 기존 헤드라인"}
        out = _owner_subject_for_regen(parent, "ignored_for_image_only", "image_only")
        self.assertEqual(out, "[이미지 재발행][운영자 검토] 기존 헤드라인")

    def test_image_only_prefix_not_duplicated(self) -> None:
        from keysuri_service_full_run import _owner_subject_for_regen

        parent = {"owner_email_subject": "[이미지 재발행][운영자 검토] 기존 헤드라인"}
        out = _owner_subject_for_regen(parent, "ignored", "image_only")
        self.assertEqual(out, "[이미지 재발행][운영자 검토] 기존 헤드라인")
        self.assertEqual(out.count("[이미지 재발행]"), 1)

    def test_customer_subject_strips_owner_only_reissue_prefixes(self) -> None:
        # Owner-only reissue prefixes must never leak into the customer-final subject.
        from keysuri_email_identity import build_keysuri_customer_subject

        for owner_subject in (
            "[본문 재발행][운영자 검토] 헤드라인: 6월 26일 국내 테크 브리핑",
            "[본문·이미지 재발행][운영자 검토] 헤드라인: 6월 26일 글로벌 테크 브리핑",
            "[이미지 재발행][운영자 검토] 헤드라인: 6월 26일 국내 테크 브리핑",
        ):
            customer_subject = build_keysuri_customer_subject(
                "keysuri_korea_tech",
                meta={"owner_email_subject": owner_subject},
            )
            self.assertNotIn("[본문 재발행]", customer_subject)
            self.assertNotIn("[본문·이미지 재발행]", customer_subject)
            self.assertNotIn("[이미지 재발행]", customer_subject)
            self.assertNotIn("[운영자 검토]", customer_subject)
            self.assertIn("헤드라인", customer_subject)

    def test_customer_subject_unaffected_when_editorial_subject_present(self) -> None:
        # In real runs, meta["email_subject"]/["editorial_subject"] are set from the
        # editorial subject (built before any owner reissue prefix is applied), so
        # the customer path never even reaches the owner_email_subject fallback.
        from keysuri_email_identity import build_keysuri_customer_subject

        customer_subject = build_keysuri_customer_subject(
            "keysuri_korea_tech",
            meta={
                "email_subject": "헤드라인: 6월 26일 국내 테크 브리핑",
                "owner_email_subject": "[본문 재발행][운영자 검토] 헤드라인: 6월 26일 국내 테크 브리핑",
            },
        )
        self.assertEqual(customer_subject, "헤드라인: 6월 26일 국내 테크 브리핑")


class ServiceFullRunContractTests(unittest.TestCase):
    def test_generated_image_source_passes(self) -> None:
        outcome = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path="output/images/x.jpg",
        )
        self.assertTrue(service_image_passes(outcome))

    def test_registry_image_cannot_pass_service_full_run(self) -> None:
        self.assertTrue(is_smoke_only_image_source(IMAGE_SOURCE_REGISTRY))
        self.assertTrue(is_smoke_only_image_source(IMAGE_SOURCE_STATIC))
        outcome = ServiceImageOutcome(
            called_image_api=False,
            image_source=IMAGE_SOURCE_REGISTRY,
            generated_image_path="static/x.jpg",
        )
        self.assertFalse(service_image_passes(outcome))

    def test_called_image_api_false_when_wrapper_not_invoked(self) -> None:
        outcome = invoke_vertex_image_generation(
            prompt="",
            output_path=Path("/tmp/empty.jpg"),
        )
        self.assertFalse(outcome.called_image_api)


class TodayGenieServiceFullRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com",
                "GENIE_OWNER_REVIEW_SEND": "1",
                "EMAIL_TO": "soulampsito@gmail.com",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    def test_service_images_call_image_api_wrapper(self) -> None:
        with patch("today_genie_service_full_run.invoke_vertex_image_generation") as mock_invoke:
            mock_invoke.side_effect = [
                ServiceImageOutcome(
                    called_image_api=True,
                    image_generation_status="generated",
                    image_source=IMAGE_SOURCE_GENERATED,
                    generated_image_path="output/images/t.jpg",
                ),
                ServiceImageOutcome(
                    called_image_api=True,
                    image_generation_status="generated",
                    image_source=IMAGE_SOURCE_GENERATED,
                    generated_image_path="output/images/b.jpg",
                ),
            ]
            bundle = generate_today_genie_service_images(
                _MINIMAL_TODAY_DATA,
                _RUNTIME_INPUT,
                run_id="20260611_150000_today_genie_aabbccdd",
            )
        self.assertEqual(mock_invoke.call_count, 2)
        self.assertTrue(bundle.ok)
        self.assertTrue(bundle.called_image_api)

    def test_static_image_bundle_cannot_pass_service_full_run(self) -> None:
        bundle = generate_today_genie_service_images(
            {"image_prompt_studio": "", "image_prompt_outdoor": ""},
            {},
            run_id="20260611_150000_today_genie_aabbccdd",
        )
        self.assertFalse(bundle.ok)
        self.assertFalse(bundle.called_image_api)

    @patch("today_genie_service_full_run.save_run_artifact")
    @patch("today_genie_service_full_run.run_genie_job")
    def test_service_full_run_persists_generated_image_and_email_html(
        self,
        mock_job: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        mock_job.return_value = _pass_today_orchestration_result()
        with patch(
            "today_genie_service_full_run.generate_today_genie_service_images"
        ) as mock_images:
            mock_images.return_value = type(
                "B",
                (),
                {
                    "ok": True,
                    "called_image_api": True,
                    "top": ServiceImageOutcome(
                        called_image_api=True,
                        image_generation_status="generated",
                        image_source=IMAGE_SOURCE_GENERATED,
                        generated_image_path="output/images/t.jpg",
                    ),
                    "bottom": ServiceImageOutcome(
                        called_image_api=True,
                        image_generation_status="generated",
                        image_source=IMAGE_SOURCE_GENERATED,
                        generated_image_path="output/images/b.jpg",
                    ),
                    "primary_generated_image_path": "output/images/t.jpg",
                },
            )()
            with patch("today_genie_service_full_run._inline_parts_from_bundle") as mock_inline:
                repo = Path(__file__).resolve().parents[1]
                top = repo / "output" / "images" / "t.jpg"
                bot = repo / "output" / "images" / "b.jpg"
                top.parent.mkdir(parents=True, exist_ok=True)
                top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
                bot.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
                mock_inline.return_value = [(str(top), "cid.top", "t.jpg"), (str(bot), "cid.bot", "b.jpg")]
                payload = run_today_genie_service_full_run(send_fn=MagicMock(return_value=True))
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("called_image_api"))
        self.assertEqual(payload.get("image_source"), IMAGE_SOURCE_GENERATED)
        mock_save.assert_called_once()
        email_html = mock_save.call_args.kwargs.get("email_html") or mock_save.call_args.args[1]
        self.assertIn("운영자 검수 화면 열기", email_html)
        self.assertIn(payload["run_id"], email_html)

    @patch("today_genie_service_full_run.save_run_artifact")
    @patch("today_genie_service_full_run.run_genie_job")
    def test_image_generation_failure_prevents_email(
        self,
        mock_job: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        mock_job.return_value = _pass_today_orchestration_result()
        with patch("today_genie_service_full_run.generate_today_genie_service_images") as mock_images:
            mock_images.return_value = type(
                "B",
                (),
                {
                    "ok": False,
                    "called_image_api": True,
                    "top": ServiceImageOutcome(called_image_api=True, image_generation_status="failed"),
                    "bottom": ServiceImageOutcome(called_image_api=True, image_generation_status="failed"),
                    "primary_generated_image_path": None,
                },
            )()
            payload = run_today_genie_service_full_run(send_fn=MagicMock(return_value=True))
        self.assertFalse(payload.get("ok"))
        self.assertFalse(payload.get("email_sent"))
        mock_save.assert_called_once()

    @patch("today_genie_service_full_run.run_genie_job")
    def test_validation_block_prevents_email(self, mock_job: MagicMock) -> None:
        blocked = _pass_today_orchestration_result()
        blocked.response_data = {"validation_result": "block", "workflow_status": "review_required", "data": {}}
        blocked.decision = PublishingDecision(
            send_email=False,
            create_naver_draft=False,
            auto_publish=False,
            require_review=True,
            suppress_external=True,
            send_customer_email=False,
        )
        mock_job.return_value = blocked
        payload = run_today_genie_service_full_run()
        self.assertFalse(payload.get("ok"))
        self.assertFalse(payload.get("email_sent"))

    @patch("today_genie_service_full_run.save_run_artifact")
    @patch("today_genie_service_full_run.run_genie_job")
    def test_cost_estimate_folds_in_image_count_and_reaches_payload_and_meta(
        self,
        mock_job: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        """Text-side cost_estimate from the /generate response (main.py) must
        survive into the service_full_run payload/meta with the image count
        generated in this step folded in — never affecting ok/email_sent."""
        text_cost_estimate = {
            "estimate_only": True,
            "service_family": "today_genie",
            "model": {"text_model": "gemini-2.5-flash", "image_model": None},
            "usage": {
                "prompt_token_count": 4000,
                "candidates_token_count": 900,
                "thoughts_token_count": 0,
                "total_token_count": 4900,
                "generated_image_count": 0,
            },
            "unit_prices": {},
            "components": {},
            "total_cost_usd": None,
            "total_cost_krw": None,
            "pricing_source": "unknown",
            "pricing_note": "estimate only",
        }
        result = _pass_today_orchestration_result()
        result.response_data = {
            "validation_result": "pass",
            "workflow_status": "validated",
            "runtime_input": _RUNTIME_INPUT,
            "data": _MINIMAL_TODAY_DATA,
            "cost_estimate": text_cost_estimate,
        }
        mock_job.return_value = result
        with patch(
            "today_genie_service_full_run.generate_today_genie_service_images"
        ) as mock_images:
            mock_images.return_value = type(
                "B",
                (),
                {
                    "ok": True,
                    "called_image_api": True,
                    "top": ServiceImageOutcome(
                        called_image_api=True,
                        image_generation_status="generated",
                        image_source=IMAGE_SOURCE_GENERATED,
                        generated_image_path="output/images/t.jpg",
                    ),
                    "bottom": ServiceImageOutcome(
                        called_image_api=True,
                        image_generation_status="generated",
                        image_source=IMAGE_SOURCE_GENERATED,
                        generated_image_path="output/images/b.jpg",
                    ),
                    "primary_generated_image_path": "output/images/t.jpg",
                },
            )()
            with patch("today_genie_service_full_run._inline_parts_from_bundle") as mock_inline:
                repo = Path(__file__).resolve().parents[1]
                top = repo / "output" / "images" / "t.jpg"
                bot = repo / "output" / "images" / "b.jpg"
                top.parent.mkdir(parents=True, exist_ok=True)
                top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
                bot.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
                mock_inline.return_value = [(str(top), "cid.top", "t.jpg"), (str(bot), "cid.bot", "b.jpg")]
                payload = run_today_genie_service_full_run(send_fn=MagicMock(return_value=True))

        self.assertTrue(payload.get("ok"))
        cost_estimate = payload.get("cost_estimate")
        self.assertIsNotNone(cost_estimate)
        self.assertEqual(cost_estimate.get("service_family"), "today_genie")
        self.assertEqual(cost_estimate["usage"]["prompt_token_count"], 4000)
        self.assertEqual(cost_estimate["usage"]["generated_image_count"], 2)
        self.assertTrue(payload.get("cost_record_path"))
        self.assertTrue(payload.get("cost_ledger_path"))

        saved_meta = mock_save.call_args.args[0]
        self.assertEqual(saved_meta.get("cost_estimate"), cost_estimate)
        self.assertEqual(saved_meta.get("cost_record_path"), payload.get("cost_record_path"))

    @patch("today_genie_service_full_run.save_run_artifact")
    @patch("today_genie_service_full_run.run_genie_job")
    def test_missing_usage_in_generate_response_does_not_break_run(
        self,
        mock_job: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        """No cost_estimate/usage in the /generate response (e.g. older cached
        response shape) must not break the service_full_run — cost_estimate
        just falls back to unknown/partial, generation still succeeds."""
        result = _pass_today_orchestration_result()
        mock_job.return_value = result
        with patch("today_genie_service_full_run.generate_today_genie_service_images") as mock_images:
            mock_images.return_value = type(
                "B",
                (),
                {
                    "ok": True,
                    "called_image_api": True,
                    "top": ServiceImageOutcome(
                        called_image_api=True,
                        image_generation_status="generated",
                        image_source=IMAGE_SOURCE_GENERATED,
                        generated_image_path="output/images/t.jpg",
                    ),
                    "bottom": ServiceImageOutcome(
                        called_image_api=True,
                        image_generation_status="generated",
                        image_source=IMAGE_SOURCE_GENERATED,
                        generated_image_path="output/images/b.jpg",
                    ),
                    "primary_generated_image_path": "output/images/t.jpg",
                },
            )()
            with patch("today_genie_service_full_run._inline_parts_from_bundle") as mock_inline:
                repo = Path(__file__).resolve().parents[1]
                top = repo / "output" / "images" / "t.jpg"
                bot = repo / "output" / "images" / "b.jpg"
                top.parent.mkdir(parents=True, exist_ok=True)
                top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
                bot.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
                mock_inline.return_value = [(str(top), "cid.top", "t.jpg"), (str(bot), "cid.bot", "b.jpg")]
                payload = run_today_genie_service_full_run(send_fn=MagicMock(return_value=True))
        self.assertTrue(payload.get("ok"))
        cost_estimate = payload.get("cost_estimate")
        self.assertIsNotNone(cost_estimate)
        self.assertEqual(cost_estimate.get("usage", {}).get("generated_image_count"), 2)


class KeysuriServiceFullRunTests(unittest.TestCase):
    def test_smoke_contract_preview_job_not_service_full_run(self) -> None:
        with patch("internal_jobs.run_keysuri_live_source_smoke") as mock_smoke:
            mock_smoke.return_value = LiveSourceSmokeResult(
                ok=True,
                program_id=PROGRAM_GLOBAL,
                source_pack_path="/tmp/p.json",
                html_path="/tmp/h.html",
                fetched_item_count=5,
                feed_urls_used=[],
                sample_marker_pass=True,
                side_effects={"called_image_api": False},
            )
            payload = create_keysuri_owner_review_job(PROGRAM_GLOBAL, dry_run=False, service_full_run=False)
        self.assertFalse(payload.get("service_full_run", False))
        self.assertFalse(payload.get("side_effects", {}).get("called_image_api"))

    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run.send_genie_email")
    @patch("keysuri_service_full_run._render_service_html")
    @patch("keysuri_service_full_run._reload_generated_briefing")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    def test_global_service_full_run_calls_gemini_and_image_api(
        self,
        mock_image: MagicMock,
        mock_reload: MagicMock,
        mock_render: MagicMock,
        mock_send: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_watermark: MagicMock,
    ) -> None:
        from keysuri_service_full_run import run_keysuri_service_full_run

        repo = Path(__file__).resolve().parents[1]
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_service.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_GLOBAL}), encoding="utf-8")
        raw_path = repo / "output" / "keysuri_preview" / "raw_service.txt"
        raw_path.write_text("{}", encoding="utf-8")

        def _smoke(**_kwargs):
            return LiveSourceSmokeResult(
                ok=True,
                program_id=PROGRAM_GLOBAL,
                source_pack_path=str(pack_path),
                html_path=str(repo / "output" / "keysuri_preview" / "h.html"),
                fetched_item_count=5,
                feed_urls_used=["https://x"],
                sample_marker_pass=True,
                called_gemini=True,
                use_gemini=True,
                contract_preview=True,
                raw_response_path=str(raw_path),
                preview_overall_status="PASS_OWNER_REVIEW_READY",
                validation_status="PASS",
                side_effects={"called_gemini": True, "called_image_api": False},
            )

        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path="output/images/keysuri_global_canary.jpg",
        )
        img_file = repo / "output" / "images" / "keysuri_global_canary.jpg"
        img_file.parent.mkdir(parents=True, exist_ok=True)
        img_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
        mock_watermark.side_effect = _mock_keysuri_watermark
        mock_prompt_input.return_value = {"program_id": PROGRAM_GLOBAL, "prompt_status": "ready_for_generation"}
        mock_reload.return_value = {"title": "t", "summary": "s", "top_5_news": []}

        def _render_side_effect(*_args, **_kwargs):
            mode = _kwargs.get("image_mode", "preview")
            if mode == "email":
                return (
                    _minimal_contract_preview_document(),
                    "output/admin_runs/keysuri_service/x.html",
                )
            return (_minimal_contract_preview_document(), "output/admin_runs/keysuri_service/x.html")

        mock_render.side_effect = _render_side_effect
        mock_send.return_value = True

        with patch.dict(os.environ, {"GENIE_OWNER_REVIEW_SEND": "1", "GENIE_ADMIN_PUBLIC_BASE_URL": "https://ex.com"}, clear=False):
            payload = run_keysuri_service_full_run(
                PROGRAM_GLOBAL,
                smoke_runner=_smoke,
                send_fn=mock_send,
            )
        self.assertEqual(payload.get("program_id"), PROGRAM_GLOBAL)
        self.assertTrue(payload.get("called_gemini"))
        self.assertTrue(payload.get("called_image_api"))
        self.assertEqual(payload.get("image_source"), IMAGE_SOURCE_GENERATED)
        self.assertTrue(payload.get("email_sent"))
        mock_save.assert_called_once()
        mock_send.assert_called_once()
        send_kwargs = mock_send.call_args.kwargs
        self.assertIn("inline_jpeg_parts", send_kwargs)
        inline = send_kwargs.get("inline_jpeg_parts") or []
        self.assertTrue(inline)
        self.assertIn("_mirai_on_watermarked", Path(inline[0][0]).name)
        email_html = mock_save.call_args.kwargs.get("email_html") or mock_save.call_args.args[1]
        self.assertIn("운영자 검수 화면 열기", email_html)
        self.assertIn(payload["run_id"], email_html)
        self.assertIn("cid:", email_html)
        saved_meta = mock_save.call_args.args[0]
        self.assertFalse(saved_meta.get("artifact_storage_durable"))
        self.assertIn("/admin/runs/", str(saved_meta.get("owner_review_url") or ""))
        self.assertEqual(saved_meta.get("top_shot_watermark_status"), "applied")
        self.assertEqual(saved_meta.get("generated_image_path_raw"), "output/images/keysuri_global_canary.jpg")
        self.assertIn("_mirai_on_watermarked", str(saved_meta.get("generated_image_path")))

    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    def test_korea_program_id_not_cross_contaminated(
        self,
        mock_image: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_watermark: MagicMock,
    ) -> None:
        from keysuri_service_full_run import run_keysuri_service_full_run

        repo = Path(__file__).resolve().parents[1]
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_korea.json"
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_KOREA}), encoding="utf-8")

        def _smoke(program_id: str, **_kwargs):
            return LiveSourceSmokeResult(
                ok=True,
                program_id=program_id,
                source_pack_path=str(pack_path),
                html_path="/tmp/k.html",
                fetched_item_count=5,
                feed_urls_used=[],
                sample_marker_pass=True,
                called_gemini=True,
                preview_overall_status="PASS_OWNER_REVIEW_READY",
                raw_response_path=str(repo / "output" / "keysuri_preview" / "raw_korea.txt"),
                side_effects={"called_gemini": True},
            )

        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path="output/images/keysuri_korea_canary.jpg",
        )
        img_file = repo / "output" / "images" / "keysuri_korea_canary.jpg"
        img_file.parent.mkdir(parents=True, exist_ok=True)
        img_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
        mock_watermark.side_effect = _mock_keysuri_watermark
        mock_prompt_input.return_value = {"program_id": PROGRAM_KOREA, "prompt_status": "ready_for_generation"}
        with patch("keysuri_service_full_run._reload_generated_briefing", return_value={"title": "k"}):
            with patch("keysuri_service_full_run._render_service_html", return_value=(_minimal_contract_preview_document(), "out/k.html")):
                with patch("keysuri_service_full_run.send_genie_email", return_value=True):
                    with patch.dict(os.environ, {
                        "GENIE_OWNER_REVIEW_SEND": "1",
                        "GENIE_ADMIN_PUBLIC_BASE_URL": "https://ex.com",
                        "KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED": "off",
                    }, clear=False):
                        payload = run_keysuri_service_full_run(PROGRAM_KOREA, smoke_runner=_smoke, send_fn=MagicMock(return_value=True))
        self.assertEqual(payload.get("program_id"), PROGRAM_KOREA)
        self.assertNotEqual(payload.get("program_id"), PROGRAM_GLOBAL)


class KeysuriGlobalServiceFullRunEmailTests(unittest.TestCase):
    """Kee-Suri Global service_full_run owner-review email uses CID (Gmail-safe)."""

    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com",
                "GENIE_OWNER_REVIEW_SEND": "1",
                "GENIE_INTERNAL_JOB_TOKEN": "not-used",
            },
            clear=False,
        )
        self._env.start()
        self._token = "unit-test-internal-token"

    def tearDown(self) -> None:
        self._env.stop()

    def _global_smoke(self, pack_path: Path, raw_path: Path) -> LiveSourceSmokeResult:
        return LiveSourceSmokeResult(
            ok=True,
            program_id=PROGRAM_GLOBAL,
            source_pack_path=str(pack_path),
            html_path=str(pack_path.parent / "h.html"),
            fetched_item_count=5,
            feed_urls_used=["https://example.com/feed"],
            sample_marker_pass=True,
            called_gemini=True,
            use_gemini=True,
            contract_preview=False,
            parse_status="parsed_valid",
            raw_response_path=str(raw_path),
            preview_overall_status="PASS_OWNER_REVIEW_READY",
            validation_status="PASS",
            generated_briefing={"title": "글로벌 브리핑", "summary": "요약", "top_5_news": []},
            side_effects={"called_gemini": True, "called_image_api": False},
        )

    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run.send_genie_email")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_global_email_uses_cid_not_local_paths(
        self,
        mock_run_id: MagicMock,
        mock_image: MagicMock,
        mock_send: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_watermark: MagicMock,
    ) -> None:
        from keysuri_service_full_run import (
            keysuri_global_service_email_cid_src,
            run_keysuri_service_full_run,
        )

        repo = Path(__file__).resolve().parents[1]
        run_id = "20260611_150810_keysuri_global_tech_5cf81e6a"
        mock_run_id.return_value = run_id
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_global_cid.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_GLOBAL}), encoding="utf-8")
        raw_path = repo / "output" / "keysuri_preview" / "raw_global_cid.txt"
        raw_path.write_text("{}", encoding="utf-8")

        image_rel = repo / "output" / "images" / "keysuri_global_service_test.jpg"
        image_rel.parent.mkdir(parents=True, exist_ok=True)
        image_rel.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
        mock_watermark.side_effect = _mock_keysuri_watermark

        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=str(image_rel.relative_to(repo)),
        )
        mock_prompt_input.return_value = {
            "program_id": PROGRAM_GLOBAL,
            "prompt_status": "ready_for_generation",
            "source_pack": {"sources": []},
        }
        mock_send.return_value = True
        fake_trace = {
            "envelope_to": ["tera9003@daum.net", "tomato3593@gmail.com", "tera9003@daum.net"],
            "mime_html_sha256": "abc123",
            "mime_html_bytes_len": 2048,
            "inline_input_hashes": [
                {
                    "path": str(image_rel.resolve()),
                    "cid": "keysuri_topshot_global_20260611",
                    "filename": "keysuri_global_service_test_mirai_on_watermarked.jpg",
                    "sha256": "image-sha",
                }
            ],
        }

        with patch("keysuri_service_full_run.email_sender.last_send_trace", return_value=fake_trace):
            with patch("keysuri_service_full_run.email_sender.last_send_diagnostic", return_value=""):
                payload = run_keysuri_service_full_run(
                    PROGRAM_GLOBAL,
                    trigger_source="manual_service_full_run",
                    smoke_runner=lambda **_kw: self._global_smoke(pack_path, raw_path),
                    send_fn=mock_send,
                )

        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("service_full_run"))
        self.assertEqual(payload.get("program_id"), PROGRAM_GLOBAL)
        self.assertTrue(payload.get("called_image_api"))
        self.assertEqual(payload.get("image_source"), IMAGE_SOURCE_GENERATED)
        self.assertTrue(payload.get("email_sent"))
        self.assertFalse(payload.get("artifact_storage_durable"))
        self.assertIn(run_id, str(payload.get("owner_review_url") or ""))
        self.assertIn("/admin/runs/", str(payload.get("owner_review_url") or ""))
        self.assertNotIn(self._token, str(payload.get("owner_review_url") or ""))

        mock_send.assert_called_once()
        send_kwargs = mock_send.call_args.kwargs
        inline = send_kwargs.get("inline_jpeg_parts") or []
        self.assertEqual(len(inline), 1)
        fs_path, cid_token, _fname = inline[0]
        self.assertTrue(Path(fs_path).is_file())
        self.assertIn("_mirai_on_watermarked", Path(fs_path).name)
        self.assertEqual(cid_token, keysuri_global_service_email_cid_src(run_id).replace("cid:", ""))

        email_html = mock_send.call_args.args[0]
        self.assertIn(keysuri_global_service_email_cid_src(run_id), email_html)
        self.assertNotIn("cid:keysuri_bottomshot_korea_", email_html)
        self.assertNotIn('id="bottom-shot-image"', email_html)
        self.assertNotIn('id="bottom-shot-placeholder"', email_html)
        self.assertNotIn("output/images/", email_html)
        self.assertNotIn("image_canary/", email_html)
        self.assertNotIn("../", email_html)
        self.assertIn("운영자 검수 화면 열기", email_html)
        self.assertIn(f"/admin/runs/{run_id}", email_html)
        self.assertNotIn("GENIE_INTERNAL_JOB_TOKEN", email_html)
        self.assertNotIn(self._token, email_html)
        # Gmail-safe Global owner email renderer
        self.assertIn("키수리 글로벌 테크 브리핑", email_html)

        saved_meta = mock_save.call_args.args[0]
        self.assertEqual(saved_meta.get("owner_email_delivery_status"), "smtp_accepted")
        self.assertTrue(saved_meta.get("owner_email_smtp_attempted"))
        self.assertTrue(saved_meta.get("owner_email_sent_at_kst"))
        self.assertEqual(saved_meta.get("owner_email_recipient_count"), 2)
        self.assertEqual(saved_meta.get("owner_email_recipient_domains"), ["daum.net", "gmail.com"])
        self.assertEqual(saved_meta.get("owner_email_recipients_masked"), ["te***03@daum.net", "to***93@gmail.com"])
        self.assertTrue(str(saved_meta.get("owner_email_subject") or "").startswith("[운영자 검토][수동] "))
        self.assertIn("글로벌 브리핑", str(saved_meta.get("owner_email_subject") or ""))
        self.assertEqual(saved_meta.get("email_subject"), saved_meta.get("editorial_subject"))
        self.assertEqual(saved_meta.get("subject_source"), "generated_title")
        self.assertEqual(saved_meta.get("subject_kst_date"), "20260611")
        self.assertEqual(saved_meta.get("subject_kst_time"), "15:08")
        self.assertEqual(saved_meta.get("subject_trigger_label"), "수동")
        self.assertEqual(saved_meta.get("program_schedule_label"), "12:30")
        self.assertTrue(saved_meta.get("owner_email_preheader"))
        self.assertIn(str(saved_meta.get("owner_email_preheader") or ""), email_html)
        self.assertEqual(saved_meta.get("visible_text_quality_status"), "pass")
        self.assertFalse(saved_meta.get("visible_text_ellipsis_blocked"))
        self.assertEqual(saved_meta.get("owner_email_mime_html_sha256"), "abc123")
        self.assertEqual(saved_meta.get("owner_email_mime_html_bytes_len"), 2048)
        self.assertTrue(saved_meta.get("owner_email_send_trace_available"))
        self.assertEqual(saved_meta.get("owner_email_inline_image_hashes")[0]["sha256"], "image-sha")
        self.assertNotIn("tera9003@daum.net", json.dumps(saved_meta, ensure_ascii=False))
        self.assertNotIn("tomato3593@gmail.com", json.dumps(saved_meta, ensure_ascii=False))
        self.assertIn("글로벌 신호", email_html)
        self.assertIn('role="presentation"', email_html)
        self.assertNotIn("<style", email_html.lower())
        self.assertNotIn("audit-fold", email_html)
        self.assertNotIn("preview-metadata", email_html)
        self.assertNotIn("서비스 full-run", email_html)
        self.assertNotIn("image_source=generated", email_html)
        self.assertEqual(email_html.lower().count("<!doctype html>"), 1)
        self.assertEqual(email_html.lower().count("<html"), 1)
        self.assertEqual(email_html.lower().count("<head>"), 1)

        saved_meta = mock_save.call_args.args[0]
        self.assertTrue(saved_meta.get("service_full_run"))
        self.assertTrue(saved_meta.get("called_image_api"))
        self.assertEqual(saved_meta.get("image_source"), IMAGE_SOURCE_GENERATED)
        self.assertEqual(saved_meta.get("top_shot_watermark_status"), "applied")
        self.assertEqual(saved_meta.get("top_shot_watermark_text"), "MirAI:ON")
        self.assertEqual(saved_meta.get("generated_image_path_raw"), str(image_rel.relative_to(repo)))
        self.assertIn("_mirai_on_watermarked", str(saved_meta.get("generated_image_path")))
        self.assertIn("_mirai_on_watermarked", str(saved_meta.get("generated_image_path_watermarked")))
        self.assertFalse(saved_meta.get("artifact_storage_durable"))

    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run.send_genie_email")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_cost_estimate_attached_to_payload_and_artifact_meta(
        self,
        mock_run_id: MagicMock,
        mock_image: MagicMock,
        mock_send: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_watermark: MagicMock,
    ) -> None:
        """Response payload and saved artifact meta must carry a best-effort
        cost_estimate (usage + optional totals) — never affecting ok/validation."""
        from keysuri_service_full_run import run_keysuri_service_full_run

        repo = Path(__file__).resolve().parents[1]
        run_id = "20260611_150900_keysuri_global_tech_c0517234"
        mock_run_id.return_value = run_id
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_global_cost.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_GLOBAL}), encoding="utf-8")
        raw_path = repo / "output" / "keysuri_preview" / "raw_global_cost.txt"
        raw_path.write_text("{}", encoding="utf-8")

        image_rel = repo / "output" / "images" / "keysuri_global_service_cost_test.jpg"
        image_rel.parent.mkdir(parents=True, exist_ok=True)
        image_rel.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
        mock_watermark.side_effect = _mock_keysuri_watermark
        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=str(image_rel.relative_to(repo)),
        )
        mock_prompt_input.return_value = {
            "program_id": PROGRAM_GLOBAL,
            "prompt_status": "ready_for_generation",
            "source_pack": {"sources": []},
        }
        mock_send.return_value = True

        def _smoke_with_usage(**kwargs):
            sink = kwargs.get("usage_sink")
            if isinstance(sink, dict):
                sink.update(
                    {
                        "model": "gemini-3-flash-preview",
                        "prompt_token_count": 12003,
                        "candidates_token_count": 478,
                        "thoughts_token_count": 11792,
                        "total_token_count": 24273,
                    }
                )
            return LiveSourceSmokeResult(
                ok=True,
                program_id=PROGRAM_GLOBAL,
                source_pack_path=str(pack_path),
                html_path=str(pack_path.parent / "h.html"),
                fetched_item_count=5,
                feed_urls_used=["https://example.com/feed"],
                sample_marker_pass=True,
                called_gemini=True,
                use_gemini=True,
                contract_preview=False,
                parse_status="parsed_valid",
                raw_response_path=str(raw_path),
                preview_overall_status="PASS_OWNER_REVIEW_READY",
                validation_status="PASS",
                generated_briefing={"title": "글로벌 브리핑", "summary": "요약", "top_5_news": []},
                side_effects={"called_gemini": True, "called_image_api": False},
            )

        with patch.dict(
            os.environ,
            {"GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com", "GENIE_OWNER_REVIEW_SEND": "1"},
            clear=False,
        ):
            with patch("keysuri_service_full_run.email_sender.last_send_trace", return_value={}):
                with patch("keysuri_service_full_run.email_sender.last_send_diagnostic", return_value=""):
                    payload = run_keysuri_service_full_run(
                        PROGRAM_GLOBAL,
                        trigger_source="manual_service_full_run",
                        smoke_runner=_smoke_with_usage,
                        send_fn=mock_send,
                    )

        self.assertTrue(payload.get("ok"))
        cost_estimate = payload.get("cost_estimate")
        self.assertIsNotNone(cost_estimate)
        self.assertTrue(cost_estimate.get("estimate_only"))
        self.assertEqual(cost_estimate.get("model"), "gemini-3-flash-preview")
        self.assertEqual(cost_estimate.get("run_id"), run_id)
        self.assertEqual(cost_estimate["usage"]["prompt_token_count"], 12003)
        self.assertEqual(cost_estimate["usage"]["thoughts_token_count"], 11792)
        self.assertTrue(payload.get("cost_record_path"))
        self.assertTrue(payload.get("cost_ledger_path"))

        saved_meta = mock_save.call_args.args[0]
        self.assertEqual(saved_meta.get("cost_estimate"), cost_estimate)
        self.assertEqual(saved_meta.get("cost_record_path"), payload.get("cost_record_path"))

    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_visible_text_unrecoverable_ellipsis_blocks_owner_smtp(
        self,
        mock_run_id: MagicMock,
        mock_image: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
    ) -> None:
        from keysuri_service_full_run import run_keysuri_service_full_run
        from keysuri_visible_text_quality import KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED

        repo = Path(__file__).resolve().parents[1]
        run_id = "20260611_150810_keysuri_global_tech_blocked"
        mock_run_id.return_value = run_id
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_global_block.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_GLOBAL}), encoding="utf-8")
        raw_path = repo / "output" / "keysuri_preview" / "raw_global_block.txt"
        raw_path.write_text("{}", encoding="utf-8")
        image_rel = repo / "output" / "images" / "keysuri_global_service_block.jpg"
        image_rel.parent.mkdir(parents=True, exist_ok=True)
        image_rel.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=str(image_rel.relative_to(repo)),
        )
        mock_prompt_input.return_value = {
            "program_id": PROGRAM_GLOBAL,
            "prompt_status": "ready_for_generation",
            "source_pack": {"sources": []},
        }
        smoke = self._global_smoke(pack_path, raw_path)
        smoke.generated_briefing = {
            "top_5_news": {"items": [{"headline": "확인 불가 (…)"}]},
            "title": "글로벌 브리핑",
        }
        mock_send = MagicMock(return_value=True)

        payload = run_keysuri_service_full_run(
            PROGRAM_GLOBAL,
            trigger_source="manual_service_full_run",
            smoke_runner=lambda **_kw: smoke,
            send_fn=mock_send,
        )

        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED)
        mock_send.assert_not_called()
        saved_meta = mock_save.call_args.args[0]
        self.assertEqual(saved_meta.get("visible_text_quality_status"), "block")
        self.assertTrue(saved_meta.get("visible_text_ellipsis_blocked"))
        self.assertIn(KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED, saved_meta.get("visible_text_quality_issue_codes"))
        self.assertFalse(saved_meta.get("email_sent"))

    @patch("keysuri_service_full_run.validate_global_post_render_visible_quality")
    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_post_render_qa_is_called_on_final_email_html_in_real_send_path(
        self,
        mock_run_id: MagicMock,
        mock_image: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_watermark: MagicMock,
        mock_post_render_qa: MagicMock,
    ) -> None:
        """contract_preview=False real owner-review path must call the post-render QA
        gate with the FINAL Gmail email HTML, before SMTP dispatch."""
        from keysuri_briefing_content_quality import (
            BriefingContentIssue,
            BriefingContentQualityResult,
        )
        from keysuri_service_full_run import (
            KEYSURI_GLOBAL_POST_RENDER_QA_BLOCKED,
            run_keysuri_service_full_run,
        )

        repo = Path(__file__).resolve().parents[1]
        run_id = "20260709_090000_keysuri_global_tech_ab12cd34"
        mock_run_id.return_value = run_id
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_global_qa_wired.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_GLOBAL}), encoding="utf-8")
        raw_path = repo / "output" / "keysuri_preview" / "raw_global_qa_wired.txt"
        raw_path.write_text("{}", encoding="utf-8")
        image_rel = repo / "output" / "images" / "keysuri_global_service_qa_wired.jpg"
        image_rel.parent.mkdir(parents=True, exist_ok=True)
        image_rel.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
        mock_watermark.side_effect = _mock_keysuri_watermark
        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=str(image_rel.relative_to(repo)),
        )
        mock_prompt_input.return_value = {
            "program_id": PROGRAM_GLOBAL,
            "prompt_status": "ready_for_generation",
            "source_pack": {"sources": []},
        }
        smoke = self._global_smoke(pack_path, raw_path)
        # Deliberately thin/empty top_5_news so the ellipsis gate upstream has
        # nothing to trip on — only the post-render QA gate should decide here.
        smoke.generated_briefing = {
            "top_5_news": {"items": []},
            "title": "글로벌 브리핑",
        }
        mock_post_render_qa.return_value = BriefingContentQualityResult(
            ok=False,
            issues=[
                BriefingContentIssue(
                    "global_repeated_common_filler", "test forced block"
                )
            ],
            warnings=[],
        )
        mock_send = MagicMock(return_value=True)

        payload = run_keysuri_service_full_run(
            PROGRAM_GLOBAL,
            trigger_source="manual_service_full_run",
            smoke_runner=lambda **_kw: smoke,
            send_fn=mock_send,
        )

        mock_post_render_qa.assert_called_once()
        called_html = mock_post_render_qa.call_args.args[0]
        self.assertIn("<!DOCTYPE html>", called_html)
        self.assertIn("글로벌 테크 TOP 5", called_html)

        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), KEYSURI_GLOBAL_POST_RENDER_QA_BLOCKED)
        self.assertIn("global_repeated_common_filler", payload.get("issue_codes") or [])
        self.assertFalse(payload.get("email_sent"))
        mock_send.assert_not_called()
        saved_meta = mock_save.call_args.args[0]
        self.assertEqual(saved_meta.get("validation_result"), "block")
        self.assertFalse(saved_meta.get("email_sent"))
        self.assertFalse(saved_meta.get("smtp_attempted"))

    def test_final_gmail_html_with_repeated_filler_blocks_smtp(self) -> None:
        """Two TOP5 items sharing the exact common filler sentence in the FINAL
        Gmail owner-review HTML must be caught by validate_global_post_render_visible_quality
        — the same function wired into the real send path — before SMTP would fire."""
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_global_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality
        from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        fixture = build_global_contract_fixture()
        fixture["top_shot_image_src"] = "cid:keysuri_topshot_global_qa_filler"
        filler = "글로벌 테크는 AI만이 아니라 칩·인프라·로봇·에너지·정책이 함께 움직이는 날입니다."
        for item in fixture["top_5_items"][:2]:
            item["why_now"] = (
                f"공식 발표와 비용 구조 변화가 겹치는 시점입니다. {filler} "
                "후속 가격·API 조건을 확인해야 합니다."
            )
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)
        email_html = build_keysuri_global_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Global Tech",
            admin_url="https://example.com/admin/runs/test_final_filler",
            run_id="test_final_filler",
        )
        result = validate_global_post_render_visible_quality(email_html)
        self.assertFalse(result.ok)
        self.assertIn(
            "global_repeated_common_filler",
            {i.code for i in result.issues},
        )

    def test_registry_image_cannot_pass_global_service_full_run_contract(self) -> None:
        outcome = ServiceImageOutcome(
            called_image_api=False,
            image_source=IMAGE_SOURCE_REGISTRY,
            generated_image_path="output/keysuri_preview/image_canary/x.jpg",
        )
        self.assertFalse(service_image_passes(outcome))


class KeysuriKoreaServiceFullRunBottomEmailTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com",
                "GENIE_OWNER_REVIEW_SEND": "1",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_asset_path")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_korea_owner_email_uses_top_and_bottom_inline_cids(
        self,
        mock_run_id: MagicMock,
        mock_image: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_bottom_asset: MagicMock,
        mock_watermark: MagicMock,
    ) -> None:
        from keysuri_service_full_run import (
            keysuri_korea_bottom_service_email_cid_src,
            keysuri_korea_service_email_cid_src,
            run_keysuri_service_full_run,
        )

        repo = Path(__file__).resolve().parents[1]
        run_id = "20260615_183000_keysuri_korea_tech_5cf81e6a"
        mock_run_id.return_value = run_id
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_korea_bottom_cid.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_KOREA}), encoding="utf-8")
        raw_path = repo / "output" / "keysuri_preview" / "raw_korea_bottom_cid.txt"
        raw_path.write_text("{}", encoding="utf-8")

        top_image = repo / "output" / "images" / "keysuri_korea_service_test.jpg"
        top_image.parent.mkdir(parents=True, exist_ok=True)
        top_image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
        anchor_image = repo / "output" / "images" / "keysuri_korea_bottom_anchor_105936_test.jpg"
        anchor_image.write_bytes(b"\xff\xd8\xff" + b"\x11" * 128)
        mock_bottom_asset.return_value = (anchor_image, [])
        bottom_raw = repo / "output/admin_runs/keysuri_service_assets" / f"{run_id}_korea_bottom_v6.jpg"
        bottom_image = bottom_raw.with_name(f"{bottom_raw.stem}_mirai_on_watermarked.jpg")
        mock_watermark.side_effect = _mock_keysuri_watermark

        def _mock_bottom_generate(**kwargs):
            self.assertEqual(kwargs["primary_reference_path"], anchor_image)
            self.assertIn("image_keysuri_asset_01_main_briefing.png", str(kwargs["secondary_reference_path"]))
            kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["output_path"].write_bytes(b"\xff\xd8\xff" + b"\x12" * 128)
            return kwargs["output_path"]

        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=str(top_image.relative_to(repo)),
        )
        mock_prompt_input.return_value = {
            "program_id": PROGRAM_KOREA,
            "prompt_status": "ready_for_generation",
            "source_pack": {"sources": []},
        }
        mock_send = MagicMock(return_value=True)

        smoke = LiveSourceSmokeResult(
            ok=True,
            program_id=PROGRAM_KOREA,
            source_pack_path=str(pack_path),
            html_path=str(pack_path.parent / "k.html"),
            fetched_item_count=5,
            feed_urls_used=["https://example.com/feed"],
            sample_marker_pass=True,
            called_gemini=True,
            use_gemini=True,
            contract_preview=False,
            parse_status="parsed_valid",
            raw_response_path=str(raw_path),
            preview_overall_status="PASS_OWNER_REVIEW_READY",
            validation_status="PASS",
            generated_briefing={"title": "국내 브리핑", "summary": "요약", "top_5_news": []},
            side_effects={"called_gemini": True, "called_image_api": False},
        )

        with patch.dict(os.environ, {"KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED": "true"}, clear=False):
            payload = run_keysuri_service_full_run(
                PROGRAM_KOREA,
                smoke_runner=lambda **_kw: smoke,
                bottom_generate_fn=_mock_bottom_generate,
                bottom_watermark_fn=_mock_keysuri_watermark,
                send_fn=mock_send,
            )

        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("program_id"), PROGRAM_KOREA)
        self.assertEqual(payload.get("korea_bottom_shot_status"), "available")
        inline = mock_send.call_args.kwargs.get("inline_jpeg_parts") or []
        self.assertEqual(len(inline), 2)
        self.assertEqual(inline[0][1], keysuri_korea_service_email_cid_src(run_id).replace("cid:", ""))
        self.assertEqual(inline[1][1], keysuri_korea_bottom_service_email_cid_src(run_id).replace("cid:", ""))
        self.assertIn("_mirai_on_watermarked", Path(inline[0][0]).name)
        self.assertEqual(Path(inline[1][0]).resolve(), bottom_image.resolve())
        self.assertIn("korea_bottom_v6", Path(inline[1][0]).name)

        email_html = mock_send.call_args.args[0]
        self.assertIn(keysuri_korea_service_email_cid_src(run_id), email_html)
        self.assertIn(keysuri_korea_bottom_service_email_cid_src(run_id), email_html)
        self.assertIn('id="bottom-shot-image"', email_html)
        self.assertNotIn('id="bottom-shot-placeholder"', email_html)
        self.assertLess(email_html.find("원-라인 체크포인트"), email_html.find('id="bottom-shot-image"'))
        self.assertLess(email_html.find('id="bottom-shot-image"'), email_html.find("본 브리핑은 운영책임자의 직접 검수 대기 상태입니다"))

        saved_meta = mock_save.call_args.args[0]
        self.assertEqual(saved_meta.get("customer_delivery_status"), "not_sent")
        self.assertTrue(saved_meta.get("bottom_shot_variation_enabled"))
        self.assertEqual(saved_meta.get("bottom_shot_source"), "generated_v6_multi_ref")
        self.assertTrue(saved_meta.get("bottom_shot_generated"))
        self.assertEqual(saved_meta.get("bottom_anchor_asset_id"), "keysuri_korea_bottom_20260605_105936")
        self.assertEqual(saved_meta.get("bottom_anchor_slot"), 0)
        self.assertEqual(saved_meta.get("secondary_reference_asset_id"), "Asset01")
        self.assertEqual(saved_meta.get("secondary_reference_slot"), 1)
        self.assertEqual(saved_meta.get("bottom_shot_image_path"), str(bottom_image.relative_to(repo)))
        self.assertEqual(saved_meta.get("bottom_shot_watermark_status"), "applied")
        self.assertTrue(saved_meta.get("bottom_shot_wardrobe_family"))
        self.assertTrue(saved_meta.get("bottom_shot_wardrobe_descriptor"))
        self.assertTrue(saved_meta.get("bottom_shot_color_palette"))
        self.assertTrue(saved_meta.get("bottom_shot_silhouette"))
        self.assertTrue(saved_meta.get("bottom_shot_prop"))
        self.assertTrue(saved_meta.get("bottom_shot_scene"))
        self.assertTrue(saved_meta.get("bottom_shot_anti_copy_instruction_applied"))
        self.assertIn("Selected wardrobe:", saved_meta.get("bottom_shot_prompt_preview", ""))
        self.assertIsInstance(saved_meta.get("bottom_shot_prompt_metadata"), dict)
        self.assertEqual(saved_meta.get("korea_bottom_shot_asset_id"), f"keysuri_korea_bottom_generated_{run_id}")
        self.assertEqual(saved_meta.get("korea_bottom_shot_status"), "available")
        self.assertEqual(saved_meta.get("top_shot_watermark_status"), "applied")
        self.assertEqual(saved_meta.get("generated_image_path_raw"), str(top_image.relative_to(repo)))
        self.assertIn("_mirai_on_watermarked", str(saved_meta.get("generated_image_path_watermarked")))

    def test_korea_bottom_variation_defaults_enabled_when_env_unset(self) -> None:
        from keysuri_service_full_run import korea_bottom_variation_enabled

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED", None)
            self.assertTrue(korea_bottom_variation_enabled())

    @patch("keysuri_service_full_run.generate_keysuri_korea_bottom_v6")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_asset_path")
    def test_korea_bottom_generated_success_does_not_use_fixed_fallback(
        self,
        mock_fixed_bottom: MagicMock,
        mock_generate: MagicMock,
    ) -> None:
        from keysuri_bottom_shot_generation import BottomShotGenerationResult
        from keysuri_service_full_run import resolve_korea_bottom_email_image_path

        repo = Path(__file__).resolve().parents[1]
        bottom_image = repo / "output" / "images" / "keysuri_korea_bottom_generated_gate_test.jpg"
        bottom_image.parent.mkdir(parents=True, exist_ok=True)
        bottom_image.write_bytes(b"\xff\xd8\xff" + b"\x22" * 128)
        anchor_image = repo / "output" / "images" / "keysuri_korea_bottom_anchor_gate_test.jpg"
        anchor_image.write_bytes(b"\xff\xd8\xff" + b"\x21" * 128)
        mock_fixed_bottom.return_value = (anchor_image, [])
        mock_generate.return_value = BottomShotGenerationResult(
            ok=True,
            image_path=bottom_image,
            raw_image_path=bottom_image,
            metadata={
                "bottom_shot_source": "generated_v6_multi_ref",
                "bottom_shot_generated": True,
                "bottom_shot_model": "gemini-2.5-flash-image",
                "bottom_shot_weather_key": "clear_cool",
                "bottom_shot_wardrobe_variant": 1,
                "bottom_shot_pose_variant": "pose-b",
                "bottom_anchor_asset_id": "keysuri_korea_bottom_20260605_105936",
                "bottom_anchor_role": "primary_bottom_visual_anchor",
                "bottom_anchor_slot": 0,
                "secondary_reference_asset_id": "Asset01",
                "secondary_reference_role": "secondary_same_person_continuity_reference",
                "secondary_reference_slot": 1,
                "bottom_shot_watermark_status": "applied",
            },
        )

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED", None)
            path, issues, meta = resolve_korea_bottom_email_image_path("20260615_183000_keysuri_korea_tech_gate")

        self.assertEqual(path, bottom_image)
        self.assertEqual(issues, [])
        self.assertTrue(meta.get("bottom_shot_variation_enabled"))
        self.assertEqual(meta.get("bottom_shot_source"), "generated_v6_multi_ref")
        self.assertTrue(meta.get("bottom_shot_generated"))
        self.assertEqual(meta.get("bottom_anchor_slot"), 0)
        self.assertEqual(meta.get("secondary_reference_slot"), 1)
        self.assertEqual(meta.get("bottom_shot_watermark_status"), "applied")
        mock_generate.assert_called_once()
        self.assertEqual(mock_generate.call_args.kwargs.get("primary_reference_path"), anchor_image)
        mock_fixed_bottom.assert_called_once()

    @patch("keysuri_service_full_run.generate_keysuri_korea_bottom_v6")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_asset_path")
    def test_korea_bottom_generation_failure_uses_fixed_105936_fallback(
        self,
        mock_fixed_bottom: MagicMock,
        mock_generate: MagicMock,
    ) -> None:
        from keysuri_bottom_shot_generation import BottomShotGenerationResult
        from keysuri_service_full_run import resolve_korea_bottom_email_image_path

        repo = Path(__file__).resolve().parents[1]
        bottom_image = repo / "output" / "images" / "keysuri_korea_bottom_105936_failure_test.jpg"
        bottom_image.parent.mkdir(parents=True, exist_ok=True)
        bottom_image.write_bytes(b"\xff\xd8\xff" + b"\x33" * 128)
        mock_fixed_bottom.return_value = (bottom_image, [])
        mock_generate.return_value = BottomShotGenerationResult(
            ok=False,
            metadata={"bottom_shot_generation_status": "failed"},
            error_code="bottom_v6_generation_failed",
            error_message="mock failure",
        )

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED", None)
            path, issues, meta = resolve_korea_bottom_email_image_path("20260615_183000_keysuri_korea_tech_gate")

        self.assertEqual(path, bottom_image)
        self.assertEqual(issues, [])
        self.assertTrue(meta.get("bottom_shot_variation_enabled"))
        self.assertEqual(meta.get("bottom_shot_source"), "fixed_105936_fallback")
        self.assertFalse(meta.get("bottom_shot_generated"))
        self.assertIn("bottom_v6_generation_failed", meta.get("bottom_shot_fallback_reason"))
        self.assertEqual(meta.get("bottom_shot_watermark_status"), "applied")
        mock_fixed_bottom.assert_called_once()
        mock_generate.assert_called_once()

    @patch("keysuri_service_full_run.generate_keysuri_korea_bottom_v6")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_asset_path")
    def test_korea_bottom_explicit_off_uses_fallback_without_generation(
        self,
        mock_fixed_bottom: MagicMock,
        mock_generate: MagicMock,
    ) -> None:
        from keysuri_service_full_run import resolve_korea_bottom_email_image_path

        bottom_image = Path(__file__).resolve().parents[1] / "output/images/keysuri_korea_bottom_off.jpg"
        bottom_image.parent.mkdir(parents=True, exist_ok=True)
        bottom_image.write_bytes(b"\xff\xd8\xff" + b"\x44" * 128)
        mock_fixed_bottom.return_value = (bottom_image, [])

        with patch.dict(os.environ, {"KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED": "off"}, clear=False):
            path, issues, meta = resolve_korea_bottom_email_image_path("20260615_183000_keysuri_korea_tech_off")

        self.assertEqual(path, bottom_image)
        self.assertEqual(issues, [])
        self.assertFalse(meta.get("bottom_shot_variation_enabled"))
        self.assertEqual(meta.get("bottom_shot_source"), "fixed_105936_fallback")
        self.assertEqual(meta.get("bottom_shot_fallback_reason"), "variation_explicitly_disabled")
        mock_generate.assert_not_called()

    @patch("keysuri_service_full_run.validate_korea_post_render_visible_quality")
    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_asset_path")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_korea_post_render_qa_blocks_smtp_on_real_send_path(
        self,
        mock_run_id: MagicMock,
        mock_image: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_bottom_asset: MagicMock,
        mock_watermark: MagicMock,
        mock_korea_qa: MagicMock,
    ) -> None:
        """Korea contract_preview=False real owner-review path must call the Korea
        post-render QA gate with the FINAL Gmail email HTML and block SMTP
        (email_sent=False, smtp_attempted=False, issue_codes exposed) on failure."""
        from keysuri_briefing_content_quality import (
            BriefingContentIssue,
            BriefingContentQualityResult,
        )
        from keysuri_service_full_run import (
            KEYSURI_KOREA_POST_RENDER_QA_BLOCKED,
            run_keysuri_service_full_run,
        )

        repo = Path(__file__).resolve().parents[1]
        run_id = "20260709_183000_keysuri_korea_tech_ab12cd35"
        mock_run_id.return_value = run_id
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_korea_qa_wired.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_KOREA}), encoding="utf-8")
        raw_path = repo / "output" / "keysuri_preview" / "raw_korea_qa_wired.txt"
        raw_path.write_text("{}", encoding="utf-8")
        top_image = repo / "output" / "images" / "keysuri_korea_service_qa_wired.jpg"
        top_image.parent.mkdir(parents=True, exist_ok=True)
        top_image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
        anchor_image = repo / "output" / "images" / "keysuri_korea_bottom_anchor_qa_wired.jpg"
        anchor_image.write_bytes(b"\xff\xd8\xff" + b"\x11" * 128)
        mock_bottom_asset.return_value = (anchor_image, [])
        mock_watermark.side_effect = _mock_keysuri_watermark
        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=str(top_image.relative_to(repo)),
        )
        mock_prompt_input.return_value = {
            "program_id": PROGRAM_KOREA,
            "prompt_status": "ready_for_generation",
            "source_pack": {"sources": []},
        }
        mock_korea_qa.return_value = BriefingContentQualityResult(
            ok=False,
            issues=[
                BriefingContentIssue(
                    "korea_signal_distribution_badge_fragment", "test forced block"
                )
            ],
            warnings=[],
        )
        mock_send = MagicMock(return_value=True)

        smoke = LiveSourceSmokeResult(
            ok=True,
            program_id=PROGRAM_KOREA,
            source_pack_path=str(pack_path),
            html_path=str(pack_path.parent / "k.html"),
            fetched_item_count=5,
            feed_urls_used=["https://example.com/feed"],
            sample_marker_pass=True,
            called_gemini=True,
            use_gemini=True,
            contract_preview=False,
            parse_status="parsed_valid",
            raw_response_path=str(raw_path),
            preview_overall_status="PASS_OWNER_REVIEW_READY",
            validation_status="PASS",
            generated_briefing={"title": "국내 브리핑", "summary": "요약", "top_5_news": []},
            side_effects={"called_gemini": True, "called_image_api": False},
        )

        with patch.dict(os.environ, {"KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED": "off"}, clear=False):
            payload = run_keysuri_service_full_run(
                PROGRAM_KOREA,
                smoke_runner=lambda **_kw: smoke,
                send_fn=mock_send,
            )

        mock_korea_qa.assert_called_once()
        called_html = mock_korea_qa.call_args.args[0]
        self.assertIn("<!DOCTYPE html>", called_html)

        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("validation_result"), "block")
        self.assertEqual(payload.get("error"), KEYSURI_KOREA_POST_RENDER_QA_BLOCKED)
        self.assertIn(
            "korea_signal_distribution_badge_fragment", payload.get("issue_codes") or []
        )
        self.assertFalse(payload.get("email_sent"))
        self.assertFalse(payload.get("smtp_attempted"))
        mock_send.assert_not_called()
        saved_meta = mock_save.call_args.args[0]
        self.assertEqual(saved_meta.get("validation_result"), "block")
        self.assertFalse(saved_meta.get("email_sent"))
        self.assertFalse(saved_meta.get("smtp_attempted"))


class KeysuriGlobalOwnerReviewEmailDesignRestorationTests(unittest.TestCase):
    """Global service_full_run owner email must use Gmail-safe inline/table renderer."""

    def test_global_gmail_owner_email_is_safe_and_preserves_hierarchy(self) -> None:
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            IMAGE_MODE_PREVIEW,
            build_keysuri_global_gmail_owner_email_html,
            prepare_contract_preview_fixture,
            render_keysuri_contract_preview_html,
        )
        from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        fixture = build_global_contract_fixture()
        fixture["top_shot_image_src"] = "cid:keysuri_topshot_global_20260611"
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)

        preview_html = render_keysuri_contract_preview_html(
            fixture,
            repo_root=repo,
            image_mode=IMAGE_MODE_PREVIEW,
            auto_prepare=False,
        )
        email_html = build_keysuri_global_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Global Tech",
            admin_url="https://example.com/admin/runs/test_run",
            run_id="test_run",
        )
        lowered = email_html.lower()

        for forbidden in (
            "<style",
            "var(--",
            "display:flex",
            "<details",
            "audit-fold",
            "operation-metadata",
            "validation-result-box",
            "compliance-checklist",
            "운영 정보",
            "contract compliance checklist",
            "output/",
            "image_canary/",
            "../",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden.lower(), lowered)

        self.assertIn("cid:keysuri_topshot_global_", email_html)
        self.assertIn("키수리 글로벌 테크 브리핑", email_html)
        self.assertIn("글로벌 신호", email_html)
        self.assertIn("테크 비서 키수리", email_html)
        self.assertIn("TOP 5", email_html.upper())
        self.assertIn("키수리의 딥-다이브", email_html)
        self.assertIn("원-라인 체크포인트", email_html)
        self.assertIn("다음 48시간 관찰 포인트", email_html)
        self.assertIn("산업 레이어가 어디로 이동하나", email_html)
        self.assertLess(
            email_html.find("키수리의 딥-다이브"),
            email_html.find("원-라인 체크포인트"),
        )
        self.assertLess(
            email_html.find("원-라인 체크포인트"),
            email_html.find("다음 48시간 관찰 포인트"),
        )
        self.assertIn("https://blog.google/technology/ai/", email_html)
        self.assertIn("운영자 검수 화면 열기", email_html)
        self.assertIn("/admin/runs/test_run", email_html)
        self.assertIn('role="presentation"', email_html)
        self.assertNotIn("원문 확인이 필요", email_html)
        self.assertIn(
            "향후 공식 발표를 통해 세부 내용이 보완될 가능성이 있습니다.",
            email_html,
        )

        self.assertIn("premium-briefing theme-global", preview_html)
        self.assertIn('<div class="briefing-shell">', preview_html)
        self.assertIn('id="top5-section"', preview_html)
        self.assertIn("키수리의 딥-다이브", preview_html)
        self.assertIn("원-라인 체크포인트", preview_html)
        self.assertIn("<style", preview_html.lower())

    def test_global_gmail_owner_email_removes_internal_score_disclosure(self) -> None:
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            IMAGE_MODE_PREVIEW,
            build_keysuri_global_gmail_owner_email_html,
            prepare_contract_preview_fixture,
            render_keysuri_contract_preview_html,
        )
        from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        fixture = build_global_contract_fixture()
        fixture["top_shot_image_src"] = "cid:keysuri_topshot_global_20260630"
        for idx, item in enumerate(fixture["top_5_items"], start=1):
            item["primary_category"] = "ai_software_platform"
            if idx == 1:
                item["selection_reason"] = (
                    "이 뉴스는 총점 54점을 기록했으며 AI·소프트웨어·플랫폼 "
                    "카테고리에서 중요한 소식으로 선정되었습니다."
                )
            else:
                item["selection_reason"] = f"총점 {50 + idx}점을 기록했으며 내부 scoring 결과입니다."
            item["selection_rationale"] = item["selection_reason"]

        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)

        preview_html = render_keysuri_contract_preview_html(
            fixture,
            repo_root=repo,
            image_mode=IMAGE_MODE_PREVIEW,
            auto_prepare=False,
        )
        email_html = build_keysuri_global_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Global Tech",
            admin_url="https://example.com/admin/runs/test_sanitized_run",
            run_id="test_sanitized_run",
        )

        self.assertEqual(len(fixture["top_5_items"]), 5)
        self.assertIn("선정 이유", email_html)
        self.assertIn("선정 이유", preview_html)
        for forbidden in (
            "총점",
            "54점",
            "점수",
            "스코어",
            "높은 점수",
            "가장 높은 점수",
            "기록했으며",
        ):
            with self.subTest(rendered="gmail", forbidden=forbidden):
                self.assertNotIn(forbidden, email_html)
            with self.subTest(rendered="preview", forbidden=forbidden):
                self.assertNotIn(forbidden, preview_html)
        for forbidden in ("score", "scoring"):
            with self.subTest(rendered="gmail", forbidden=forbidden):
                self.assertNotIn(forbidden, email_html.lower())
            with self.subTest(rendered="preview", forbidden=forbidden):
                self.assertNotIn(forbidden, preview_html.lower())
        for rendered in (email_html, preview_html):
            self.assertIn("주인님께 먼저 확인하실 만한 신호로 판단되었습니다", rendered)

    def test_korea_renderer_available_but_not_sent_by_global_service_full_run(self) -> None:
        from keysuri_contract_preview_renderer import render_keysuri_contract_preview_html
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        korea_html = render_keysuri_contract_preview_html(
            build_korea_contract_fixture(),
            repo_root=repo,
        )
        self.assertIn("theme-korea", korea_html)
        self.assertIn("키수리 국내 테크 브리핑", korea_html)

    def test_global_gmail_owner_email_no_score_in_body_fields(self) -> None:
        """score/총점/점수/스코어/scoring must be stripped from non-selection_reason body fields."""
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            IMAGE_MODE_PREVIEW,
            build_keysuri_global_gmail_owner_email_html,
            prepare_contract_preview_fixture,
            render_keysuri_contract_preview_html,
        )
        from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        fixture = build_global_contract_fixture()
        fixture["top_shot_image_src"] = "cid:keysuri_topshot_global_20260701"
        for idx, item in enumerate(fixture["top_5_items"], start=1):
            item["primary_category"] = "ai_software_platform"
            item["what_happened"] = (
                f"이 뉴스는 총점 {50 + idx}점을 기록했으며 AI 플랫폼 변화가 확인되었습니다. "
                "해당 기업은 3분기 목표 달성을 발표했습니다."
            )
            item["why_now"] = (
                f"내부 scoring 결과 점수 {60 + idx}에 해당합니다. "
                "시장 영향은 반도체 공급망 전반에 걸쳐 나타납니다."
            )
            item["owner_angle"] = (
                f"스코어 {70 + idx}점 기준으로 선정된 항목입니다. "
                "주인님께서 주목하실 만한 공급망 의사결정 시그널입니다."
            )

        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)
        email_html = build_keysuri_global_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Global Tech",
            admin_url="https://example.com/admin/runs/test_body_fields",
            run_id="test_body_fields",
        )
        preview_html = render_keysuri_contract_preview_html(
            fixture,
            repo_root=repo,
            image_mode=IMAGE_MODE_PREVIEW,
            auto_prepare=False,
        )

        self.assertEqual(len(fixture["top_5_items"]), 5)
        for forbidden in ("총점", "점수", "스코어"):
            with self.subTest(rendered="gmail", forbidden=forbidden):
                self.assertNotIn(forbidden, email_html)
            with self.subTest(rendered="preview", forbidden=forbidden):
                self.assertNotIn(forbidden, preview_html)
        for forbidden in ("score", "scoring"):
            with self.subTest(rendered="gmail", forbidden=forbidden):
                self.assertNotIn(forbidden, email_html.lower())
            with self.subTest(rendered="preview", forbidden=forbidden):
                self.assertNotIn(forbidden, preview_html.lower())
        # Legitimate prose from the same items must survive stripping
        for kept in ("반도체 공급망", "공급망 의사결정 시그널"):
            with self.subTest(kept=kept):
                self.assertIn(kept, email_html)


class KeysuriKoreaOwnerReviewEmailDesignTests(unittest.TestCase):
    """Korea service_full_run owner email must use Gmail-safe inline/table renderer."""

    def test_korea_gmail_owner_email_is_safe_and_preserves_hierarchy(self) -> None:
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_korea_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_service_full_run import keysuri_korea_service_email_cid_src
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        fixture = build_korea_contract_fixture()
        fixture["top_shot_image_src"] = keysuri_korea_service_email_cid_src("20260615_180000_keysuri_korea_tech_test")
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)

        email_html = build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url="https://example.com/admin/runs/test_korea_run",
            run_id="test_korea_run",
        )
        lowered = email_html.lower()

        for forbidden in (
            "<style",
            "var(--",
            "display:flex",
            "<details",
            "audit-fold",
            "operation-metadata",
            "validation-result-box",
            "compliance-checklist",
            "운영 정보",
            "contract compliance checklist",
            "output/",
            "image_canary/",
            "../",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden.lower(), lowered)

        self.assertIn("cid:keysuri_topshot_korea_", email_html)
        self.assertIn("키수리 국내 테크 브리핑", email_html)
        self.assertIn("오늘 국내에서 움직인 것", email_html)
        self.assertIn("국내 테크 TOP", email_html.upper())
        self.assertIn("키수리의 시장 판단", email_html)
        self.assertNotIn("키수리의 딥-다이브", email_html)
        self.assertIn("원-라인 체크포인트", email_html)
        self.assertIn("한국 시장 관찰 포인트", email_html)
        self.assertIn("글로벌·국내 TOP5", email_html)
        self.assertIn('id="bottom-shot-placeholder"', email_html)
        self.assertIn("마무리 및 출처 리스트", email_html)
        self.assertIn("운영자 검수 화면 열기", email_html)
        self.assertIn("/admin/runs/test_korea_run", email_html)
        self.assertIn('role="presentation"', email_html)
        self.assertIn("#14110d", email_html)
        self.assertNotIn("105936", email_html)
        self.assertNotIn("cid:keysuri_bottom", email_html.lower())
        self.assertNotIn("production-ready", email_html.lower())
        self.assertNotIn("production_asset", email_html.lower())
        review_marker = "본 브리핑은 운영책임자의 직접 검수 대기 상태입니다"
        self.assertLess(email_html.find("키수리의 시장 판단"), email_html.find("원-라인 체크포인트"))
        self.assertLess(email_html.find("원-라인 체크포인트"), email_html.find('id="bottom-shot-placeholder"'))
        self.assertLess(email_html.find('id="bottom-shot-placeholder"'), email_html.find(review_marker))
        self.assertLess(email_html.find(review_marker), email_html.find("퇴근 전 메모"))
        self.assertLess(email_html.find("퇴근 전 메모"), email_html.find("마무리 및 출처 리스트"))

    def test_korea_gmail_owner_email_renders_bottom_cid_when_available(self) -> None:
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_korea_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_service_full_run import (
            keysuri_korea_bottom_service_email_cid_src,
            keysuri_korea_service_email_cid_src,
        )
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        run_id = "20260615_180000_keysuri_korea_tech_test"
        fixture = build_korea_contract_fixture()
        fixture["top_shot_image_src"] = keysuri_korea_service_email_cid_src(run_id)
        fixture["bottom_shot_image_src"] = keysuri_korea_bottom_service_email_cid_src(run_id)
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)

        email_html = build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url="https://example.com/admin/runs/test_korea_bottom",
            run_id="test_korea_bottom",
        )
        review_marker = "본 브리핑은 운영책임자의 직접 검수 대기 상태입니다"
        self.assertIn("cid:keysuri_topshot_korea_", email_html)
        self.assertIn("cid:keysuri_bottomshot_korea_", email_html)
        self.assertIn('id="bottom-shot-image"', email_html)
        self.assertNotIn('id="bottom-shot-placeholder"', email_html)
        self.assertLess(email_html.find("원-라인 체크포인트"), email_html.find('id="bottom-shot-image"'))
        self.assertLess(email_html.find('id="bottom-shot-image"'), email_html.find(review_marker))

    def test_korea_gmail_email_rejects_known_broken_endings_and_synthesizes_deep_dive(self) -> None:
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_korea_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_service_full_run import keysuri_korea_service_email_cid_src
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        fixture = build_korea_contract_fixture()
        fixture["top_shot_image_src"] = keysuri_korea_service_email_cid_src("20260615_180000_keysuri_korea_tech_test")
        for idx, item in enumerate(fixture.get("top_5_items") or []):
            if not isinstance(item, dict):
                continue
            if idx == 0:
                item["selection_reason"] = (
                    "이 뉴스는 삼성전자의 국내 스타트업 생태계 지원 의지를 보여주는 중요한 신호입니다. "
                    "특히 AI, 로봇 등 미래 기술 분야 스타트업 발굴은 국내 기술 혁신과 자본 흐름에 직접적인 영향을 미칠 수 있어 국내 스타트업/투"
                )
                item["why_now"] = (
                    "국내 스타트업 생태계에 직접적인 투자 기회를 제공하는 중요한 창구입니"
                )
            if idx == 1:
                item["korean_title"] = "전기공사협회 전북도회, 국토부 장관과 건설산업 활성화 간담회 참석"
                item["selection_reason"] = (
                    "이 뉴스는 국내 건설 및 인프라 산업의 정책 방향과 대기업의 지역 투자 연계 가능성을 보여줍니다. "
                    "특히 새만금 사업과 AI 건설·로봇 혁신센터 설립 논의는 국내 산업 전반에 미칠 파급력이 커 국내 대기업 테크 전략"
                )
            if idx == 2:
                item["korean_title"] = "KH바텍, 휴머노이드 로봇 감속기 공급 협력 논의 중"
                item["selection_reason"] = (
                    "국내 전자부품 기업이 글로벌 휴머노이드 로봇 시장에 핵심 부품을 공급할 가능성은 국내 로봇 산업의 성장 잠재력과 기술력을 보여줍니다. "
                    "이는 글로벌 로봇 트렌드가 국내 기업에 미치는 영향을 분석하는 데 중요하여 글로벌"
                )
            if idx == 3:
                item["why_now"] = (
                    "정부의 자본시장 개편은 시장의 신뢰 회복을 목표로 하지만, 벤처업계는 혁신 기업의 성장을 저해할 수 있다고 보고 있습니다. "
                    "코스닥 시장은 국내 벤처기업의 주요 자금 조달 및 회수 통로이므로, 관련 정책 변화는 국내 스타트업 생태계 전반에 큰 영향을 미 미칩니다."
                )
            item["owner_angle"] = item.get("owner_angle") or "내일 파트너 일정을 점검하시면 됩니다."
        fixture["korea_deep_dive_sections"] = []
        fixture["deep_dive_uncertainty"] = (
            "삼성전자 C랩 아웃사이드 9기 선정 기업들이 실제 어떤 혁신을 이끌어낼지, "
            "그리고 이들이 국내 산업 생태계에 미칠 구체적인 영향은 무엇일까요?"
        )
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)

        email_html = build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url="https://example.com/admin/runs/test_korea_quality",
            run_id="test_korea_quality",
        )
        import re

        for broken in (
            "국내 스타트업/투",
            "국내 대기업 테크 전략",
            "중요하여 글로벌",
            "무엇일까요",
            "영향을 미 미칩니다",
            "창구입니",
            "사업 전략 수립에",
            "중요한 흐름",
            "주인님의 투",
            "작용합",
            "제공합니",
        ):
            self.assertNotRegex(email_html, rf"{re.escape(broken)}(?:\s|<|$)", msg=f"broken ending leaked: {broken}")
        self.assertNotRegex(email_html, r"조명합(?:\s|<|$)")
        self.assertIn("글로벌 AI 인프라", email_html)
        self.assertIn("한국 기업", email_html)
        deep_start = email_html.find("키수리의 시장 판단")
        checkpoint_start = email_html.find("원-라인 체크포인트", deep_start)
        deep_section = email_html[deep_start:checkpoint_start]
        self.assertNotIn("삼성전자, &#x27;C랩 아웃사이드&#x27;", deep_section)
        self.assertNotIn("전기공사협회 전북도회", deep_section)
        self.assertIn('id="bottom-shot-placeholder"', email_html)
        risk_start = email_html.find("위험 요인", deep_start)
        judgment_start = email_html.find("키수리 판단", risk_start)
        risk_blob = email_html[risk_start:judgment_start]
        self.assertNotIn("?", risk_blob)
        self.assertNotRegex(
            email_html[judgment_start : judgment_start + 400],
            r"키수리\s*판단\s*[:：]",
        )

    def test_korea_gmail_owner_email_no_score_disclosure(self) -> None:
        """Korea email must strip score/총점/점수/스코어/scoring from all body fields."""
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_korea_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_service_full_run import keysuri_korea_service_email_cid_src
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        fixture = build_korea_contract_fixture()
        fixture["top_shot_image_src"] = keysuri_korea_service_email_cid_src(
            "20260701_180000_keysuri_korea_tech_test"
        )
        for idx, item in enumerate(fixture["top_5_items"], start=1):
            item["what_happened"] = (
                f"이 뉴스는 총점 {50 + idx}점을 기록했으며 국내 반도체 공급망에 영향을 미칩니다. "
                "관련 정책 발표가 이번 주 예정되어 있습니다."
            )
            item["why_now"] = (
                f"내부 scoring 지표 기준 점수 {60 + idx}에 해당합니다. "
                "국내 기업의 조달 일정이 직접적으로 연결됩니다."
            )
            item["owner_angle"] = (
                f"스코어 {70 + idx}점 기준 최우선 선별 항목입니다. "
                "주인님께서 내일 직접 점검하실 공급망 포인트가 포함됩니다."
            )

        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)
        email_html = build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url="https://example.com/admin/runs/test_korea_fields",
            run_id="test_korea_fields",
        )

        self.assertEqual(len(fixture["top_5_items"]), 5)
        for forbidden in ("총점", "점수", "스코어"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, email_html)
        for forbidden in ("score", "scoring"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, email_html.lower())
        # Legitimate prose sentences that don't contain scores must survive
        for kept in ("관련 정책 발표", "공급망 포인트"):
            with self.subTest(kept=kept):
                self.assertIn(kept, email_html)


class KeysuriKoreaScheduledHoldDiagnosticsTests(unittest.TestCase):
    """A pre-Gemini hold on a scheduled Korea run must (a) not send to customers,
    and (b) leave a full candidate-funnel diagnostic on the artifact so the
    failure is diagnosable straight from the JSON — the missing-diagnostics gap
    behind the 2026-07-01 18:30 KST 500."""

    _FUNNEL = {
        "normalized_candidate_count": 26,
        "korea_scope_candidate_count": 18,
        "relevance_candidate_count": 11,
        "candidate_count_before_dedup": 5,
        "sent_log_read_count": 0,
        "exposure_log_read_count": 5,
        "recent_combined_log_count": 5,
        "dedup_removed_count": 5,
        "dedup_removed_by_sent_log_count": 0,
        "dedup_removed_by_exposure_log_count": 5,
        "candidate_count_after_dedup": 0,
        "final_selected_count": 0,
        "hold_reason": "insufficient_fresh_candidates_after_dedup",
    }

    @patch("keysuri_service_full_run.save_run_artifact")
    def test_scheduled_hold_persists_funnel_and_stays_not_sent(
        self, mock_save: MagicMock
    ) -> None:
        from keysuri_service_full_run import run_keysuri_service_full_run

        repo = Path(__file__).resolve().parents[1]
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_korea_hold.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(
            json.dumps({"sources": [], "program_id": PROGRAM_KOREA}), encoding="utf-8"
        )

        def _smoke(**_kwargs):
            self.assertEqual(_kwargs.get("trigger_source"), "scheduled_service_full_run")
            return LiveSourceSmokeResult(
                ok=False,
                program_id=PROGRAM_KOREA,
                source_pack_path=str(pack_path),
                html_path="",
                fetched_item_count=13,
                feed_urls_used=[],
                sample_marker_pass=False,
                placeholder_gate_pass=False,
                called_gemini=False,
                use_gemini=True,
                candidate_funnel_summary=dict(self._FUNNEL),
                hold_reason="insufficient_fresh_candidates_after_dedup",
                error="prompt_status='hold_review_required' after live source pack",
            )

        payload = run_keysuri_service_full_run(
            PROGRAM_KOREA,
            trigger_source="scheduled_service_full_run",
            smoke_runner=_smoke,
        )

        self.assertFalse(payload.get("email_sent"))
        mock_save.assert_called_once()
        meta = mock_save.call_args.args[0]
        # Customer-facing state stays untouched.
        self.assertEqual(meta.get("customer_delivery_status"), "not_sent")
        self.assertFalse(meta.get("email_sent"))
        self.assertFalse(meta.get("smtp_attempted"))
        # Full funnel is now recoverable from the failure artifact.
        self.assertEqual(meta.get("fetched_item_count"), 13)
        self.assertEqual(meta.get("raw_fetched_count"), 13)
        self.assertEqual(meta.get("candidate_count_before_dedup"), 5)
        self.assertEqual(meta.get("dedup_removed_by_exposure_log_count"), 5)
        self.assertEqual(meta.get("dedup_removed_by_sent_log_count"), 0)
        self.assertEqual(meta.get("candidate_count_after_dedup"), 0)
        self.assertEqual(meta.get("normalized_candidate_count"), 26)
        self.assertEqual(meta.get("korea_scope_candidate_count"), 18)
        self.assertEqual(meta.get("relevance_candidate_count"), 11)
        self.assertEqual(meta.get("hold_reason"), "insufficient_fresh_candidates_after_dedup")
        self.assertIsInstance(meta.get("candidate_funnel_summary"), dict)
        # The saved email body is empty on a hold; no internal marker leaks.
        email_html = mock_save.call_args.kwargs.get("email_html")
        if email_html is None and len(mock_save.call_args.args) > 1:
            email_html = mock_save.call_args.args[1]
        self.assertEqual(email_html, "")

    @patch("keysuri_service_full_run.save_run_artifact")
    def test_gemini_parse_failure_persists_funnel_and_parse_diagnostics(
        self, mock_save: MagicMock
    ) -> None:
        from keysuri_service_full_run import run_keysuri_service_full_run

        def _smoke(**_kwargs):
            return LiveSourceSmokeResult(
                ok=False,
                program_id=PROGRAM_KOREA,
                source_pack_path="/tmp/keysuri-pack.json",
                html_path="",
                fetched_item_count=13,
                feed_urls_used=[],
                sample_marker_pass=False,
                placeholder_gate_pass=False,
                called_gemini=True,
                use_gemini=True,
                parse_status="parsed_invalid",
                raw_response_path="/tmp/keysuri-raw.txt",
                candidate_funnel_summary=dict(self._FUNNEL),
                parse_meta={
                    "deep_dive_key_implications_repair_attempted": True,
                    "deep_dive_key_implications_repair_success": False,
                    "raw_parsed_field_presence_summary": {
                        "deep_dive_present": True,
                        "deep_dive_key_implications_count": 0,
                    },
                },
                parse_diagnostics={
                    "prompt_input_diagnostic_snapshot": {
                        "program_id": PROGRAM_KOREA,
                        "top_5_news_item_count": 5,
                    },
                    "raw_parsed_field_presence_summary": {
                        "deep_dive_present": True,
                        "deep_dive_key_implications_count": 0,
                    },
                    "parse_failure_field": "deep_dive.key_implications",
                    "parse_failure_reason": "deep_dive.key_implications must be a non-empty list",
                    "repair_attempted": True,
                    "repair_success": False,
                },
                error=(
                    "Gemini parse failed (parsed_invalid): "
                    "deep_dive_key_implications_empty: deep_dive.key_implications must be a non-empty list"
                ),
            )

        payload = run_keysuri_service_full_run(
            PROGRAM_KOREA,
            trigger_source="scheduled_service_full_run",
            smoke_runner=_smoke,
        )

        self.assertFalse(payload.get("email_sent"))
        mock_save.assert_called_once()
        meta = mock_save.call_args.args[0]
        self.assertEqual(meta.get("validation_result"), "block")
        self.assertEqual(meta.get("customer_delivery_status"), "not_sent")
        self.assertIsInstance(meta.get("candidate_funnel_summary"), dict)
        self.assertEqual(meta.get("candidate_count_after_dedup"), 0)
        self.assertEqual(meta.get("parse_failure_field"), "deep_dive.key_implications")
        self.assertTrue(meta.get("repair_attempted"))
        self.assertFalse(meta.get("repair_success"))
        self.assertIsInstance(meta.get("prompt_input_diagnostic_snapshot"), dict)
        self.assertIsInstance(meta.get("raw_parsed_field_presence_summary"), dict)
        email_html = mock_save.call_args.kwargs.get("email_html")
        if email_html is None and len(mock_save.call_args.args) > 1:
            email_html = mock_save.call_args.args[1]
        self.assertEqual(email_html, "")

    @patch("keysuri_service_full_run.save_run_artifact")
    def test_hold_without_funnel_records_unavailable_reason(
        self, mock_save: MagicMock
    ) -> None:
        from keysuri_service_full_run import run_keysuri_service_full_run

        repo = Path(__file__).resolve().parents[1]
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_korea_hold2.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(
            json.dumps({"sources": [], "program_id": PROGRAM_KOREA}), encoding="utf-8"
        )

        def _smoke(**_kwargs):
            return LiveSourceSmokeResult(
                ok=False,
                program_id=PROGRAM_KOREA,
                source_pack_path=str(pack_path),
                html_path="",
                fetched_item_count=2,
                feed_urls_used=[],
                sample_marker_pass=False,
                placeholder_gate_pass=False,
                called_gemini=False,
                use_gemini=True,
                error="Insufficient live feed items (2)",
            )

        run_keysuri_service_full_run(
            PROGRAM_KOREA,
            trigger_source="scheduled_service_full_run",
            smoke_runner=_smoke,
        )
        meta = mock_save.call_args.args[0]
        self.assertIsNone(meta.get("candidate_funnel_summary"))
        self.assertEqual(
            meta.get("candidate_funnel_unavailable_reason"),
            "selection_funnel_summary_not_produced_by_smoke_result",
        )
        self.assertEqual(meta.get("fetched_item_count"), 2)


class KeysuriKoreaVisibleInternalMarkerTests(unittest.TestCase):
    """Internal backfill/scope markers must never surface in reader-facing HTML."""

    def test_backfill_and_scope_markers_absent_from_owner_email(self) -> None:
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_korea_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_service_full_run import keysuri_korea_service_email_cid_src
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        fixture = build_korea_contract_fixture()
        fixture["top_shot_image_src"] = keysuri_korea_service_email_cid_src(
            "20260701_183000_keysuri_korea_tech_test"
        )
        # Even if internal audit markers were (wrongly) copied into item fields,
        # the renderer must not surface them. Seed them to prove containment.
        for item in fixture["top_5_items"]:
            item.setdefault("internal_issue_codes", ["keysuri_korea_exposure_dedup_backfill_used"])
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)
        email_html = build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url="https://example.com/admin/runs/test_korea_marker",
            run_id="test_korea_marker",
        )
        for forbidden in (
            "keysuri_korea_exposure_dedup_backfill_used",
            "_repaired_news_scope",
            "총점",
            "점수",
            "스코어",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, email_html)
        for forbidden in ("score", "scoring"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, email_html.lower())


class KeysuriKoreaContractPreviewBottomOrderingTests(unittest.TestCase):
    """Contract preview must be rendered after Bottom decision so it shows actual Bottom."""

    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com",
                "GENIE_OWNER_REVIEW_SEND": "0",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_asset_path")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_korea_contract_preview_shows_bottom_image_not_placeholder(
        self,
        mock_run_id: MagicMock,
        mock_image: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_bottom_asset: MagicMock,
        mock_watermark: MagicMock,
    ) -> None:
        """After bottom resolution is moved before preview build, preview HTML should
        contain bottom image (data-URI) not the placeholder div."""
        from keysuri_service_full_run import run_keysuri_service_full_run

        repo = Path(__file__).resolve().parents[1]
        run_id = "20260619_120000_keysuri_korea_tech_ab120001"
        mock_run_id.return_value = run_id
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_korea_preview_order.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_KOREA}), encoding="utf-8")
        raw_path = repo / "output" / "keysuri_preview" / "raw_korea_preview_order.txt"
        raw_path.write_text("{}", encoding="utf-8")

        top_image = repo / "output" / "images" / "keysuri_korea_preview_order_top.jpg"
        top_image.parent.mkdir(parents=True, exist_ok=True)
        top_image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
        anchor_image = repo / "output" / "images" / "keysuri_korea_preview_order_anchor.jpg"
        anchor_image.write_bytes(b"\xff\xd8\xff" + b"\x11" * 128)
        mock_bottom_asset.return_value = (anchor_image, [])
        bottom_raw = repo / "output/admin_runs/keysuri_service_assets" / f"{run_id}_korea_bottom_v6.jpg"
        bottom_image = bottom_raw.with_name(f"{bottom_raw.stem}_mirai_on_watermarked.jpg")
        mock_watermark.side_effect = _mock_keysuri_watermark

        def _mock_bottom_generate(**kwargs):
            kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["output_path"].write_bytes(b"\xff\xd8\xff" + b"\x22" * 128)
            return kwargs["output_path"]

        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=str(top_image.relative_to(repo)),
        )
        mock_prompt_input.return_value = {
            "program_id": PROGRAM_KOREA,
            "prompt_status": "ready_for_generation",
            "source_pack": {"sources": []},
        }

        smoke = LiveSourceSmokeResult(
            ok=True,
            program_id=PROGRAM_KOREA,
            source_pack_path=str(pack_path),
            html_path=str(pack_path.parent / "ko.html"),
            fetched_item_count=5,
            feed_urls_used=["https://example.com/feed"],
            sample_marker_pass=True,
            called_gemini=True,
            use_gemini=True,
            contract_preview=False,
            parse_status="parsed_valid",
            raw_response_path=str(raw_path),
            preview_overall_status="PASS_OWNER_REVIEW_READY",
            validation_status="PASS",
            generated_briefing={"title": "국내 브리핑", "summary": "요약", "top_5_news": []},
            side_effects={"called_gemini": True, "called_image_api": False},
        )

        with patch.dict(os.environ, {"KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED": "true"}, clear=False):
            payload = run_keysuri_service_full_run(
                PROGRAM_KOREA,
                smoke_runner=lambda **_kw: smoke,
                bottom_generate_fn=_mock_bottom_generate,
                bottom_watermark_fn=_mock_keysuri_watermark,
            )

        self.assertEqual(payload.get("program_id"), PROGRAM_KOREA)
        self.assertEqual(payload.get("korea_bottom_shot_status"), "available")

        # T8: contract preview HTML must NOT contain bottom-shot-placeholder
        html_rel = payload.get("html_path") or ""
        if html_rel:
            preview_html = (repo / html_rel).read_text(encoding="utf-8")
            self.assertNotIn(
                'id="bottom-shot-placeholder"',
                preview_html,
                "preview HTML still shows placeholder — bottom resolution order not fixed",
            )
            # T9: preview HTML contains bottom data-URI image
            self.assertIn('id="bottom-shot-image"', preview_html)

        saved_meta = mock_save.call_args.args[0]
        self.assertIn("top_image_cid", saved_meta)
        self.assertIn("bottom_image_cid", saved_meta)
        self.assertIn("owner_email_image_cids", saved_meta)
        self.assertIn("customer_email_image_cids", saved_meta)
        owner_cids = saved_meta["owner_email_image_cids"]
        customer_cids = saved_meta["customer_email_image_cids"]
        self.assertEqual(len(owner_cids), 2)
        self.assertEqual(owner_cids, customer_cids)


class ServiceFullRunInternalEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._env = patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": _TOKEN}, clear=False)
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    @patch("today_genie_service_full_run.run_today_genie_service_full_run")
    def test_today_endpoint_service_full_run_flag(self, mock_run: MagicMock) -> None:
        mock_run.return_value = {
            "ok": True,
            "service_full_run": True,
            "run_id": "20260611_150000_today_genie_aabbccdd",
            "called_image_api": True,
            "image_source": "generated",
            "email_sent": True,
        }
        resp = self.client.post(
            "/internal/jobs/create-owner-review",
            headers={"X-Genie-Internal-Job-Token": _TOKEN},
            json={"service_full_run": True, "send_owner_email": True},
        )
        self.assertEqual(resp.status_code, 200)
        mock_run.assert_called_once()

    @patch("keysuri_service_full_run.run_keysuri_service_full_run")
    def test_keysuri_endpoint_service_full_run_flag(self, mock_run: MagicMock) -> None:
        mock_run.return_value = {
            "ok": True,
            "service_full_run": True,
            "program_id": PROGRAM_GLOBAL,
            "called_image_api": True,
            "email_sent": True,
        }
        resp = self.client.post(
            "/internal/jobs/create-keysuri-owner-review",
            headers={"X-Genie-Internal-Job-Token": _TOKEN},
            json={
                "program_id": PROGRAM_GLOBAL,
                "service_full_run": True,
                "send_owner_email": True,
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("service_full_run"))


class OwnerReviewExposureLogWriteTriggerTests(unittest.TestCase):
    """Unit coverage for the owner-review exposure log gate helpers added to
    keysuri_service_full_run.py: write-trigger gating on email_sent, and
    reissue same-selection dedup (image_only must never even be offered the
    chance to double-count; body_only/body_and_image only write on a real
    selection change).
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {"GENIE_OWNER_REVIEW_EXPOSURE_LOG_PATH": str(Path(self.tmp.name) / "owner_review_exposure_log.json")},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def _item(self, title: str, url: str) -> dict:
        return {"title": title, "url": url, "source": "Example", "normalized_source": "example"}

    def test_selection_item_key_prefers_canonical_url(self) -> None:
        from keysuri_service_full_run import _selection_item_key

        self.assertEqual(
            _selection_item_key({"canonical_url": "https://x.com/a", "url": "https://x.com/a?utm=1"}),
            "https://x.com/a",
        )

    def test_selection_item_key_falls_back_to_source_and_title(self) -> None:
        from keysuri_service_full_run import _selection_item_key

        self.assertEqual(
            _selection_item_key({"normalized_source": "example", "normalized_title": "Headline"}),
            "example|headline",
        )

    def test_selection_key_set_ignores_non_dict_items(self) -> None:
        from keysuri_service_full_run import _selection_key_set

        self.assertEqual(_selection_key_set([{"canonical_url": "https://x.com/a"}, "not-a-dict", None]), {"https://x.com/a"})

    def test_write_skipped_when_email_not_sent(self) -> None:
        from keysuri_service_full_run import _maybe_write_owner_review_exposure_log
        from owner_review_exposure_log_store import load_owner_review_exposure_log

        meta = {
            "program_id": PROGRAM_GLOBAL,
            "run_id": "r1",
            "selected_items": [self._item("Title", "https://x.com/a")],
            "customer_delivery_status": "sent",
        }
        _maybe_write_owner_review_exposure_log(meta, email_sent=False, exposure_kind="owner_review_email")
        self.assertFalse(meta["exposure_log_updated"])
        self.assertEqual(meta["exposure_log_update_error"], "email_not_sent")
        self.assertEqual(load_owner_review_exposure_log(), [])

    def test_write_succeeds_on_real_owner_review_email(self) -> None:
        from keysuri_service_full_run import _maybe_write_owner_review_exposure_log
        from owner_review_exposure_log_store import load_owner_review_exposure_log

        meta = {
            "program_id": PROGRAM_GLOBAL,
            "run_id": "r1",
            "selected_items": [self._item("Title", "https://x.com/a")],
            "customer_delivery_status": "sent",
        }
        _maybe_write_owner_review_exposure_log(meta, email_sent=True, exposure_kind="owner_review_email")
        self.assertTrue(meta["exposure_log_updated"])
        self.assertEqual(meta["exposure_log_written_count"], 1)
        self.assertIn("exposure_log_path", meta)
    def test_write_skipped_for_various_customer_delivery_statuses(self) -> None:
        from keysuri_service_full_run import _maybe_write_owner_review_exposure_log
        from owner_review_exposure_log_store import load_owner_review_exposure_log

        # Verify all these statuses block the write even if email_sent=True
        blocked_statuses = [None, "", "not_sent", "blocked", "failed", "pending"]
        
        for status in blocked_statuses:
            meta = {
                "program_id": PROGRAM_GLOBAL,
                "run_id": f"r-{status}",
                "selected_items": [self._item("Title", "https://x.com/a")],
            }
            if status is not None:
                meta["customer_delivery_status"] = status
                
            _maybe_write_owner_review_exposure_log(meta, email_sent=True, exposure_kind="owner_review_email")
            self.assertFalse(meta.get("exposure_log_updated"))
            self.assertEqual(meta.get("exposure_log_update_error"), "customer_not_sent_yet")
            self.assertEqual(len(load_owner_review_exposure_log()), 0)

    def test_write_succeeds_for_sent_and_success_customer_delivery_statuses(self) -> None:
        from keysuri_service_full_run import _maybe_write_owner_review_exposure_log
        from owner_review_exposure_log_store import load_owner_review_exposure_log

        # Verify these statuses succeed when email_sent=True
        success_statuses = ["sent", "success"]
        
        for i, status in enumerate(success_statuses):
            meta = {
                "program_id": PROGRAM_GLOBAL,
                "run_id": f"r-{status}",
                "selected_items": [self._item("Title", f"https://x.com/a{i}")],
                "customer_delivery_status": status,
            }
            _maybe_write_owner_review_exposure_log(meta, email_sent=True, exposure_kind="owner_review_email")
            self.assertTrue(meta.get("exposure_log_updated"))
            self.assertEqual(len(load_owner_review_exposure_log()), i + 1)

    def test_missing_selected_items_does_not_crash_and_skips_write(self) -> None:
        from keysuri_service_full_run import _maybe_write_owner_review_exposure_log
        from owner_review_exposure_log_store import load_owner_review_exposure_log

        meta = {"program_id": PROGRAM_GLOBAL, "run_id": "r1", "customer_delivery_status": "sent"}
        _maybe_write_owner_review_exposure_log(meta, email_sent=True, exposure_kind="owner_review_email")
        self.assertFalse(meta["exposure_log_updated"])
        self.assertEqual(meta["exposure_log_update_error"], "selected_items_missing")
        self.assertEqual(load_owner_review_exposure_log(), [])

    def test_reissue_body_only_same_selection_is_skipped(self) -> None:
        from keysuri_service_full_run import _maybe_write_owner_review_exposure_log
        from owner_review_exposure_log_store import load_owner_review_exposure_log

        selected = [self._item("Title", "https://x.com/a")]
        parent = {"selected_items": selected}
        meta = {"program_id": PROGRAM_GLOBAL, "run_id": "r2", "selected_items": selected, "customer_delivery_status": "sent"}
        _maybe_write_owner_review_exposure_log(
            meta, email_sent=True, exposure_kind="owner_review_reissue_body", parent=parent
        )
        self.assertEqual(meta["exposure_log_reissue_compare_status"], "same_selection_skipped")
        self.assertFalse(meta["exposure_log_updated"])
        self.assertIsNone(meta["exposure_log_update_error"])
        self.assertEqual(load_owner_review_exposure_log(), [])

    def test_reissue_body_only_changed_selection_is_written(self) -> None:
        from keysuri_service_full_run import _maybe_write_owner_review_exposure_log
        from owner_review_exposure_log_store import load_owner_review_exposure_log

        parent = {"selected_items": [self._item("Old", "https://x.com/old")]}
        meta = {
            "program_id": PROGRAM_GLOBAL,
            "run_id": "r3",
            "selected_items": [self._item("New", "https://x.com/new")],
            "customer_delivery_status": "sent",
        }
        _maybe_write_owner_review_exposure_log(
            meta, email_sent=True, exposure_kind="owner_review_reissue_body", parent=parent
        )
        self.assertEqual(meta["exposure_log_reissue_compare_status"], "selection_changed_written")
        self.assertTrue(meta["exposure_log_updated"])
        self.assertEqual(len(load_owner_review_exposure_log()), 1)

    def test_reissue_body_and_image_changed_selection_is_written(self) -> None:
        from keysuri_service_full_run import _maybe_write_owner_review_exposure_log
        from owner_review_exposure_log_store import load_owner_review_exposure_log

        parent = {"selected_items": [self._item("Old", "https://x.com/old")]}
        meta = {
            "program_id": PROGRAM_GLOBAL,
            "run_id": "r4",
            "selected_items": [self._item("New", "https://x.com/new")],
            "customer_delivery_status": "sent",
        }
        _maybe_write_owner_review_exposure_log(
            meta, email_sent=True, exposure_kind="owner_review_reissue_body_and_image", parent=parent
        )
        self.assertTrue(meta["exposure_log_updated"])
        self.assertEqual(len(load_owner_review_exposure_log()), 1)

    def test_reissue_missing_parent_selection_fails_safe_without_writing(self) -> None:
        from keysuri_service_full_run import _maybe_write_owner_review_exposure_log
        from owner_review_exposure_log_store import load_owner_review_exposure_log

        meta = {
            "program_id": PROGRAM_GLOBAL,
            "run_id": "r5",
            "selected_items": [self._item("New", "https://x.com/new")],
            "customer_delivery_status": "sent",
        }
        _maybe_write_owner_review_exposure_log(
            meta, email_sent=True, exposure_kind="owner_review_reissue_body", parent=None
        )
        self.assertEqual(meta["exposure_log_reissue_compare_status"], "parent_selection_unavailable")
        self.assertFalse(meta["exposure_log_updated"])
        self.assertEqual(load_owner_review_exposure_log(), [])

    def test_image_only_reissue_never_calls_exposure_log_writer(self) -> None:
        """run_keysuri_image_only_reissue must not reference the exposure-log
        write helpers at all -- image_only reuses the parent body verbatim, so
        any call here would risk double-counting. Source-level guard.
        """
        import inspect

        import keysuri_service_full_run as mod

        source = inspect.getsource(mod.run_keysuri_image_only_reissue)
        self.assertNotIn("_write_owner_review_exposure_log", source)
        self.assertNotIn("_maybe_write_owner_review_exposure_log", source)


if __name__ == "__main__":
    unittest.main()
