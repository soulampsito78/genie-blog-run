"""2026-09-09: REVIEW_REQUIRED must not create a reissue deadlock.

Production run ``20260909_063102_today_genie_bc5aae92`` (validation_result=
``draft_only``) had Admin telling the owner two incompatible things:

    customer send -> blocked  "런타임 검증이 pass가 아닙니다 … 재발행 후 다시 승인하세요."
    reissue       -> blocked  "검증을 통과하지 못한 실행은 재발행 원본으로 사용할 수 없습니다."

Following the first instruction landed on the second refusal, so the only
remediation path was unreachable for exactly the runs that needed it.

Reissue eligibility is not customer-send eligibility. A reissue replaces
defective output; what a child inherits is the parent's preserved evidence, not
its verdict. These tests pin that split: a reviewable parent is remediable, a
hard-failed or corrupt one is not, scoped evidence is required only where the
scope actually reuses it, and customer send stays independently blocked.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from admin_routes import _APPROVE_ERROR_MESSAGES, _REISSUE_PARENT_BLOCK_MESSAGES
from admin_store import (
    REISSUE_PARENT_BLOCK_REASONS,
    can_approve_customer_send,
    reissue_parent_block_reason,
    reissue_parent_review_class,
    save_run_artifact,
)
from main import app
from product_surface_contract import PRODUCT_REVIEW_REQUIRED

_TODAY_PARENT = "20260909_063102_today_genie_bc5aae92"
_KOREA_PARENT = "20260907_183002_keysuri_korea_tech_ac93e962"

# Send blocks whose owner-facing copy tells the owner to reissue. Every one of
# them must name a class the reissue entry actually accepts.
_REMEDIATION_SEND_BLOCKS = (
    "review_required_remediation_needed",
    "product_surface_remediation_needed",
)


def _today_meta(**overrides: Any) -> Dict[str, Any]:
    """A Today artifact shaped like the production 06:30 natural run."""
    meta: Dict[str, Any] = {
        "run_id": _TODAY_PARENT,
        "mode": "today_genie",
        "validation_result": "draft_only",
        "workflow_status": "review_required",
        "artifact_status": "emailed",
        "customer_surface_status": "CUSTOMER_SURFACE_PASS",
        "owner_review_status": "reopened",
        "customer_delivery_status": "not_sent",
        "response_status": 200,
        "email_sent": True,
        "issue_codes": ["unanchored_briefing_vs_input_news"],
    }
    meta.update(overrides)
    return meta


def _korea_meta(**overrides: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "run_id": _KOREA_PARENT,
        "mode": "keysuri_korea_tech",
        "program_id": "keysuri_korea_tech",
        "validation_result": "pass",
        "artifact_status": "emailed",
        "customer_surface_status": "CUSTOMER_SURFACE_PASS",
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "safety_verdict": "SAFE",
        "editorial_verdict": "READY",
        "email_sent": True,
        "generated_image_path_watermarked": "output/keysuri_preview/top.jpg",
    }
    meta.update(overrides)
    return meta


class ReissueParentClassificationTests(unittest.TestCase):
    """§2 authority: which parents may seed a corrected child run."""

    def test_pass_parent_is_reissuable(self) -> None:
        meta = _today_meta(validation_result="pass", workflow_status="validated")
        self.assertEqual(reissue_parent_review_class(meta), "pass")
        self.assertIsNone(reissue_parent_block_reason(meta))

    def test_review_required_parent_with_evidence_is_reissuable(self) -> None:
        meta = _today_meta()
        self.assertEqual(reissue_parent_review_class(meta), "review_required")
        self.assertIsNone(reissue_parent_block_reason(meta))

    def test_product_review_required_parent_with_evidence_is_reissuable(self) -> None:
        meta = _today_meta(
            validation_result="pass",
            workflow_status="validated",
            customer_surface_status=PRODUCT_REVIEW_REQUIRED,
        )
        self.assertEqual(reissue_parent_review_class(meta), "product_review_required")
        self.assertIsNone(reissue_parent_block_reason(meta))

    def test_hard_fail_parent_is_blocked(self) -> None:
        blocked = _today_meta(validation_result="block", artifact_status="failed")
        self.assertEqual(reissue_parent_review_class(blocked), "hard_fail")
        self.assertEqual(
            reissue_parent_block_reason(blocked), "parent_validation_not_pass"
        )

    def test_failed_artifact_status_alone_is_hard_fail(self) -> None:
        blocked = _today_meta(validation_result="draft_only", artifact_status="failed")
        self.assertEqual(reissue_parent_review_class(blocked), "hard_fail")
        self.assertEqual(
            reissue_parent_block_reason(blocked), "parent_validation_not_pass"
        )

    def test_unknown_verdict_fails_closed(self) -> None:
        """An unrecognized verdict is not silently promoted to reviewable."""
        meta = _today_meta(validation_result="hold", workflow_status="")
        self.assertEqual(reissue_parent_review_class(meta), "unclassified")
        self.assertEqual(reissue_parent_block_reason(meta), "parent_validation_not_pass")

    def test_errored_parent_is_blocked_even_when_validation_passed(self) -> None:
        meta = _today_meta(validation_result="pass", error="generation_failed")
        self.assertEqual(reissue_parent_block_reason(meta), "parent_run_errored")

    def test_dry_run_parent_is_blocked(self) -> None:
        meta = _today_meta(admin_reissue_dry_run=True)
        self.assertEqual(
            reissue_parent_block_reason(meta), "parent_not_reissuable_dry_run"
        )

    def test_corrupt_artifact_is_blocked(self) -> None:
        self.assertEqual(
            reissue_parent_block_reason(None), "parent_artifact_unusable"
        )
        self.assertEqual(
            reissue_parent_block_reason("not-an-artifact"), "parent_artifact_unusable"
        )
        self.assertEqual(
            reissue_parent_block_reason(_today_meta(run_id="not a run id")),
            "parent_artifact_unusable",
        )
        self.assertEqual(
            reissue_parent_block_reason(_today_meta(selected_items="corrupt")),
            "parent_artifact_unusable",
        )
        self.assertEqual(
            reissue_parent_block_reason(
                _today_meta(regen_generated_briefing_snapshot=["corrupt"])
            ),
            "parent_artifact_unusable",
        )

    def test_placeholder_content_still_blocks_a_reviewable_parent(self) -> None:
        """The 2026-07-30 fabricated-card guard survives the eligibility rewrite."""
        meta = _today_meta(
            selected_items=[{"headline": f"기반 AI·테크 신호 {i}"} for i in range(1, 6)]
        )
        self.assertEqual(
            reissue_parent_block_reason(meta), "parent_placeholder_content"
        )


class ReissueScopeEvidenceTests(unittest.TestCase):
    """§6: a scope is blocked only for the evidence that scope actually reuses."""

    def test_today_body_only_blocked_when_claimed_images_are_gone(self) -> None:
        meta = _today_meta(
            image_source="generated",
            image_generation_status="generated",
            generated_image_paths={},
        )
        self.assertEqual(
            reissue_parent_block_reason(meta, scope="body_only"),
            "parent_missing_image_evidence",
        )
        # The scope that regenerates imagery does not need the parent's images.
        self.assertIsNone(reissue_parent_block_reason(meta, scope="body_and_image"))

    def test_today_body_only_allowed_when_gcs_objects_preserve_the_images(self) -> None:
        meta = _today_meta(
            image_source="generated",
            image_generation_status="generated",
            generated_image_paths={},
            customer_image_gcs_bucket="genie-artifacts",
            customer_image_gcs_objects={"top": "a/top.jpg", "bottom": "a/bottom.jpg"},
        )
        self.assertIsNone(reissue_parent_block_reason(meta, scope="body_only"))

    def test_today_body_only_allowed_when_no_run_specific_images_were_claimed(
        self,
    ) -> None:
        """The production parent carried no image provenance; static assets cover it.

        Absent metadata is not proof of absent evidence — treating it as proof is
        the false block this rule replaces.
        """
        meta = _today_meta()
        self.assertNotIn("generated_image_paths", meta)
        self.assertIsNone(reissue_parent_block_reason(meta, scope="body_only"))

    def test_keysuri_body_only_blocked_without_any_top_image_reference(self) -> None:
        meta = _korea_meta()
        meta.pop("generated_image_path_watermarked")
        self.assertEqual(
            reissue_parent_block_reason(meta, scope="body_only"),
            "parent_missing_image_evidence",
        )
        self.assertIsNone(reissue_parent_block_reason(meta, scope="body_and_image"))

    def test_keysuri_body_only_allowed_from_inline_image_hashes(self) -> None:
        meta = _korea_meta()
        meta.pop("generated_image_path_watermarked")
        meta["owner_email_inline_image_hashes"] = [
            {"cid": "keysuri_topshot_korea", "path": "output/top.jpg"}
        ]
        self.assertIsNone(reissue_parent_block_reason(meta, scope="body_only"))

    def test_image_only_blocked_without_the_saved_owner_review_body(self) -> None:
        meta = _korea_meta()
        self.assertEqual(
            reissue_parent_block_reason(
                meta, scope="image_only", has_parent_email_html=False
            ),
            "parent_missing_body_evidence",
        )
        self.assertIsNone(
            reissue_parent_block_reason(
                meta, scope="image_only", has_parent_email_html=True
            )
        )

    def test_scope_evidence_never_overrides_a_hard_fail(self) -> None:
        meta = _korea_meta(validation_result="block")
        for scope in ("body_only", "image_only", "body_and_image"):
            with self.subTest(scope=scope):
                self.assertEqual(
                    reissue_parent_block_reason(meta, scope=scope),
                    "parent_validation_not_pass",
                )


class CustomerSendStaysBlockedTests(unittest.TestCase):
    """Reissue was opened up; customer-send safety must be untouched."""

    def test_review_required_today_run_still_cannot_be_customer_sent(self) -> None:
        ok, reason = can_approve_customer_send(_today_meta(), has_email_html=True)
        self.assertFalse(ok)
        self.assertEqual(reason, "review_required_remediation_needed")

    def test_product_review_required_run_still_cannot_be_customer_sent(self) -> None:
        meta = _today_meta(
            validation_result="pass",
            workflow_status="validated",
            customer_surface_status=PRODUCT_REVIEW_REQUIRED,
        )
        ok, reason = can_approve_customer_send(meta, has_email_html=True)
        self.assertFalse(ok)
        self.assertEqual(reason, "product_surface_remediation_needed")

    def test_product_review_required_keysuri_run_still_cannot_be_customer_sent(
        self,
    ) -> None:
        meta = _korea_meta(customer_surface_status=PRODUCT_REVIEW_REQUIRED)
        ok, reason = can_approve_customer_send(meta, has_email_html=True)
        self.assertFalse(ok)
        self.assertEqual(reason, "product_surface_remediation_needed")

    def test_reissue_eligibility_never_implies_send_eligibility(self) -> None:
        for meta in (
            _today_meta(),
            _today_meta(
                validation_result="pass",
                workflow_status="validated",
                customer_surface_status=PRODUCT_REVIEW_REQUIRED,
            ),
        ):
            with self.subTest(vr=meta["validation_result"]):
                self.assertIsNone(reissue_parent_block_reason(meta))
                self.assertFalse(
                    can_approve_customer_send(meta, has_email_html=True)[0]
                )


class AdminCopyConsistencyTests(unittest.TestCase):
    """§3: remediation instructions and actual capabilities must agree."""

    def test_every_block_reason_has_owner_facing_text(self) -> None:
        for reason in REISSUE_PARENT_BLOCK_REASONS:
            with self.subTest(reason=reason):
                self.assertIn(reason, _REISSUE_PARENT_BLOCK_MESSAGES)
                self.assertTrue(_REISSUE_PARENT_BLOCK_MESSAGES[reason].strip())

    def test_send_blocks_that_promise_a_reissue_are_actually_reissuable(self) -> None:
        """The exact contradiction: copy says reissue, the gate says no."""
        cases = {
            "review_required_remediation_needed": _today_meta(),
            "product_surface_remediation_needed": _today_meta(
                validation_result="pass",
                workflow_status="validated",
                customer_surface_status=PRODUCT_REVIEW_REQUIRED,
            ),
        }
        for code, meta in cases.items():
            with self.subTest(code=code):
                ok, reason = can_approve_customer_send(meta, has_email_html=True)
                self.assertFalse(ok)
                self.assertEqual(reason, code)
                self.assertIn("재발행", _APPROVE_ERROR_MESSAGES[code])
                self.assertIsNone(
                    reissue_parent_block_reason(meta),
                    f"{code} tells the owner to reissue but the reissue gate refuses",
                )

    def test_hard_fail_copy_does_not_claim_review_required_is_unreissuable(self) -> None:
        message = _REISSUE_PARENT_BLOCK_MESSAGES["parent_validation_not_pass"]
        self.assertIn("review_required", message)

    def test_remediation_blocks_are_the_only_ones_promising_a_reissue(self) -> None:
        for code, message in _APPROVE_ERROR_MESSAGES.items():
            if code in _REMEDIATION_SEND_BLOCKS:
                continue
            with self.subTest(code=code):
                self.assertNotIn("재발행 후 다시 승인", message)


class ReissueRouteDeadlockTests(unittest.TestCase):
    """End-to-end: the Admin reissue POST no longer stops at parent_eligibility."""

    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {"GENIE_ADMIN_PASSWORD": "test-admin-secret"},
            clear=False,
        )
        self._env.start()
        self.addCleanup(self._env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        runs_dir = Path(self._tmp.name) / "admin_runs"
        runs_dir.mkdir(parents=True)
        self._runs_patch = patch("admin_store.admin_runs_dir", return_value=runs_dir)
        self._runs_patch.start()
        self.addCleanup(self._runs_patch.stop)
        self.client = TestClient(app)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})

    def _save(self, **overrides: Any) -> str:
        meta = _today_meta(**overrides)
        save_run_artifact(meta, email_html="<p>owner review body</p>")
        return meta["run_id"]

    def test_review_required_parent_reaches_the_body_only_runner(self) -> None:
        run_id = self._save()
        child = "20260909_090000_today_genie_11223344"
        runner = MagicMock(return_value={"ok": True, "run_id": child, "email_sent": True})
        with patch("admin_routes.run_today_body_only_reissue", runner):
            resp = self.client.post(
                f"/admin/runs/{run_id}/reissue",
                data={"reason_option": "content_quality", "reissue_scope": "body_only"},
                follow_redirects=False,
            )
        runner.assert_called_once()
        self.assertEqual(resp.status_code, 303)
        self.assertIn(child, resp.headers.get("location", ""))

    def test_hard_failed_parent_is_still_refused_at_parent_eligibility(self) -> None:
        run_id = self._save(
            run_id="20260909_063103_today_genie_bc5aae93",
            validation_result="block",
            artifact_status="failed",
        )
        runner = MagicMock()
        with patch("admin_routes.run_today_body_only_reissue", runner):
            resp = self.client.post(
                f"/admin/runs/{run_id}/reissue",
                data={"reason_option": "content_quality", "reissue_scope": "body_only"},
                follow_redirects=False,
            )
        runner.assert_not_called()
        self.assertEqual(resp.status_code, 400)
        self.assertIn("parent_eligibility", resp.text)

    def test_run_detail_offers_the_reissue_it_told_the_owner_to_use(self) -> None:
        run_id = self._save(run_id="20260909_063104_today_genie_bc5aae94")
        html = self.client.get(f"/admin/runs/{run_id}").text
        self.assertIn("승인 발송 불가", html)
        self.assertIn("review_required_remediation_needed", html)
        self.assertNotIn("재발행 불가", html)
        self.assertIn(f'action="/admin/runs/{run_id}/reissue"', html)

    def test_run_detail_hides_the_reissue_form_when_the_parent_is_refused(self) -> None:
        run_id = self._save(
            run_id="20260909_063105_today_genie_bc5aae95",
            validation_result="block",
            artifact_status="failed",
        )
        html = self.client.get(f"/admin/runs/{run_id}").text
        self.assertIn("재발행 불가", html)
        self.assertNotIn(f'action="/admin/runs/{run_id}/reissue"', html)


if __name__ == "__main__":
    unittest.main()
