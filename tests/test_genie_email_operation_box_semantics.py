"""TDD tests for Genie email operation box semantics (pre-implementation).

Defines intended owner/admin vs customer label separation before changing
main.py / renderers.py. Some tests are expected to FAIL until the semantics
fix patch lands — see docs/genie/GENIE_EMAIL_OPERATION_BOX_SEMANTICS_FIX_PLAN.md.

Reference:
- docs/REVIEW_OPERATION_BOX_POLICY.md
- docs/genie/GENIE_EMAIL_OPERATION_BOX_SEMANTICS_FIX_PLAN.md
"""
from __future__ import annotations

import re
import unittest

from main import email_operational_handoff_meta
from orchestrator import OrchestrationResult, build_run_artifact_metadata
from publishing_policy import PublishingDecision
from renderers import render_email_operational_box
from today_geenee_customer_delivery import (
    prepare_customer_final_html,
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

    def test_customer_final_html_has_no_review_confirmation_box_yet(self) -> None:
        html = "<p>body only</p>"
        out = prepare_customer_final_html(html)
        self.assertNotIn("review-confirmation", out.lower().replace("_", "-"))


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
