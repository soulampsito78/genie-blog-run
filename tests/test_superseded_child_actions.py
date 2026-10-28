"""Focused regression tests for superseded child run action suppression and safety boundaries.

Covers:
1. Actual summary-shaped lineage without parent_run_id (regen_parent_run_id + automatic_remediation_parent_run_id).
2. Accepted parent vs unsent child:
   - Run detail is reference-only with parent link; approval CTA, reissue form, hold/reopen form suppressed.
   - Direct GET /admin/runs/{run_id}/approve-confirm returns 400 (zero snapshot created).
   - Direct POST /admin/runs/{run_id}/approve rejects (zero send, zero attempt recorded).
   - Direct POST /admin/runs/{run_id}/reissue returns 400 (zero model call, zero budget consumed).
   - Direct POST /admin/runs/{run_id}/hold and /reopen reject without mutating child artifact.
3. Genuine publication boundaries prevent second edition:
   - Attempted, unknown, refused parent statuses and canonical attempt flags:
     customer_email_smtp_attempted, smtp_attempted, customer_email_delivery_attempted.
   - Positive counts: smtp_accepted, customer_delivery_accepted, smtp_refused, customer_delivery_refused,
     customer_delivery_unknown, smtp_unknown.
4. Target count alone remains eligible:
   - Parent with customer_email_recipient_count=15 but not_sent, no attempt/outcome -> child remains eligible.
5. Durable-only reservation stops effects:
   - publication_attempts record exists in safety store -> stops effects without SMTP proof.
6. Fail-closed on missing, corrupt, or contradictory lineage/identity:
   - Missing parent artifact, corrupt JSON.
   - Mismatched date, mismatched mode, metadata mode contradicting run ID mode.
   - Conflicting parent aliases or cyclic self-parent (parent_run_id == self or regen_parent_run_id == self).
7. Self-stamp natural run:
   - automatic_remediation_parent_run_id == self -> eligible natural run, not a child.
8. Truthful panels:
   - Graded quality panel and auto-remediation panel (including child_still_reviewable) render reference-only copy
     without self-links or instructions to approve/reissue.
9. Future-day unsent natural run & held normal unsent Today run controls preserved.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import admin_safety_store as s_store
import admin_store
from admin_store import (
    can_approve_customer_send,
    extract_parent_lineage,
    extract_parent_run_id,
    hold_run,
    load_run_artifact,
    reissue_parent_block_reason,
    reopen_held_run,
    save_run_artifact,
    superseded_child_check,
)
from admin_view_models import (
    is_child_run,
    owner_state,
    run_projection,
    run_submission_disposition,
)
from delegated_delivery_safety import PRODUCTS, _digest
from main import app


class SupersededChildActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self._temp_dir.name) / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.safety_dir = Path(self._temp_dir.name) / "safety"
        self.safety_dir.mkdir(parents=True, exist_ok=True)

        self._patch_runs = patch.object(admin_store, "admin_runs_dir", return_value=self.runs_dir)
        self._patch_safety = patch.object(s_store, "_local_root", return_value=self.safety_dir)
        self._patch_runs.start()
        self._patch_safety.start()

        self._saved_env = {
            k: os.environ.get(k)
            for k in [
                "GENIE_ADMIN_PASSWORD",
                "GENIE_ADMIN_SAFETY_LOCAL_DIR",
                "GENIE_ADMIN_ALLOW_LOCAL_SAFETY_STORE",
                "GENIE_ADMIN_ARTIFACT_BUCKET",
                "GENIE_ARTIFACT_BUCKET",
            ]
        }
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-secret"
        os.environ["GENIE_ADMIN_SAFETY_LOCAL_DIR"] = str(self.safety_dir)
        os.environ["GENIE_ADMIN_ALLOW_LOCAL_SAFETY_STORE"] = "1"
        os.environ.pop("GENIE_ADMIN_ARTIFACT_BUCKET", None)
        os.environ.pop("GENIE_ARTIFACT_BUCKET", None)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._patch_safety.stop()
        self._patch_runs.stop()
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._temp_dir.cleanup()

    def _login(self) -> None:
        self.client.post("/admin/login", data={"password": "test-secret"}, follow_redirects=False)

    def _save_run(self, meta: dict) -> None:
        save_run_artifact(meta, email_html="<p>briefing</p>")

    def test_summary_shaped_lineage_accepted_parent_renders_reference_only_detail(self) -> None:
        """Exact incident shape: regen_parent_run_id + auto_parent_id, parent is accepted.

        Child detail is reference-only with parent link; approval CTA, reissue form, hold form suppressed.
        """
        parent_id = "20261028_123001_keysuri_global_tech_d26e88e2"
        child_id = "20261028_124632_keysuri_global_tech_acf60d79"

        parent_meta = {
            "run_id": parent_id,
            "mode": "keysuri_global_tech",
            "program_id": "keysuri_global_tech",
            "validation_result": "pass",
            "customer_delivery_status": "smtp_accepted",
            "customer_email_delivery_status": "smtp_accepted",
            "smtp_accepted_recipient_count": 10,
            "customer_delivery_accepted_count": 10,
            "smtp_refused_recipient_count": 0,
        }
        child_meta = {
            "run_id": child_id,
            "mode": "keysuri_global_tech",
            "program_id": "keysuri_global_tech",
            "regen_parent_run_id": parent_id,
            "automatic_remediation_parent_run_id": parent_id,
            "automatic_remediation_triggered": True,
            "automatic_remediation_result": "child_still_reviewable",
            "automatic_remediation_child_run_id": child_id,
            "validation_result": "pass",
            "customer_delivery_status": "not_sent",
            "customer_email_delivery_status": "not_sent",
            "owner_review_status": "pending_review",
            "safety_verdict": "SAFE",
            "editorial_verdict": "REVIEW",
            "reader_surface_enforced": True,
            "reader_surface_complete": True,
        }
        self._save_run(parent_meta)
        self._save_run(child_meta)

        self._login()
        resp = self.client.get(f"/admin/runs/{child_id}")
        self.assertEqual(resp.status_code, 200)
        html = resp.text

        # 1. Reference-only notice present with link to parent run
        self.assertIn("참고용 보존 실행", html)
        self.assertIn(f"/admin/runs/{parent_id}", html)
        self.assertNotIn("(Superseded Child)", html)

        # 2. No approval CTA button/link
        self.assertNotIn(f"/admin/runs/{child_id}/approve-confirm", html)
        self.assertIn("승인 발송 불가: 동일 발행일의 원본 실행이 이미 처리되어", html)

        # 3. No reissue form
        self.assertNotIn(f'action="/admin/runs/{child_id}/reissue"', html)
        self.assertIn("재발행 불가: 동일 발행일의 원본 실행이 이미 처리되어", html)

        # 4. No hold form
        self.assertNotIn(f'action="/admin/runs/{child_id}/hold"', html)
        self.assertNotIn(f'action="/admin/runs/{child_id}/reopen"', html)

        # 5. Auto remediation panel does NOT render self-link or review instruction
        self.assertNotIn("새 교정본 열기 →", html)
        self.assertIn("원본 실행이 이미 처리되어 추가 수동 재발행은 하지 않습니다.", html)

        # 6. Graded quality panel does NOT instruct to approve or reissue
        self.assertNotIn("수정 요청, 거절, 또는 경고 확인 후 승인을 선택할 수 있습니다.", html)

        # 7. Main validation panel is reference-only without fresh approval/reissue advice
        self.assertNotIn("고객 발송 전 확인하거나 수정을 요청하세요", html)
        self.assertNotIn("경고 확인 후 승인 가능", html)
        self.assertNotIn("보류된 검수입니다. 다시 검수하기로 전환한 뒤 승인하세요.", html)
        self.assertIn("참고용 보존", html)
        self.assertIn("안전성: 안전", html)
        self.assertIn("편집 품질: 검토 필요", html)
        self.assertIn("참고용 보존 (새 발송 차단)", html)
        self.assertIn("과거 교정 이력 (참고용)", html)

    @patch("admin_routes._verify_csrf", return_value=True)
    @patch("admin_approval.create_approval_snapshot")
    @patch("email_sender.send_genie_email")
    @patch("admin_routes.run_keysuri_text_only_reissue")
    @patch("admin_routes.run_keysuri_image_only_reissue")
    @patch("admin_routes.run_keysuri_text_and_image_reissue")
    @patch("admin_routes.execute_orchestrator_run")
    def test_direct_stale_routes_fail_closed_zero_effects(
        self,
        mock_orch: MagicMock,
        mock_k_text_img: MagicMock,
        mock_k_img: MagicMock,
        mock_k_text: MagicMock,
        mock_sender: MagicMock,
        mock_snapshot: MagicMock,
        mock_csrf: MagicMock,
    ) -> None:
        """Direct GET /approve-confirm, POST /approve, POST /reissue, POST /hold produce zero effects."""
        parent_id = "20261028_123001_keysuri_global_tech_d26e88e2"
        child_id = "20261028_124632_keysuri_global_tech_acf60d79"

        parent_meta = {
            "run_id": parent_id,
            "mode": "keysuri_global_tech",
            "validation_result": "pass",
            "customer_delivery_status": "smtp_accepted",
            "smtp_accepted_recipient_count": 10,
        }
        child_meta = {
            "run_id": child_id,
            "mode": "keysuri_global_tech",
            "regen_parent_run_id": parent_id,
            "validation_result": "pass",
            "customer_delivery_status": "not_sent",
            "customer_email_delivery_status": "not_sent",
            "owner_review_status": "pending_review",
        }
        self._save_run(parent_meta)
        self._save_run(child_meta)

        self._login()

        # 1. Direct GET /approve-confirm -> 400, no snapshot created
        confirm_resp = self.client.get(f"/admin/runs/{child_id}/approve-confirm")
        self.assertEqual(confirm_resp.status_code, 400)
        self.assertIn("Approve blocked", confirm_resp.text)
        mock_snapshot.assert_not_called()
        self.assertEqual(len(list(self.safety_dir.glob("approval_snapshots/*"))), 0)

        # 2. Direct POST /approve -> 303 redirect with error code
        approve_resp = self.client.post(
            f"/admin/runs/{child_id}/approve",
            data={
                "customer_send_confirm": "1",
                "csrf_token": "valid_token",
            },
            follow_redirects=False,
        )
        self.assertEqual(approve_resp.status_code, 303)
        self.assertIn("approve_error=superseded_child_reference_only", approve_resp.headers["location"])
        mock_sender.assert_not_called()

        # Child artifact remains unmutated
        fresh_child = load_run_artifact(child_id)
        self.assertEqual(fresh_child.get("customer_delivery_status"), "not_sent")

        # 3. Direct POST /reissue -> 400 blocked
        reissue_resp = self.client.post(
            f"/admin/runs/{child_id}/reissue",
            data={
                "reissue_scope": "body_only",
                "reason_option": "qa_check",
                "csrf_token": "valid_token",
            },
            follow_redirects=False,
        )
        self.assertEqual(reissue_resp.status_code, 400)
        self.assertIn("Reissue blocked", reissue_resp.text)
        mock_k_text.assert_not_called()
        mock_k_img.assert_not_called()
        mock_k_text_img.assert_not_called()
        mock_orch.assert_not_called()

        # 4. Direct POST /hold -> fails without mutating
        hold_resp = self.client.post(
            f"/admin/runs/{child_id}/hold",
            data={"csrf_token": "valid_token"},
            follow_redirects=False,
        )
        self.assertEqual(hold_resp.status_code, 303)
        fresh_child = load_run_artifact(child_id)
        self.assertNotEqual(fresh_child.get("owner_review_status"), "held")

        # 5. Direct POST /reopen -> fails without mutating
        reopen_resp = self.client.post(
            f"/admin/runs/{child_id}/reopen",
            data={"csrf_token": "valid_token"},
            follow_redirects=False,
        )
        self.assertEqual(reopen_resp.status_code, 303)

        # Publication attempt store remains unchanged
        self.assertEqual(len(list(self.safety_dir.glob("publication_attempts/*"))), 0)

    def test_canonical_attempt_flags_and_publication_boundaries(self) -> None:
        """Genuine attempt flags trigger superseded boundary."""
        parent_id = "20261028_123001_keysuri_global_tech_d26e88e2"
        child_id = "20261028_124632_keysuri_global_tech_acf60d79"

        attempt_flags = [
            {"customer_email_smtp_attempted": True},
            {"smtp_attempted": True},
            {"customer_email_delivery_attempted": True},
            {"customer_delivery_attempted": True},
            {"customer_delivery_attempted_at": "2026-10-28T12:35:00+09:00"},
            {"customer_delivery_attempt_count": 1},
            {"customer_delivery_status": "partial_refusal"},
            {"customer_email_delivery_status": "outcome_unknown"},
            {"smtp_accepted_recipient_count": 5},
            {"customer_delivery_accepted_count": 5},
            {"smtp_refused_recipient_count": 1},
            {"customer_delivery_refused_count": 1},
            {"customer_delivery_unknown_count": 2},
            {"smtp_unknown_recipient_count": 2},
            {"smtp_refused_recipients_masked": ["u***@example.com"]},
        ]
        for flag in attempt_flags:
            p_meta = {
                "run_id": parent_id,
                "mode": "keysuri_global_tech",
                "customer_delivery_status": "not_sent",
                "customer_email_delivery_status": "not_sent",
                **flag,
            }
            c_meta = {
                "run_id": child_id,
                "mode": "keysuri_global_tech",
                "regen_parent_run_id": parent_id,
                "customer_delivery_status": "not_sent",
            }
            self._save_run(p_meta)
            self._save_run(c_meta)

            is_sup, pid, pmeta, reason = superseded_child_check(c_meta)
            self.assertTrue(is_sup, f"Failed for flag: {flag}")
            self.assertEqual(reason, "superseded_child_reference_only")

    def test_target_count_alone_remains_eligible(self) -> None:
        """Unsent parent with recipient target count alone does not make parent submitted."""
        parent_id = "20261028_123001_keysuri_global_tech_d26e88e2"
        child_id = "20261028_124632_keysuri_global_tech_acf60d79"

        parent_meta = {
            "run_id": parent_id,
            "mode": "keysuri_global_tech",
            "customer_delivery_status": "not_sent",
            "customer_email_delivery_status": "not_sent",
            "customer_email_recipient_count": 15,
            "customer_recipient_count": 15,
            "customer_delivery_target_count": 15,
            "smtp_accepted_recipient_count": 0,
            "smtp_refused_recipient_count": 0,
            "customer_delivery_unknown_count": 0,
        }
        child_meta = {
            "run_id": child_id,
            "mode": "keysuri_global_tech",
            "regen_parent_run_id": parent_id,
            "customer_delivery_status": "not_sent",
            "customer_email_delivery_status": "not_sent",
        }
        self._save_run(parent_meta)
        self._save_run(child_meta)

        is_sup, pid, pmeta, reason = superseded_child_check(child_meta)
        self.assertFalse(is_sup)
        self.assertEqual(reason, "")

    def test_durable_only_reservation_stops_effects(self) -> None:
        """A publication_attempts record in safety store stops effects even if parent artifact status is not_sent."""
        parent_id = "20261028_123001_keysuri_global_tech_d26e88e2"
        child_id = "20261028_124632_keysuri_global_tech_acf60d79"

        parent_meta = {
            "run_id": parent_id,
            "mode": "keysuri_global_tech",
            "customer_delivery_status": "not_sent",
            "customer_email_delivery_status": "not_sent",
        }
        child_meta = {
            "run_id": child_id,
            "mode": "keysuri_global_tech",
            "regen_parent_run_id": parent_id,
            "customer_delivery_status": "not_sent",
        }
        self._save_run(parent_meta)
        self._save_run(child_meta)

        # Write durable attempt reservation
        product = PRODUCTS["keysuri_global_tech"]
        day = "2026-10-28"
        att_id = "publication_" + _digest([product, day])
        s_store._write_json(
            f"publication_attempts/{att_id}.json",
            {"attempt_id": att_id, "run_id": parent_id, "product_code": product, "publication_date": day},
        )

        is_sup, pid, pmeta, reason = superseded_child_check(child_meta)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "superseded_child_reference_only")

    def test_missing_or_corrupt_parent_fails_closed_to_reconciliation(self) -> None:
        """Parent artifact not found or invalid JSON fails closed to parent_reconciliation_required."""
        child_id = "20261028_124632_keysuri_global_tech_acf60d79"
        parent_id = "20261028_123001_keysuri_global_tech_d26e88e2"

        child_meta = {
            "run_id": child_id,
            "mode": "keysuri_global_tech",
            "regen_parent_run_id": parent_id,
        }
        # Parent artifact is NOT saved -> missing
        is_sup, pid, pmeta, reason = superseded_child_check(child_meta)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "parent_reconciliation_required")

        # Now test corrupt parent JSON
        parent_file = self.runs_dir / f"{parent_id}.json"
        parent_file.write_text("{bad json...", encoding="utf-8")
        is_sup, pid, pmeta, reason = superseded_child_check(child_meta)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "parent_reconciliation_required")

    def test_malformed_count_fails_closed(self) -> None:
        """Non-numeric string in delivery count field fails closed to reconciliation."""
        parent_id = "20261028_123001_keysuri_global_tech_d26e88e2"
        child_id = "20261028_124632_keysuri_global_tech_acf60d79"

        parent_meta = {
            "run_id": parent_id,
            "mode": "keysuri_global_tech",
            "customer_delivery_status": "not_sent",
            "smtp_accepted_recipient_count": "MALFORMED_COUNT",
        }
        child_meta = {
            "run_id": child_id,
            "mode": "keysuri_global_tech",
            "regen_parent_run_id": parent_id,
        }
        self._save_run(parent_meta)
        self._save_run(child_meta)

        is_sup, pid, pmeta, reason = superseded_child_check(child_meta)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "parent_reconciliation_required")

    def test_mismatched_mode_or_date_fails_closed(self) -> None:
        """Date mismatch, mode mismatch, or metadata contradicting ID fails closed."""
        child_id = "20261028_124632_keysuri_global_tech_acf60d79"

        # 1. Different date
        c1 = {"run_id": child_id, "mode": "keysuri_global_tech", "parent_run_id": "20261027_123001_keysuri_global_tech_d26e88e2"}
        is_sup, _, _, reason = superseded_child_check(c1)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "parent_reconciliation_required")

        # 2. Different mode encoded in run IDs
        c2 = {"run_id": child_id, "mode": "keysuri_global_tech", "parent_run_id": "20261028_063000_today_genie_11223344"}
        is_sup, _, _, reason = superseded_child_check(c2)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "parent_reconciliation_required")

        # 3. Metadata mode contradicts ID encoded mode
        c3 = {"run_id": child_id, "mode": "today_genie", "parent_run_id": "20261028_123001_keysuri_global_tech_d26e88e2"}
        is_sup, _, _, reason = superseded_child_check(c3)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "parent_reconciliation_required")

    def test_conflicting_and_cyclic_lineage_fails_closed(self) -> None:
        """Conflicting parent aliases or cyclic self lineage fails closed."""
        child_id = "20261028_124632_keysuri_global_tech_acf60d79"

        # Conflicting parents
        c1 = {
            "run_id": child_id,
            "parent_run_id": "20261028_123001_keysuri_global_tech_d26e88e2",
            "regen_parent_run_id": "20261028_123002_keysuri_global_tech_ffffffff",
        }
        is_child, parent_id, has_conflict = extract_parent_lineage(c1)
        self.assertTrue(is_child)
        self.assertTrue(has_conflict)
        self.assertIsNone(parent_id)
        self.assertEqual(extract_parent_run_id(c1), "")
        self.assertEqual(superseded_child_check(c1)[3], "parent_reconciliation_required")

        # Cyclic parent_run_id == self
        c2 = {"run_id": child_id, "parent_run_id": child_id}
        is_child, parent_id, has_conflict = extract_parent_lineage(c2)
        self.assertTrue(is_child)
        self.assertTrue(has_conflict)
        self.assertEqual(extract_parent_run_id(c2), "")
        self.assertEqual(superseded_child_check(c2)[3], "parent_reconciliation_required")

        # Cyclic regen_parent_run_id == self
        c3 = {"run_id": child_id, "regen_parent_run_id": child_id}
        is_child, parent_id, has_conflict = extract_parent_lineage(c3)
        self.assertTrue(is_child)
        self.assertTrue(has_conflict)
        self.assertEqual(extract_parent_run_id(c3), "")
        self.assertEqual(superseded_child_check(c3)[3], "parent_reconciliation_required")

    def test_self_stamp_natural_run_is_not_child(self) -> None:
        """A natural run with automatic_remediation_parent_run_id == self is not a child."""
        natural_id = "20261028_123001_keysuri_global_tech_d26e88e2"
        meta = {
            "run_id": natural_id,
            "mode": "keysuri_global_tech",
            "automatic_remediation_parent_run_id": natural_id,
            "automatic_remediation_is_child": False,
        }
        is_child, parent_id, has_conflict = extract_parent_lineage(meta)
        self.assertFalse(is_child)
        self.assertIsNone(parent_id)
        self.assertFalse(has_conflict)
        self.assertEqual(extract_parent_run_id(meta), "")
        self.assertFalse(is_child_run(meta))
        self.assertFalse(superseded_child_check(meta)[0])

    def test_held_superseded_child_detail_and_can_approve_reason(self) -> None:
        """Held child with accepted parent (real production shape of acf60d79).

        can_approve_customer_send returns superseded_child_reference_only (not review_held).
        GET /approve-confirm returns 400 with superseded_child_reference_only error.
        Detail page renders reference-only copy with NO held advice or validation approval prompts.
        """
        parent_id = "20261028_123001_keysuri_global_tech_d26e88e2"
        child_id = "20261028_124632_keysuri_global_tech_acf60d79"

        parent_meta = {
            "run_id": parent_id,
            "mode": "keysuri_global_tech",
            "program_id": "keysuri_global_tech",
            "validation_result": "pass",
            "customer_delivery_status": "smtp_accepted",
            "customer_email_delivery_status": "smtp_accepted",
            "smtp_accepted_recipient_count": 10,
            "customer_delivery_accepted_count": 10,
            "smtp_refused_recipient_count": 0,
        }
        child_meta = {
            "run_id": child_id,
            "mode": "keysuri_global_tech",
            "program_id": "keysuri_global_tech",
            "regen_parent_run_id": parent_id,
            "automatic_remediation_parent_run_id": parent_id,
            "automatic_remediation_triggered": True,
            "automatic_remediation_result": "child_still_reviewable",
            "automatic_remediation_child_run_id": child_id,
            "validation_result": "pass",
            "customer_delivery_status": "not_sent",
            "customer_email_delivery_status": "not_sent",
            "owner_review_status": "held",
            "safety_verdict": "SAFE",
            "editorial_verdict": "REVIEW",
            "reader_surface_enforced": True,
            "reader_surface_complete": True,
        }
        self._save_run(parent_meta)
        self._save_run(child_meta)

        # 1. can_approve_customer_send precedence (superseded over review_held)
        can_appr, reason = can_approve_customer_send(child_meta, has_email_html=True, allow_manual_quality_warning=True)
        self.assertFalse(can_appr)
        self.assertEqual(reason, "superseded_child_reference_only")

        # 2. Direct approve-confirm route returns 400 with superseded error
        self._login()
        resp_confirm = self.client.get(f"/admin/runs/{child_id}/approve-confirm")
        self.assertEqual(resp_confirm.status_code, 400)
        self.assertIn("Approve blocked", resp_confirm.text)
        self.assertIn("동일 발행일의 원본 실행이 이미 처리되어 교정본 발송이 차단되었습니다 (참고용 보존).", resp_confirm.text)
        self.assertNotIn("보류된 검수입니다. 다시 검수하기로 전환한 뒤 승인하세요.", resp_confirm.text)

        # 3. Detail page inspection
        resp = self.client.get(f"/admin/runs/{child_id}")
        self.assertEqual(resp.status_code, 200)
        html = resp.text

        # Absent misleading phrases
        self.assertNotIn("고객 발송 전 확인하거나 수정을 요청하세요", html)
        self.assertNotIn("경고 확인 후 승인 가능", html)
        self.assertNotIn("보류된 검수입니다. 다시 검수하기로 전환한 뒤 승인하세요.", html)
        self.assertNotIn("다시 검수하기", html)
        self.assertNotIn("고객 발송 보류", html)

        # Present truthful reference-only phrases
        self.assertIn("참고용 보존 실행", html)
        self.assertIn(f"/admin/runs/{parent_id}", html)
        self.assertIn("안전성: 안전", html)
        self.assertIn("편집 품질: 검토 필요", html)
        self.assertIn("참고용 보존 (새 발송 차단)", html)
        self.assertIn("과거 교정 이력 (참고용)", html)
        self.assertIn("동일 발행일의 원본 실행이 이미 처리되어 교정본 발송이 차단되었습니다 (참고용 보존).", html)

    def test_future_day_and_held_controls_preserved(self) -> None:
        """Future-day natural runs and held Today controls remain properly handled."""
        future_id = "20261029_063000_today_genie_11223344"
        future_meta = {
            "run_id": future_id,
            "mode": "today_genie",
            "validation_result": "pass",
            "customer_delivery_status": "not_sent",
            "owner_review_status": "pending_review",
        }
        self._save_run(future_meta)
        self.assertFalse(superseded_child_check(future_meta)[0])

        held_id = "20261028_063000_today_genie_aabbccdd"
        held_meta = {
            "run_id": held_id,
            "mode": "today_genie",
            "validation_result": "pass",
            "customer_delivery_status": "not_sent",
            "owner_review_status": "held",
        }
        self._save_run(held_meta)
        can_appr, reason = can_approve_customer_send(held_meta, has_email_html=True)
        self.assertFalse(can_appr)
        self.assertEqual(reason, "review_held")

        self._login()
        resp = self.client.get(f"/admin/runs/{held_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("다시 검수하기", resp.text)
        self.assertIn("보류된 검수입니다. 다시 검수하기로 전환한 뒤 승인하세요.", resp.text)

    def test_published_original_natural_run_detail_shows_historical_advice_and_truthful_preview(self) -> None:
        """Natural original run with accepted delivery shows historical advice and truthful preview form."""
        parent_id = "20261028_123001_keysuri_global_tech_d26e88e2"
        child_id = "20261028_124632_keysuri_global_tech_acf60d79"
        parent_meta = {
            "run_id": parent_id,
            "mode": "keysuri_global_tech",
            "program_id": "keysuri_global_tech",
            "automatic_remediation_parent_run_id": parent_id,
            "automatic_remediation_triggered": True,
            "automatic_remediation_result": "child_still_reviewable",
            "automatic_remediation_child_run_id": child_id,
            "automatic_remediation_scope": "body_only",
            "automatic_remediation_original_issue_codes": ["keysuri_korean_repeated_token_repaired"],
            "owner_review_status": "approved",
            "validation_result": "pass",
            "safety_verdict": "SAFE",
            "editorial_verdict": "REVIEW",
            "reader_surface_enforced": True,
            "reader_surface_complete": True,
            "customer_delivery_status": "smtp_accepted",
            "customer_email_delivery_status": "smtp_accepted",
            "smtp_accepted_recipient_count": 14,
            "customer_delivery_accepted_count": 14,
            "smtp_refused_recipient_count": 0,
            "customer_email_recipient_count": 14,
        }
        self._save_run(parent_meta)

        # 1. Authoritative submission disposition
        is_sub, is_acc, disp = run_submission_disposition(parent_meta)
        self.assertTrue(is_sub)
        self.assertTrue(is_acc)
        self.assertEqual(disp, "accepted")

        # 2. Detail rendering
        self._login()
        resp = self.client.get(f"/admin/runs/{parent_id}")
        self.assertEqual(resp.status_code, 200)
        html = resp.text

        # Delivery 14 remains
        self.assertIn("14", html)
        self.assertIn("SMTP 접수", html)
        self.assertIn("SMTP SUBMITTED", html)

        # Absent fresh review/approval advice
        self.assertNotIn("고객 발송 전 확인하거나 수정을 요청하세요", html)
        self.assertNotIn("경고 확인 후 승인 가능", html)
        self.assertNotIn("수정 요청, 거절, 또는 경고 확인 후 승인을 선택할 수 있습니다.", html)
        self.assertNotIn("새 교정본 열기 →", html)
        self.assertNotIn("고객 발송: 운영자 승인 필요", html)

        # Historical advice & quality facts preserved
        self.assertIn("과거 검수 이력", html)
        self.assertIn("안전성: 안전", html)
        self.assertIn("편집 품질: 검토 필요", html)
        self.assertIn("과거 검수 이력 (새 발송 차단)", html)
        self.assertIn("과거 자동 교정 이력 (참고용)", html)
        self.assertIn("교정 수행 결과: 자동 교정본을 만들었지만 아직 검수가 필요합니다.", html)
        self.assertIn("과거 교정본 열기 (참고용) →", html)
        self.assertIn(f"/admin/runs/{child_id}", html)

        # Truthful operator preview form
        self.assertIn(f'action="/admin/runs/{parent_id}/reissue"', html)
        self.assertIn("운영자 참고용 미리보기 생성", html)
        self.assertIn("참고용 미리보기 생성", html)
        self.assertIn("생성본을 승인하더라도 이미 발송된 고객 에디션은 재전송되지 않습니다", html)
        self.assertNotIn("재발행 불가", html)

    def test_submission_disposition_distinguishes_reconciliation_and_unsubmitted(self) -> None:
        """Outcome unknown/refused stay reconciliation; approval-only/target-only remain unsubmitted."""
        # Unknown delivery
        meta_unknown = {
            "run_id": "20261028_123001_keysuri_global_tech_11111111",
            "mode": "keysuri_global_tech",
            "customer_delivery_status": "outcome_unknown",
        }
        is_sub, is_acc, disp = run_submission_disposition(meta_unknown)
        self.assertTrue(is_sub)
        self.assertFalse(is_acc)
        self.assertEqual(disp, "reconciliation")

        # Refused all delivery
        meta_refused = {
            "run_id": "20261028_123001_keysuri_global_tech_22222222",
            "mode": "keysuri_global_tech",
            "customer_delivery_status": "refused_all",
            "smtp_refused_recipient_count": 14,
        }
        is_sub, is_acc, disp = run_submission_disposition(meta_refused)
        self.assertTrue(is_sub)
        self.assertFalse(is_acc)
        self.assertEqual(disp, "reconciliation")

        # Partial refusal delivery
        meta_partial = {
            "run_id": "20261028_123001_keysuri_global_tech_33333333",
            "mode": "keysuri_global_tech",
            "customer_delivery_status": "partial_refusal",
            "smtp_accepted_recipient_count": 10,
            "smtp_refused_recipient_count": 4,
        }
        is_sub, is_acc, disp = run_submission_disposition(meta_partial)
        self.assertTrue(is_sub)
        self.assertFalse(is_acc)
        self.assertEqual(disp, "reconciliation")

        # Approval-only (not_sent)
        meta_appr_only = {
            "run_id": "20261028_123001_keysuri_global_tech_44444444",
            "mode": "keysuri_global_tech",
            "owner_review_status": "approved",
            "customer_delivery_status": "not_sent",
        }
        is_sub, is_acc, disp = run_submission_disposition(meta_appr_only)
        self.assertFalse(is_sub)
        self.assertFalse(is_acc)
        self.assertEqual(disp, "unsubmitted")

        # Target-only (not_sent)
        meta_target_only = {
            "run_id": "20261028_123001_keysuri_global_tech_55555555",
            "mode": "keysuri_global_tech",
            "customer_email_recipient_count": 14,
            "customer_delivery_status": "not_sent",
        }
        is_sub, is_acc, disp = run_submission_disposition(meta_target_only)
        self.assertFalse(is_sub)
        self.assertFalse(is_acc)
        self.assertEqual(disp, "unsubmitted")

    @patch("admin_routes._verify_csrf", return_value=True)
    @patch("admin_approval.create_approval_snapshot")
    @patch("email_sender.send_genie_email")
    def test_natural_mismatched_alias_regression_fails_closed_zero_effects(
        self,
        mock_sender: MagicMock,
        mock_snapshot: MagicMock,
        mock_csrf: MagicMock,
    ) -> None:
        """Natural run with canonical outcome unknown alias fails closed with zero send effects."""
        natural_id = "20261028_123001_keysuri_global_tech_d26e88e2"
        meta = {
            "run_id": natural_id,
            "mode": "keysuri_global_tech",
            "program_id": "keysuri_global_tech",
            "automatic_remediation_parent_run_id": natural_id,
            "validation_result": "pass",
            "safety_verdict": "SAFE",
            "editorial_verdict": "READY",
            "reader_surface_enforced": True,
            "reader_surface_complete": True,
            "customer_delivery_status": "not_sent",
            "customer_email_delivery_status": "outcome_unknown",
            "owner_review_status": "pending_review",
        }
        self._save_run(meta)

        # 1. can_approve_customer_send fails closed to delivery_outcome_unknown
        can_appr, reason = can_approve_customer_send(meta, has_email_html=True)
        self.assertFalse(can_appr)
        self.assertEqual(reason, "delivery_outcome_unknown")

        # 2. Direct GET /approve-confirm returns 400 with exact reason-specific Korean message
        self._login()
        resp_confirm = self.client.get(f"/admin/runs/{natural_id}/approve-confirm")
        self.assertEqual(resp_confirm.status_code, 400)
        self.assertIn("Approve blocked", resp_confirm.text)
        self.assertIn("SMTP 제출 후 결과를 확정하지 못했습니다. 중복 위험 때문에 새 발송을 차단합니다.", resp_confirm.text)
        mock_snapshot.assert_not_called()

        # 3. Direct POST /approve redirects 303 with exact approve_error=delivery_outcome_unknown
        resp_post = self.client.post(
            f"/admin/runs/{natural_id}/approve",
            data={
                "csrf_token": "valid",
                "customer_send_confirm": "1",
                "approve_nonce": "n" * 32,
            },
            follow_redirects=False,
        )
        self.assertEqual(resp_post.status_code, 303)
        self.assertIn("approve_error=delivery_outcome_unknown", resp_post.headers.get("location", ""))
        mock_snapshot.assert_not_called()
        mock_sender.assert_not_called()

        # 4. Artifact remains unchanged
        loaded = load_run_artifact(natural_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.get("customer_delivery_status"), "not_sent")
        self.assertEqual(loaded.get("customer_email_delivery_status"), "outcome_unknown")
        self.assertNotIn("delivery_attempted", loaded or {})
        self.assertNotIn("customer_delivery_events", loaded or {})



if __name__ == "__main__":
    unittest.main()
