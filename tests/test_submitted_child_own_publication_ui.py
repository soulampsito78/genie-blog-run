"""Synthetic tests for own-child publication day-ledger attribution and Admin UI rendering."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import admin_safety_store as s_store
import admin_store
from admin_store import (
    can_approve_customer_send,
    save_run_artifact,
    superseded_child_check,
)
from delegated_delivery_safety import PRODUCTS, _digest
from main import app


class SubmittedChildOwnPublicationUITests(unittest.TestCase):
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

    def _save_run(self, meta: dict, email_html: str = "<p>briefing</p>") -> None:
        save_run_artifact(meta, email_html=email_html)

    def test_same_child_durable_publication_not_classified_as_superseded(self) -> None:
        parent_id = "20261105_063001_today_genie_a1b2c3d4"
        child_id = "20261105_064500_today_genie_e5f6a7b8"
        cand_sha = "a" * 64
        rev_id = "del_rev_synthetic_123"

        parent_meta = {
            "run_id": parent_id,
            "mode": "today_genie",
            "program_id": "today_genie",
            "customer_delivery_status": "not_sent",
            "customer_email_delivery_status": "not_sent",
            "owner_review_status": "held",
        }
        child_meta = {
            "run_id": child_id,
            "mode": "today_genie",
            "program_id": "today_genie",
            "regen_parent_run_id": parent_id,
            "automatic_remediation_parent_run_id": parent_id,
            "approval_source": "DELEGATED_WORK_REVIEW",
            "delegated_review_status": "passed",
            "delegated_review_id": rev_id,
            "delegated_candidate_sha256": cand_sha,
            "customer_delivery_status": "ACCEPTED_ALL",
            "customer_email_delivery_status": "ACCEPTED_ALL",
            "smtp_accepted_recipient_count": 14,
            "customer_delivery_accepted_count": 14,
            "customer_delivery_attempt_count": 1,
            "customer_delivery_attempted": True,
            "validation_result": "pass",
            "owner_review_status": "pending_review",
        }
        self._save_run(parent_meta)
        self._save_run(child_meta)

        s_product = PRODUCTS["today_genie"]
        s_day = "2026-11-05"
        s_att = "publication_" + _digest([s_product, s_day])
        # Actual producer schema: attempt contains run_id and candidate_sha256; outcome references attempt_id
        att_payload = {
            "attempt_id": s_att,
            "run_id": child_id,
            "product_code": s_product,
            "publication_date": s_day,
            "candidate_sha256": cand_sha,
            "review_id": rev_id,
        }
        out_payload = {
            "attempt_id": s_att,
            "outcome": "PROVIDER_ACCEPTED",
            "evidence": {"attempt_id": s_att},
        }
        (self.safety_dir / "publication_attempts").mkdir(parents=True, exist_ok=True)
        (self.safety_dir / "publication_outcomes").mkdir(parents=True, exist_ok=True)
        (self.safety_dir / "publication_attempts" / f"{s_att}.json").write_text(
            json.dumps(att_payload), encoding="utf-8"
        )
        (self.safety_dir / "publication_outcomes" / f"{s_att}.json").write_text(
            json.dumps(out_payload), encoding="utf-8"
        )

        is_sup, p_id, _, reason = superseded_child_check(child_meta)
        self.assertFalse(is_sup)
        self.assertEqual(reason, "")

        can_app, app_reason = can_approve_customer_send(child_meta, has_email_html=True)
        self.assertFalse(can_app)
        self.assertEqual(app_reason, "customer_already_sent")

        self._login()
        resp = self.client.get(f"/admin/runs/{child_id}")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertNotIn("참고용 보존 실행", html)
        self.assertNotIn("동일 발행일의 원본 실행", html)
        self.assertIn("SMTP 접수 완료", html)
        self.assertIn("위임 AI 검수 완료", html)
        self.assertNotIn("HUMAN_OWNER", html)

    def test_real_parent_or_sibling_durable_publication_supersedes_child(self) -> None:
        parent_id = "20261105_063001_today_genie_a1b2c3d4"
        child_id = "20261105_064500_today_genie_e5f6a7b8"
        sibling_id = "20261105_064000_today_genie_11223344"

        parent_meta = {
            "run_id": parent_id,
            "mode": "today_genie",
            "customer_delivery_status": "not_sent",
        }
        child_meta = {
            "run_id": child_id,
            "mode": "today_genie",
            "regen_parent_run_id": parent_id,
            "customer_delivery_status": "not_sent",
        }
        self._save_run(parent_meta)
        self._save_run(child_meta)

        s_product = PRODUCTS["today_genie"]
        s_day = "2026-11-05"
        s_att = "publication_" + _digest([s_product, s_day])
        (self.safety_dir / "publication_attempts").mkdir(parents=True, exist_ok=True)

        # 1. Attributed to parent
        (self.safety_dir / "publication_attempts" / f"{s_att}.json").write_text(
            json.dumps({"attempt_id": s_att, "run_id": parent_id, "product_code": s_product, "publication_date": s_day}),
            encoding="utf-8",
        )
        is_sup, p_id, _, reason = superseded_child_check(child_meta)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "superseded_child_reference_only")

        # 2. Attributed to sibling
        (self.safety_dir / "publication_attempts" / f"{s_att}.json").write_text(
            json.dumps({"attempt_id": s_att, "run_id": sibling_id, "product_code": s_product, "publication_date": s_day}),
            encoding="utf-8",
        )
        is_sup, p_id, _, reason = superseded_child_check(child_meta)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "superseded_child_reference_only")

    def test_corrupt_or_conflicting_durable_attribution_fails_closed(self) -> None:
        parent_id = "20261105_063001_today_genie_a1b2c3d4"
        child_id = "20261105_064500_today_genie_e5f6a7b8"
        cand_sha = "b" * 64
        rev_id = "del_rev_synthetic_456"

        parent_meta = {"run_id": parent_id, "mode": "today_genie", "customer_delivery_status": "not_sent"}
        child_meta = {
            "run_id": child_id,
            "mode": "today_genie",
            "regen_parent_run_id": parent_id,
            "delegated_candidate_sha256": cand_sha,
            "delegated_review_id": rev_id,
            "customer_delivery_status": "not_sent",
        }
        self._save_run(parent_meta)
        self._save_run(child_meta)

        s_product = PRODUCTS["today_genie"]
        s_day = "2026-11-05"
        s_att = "publication_" + _digest([s_product, s_day])
        (self.safety_dir / "publication_attempts").mkdir(parents=True, exist_ok=True)

        # 1. Corrupt JSON
        (self.safety_dir / "publication_attempts" / f"{s_att}.json").write_text("NOT_VALID_JSON", encoding="utf-8")
        is_sup, _, _, reason = superseded_child_check(child_meta)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "parent_reconciliation_required")

        # 2. Candidate SHA mismatch
        (self.safety_dir / "publication_attempts" / f"{s_att}.json").write_text(
            json.dumps({
                "attempt_id": s_att,
                "run_id": child_id,
                "product_code": s_product,
                "publication_date": s_day,
                "candidate_sha256": "different_cand_sha",
                "review_id": rev_id,
            }),
            encoding="utf-8",
        )
        is_sup, _, _, reason = superseded_child_check(child_meta)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "parent_reconciliation_required")

    def test_unknown_delivery_own_claim_retains_reconciliation_wording(self) -> None:
        parent_id = "20261105_063001_today_genie_a1b2c3d4"
        child_id = "20261105_064500_today_genie_e5f6a7b8"

        parent_meta = {"run_id": parent_id, "mode": "today_genie", "customer_delivery_status": "not_sent"}
        child_meta = {
            "run_id": child_id,
            "mode": "today_genie",
            "program_id": "today_genie",
            "regen_parent_run_id": parent_id,
            "approval_source": "DELEGATED_WORK_REVIEW",
            "customer_delivery_status": "OUTCOME_UNKNOWN",
            "customer_delivery_attempt_count": 1,
            "customer_delivery_attempted": True,
        }
        self._save_run(parent_meta)
        self._save_run(child_meta)

        s_product = PRODUCTS["today_genie"]
        s_day = "2026-11-05"
        s_att = "publication_" + _digest([s_product, s_day])
        (self.safety_dir / "publication_attempts").mkdir(parents=True, exist_ok=True)
        (self.safety_dir / "publication_outcomes").mkdir(parents=True, exist_ok=True)
        (self.safety_dir / "publication_attempts" / f"{s_att}.json").write_text(
            json.dumps({"attempt_id": s_att, "run_id": child_id, "product_code": s_product, "publication_date": s_day}),
            encoding="utf-8",
        )
        (self.safety_dir / "publication_outcomes" / f"{s_att}.json").write_text(
            json.dumps({"attempt_id": s_att, "outcome": "UNKNOWN_AFTER_SUBMIT", "evidence": {"attempt_id": s_att}}),
            encoding="utf-8",
        )

        is_sup, _, _, _ = superseded_child_check(child_meta)
        self.assertFalse(is_sup)

        can_app, app_reason = can_approve_customer_send(child_meta, has_email_html=True)
        self.assertFalse(can_app)
        self.assertEqual(app_reason, "delivery_outcome_unknown")

        self._login()
        resp = self.client.get(f"/admin/runs/{child_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("정합성 확인 필요", resp.text)
        self.assertNotIn("동일 발행일의 원본 실행", resp.text)
