"""Authority split: product QA blocks customers, never usable owner review."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from admin_store import can_approve_customer_send
from keysuri_quality_adjudication import _canonical_delivery_matrix
from orchestrator import OrchestrationResult
from product_surface_contract import PRODUCT_REVIEW_REQUIRED, REVIEW_REQUIRED
from publishing_policy import PublishingDecision
from service_full_run_contract import (
    IMAGE_GEN_GENERATED,
    IMAGE_SOURCE_GENERATED,
    ServiceImageOutcome,
    TodayGenieServiceImageBundle,
)
from today_genie_service_full_run import _run_today_genie_service_full_run_impl


def _decision(*, send_email: bool, suppress_external: bool = False) -> PublishingDecision:
    return PublishingDecision(
        send_email=send_email,
        create_naver_draft=False,
        auto_publish=False,
        require_review=True,
        suppress_external=suppress_external,
        send_customer_email=False,
    )


def _generated_bundle() -> TodayGenieServiceImageBundle:
    top = ServiceImageOutcome(
        called_image_api=True,
        image_generation_status=IMAGE_GEN_GENERATED,
        image_source=IMAGE_SOURCE_GENERATED,
        generated_image_path="output/images/top.jpg",
    )
    bottom = ServiceImageOutcome(
        called_image_api=True,
        image_generation_status=IMAGE_GEN_GENERATED,
        image_source=IMAGE_SOURCE_GENERATED,
        generated_image_path="output/images/bottom.jpg",
    )
    return TodayGenieServiceImageBundle(
        top=top,
        bottom=bottom,
        primary_generated_image_path=top.generated_image_path,
        watermark_applied=True,
    )


class ProductAcceptanceAuthorityTests(unittest.TestCase):
    def test_global_and_korea_product_qa_do_not_suppress_safe_owner_review(self) -> None:
        for mode in ("keysuri_global_tech", "keysuri_korea_tech"):
            with self.subTest(mode=mode):
                delivery = _canonical_delivery_matrix("SAFE", "READY")
                self.assertEqual(delivery["owner_delivery_behavior"], "SEND_OWNER_REVIEW")

                meta = {
                    "mode": mode,
                    "validation_result": "pass",
                    "artifact_status": "emailed",
                    "owner_review_status": "pending_review",
                    "customer_delivery_status": "not_sent",
                    "safety_verdict": "SAFE",
                    "editorial_verdict": "READY",
                    "customer_surface_status": PRODUCT_REVIEW_REQUIRED,
                }
                allowed, reason = can_approve_customer_send(meta, has_email_html=True)
                self.assertFalse(allowed)
                self.assertEqual(reason, "product_surface_remediation_needed")

    def test_keysuri_unsafe_still_suppresses_owner_review(self) -> None:
        delivery = _canonical_delivery_matrix("UNSAFE", "READY")
        self.assertEqual(delivery["owner_delivery_behavior"], "HOLD_INCIDENT")

    def test_product_review_required_blocks_customer_approval_in_all_three_modes(self) -> None:
        metas = [
            {
                "mode": "today_genie",
                "validation_result": "pass",
                "artifact_status": "emailed",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "customer_surface_status": PRODUCT_REVIEW_REQUIRED,
            },
            {
                "mode": "keysuri_global_tech",
                "validation_result": "pass",
                "artifact_status": "emailed",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "safety_verdict": "SAFE",
                "editorial_verdict": "READY",
                "customer_surface_status": PRODUCT_REVIEW_REQUIRED,
            },
            {
                "mode": "keysuri_korea_tech",
                "validation_result": "pass",
                "artifact_status": "emailed",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "safety_verdict": "SAFE",
                "editorial_verdict": "READY",
                "customer_surface_status": PRODUCT_REVIEW_REQUIRED,
            },
        ]
        for meta in metas:
            with self.subTest(mode=meta["mode"]):
                allowed, reason = can_approve_customer_send(meta, has_email_html=True)
                self.assertFalse(allowed)
                self.assertEqual(reason, "product_surface_remediation_needed")

    def test_today_draft_only_full_run_still_generates_and_delivers_owner_review(self) -> None:
        payload = {
            "validation_result": "draft_only",
            "workflow_status": "review_required",
            "issue_codes": ["closing_lecture_tail"],
            "runtime_input": {
                "overnight_us_market": {"status": "ok"},
                "macro_indicators": {"status": "ok"},
            },
            "data": {
                "channel_drafts": {"email_subject": "Today owner review"},
                "_product_surface_qa": {
                    "customer_surface_status": PRODUCT_REVIEW_REQUIRED,
                    "issue_codes": ["customer_surface_mixed_sentence_end_style"],
                    "contract_version": "genie-product-surface-v1",
                },
            },
        }
        orchestration = OrchestrationResult(
            decision=_decision(send_email=True),
            reason_summary="owner review required",
            response_status=200,
            mode="today_genie",
            response_data=payload,
        )
        sender = Mock(return_value=True)
        with (
            patch("today_genie_service_full_run.run_genie_job", return_value=orchestration),
            patch("today_genie_service_full_run.generate_today_genie_service_images", return_value=_generated_bundle()) as image_call,
            patch("today_genie_service_full_run.build_owner_review_admin_url", return_value="https://admin.invalid/review"),
            patch("today_genie_service_full_run._inline_parts_from_bundle", return_value=[]),
            patch("today_genie_service_full_run.save_run_artifact") as save_artifact,
            patch("today_genie_service_full_run.estimate_genie_generation_cost", return_value=None),
            patch("today_genie_orchestrator_images.today_image_regen_inputs", return_value={}),
            patch("main.build_today_genie_email_html_for_cid_mime_send", return_value="운영자 검수 화면 열기"),
        ):
            result = _run_today_genie_service_full_run_impl(send_fn=sender)

        self.assertTrue(result["ok"])
        self.assertTrue(result["email_sent"])
        image_call.assert_called_once()
        sender.assert_called_once()
        saved_meta = save_artifact.call_args.args[0]
        self.assertEqual(saved_meta["runtime_safety_status"], REVIEW_REQUIRED)
        self.assertEqual(saved_meta["customer_surface_status"], PRODUCT_REVIEW_REQUIRED)

    def test_today_hard_fail_still_suppresses_images_and_owner_delivery(self) -> None:
        orchestration = OrchestrationResult(
            decision=_decision(send_email=False, suppress_external=True),
            reason_summary="unsafe",
            response_status=200,
            mode="today_genie",
            response_data={
                "validation_result": "block",
                "workflow_status": "review_required",
                "issue_codes": ["feed_json_decode_failed"],
                "data": {},
            },
        )
        sender = Mock(return_value=True)
        with (
            patch("today_genie_service_full_run.run_genie_job", return_value=orchestration),
            patch("today_genie_service_full_run.generate_today_genie_service_images") as image_call,
            patch("today_genie_service_full_run.save_run_artifact"),
        ):
            result = _run_today_genie_service_full_run_impl(send_fn=sender)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "validation_blocked")
        image_call.assert_not_called()
        sender.assert_not_called()


if __name__ == "__main__":
    unittest.main()
