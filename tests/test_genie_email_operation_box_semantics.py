"""TDD tests for Genie email operation box semantics.

Defines intended owner/admin vs customer label separation and customer
review-confirmation-box behavior before implementation lands.

Some tests are expected to FAIL until the review-confirmation patch lands —
see docs/genie/GENIE_EMAIL_OPERATION_BOX_SEMANTICS_FIX_PLAN.md.

Reference:
- docs/REVIEW_OPERATION_BOX_POLICY.md
- docs/genie/GENIE_EMAIL_OPERATION_BOX_SEMANTICS_FIX_PLAN.md
"""
from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from main import email_operational_handoff_meta
from orchestrator import OrchestrationResult, build_run_artifact_metadata
from publishing_policy import PublishingDecision
from renderers import render_email_operational_box
from today_geenee_customer_delivery import (
    prepare_customer_final_html,
    send_today_geenee_customer_final_email,
    strip_owner_operational_handoff,
)

_FORBIDDEN_LEGACY_STATUS_LABELS = frozenset({"기본 검수 통과"})
_FORBIDDEN_LEGACY_DELIVERY_LABELS = frozenset({"이메일 발송 완료"})
_FORBIDDEN_SEND_COMPLETE_FRAGMENTS = ("발송 완료",)
_FORBIDDEN_OWNER_REVIEW_COMPLETE = (
    "검수완료",
    "운영책임자의 직접 검수를 통과했습니다",
)
_ALLOWED_FUTURE_AUTOMATED_PASS_LABELS = frozenset({"자동 검증 통과"})
_ALLOWED_FUTURE_DELIVERY_LABELS = frozenset(
    {
        "운영자 검수 메일 발송 전",
        "운영자 검수 메일 상태 미확인",
        "운영자 검수 메일 미발송",
    }
)

_REVIEW_PASSED_TEXT = "본 브리핑은 운영책임자의 직접 검수를 통과했습니다."
_GENIE_FORBIDDEN_REVIEW_CONFIRMATION_STATES = (
    "preview_pending",
    "sent_archived",
    "invalid_state",
)
_CUSTOMER_REVIEW_BOX_FORBIDDEN_FRAGMENTS = (
    "발송되었습니다",
    "sent_archived",
    "재발행",
    "다시 생성",
    "수정요청",
    "수정 요청",
    "운영자 검수 상태",
    'id="genie-operational-handoff"',
    "genie-operational-handoff",
)

_OPERATIONAL_HANDOFF_RE = re.compile(
    r'<section[^>]*\bid=["\']genie-operational-handoff["\'][^>]*>.*?</section>',
    re.IGNORECASE | re.DOTALL,
)


def _extract_operational_handoff_block(html: str) -> str:
    match = _OPERATIONAL_HANDOFF_RE.search(html)
    if not match:
        raise AssertionError('Missing <section id="genie-operational-handoff"> block')
    return match.group(0)


def _sample_owner_operational_html() -> str:
    """Owner-review email fragment with admin operation box (future-facing copy)."""
    meta = email_operational_handoff_meta("today_genie", "pass")
    # Inject future-facing labels for strip tests (box content may differ pre-fix).
    meta = {
        **meta,
        "status_label": "자동 검증 통과",
        "email_delivery_label": "운영자 검수 메일 발송 전",
    }
    return (
        "<p>briefing body</p>"
        + render_email_operational_box(
            {
                **meta,
                "mode_label": "오늘의 지니 장전 브리핑",
                "execution_time_kst": "2026-06-05 09:00:00 KST",
                "result_summary": "sample",
                "mode_code": "today_genie",
                "revision_request_post_url": "https://placeholder.example.invalid",
                "rerequest_url": "#",
            }
        )
        .replace("운영 안내", "운영자 검수 상태", 2)
    )


def _sample_saved_artifact_html() -> str:
    """Artifact-like HTML: editorial + bottom slot + owner operational handoff."""
    handoff = _extract_operational_handoff_block(_sample_owner_operational_html())
    return (
        "<p>editorial briefing body</p>"
        '<section id="bottom-image-slot"><img src="cid:genie-bottom" alt="bottom" /></section>'
        + handoff
    )


def _assert_customer_review_box_absent(case: unittest.TestCase, html: str) -> None:
    normalized = html.lower().replace("_", "-")
    case.assertNotIn('id="review-confirmation-box"', html)
    case.assertNotIn("review-confirmation", normalized)
    case.assertNotIn(_REVIEW_PASSED_TEXT, html)


def _assert_review_passed_customer_box(case: unittest.TestCase, html: str) -> None:
    case.assertIn('id="review-confirmation-box"', html)
    case.assertIn('data-review-state="review_passed"', html)
    case.assertIn(_REVIEW_PASSED_TEXT, html)
    for forbidden in _CUSTOMER_REVIEW_BOX_FORBIDDEN_FRAGMENTS:
        case.assertNotIn(
            forbidden,
            html,
            msg=f"customer review HTML must not contain {forbidden!r}",
        )


class GenieEmailOperationalMetaSemanticsTests(unittest.TestCase):
    """email_operational_handoff_meta() must not conflate validation pass with send."""

    def test_pass_validation_must_not_use_legacy_send_complete_label(self) -> None:
        meta = email_operational_handoff_meta("today_genie", "pass")
        delivery = meta.get("email_delivery_label", "")
        self.assertNotIn(
            delivery,
            _FORBIDDEN_LEGACY_DELIVERY_LABELS,
            msg="validation pass must not set 이메일 발송 완료",
        )
        for fragment in _FORBIDDEN_SEND_COMPLETE_FRAGMENTS:
            self.assertNotIn(
                fragment,
                delivery,
                msg=f"email_delivery_label must not contain {fragment!r} without send result",
            )

    def test_pass_validation_must_not_use_legacy_human_review_pass_label(self) -> None:
        meta = email_operational_handoff_meta("today_genie", "pass")
        status = meta.get("status_label", "")
        self.assertNotIn(
            status,
            _FORBIDDEN_LEGACY_STATUS_LABELS,
            msg="validation pass must not use 기본 검수 통과",
        )

    def test_pass_validation_prefers_future_automated_pass_label_when_present(self) -> None:
        meta = email_operational_handoff_meta("today_genie", "pass")
        status = meta.get("status_label", "")
        if status in _ALLOWED_FUTURE_AUTOMATED_PASS_LABELS:
            return
        self.fail(
            f"expected status_label in {_ALLOWED_FUTURE_AUTOMATED_PASS_LABELS}, got {status!r}"
        )

    def test_pass_validation_delivery_label_is_explicit_non_send_complete_when_present(
        self,
    ) -> None:
        meta = email_operational_handoff_meta("today_genie", "pass")
        delivery = meta.get("email_delivery_label", "")
        if delivery in _ALLOWED_FUTURE_DELIVERY_LABELS:
            return
        self.fail(
            f"expected email_delivery_label in {_ALLOWED_FUTURE_DELIVERY_LABELS}, got {delivery!r}"
        )

    def test_pass_meta_must_not_imply_owner_review_completion(self) -> None:
        meta = email_operational_handoff_meta("today_genie", "pass")
        blob = " ".join(str(v) for v in meta.values())
        for forbidden in _FORBIDDEN_OWNER_REVIEW_COMPLETE:
            self.assertNotIn(forbidden, blob)


class GenieEmailOperationalBoxRenderSemanticsTests(unittest.TestCase):
    """render_email_operational_box() owner/admin surface semantics."""

    def setUp(self) -> None:
        self.meta = email_operational_handoff_meta("today_genie", "pass")

    def test_admin_box_has_operational_handoff_dom_id(self) -> None:
        html = render_email_operational_box(self.meta)
        self.assertIn('id="genie-operational-handoff"', html)

    def test_admin_box_title_is_owner_review_status_not_generic_ops_notice(self) -> None:
        html = render_email_operational_box(self.meta)
        self.assertIn("운영자 검수 상태", html)
        self.assertNotIn(">운영 안내<", html)

    def test_admin_box_may_contain_reissue_copy_inside_handoff_only(self) -> None:
        html = render_email_operational_box(self.meta)
        block = _extract_operational_handoff_block(html)
        self.assertIn("재발행", block)
        self.assertIn("수정 요청", block)

    def test_pass_rendered_box_must_not_imply_owner_review_completion(self) -> None:
        html = render_email_operational_box(self.meta)
        for forbidden in _FORBIDDEN_OWNER_REVIEW_COMPLETE:
            self.assertNotIn(forbidden, html)


class GenieCustomerFinalHtmlSemanticsTests(unittest.TestCase):
    """Customer final HTML must strip admin box and omit review confirmation (phase 1)."""

    def test_strip_removes_admin_operation_box_and_admin_copy(self) -> None:
        html = _sample_owner_operational_html()
        out = strip_owner_operational_handoff(html)
        for forbidden in (
            'id="genie-operational-handoff"',
            "운영자 검수 상태",
            "재발행",
            "수정 요청",
            "운영자 검수 메일",
            "이메일 발송 완료",
        ):
            self.assertNotIn(forbidden, out, msg=f"stripped HTML must not contain {forbidden!r}")

    def test_prepare_customer_final_html_strips_admin_box(self) -> None:
        html = _sample_owner_operational_html()
        out = prepare_customer_final_html(html)
        self.assertNotIn('id="genie-operational-handoff"', out)
        self.assertIn("briefing body", out)

    def test_default_customer_final_html_has_no_review_confirmation_box(self) -> None:
        html = _sample_saved_artifact_html()
        out = prepare_customer_final_html(html)
        _assert_customer_review_box_absent(self, out)
        self.assertIn("editorial briefing body", out)

    def test_customer_final_html_has_no_review_confirmation_box_yet(self) -> None:
        """Backward-compatible alias for minimal body-only strip path."""
        html = "<p>body only</p>"
        out = prepare_customer_final_html(html)
        _assert_customer_review_box_absent(self, out)


class GenieCustomerReviewConfirmationBoxTests(unittest.TestCase):
    """Customer #review-confirmation-box on approved delivery path (TDD)."""

    def test_explicit_review_passed_state_inserts_customer_safe_review_box(self) -> None:
        html = _sample_saved_artifact_html()
        out = prepare_customer_final_html(
            html,
            review_confirmation_state="review_passed",
        )
        _assert_review_passed_customer_box(self, out)
        self.assertIn("editorial briefing body", out)
        self.assertIn("bottom-image-slot", out)

    def test_unsupported_review_confirmation_states_raise_value_error(self) -> None:
        html = _sample_saved_artifact_html()
        for state in _GENIE_FORBIDDEN_REVIEW_CONFIRMATION_STATES:
            with self.subTest(state=state):
                with self.assertRaises(ValueError):
                    prepare_customer_final_html(
                        html,
                        review_confirmation_state=state,
                    )

    def test_review_confirmation_inserted_after_operational_handoff_stripped(self) -> None:
        html = _sample_saved_artifact_html()
        self.assertIn('id="genie-operational-handoff"', html)
        out = prepare_customer_final_html(
            html,
            review_confirmation_state="review_passed",
        )
        _assert_review_passed_customer_box(self, out)
        self.assertNotIn('id="genie-operational-handoff"', out)
        self.assertNotIn("재발행", out)
        self.assertNotIn("수정 요청", out)
        self.assertNotIn("운영자 검수 상태", out)

    def test_review_passed_exact_copy_matches_policy(self) -> None:
        html = _sample_saved_artifact_html()
        out = prepare_customer_final_html(
            html,
            review_confirmation_state="review_passed",
        )
        self.assertIn(_REVIEW_PASSED_TEXT, out)
        self.assertNotIn("발송되었습니다", out)

    def setUp(self) -> None:
        self._env_patch = patch.dict(
            "os.environ",
            {
                "GENIE_CUSTOMER_EMAIL_TO": "customer@example.com",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_USER": "user@example.com",
                "SMTP_PASSWORD": "secret",
            },
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    @patch("today_geenee_customer_delivery.send_genie_email")
    @patch("today_geenee_customer_delivery._resolve_today_genie_inline_jpeg_parts")
    def test_send_path_passes_review_passed_into_customer_html(
        self,
        mock_inline,
        mock_send,
    ) -> None:
        mock_inline.return_value = [("/tmp/top.jpg", "cid.top", "top.jpg")]
        mock_send.return_value = True
        saved_html = _sample_saved_artifact_html()
        meta = {"mode": "today_genie", "email_subject": "[운영자 검토] 오늘의 지니"}
        self.assertTrue(
            send_today_geenee_customer_final_email(saved_html, meta),
        )
        mock_send.assert_called_once()
        outbound_html = mock_send.call_args.args[0]
        _assert_review_passed_customer_box(self, outbound_html)
        self.assertIn("editorial briefing body", outbound_html)


class GenieOwnerVsCustomerDeliveryMetadataTests(unittest.TestCase):
    """Owner Gmail send and customer delivery are separate persisted concepts."""

    def test_artifact_metadata_separates_email_sent_and_customer_delivery_status(self) -> None:
        decision = PublishingDecision(
            send_email=True,
            create_naver_draft=False,
            auto_publish=False,
            require_review=True,
            suppress_external=False,
            send_customer_email=False,
        )
        result = OrchestrationResult(
            decision=decision,
            reason_summary="ok",
            response_status=200,
            mode="today_genie",
            response_data={"validation_result": "pass", "workflow_status": "validated"},
        )
        meta = build_run_artifact_metadata(result, run_id="test_run", email_sent=True)
        self.assertIn("email_sent", meta)
        self.assertIn("customer_delivery_status", meta)
        self.assertTrue(meta["email_sent"])
        self.assertEqual(meta["customer_delivery_status"], "not_sent")
        self.assertNotEqual(meta["email_sent"], meta["customer_delivery_status"])


if __name__ == "__main__":
    unittest.main()
