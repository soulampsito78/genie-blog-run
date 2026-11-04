"""Unit and integration tests for GENIE editorial release policy.

Verifies:
1. Editorial-only vs mixed numeric/source/unknown/hard cases.
2. Harmless surface pass WITH diagnostics/warnings preserved.
3. Body-time remains blocking while replay edition label is nonblocking.
4. Lexical false positive resolution for operational advice predicates.
5. After 09:00 harmless manual allowed vs default automated draft blocked.
6. Authenticated human review projection and pending editorial-only projection.
7. Hard safety guards (HOLD, duplicate, already sent, unknown delivery outcome) unaffected.
"""
from __future__ import annotations

import copy
from datetime import datetime
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from admin_store import can_approve_customer_send
from admin_view_models import validation_projection
from customer_review_confirmation import (
    HUMAN_OWNER,
    HUMAN_OWNER_WARNING_TEXT,
    today_quality_warning_present,
)
from main import (
    _align_replay_subject_edition_label,
    product_surface_review_fields,
    stabilize_today_genie_validation_fields,
)
from product_surface_contract import (
    CUSTOMER_SURFACE_PASS,
    PRODUCT_REVIEW_REQUIRED,
    ProductSurfaceFinding,
    ProductSurfaceResult,
    evaluate_product_surface,
    prepare_final_customer_copy,
    product_surface_run_fields,
)
from publication_review_policy import (
    ALL_HARMLESS_EDITORIAL_CODES,
    SURFACE_EDITORIAL_ONLY_CODES,
    VALIDATOR_EDITORIAL_ONLY_CODES,
    are_all_editorial_harmless,
    classify_surface_findings,
    classify_validator_issues,
    is_harmless_editorial_code,
)
from tests.synthetic_today_source_binding import bind_synthetic_today_sources
from today_genie_source_provenance import SOURCE_PROVENANCE_ISSUE
from validators import (
    ValidationIssue,
    _detail_has_what_and_why_today,
    _today_genie_result_from_issues,
    _today_replay_copy_issues,
)


class EditorialClassificationPolicyTests(unittest.TestCase):
    def test_validator_editorial_codes_classified_correctly(self):
        for code in (
            "weak_opening",
            "meta_lead_opening",
            "template_title",
            "repetitive_market_generalities",
            "generic_finance_filler",
            "low_summary_density",
            "low_watchpoint_density",
            "low_interpretation_density",
            "low_risk_density",
            "summary_lecture_tail",
            "watchpoint_lecture_tail",
            "risk_lecture_tail",
            "closing_lecture_tail",
            "today_replay_edition_label_warning",
        ):
            self.assertIn(code, VALIDATOR_EDITORIAL_ONLY_CODES)
            self.assertTrue(is_harmless_editorial_code(code))

    def test_surface_editorial_codes_classified_correctly(self):
        for code in (
            "customer_surface_mixed_sentence_end_style",
            "customer_surface_repeated_sentence_skeleton",
            "customer_surface_repeated_canned_bridge",
            "customer_surface_duplicate_filler",
            "global_visible_repeated_low_information_label",
            "today_replay_edition_label_warning",
        ):
            self.assertIn(code, SURFACE_EDITORIAL_ONLY_CODES)
            self.assertTrue(is_harmless_editorial_code(code))

    def test_factual_number_security_unknown_remain_blocking(self):
        for code in (
            "number_table_accuracy_not_verified",
            "unsupported_numeric_claim",
            "missing_decision_line",
            "today_replay_temporal_conflict",
            "top3_item_insufficient_briefing",
            "top3_item_missing_domestic_watch",
            "customer_surface_raw_english_headline",
            "customer_surface_internal_placeholder_leak",
            "internal_or_system_language_leak",
            "top3_watchpoints_missing",
            "unknown_diagnostic_code",
        ):
            self.assertNotIn(code, ALL_HARMLESS_EDITORIAL_CODES)
            self.assertFalse(is_harmless_editorial_code(code))

    def test_validator_result_from_issues_editorial_only_passes_gate(self):
        # Purely editorial findings must pass the validation hard gate
        editorial_issues = [
            ValidationIssue("weak_opening", "도입부 요약 보강 권장", "warning"),
            ValidationIssue("summary_lecture_tail", "설명조 종결 어미", "warning"),
        ]
        self.assertEqual(_today_genie_result_from_issues(editorial_issues), "pass")

    def test_validator_exact_style_codes_pass_with_diagnostics_retained(self):
        style_issues = [
            ValidationIssue("meta_lead_opening", "오프닝 인사말 형태 감지", "warning"),
            ValidationIssue("template_title", "템플릿형 제목 감지", "warning"),
            ValidationIssue("repetitive_market_generalities", "시장 총론 반복 감지", "warning"),
            ValidationIssue("generic_finance_filler", "정형 문구 감지", "warning"),
        ]
        self.assertEqual(_today_genie_result_from_issues(style_issues), "pass")
        blocking, editorial = classify_validator_issues(style_issues)
        self.assertEqual(blocking, [])
        self.assertEqual(
            editorial,
            [
                "meta_lead_opening",
                "template_title",
                "repetitive_market_generalities",
                "generic_finance_filler",
            ],
        )

    def test_validator_result_from_issues_mixed_numeric_draft_only(self):
        # Mixed with factual/numeric unknown must retain draft_only
        mixed_issues = [
            ValidationIssue("weak_opening", "도입부 요약 보강 권장", "warning"),
            ValidationIssue("number_table_accuracy_not_verified", "수치 대조 미확인", "warning"),
        ]
        self.assertEqual(_today_genie_result_from_issues(mixed_issues), "draft_only")

    def test_validator_exact_style_codes_mixed_unsupported_numeric_claim_draft_only(self):
        mixed_issues = [
            ValidationIssue("meta_lead_opening", "오프닝 인사말 형태 감지", "warning"),
            ValidationIssue("template_title", "템플릿형 제목 감지", "warning"),
            ValidationIssue("repetitive_market_generalities", "시장 총론 반복 감지", "warning"),
            ValidationIssue("generic_finance_filler", "정형 문구 감지", "warning"),
            ValidationIssue("unsupported_numeric_claim", "근거 없는 수치 주장", "warning"),
        ]
        self.assertEqual(_today_genie_result_from_issues(mixed_issues), "draft_only")
        blocking, editorial = classify_validator_issues(mixed_issues)
        self.assertEqual(blocking, ["unsupported_numeric_claim"])
        self.assertEqual(
            editorial,
            [
                "meta_lead_opening",
                "template_title",
                "repetitive_market_generalities",
                "generic_finance_filler",
            ],
        )

    def test_validator_result_from_issues_hard_fail_blocks(self):
        # Hard fail codes must always block
        hard_issues = [
            ValidationIssue("weak_opening", "도입부 요약", "warning"),
            ValidationIssue("top3_watchpoints_missing", "핵심 체크포인트 누락", "error"),
        ]
        self.assertEqual(_today_genie_result_from_issues(hard_issues), "block")


class SurfaceContractEditorialPolicyTests(unittest.TestCase):
    def test_harmless_surface_pass_with_warnings_exposed(self):
        # Bind a valid complete synthetic today payload
        base_payload = {
            "key_watchpoints": [
                {"headline": "연준 문서의 발표 조건", "detail": "야간·장전 맥락에서 기업 1 흐름이 대응 축으로 남아 있다."},
                {"headline": "엔비디아 공급 계약의 기준", "detail": "야간·장전 맥락에서 기업 2 흐름이 대응 축으로 남아 있다."},
                {"headline": "운송 노선의 비용 구조", "detail": "야간·장전 맥락에서 기업 3 흐름이 대응 축으로 남아 있다."},
            ]
        }
        payload, source = bind_synthetic_today_sources(base_payload, fixture="release-provenance-counterexamples")
        res = evaluate_product_surface("today_genie", payload, source_input=source)
        # Status must be CUSTOMER_SURFACE_PASS and customer_ready True
        self.assertEqual(res.status, CUSTOMER_SURFACE_PASS)
        self.assertTrue(res.customer_ready)
        # All findings and diagnostics preserved
        self.assertTrue(len(res.findings) > 0)
        self.assertIn("customer_surface_repeated_sentence_skeleton", res.editorial_warning_codes)
        self.assertEqual(res.blocking_issue_codes, ())

        d = res.as_dict()
        self.assertTrue(d["customer_ready"])
        self.assertEqual(d["customer_surface_status"], CUSTOMER_SURFACE_PASS)
        self.assertIn("customer_surface_repeated_sentence_skeleton", d["editorial_warning_codes"])
        self.assertEqual(d["blocking_issue_codes"], [])

        # Material requirement 5: Assert that genuine missing source findings still block
        broken_payload = copy.deepcopy(payload)
        broken_payload["key_watchpoints"][0]["source_url"] = ""
        res_blocked = evaluate_product_surface("today_genie", broken_payload, source_input=source)
        self.assertEqual(res_blocked.status, PRODUCT_REVIEW_REQUIRED)
        self.assertFalse(res_blocked.customer_ready)
        self.assertIn(SOURCE_PROVENANCE_ISSUE, res_blocked.blocking_issue_codes)

    def test_mixed_surface_finding_retains_product_review_required(self):
        findings = (
            ProductSurfaceFinding("customer_surface_repeated_sentence_skeleton", "path1", "반복 어미"),
            ProductSurfaceFinding("customer_surface_raw_english_headline", "path2", "미번역 헤드라인"),
        )
        blocking, editorial = classify_surface_findings(findings)
        self.assertEqual(blocking, ["customer_surface_raw_english_headline"])
        self.assertEqual(editorial, ["customer_surface_repeated_sentence_skeleton"])
        res = ProductSurfaceResult(
            status=PRODUCT_REVIEW_REQUIRED,
            findings=findings,
            blocking_issue_codes=tuple(blocking),
            editorial_warning_codes=tuple(editorial),
        )
        self.assertFalse(res.customer_ready)
        self.assertEqual(res.status, PRODUCT_REVIEW_REQUIRED)


class LexicalFalsePositiveAndReplayTests(unittest.TestCase):
    def test_advice_predicates_count_as_operational_advice(self):
        # Valid length, 2 sentences, interpretation cue and '주목할 필요가 있습니다'
        detail1 = (
            "미국 연준의 기준금리 결정 발표 이후 국채 금리가 급변동세를 보였습니다. "
            "국내 채권시장과 환율 흐름에 미칠 영향을 면밀히 주목할 필요가 있습니다."
        )
        self.assertTrue(_detail_has_what_and_why_today(detail1))

        # '면밀히 살펴야 합니다' with genuine meaning/causal cues (발표, 이슈, 영향을)
        detail2 = (
            "글로벌 빅테크 기업들의 실적 가이던스 발표 이후 시장 변동성 이슈가 발생했습니다. "
            "국내 관련 수혜주들의 수급에 미칠 영향을 면밀히 살펴야 합니다."
        )
        self.assertTrue(_detail_has_what_and_why_today(detail2))

    def test_keyword_padding_without_structure_rejected(self):
        # Short length
        self.assertFalse(_detail_has_what_and_why_today("주목할 필요가 있습니다. 짧은 문장입니다."))
        # Single sentence
        self.assertFalse(_detail_has_what_and_why_today("단일 문장으로 길게 쓴 경우 주목할 필요가 있습니다만 구체적이지 않습니다."))

    def test_replay_edition_label_vs_temporal_body_conflict(self):
        rt = {
            "target_date": "2026-10-28",
            "briefing_generated_at_kst": "2026-10-28T11:00:00+09:00",
            "today_news_selection_frozen": True,
            "today_replay_context": {
                "schema": "today-replay-context-v1",
                "parent_run_id": "20261028_063000_today_genie_12345678",
                "target_date": "2026-10-28",
                "prepared_at_kst": "2026-10-28T11:00:00+09:00",
            },
        }

        # Title containing bare edition label '[10월 28일 장전]' -> warning (nonblocking)
        data_title = {
            "today_replay_context": rt["today_replay_context"],
            "title": "[10월 28일 장전] 반도체 수급",
        }
        issues_title = _today_replay_copy_issues(data_title, rt)
        self.assertEqual(len(issues_title), 1)
        self.assertEqual(issues_title[0].code, "today_replay_edition_label_warning")
        self.assertEqual(issues_title[0].severity, "warning")
        # Harmless edition label warning passes gate!
        self.assertEqual(_today_genie_result_from_issues(issues_title), "pass")

        # Body containing temporal instruction -> error, blocks
        data_body = {
            "today_replay_context": rt["today_replay_context"],
            "summary": "오늘 장전에는 수급을 확인하며 장을 시작해야 합니다.",
        }
        issues_body = _today_replay_copy_issues(data_body, rt)
        self.assertEqual(len(issues_body), 1)
        self.assertEqual(issues_body[0].code, "today_replay_temporal_conflict")
        self.assertEqual(issues_body[0].severity, "error")
        self.assertEqual(_today_genie_result_from_issues(issues_body), "draft_only")

    def test_align_replay_subject_edition_label_anchored_date(self):
        # Current-date anchored bracket prefix matches target_date
        subj = "[10월 28일 장전] 코스피 시황 브리핑"
        aligned = _align_replay_subject_edition_label(subj, target_date="2026-10-28")
        self.assertEqual(aligned, "[10월 28일 재발행] 코스피 시황 브리핑")

        # Anchored colon forms with and without replay prefix
        subj_colon1 = "[재발행] 10월 28일 장전: 가상 지수 흐름"
        aligned_colon1 = _align_replay_subject_edition_label(subj_colon1, target_date="2026-10-28")
        self.assertEqual(aligned_colon1, "[재발행] 10월 28일 재발행: 가상 지수 흐름")

        subj_colon2 = "10월 28일 장전: 가상 지수 흐름"
        aligned_colon2 = _align_replay_subject_edition_label(subj_colon2, target_date="2026-10-28")
        self.assertEqual(aligned_colon2, "10월 28일 재발행: 가상 지수 흐름")

        # Mismatched/historical date preserved
        past_subj = "[10월 27일 장전] 코스피 시황"
        aligned_past = _align_replay_subject_edition_label(past_subj, target_date="2026-10-28")
        self.assertEqual(aligned_past, "[10월 27일 장전] 코스피 시황")


class ManualSendRouteAndAfter09Tests(unittest.TestCase):
    def _sample_valid_meta(self, issue_codes, **overrides):
        meta = {
            "mode": "today_genie",
            "response_status": 200,
            "validation_result": "draft_only",
            "runtime_safety_status": "REVIEW_REQUIRED",
            "customer_surface_status": "CUSTOMER_SURFACE_PASS",
            "target_date": "2026-11-04",
            "run_id": "20261104_103000_today_genie_11223344",
            "created_at": "2026-11-04T10:30:00+09:00",
            "required_count": 3,
            "selected_items": ["item1", "item2", "item3"],
            "issue_codes": list(issue_codes),
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
            "artifact_status": "emailed",
        }
        meta.update(overrides)
        return meta

    def test_harmless_editorial_draft_allowed_after_09_manual(self):
        # 10:30 KST (after 09:00)
        now_1030 = datetime(2026, 11, 4, 10, 30, tzinfo=ZoneInfo("Asia/Seoul"))
        meta = self._sample_valid_meta(["customer_surface_repeated_sentence_skeleton"])

        # 1. Automated default caller (allow_manual_quality_warning=False) remains blocked
        can_approve_auto, reason_auto = can_approve_customer_send(
            meta, has_email_html=True, allow_manual_quality_warning=False, now=now_1030
        )
        self.assertFalse(can_approve_auto)
        self.assertEqual(reason_auto, "review_required_remediation_needed")

        # 2. Authenticated manual route (allow_manual_quality_warning=True) allowed after 09:00 with valid mocks
        with patch("delegated_delivery_safety.publication_guard_required", return_value=False), \
             patch("today_geenee_customer_delivery.customer_delivery_config_ready", return_value=(True, "ok")), \
             patch("admin_store.superseded_child_check", return_value=(False, None, None, "")):
            can_approve_manual, reason_manual = can_approve_customer_send(
                meta, has_email_html=True, allow_manual_quality_warning=True, now=now_1030
            )
            self.assertTrue(can_approve_manual)
            self.assertEqual(reason_manual, "ok")

    def test_legacy_ambiguous_warning_blocks_after_09(self):
        # Legacy ambiguous warning: today_replay_temporal_conflict
        now_1030 = datetime(2026, 11, 4, 10, 30, tzinfo=ZoneInfo("Asia/Seoul"))
        meta = self._sample_valid_meta(
            ["today_replay_temporal_conflict"],
            customer_surface_status=PRODUCT_REVIEW_REQUIRED,
        )
        self.assertFalse(today_quality_warning_present(meta, now=now_1030))

        # But allowed before 09:00
        now_0830 = datetime(2026, 11, 4, 8, 30, tzinfo=ZoneInfo("Asia/Seoul"))
        self.assertTrue(today_quality_warning_present(meta, now=now_0830))

    def test_unknown_or_numeric_issue_never_allowed(self):
        now_0830 = datetime(2026, 11, 4, 8, 30, tzinfo=ZoneInfo("Asia/Seoul"))
        meta = self._sample_valid_meta(["number_table_accuracy_not_verified"])
        self.assertFalse(today_quality_warning_present(meta, now=now_0830))
        with patch("delegated_delivery_safety.publication_guard_required", return_value=False), \
             patch("today_geenee_customer_delivery.customer_delivery_config_ready", return_value=(True, "ok")), \
             patch("admin_store.superseded_child_check", return_value=(False, None, None, "")):
            can_approve, reason = can_approve_customer_send(
                meta, has_email_html=True, allow_manual_quality_warning=True, now=now_0830
            )
            self.assertFalse(can_approve)
            self.assertEqual(reason, "review_required_remediation_needed")


class ProjectionAndCopyTests(unittest.TestCase):
    def test_authenticated_human_approval_projection_positive(self):
        # Real public server audit fields: owner_review_status='approved', approval_source='HUMAN_OWNER',
        # approval_channel='browser_confirm', approval_nonce_used=True
        meta = {
            "owner_review_status": "approved",
            "approval_source": "HUMAN_OWNER",
            "approval_channel": "browser_confirm",
            "approval_nonce_used": True,
            "validation_result": "draft_only",
            "issue_codes": ["customer_surface_repeated_sentence_skeleton"],
        }
        proj = validation_projection(meta)
        self.assertEqual(proj["label"], "운영자 최종 확인 완료")
        self.assertEqual(proj["tone"], "good")
        self.assertIn("운영책임자의 직접 검수", proj["summary"])
        self.assertIn("customer_surface_repeated_sentence_skeleton", proj["issues"])

    def test_authenticated_human_approval_projection_all_three_products(self):
        # Today
        meta_today = {
            "mode": "today_genie",
            "owner_review_status": "approved",
            "approval_source": "HUMAN_OWNER",
            "approval_channel": "browser_confirm",
            "approval_nonce_used": True,
            "validation_result": "draft_only",
            "product_surface_issue_codes": ["customer_surface_repeated_sentence_skeleton"],
        }
        proj_today = validation_projection(meta_today)
        self.assertEqual(proj_today["label"], "운영자 최종 확인 완료")
        self.assertEqual(proj_today["tone"], "good")
        self.assertIn("운영책임자의 직접 검수", proj_today["summary"])
        self.assertIn("customer_surface_repeated_sentence_skeleton", proj_today["issues"])

        # Keysuri Global Tech
        meta_global = {
            "mode": "keysuri_global_tech",
            "safety_verdict": "SAFE",
            "editorial_verdict": "REVIEW",
            "owner_review_status": "approved",
            "approval_source": "HUMAN_OWNER",
            "approval_channel": "browser_confirm",
            "approval_nonce_used": True,
            "product_surface_editorial_warning_codes": ["customer_surface_mixed_sentence_end_style"],
        }
        proj_global = validation_projection(meta_global)
        self.assertEqual(proj_global["label"], "운영자 최종 확인 완료")
        self.assertEqual(proj_global["tone"], "good")
        self.assertIn("운영책임자의 직접 검수", proj_global["summary"])
        self.assertIn("customer_surface_mixed_sentence_end_style", proj_global["issues"])

        # Keysuri Korea Tech
        meta_korea = {
            "mode": "keysuri_korea_tech",
            "safety_verdict": "SAFE",
            "editorial_verdict": "READY",
            "owner_review_status": "approved",
            "approval_source": "HUMAN_OWNER",
            "approval_channel": "browser_confirm",
            "approval_nonce_used": True,
            "product_surface_issue_codes": ["customer_surface_duplicate_filler"],
            "product_surface_editorial_warning_codes": ["customer_surface_repeated_canned_bridge"],
        }
        proj_korea = validation_projection(meta_korea)
        self.assertEqual(proj_korea["label"], "운영자 최종 확인 완료")
        self.assertEqual(proj_korea["tone"], "good")
        self.assertIn("운영책임자의 직접 검수", proj_korea["summary"])
        self.assertIn("customer_surface_duplicate_filler", proj_korea["issues"])
        self.assertIn("customer_surface_repeated_canned_bridge", proj_korea["issues"])

    def test_surface_only_warnings_visible_in_all_code_lists(self):
        meta = {
            "mode": "keysuri_global_tech",
            "owner_review_status": "pending_review",
            "product_surface_issue_codes": ["customer_surface_mixed_sentence_end_style"],
            "product_surface_editorial_warning_codes": ["customer_surface_repeated_sentence_skeleton"],
            "validation_issue_codes": ["weak_opening"],
        }
        proj = validation_projection(meta)
        self.assertIn("customer_surface_mixed_sentence_end_style", proj["issues"])
        self.assertIn("customer_surface_repeated_sentence_skeleton", proj["issues"])
        self.assertIn("weak_opening", proj["issues"])

    def test_keysuri_spoof_negatives_retain_automated_verdicts(self):
        # Fake approvals on Keysuri must NOT trigger human confirmed projection
        meta_global_fake = {
            "mode": "keysuri_global_tech",
            "safety_verdict": "SAFE",
            "editorial_verdict": "REVIEW",
            "owner_review_status": "approved",
            "approval_source": "AI_AGENT",
            "approval_channel": "browser_confirm",
            "approval_nonce_used": True,
        }
        self.assertEqual(validation_projection(meta_global_fake)["label"], "검토 필요")

        meta_korea_ts_only = {
            "mode": "keysuri_korea_tech",
            "safety_verdict": "SAFE",
            "editorial_verdict": "READY",
            "owner_review_status": "pending_review",
            "approved_at": "2026-11-04T09:00:00+09:00",
        }
        self.assertEqual(validation_projection(meta_korea_ts_only)["label"], "검수 준비 완료")

    def test_authenticated_human_approval_projection_negative_fakes(self):
        # Timestamp-only must not trigger completed label
        meta_ts_only = {
            "owner_review_status": "pending_review",
            "approved_at": "2026-11-04T09:00:00+09:00",
            "validation_result": "draft_only",
        }
        self.assertNotEqual(validation_projection(meta_ts_only)["label"], "운영자 최종 확인 완료")

        # Nonce-only without browser confirm
        meta_nonce_only = {
            "owner_review_status": "approved",
            "approval_source": "AI_AGENT",
            "approval_channel": "automated",
            "approval_nonce_used": True,
            "validation_result": "draft_only",
        }
        self.assertNotEqual(validation_projection(meta_nonce_only)["label"], "운영자 최종 확인 완료")

        # Fake flags without nonce used
        meta_fake = {
            "owner_review_status": "approved",
            "approval_source": "HUMAN_OWNER",
            "approval_channel": "browser_confirm",
            "approval_nonce_used": False,
            "validation_result": "draft_only",
        }
        self.assertNotEqual(validation_projection(meta_fake)["label"], "운영자 최종 확인 완료")

    def test_pending_editorial_only_warning_projection_no_unsupported_factual_pass(self):
        meta = {
            "owner_review_status": "pending_review",
            "validation_result": "pass",
            "issue_codes": ["weak_opening", "closing_lecture_tail"],
        }
        proj = validation_projection(meta)
        self.assertEqual(proj["label"], "편집 참고사항")
        self.assertEqual(proj["tone"], "warn")
        self.assertIn("재발행은 선택 사항", proj["summary"])
        self.assertIn("편집 참고사항이 보존", proj["summary"])

        # Material requirement 9: prove NO unsupported factual PASS wording
        for check in proj["checks"]:
            self.assertNotIn("사실성 검수 통과", check["label"])
            self.assertNotIn("필수 구성 및 사실성", check["label"])
        self.assertNotIn("사실성 검수를 통과", proj["summary"])

    def test_human_owner_warning_text_truthful(self):
        self.assertIn("운영책임자의 직접 검수", HUMAN_OWNER_WARNING_TEXT)
        self.assertIn("최종 발송 승인", HUMAN_OWNER_WARNING_TEXT)


class HardSafetyGuardsUnaffectedTests(unittest.TestCase):
    def test_hold_blocks_approval(self):
        meta = {
            "mode": "today_genie",
            "owner_review_status": "held",
            "customer_delivery_status": "not_sent",
            "validation_result": "pass",
        }
        can_approve, reason = can_approve_customer_send(
            meta, has_email_html=True, allow_manual_quality_warning=True
        )
        self.assertFalse(can_approve)
        self.assertEqual(reason, "review_held")

    def test_already_sent_blocks_approval(self):
        # Complete accepted delivery evidence
        meta = {
            "mode": "today_genie",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "ACCEPTED_ALL",
            "customer_recipient_count": 1,
            "smtp_accepted_recipient_count": 1,
            "smtp_refused_recipient_count": 0,
            "customer_email_sent_at_kst": "2026-11-04T08:00:00+09:00",
            "validation_result": "pass",
        }
        can_approve, reason = can_approve_customer_send(
            meta, has_email_html=True, allow_manual_quality_warning=True
        )
        self.assertFalse(can_approve)
        self.assertEqual(reason, "customer_already_sent")

    def test_incomplete_delivery_evidence_blocks_as_outcome_unknown(self):
        # Incomplete metadata triggers outcome unknown guard
        meta_incomplete = {
            "mode": "today_genie",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "ACCEPTED_ALL",
            "validation_result": "pass",
        }
        can_approve, reason = can_approve_customer_send(
            meta_incomplete, has_email_html=True, allow_manual_quality_warning=True
        )
        self.assertFalse(can_approve)
        self.assertEqual(reason, "delivery_outcome_unknown")

    def test_delivery_outcome_unknown_blocks_approval(self):
        meta = {
            "mode": "today_genie",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "OUTCOME_UNKNOWN",
            "validation_result": "pass",
        }
        can_approve, reason = can_approve_customer_send(
            meta, has_email_html=True, allow_manual_quality_warning=True
        )
        self.assertFalse(can_approve)
        self.assertEqual(reason, "delivery_outcome_unknown")


if __name__ == "__main__":
    unittest.main()
