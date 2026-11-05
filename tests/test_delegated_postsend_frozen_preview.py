"""Synthetic tests for post-send read-only frozen preview of accepted Today warning candidate."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import admin_safety_store as s_store
import admin_store
from admin_routes import _delegated_email_preview_target
from admin_store import can_approve_customer_send, save_run_artifact
from customer_review_confirmation import (
    DELEGATED_REVIEW_TEXT,
    DELEGATED_WORK_REVIEW,
)
from delegated_delivery_safety import PRODUCTS, _digest
from delegated_gate import digest
from product_surface_contract import PRODUCT_REVIEW_REQUIRED
from renderers import (
    TODAY_GENIE_EMAIL_CID_BOTTOM,
    TODAY_GENIE_EMAIL_CID_TOP,
    today_genie_email_inline_cid_pair,
)
from today_geenee_customer_delivery import (
    REVIEW_CONFIRMATION_STATE_REVIEW_PASSED,
    build_customer_final_subject,
    prepare_customer_final_html,
    render_today_geenee_postsend_frozen_preview,
)


class DelegatedPostsendFrozenPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self._temp_dir.name)
        self.runs_dir = self.base_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.safety_dir = self.base_dir / "safety"
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
                "GENIE_RECIPIENT_AUTHORITY",
            ]
        }
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-secret"
        os.environ["GENIE_ADMIN_SAFETY_LOCAL_DIR"] = str(self.safety_dir)
        os.environ["GENIE_ADMIN_ALLOW_LOCAL_SAFETY_STORE"] = "1"
        os.environ["GENIE_RECIPIENT_AUTHORITY"] = "ADMIN_BETA_DELEGATION"

        self.top_img = self.base_dir / "top.jpg"
        self.bottom_img = self.base_dir / "bottom.jpg"
        self.top_img.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIFtop")
        self.bottom_img.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIFbottom")

    def tearDown(self) -> None:
        self._patch_safety.stop()
        self._patch_runs.stop()
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._temp_dir.cleanup()

    def _build_accepted_today_run(self, run_id: str = "20261105_063000_today_genie_12345678"):
        saved_html = (
            f'<img src="cid:{TODAY_GENIE_EMAIL_CID_TOP}">'
            "<p>Today Briefing Content</p>"
            f'<img src="cid:{TODAY_GENIE_EMAIL_CID_BOTTOM}">'
        )
        review_id = "del_rev_syn_001"
        cand_sha = "c" * 64

        s_product = PRODUCTS["today_genie"]
        s_day = f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}"
        attempt_id = "publication_" + _digest([s_product, s_day])

        meta = {
            "run_id": run_id,
            "mode": "today_genie",
            "program_id": "today_genie",
            "approval_source": DELEGATED_WORK_REVIEW,
            "delegated_review_status": "passed",
            "delegated_review_id": review_id,
            "delegated_candidate_sha256": cand_sha,
            "delegated_delivery_attempt_id": attempt_id,
            "customer_delivery_status": "ACCEPTED_ALL",
            "customer_email_delivery_status": "ACCEPTED_ALL",
            "customer_surface_status": PRODUCT_REVIEW_REQUIRED,
            "smtp_accepted_recipient_count": 14,
            "customer_delivery_accepted_count": 14,
            "customer_delivery_attempt_count": 1,
            "customer_delivery_attempted": True,
            "image_source": "generated",
            "image_generation_status": "generated",
            "generated_image_paths": {"top": str(self.top_img), "bottom": str(self.bottom_img)},
            "run_specific_images": True,
            "top_image_cid": TODAY_GENIE_EMAIL_CID_TOP,
            "bottom_image_cid": TODAY_GENIE_EMAIL_CID_BOTTOM,
        }

        subject = build_customer_final_subject(meta, saved_html)
        subject_sha = hashlib.sha256(str(subject).encode("utf-8")).hexdigest()

        reconstructed_body = prepare_customer_final_html(
            saved_html,
            review_confirmation_state=REVIEW_CONFIRMATION_STATE_REVIEW_PASSED,
            approval_source=DELEGATED_WORK_REVIEW,
        )
        body_sha = hashlib.sha256(reconstructed_body.encode("utf-8")).hexdigest()
        recv_html_sha = hashlib.sha256(saved_html.encode("utf-8")).hexdigest()

        top_sha = hashlib.sha256(self.top_img.read_bytes()).hexdigest()
        bottom_sha = hashlib.sha256(self.bottom_img.read_bytes()).hexdigest()
        image_identity = [
            {"role": "top", "cid": TODAY_GENIE_EMAIL_CID_TOP, "filename": "top.jpg", "sha256": top_sha},
            {"role": "bottom", "cid": TODAY_GENIE_EMAIL_CID_BOTTOM, "filename": "bottom.jpg", "sha256": bottom_sha},
        ]
        image_sha256 = {"top": top_sha, "bottom": bottom_sha}

        orig_art_meta = {
            "run_id": run_id,
            "mode": "today_genie",
            "program_id": "today_genie",
            "customer_surface_status": PRODUCT_REVIEW_REQUIRED,
        }
        art_sha = digest(orig_art_meta)

        # 1. delegated_review_events/<review_id>.json
        (self.safety_dir / "delegated_review_events").mkdir(parents=True, exist_ok=True)
        event_payload = {
            "event_sha256": "evt_sha_123",
            "event": {
                "event_id": "evt_syn_123",
                "run_id": run_id,
                "candidate_sha256": cand_sha,
                "review": {
                    "reviewer_model": "test-agent",
                    "reviewed_at": "2026-11-05T06:31:00Z",
                    "policy_version": "v1",
                    "artifact_metadata": orig_art_meta,
                    "artifact_sha256": art_sha,
                    "received_html_sha256": recv_html_sha,
                    "subject_sha256": subject_sha,
                    "body_sha256": body_sha,
                    "image_identity": image_identity,
                    "image_sha256": image_sha256,
                },
            },
            "principal": "test-principal",
        }
        (self.safety_dir / "delegated_review_events" / f"{review_id}.json").write_text(
            json.dumps(event_payload), encoding="utf-8"
        )

        # 2. delegated_review_results/<review_id>.json
        (self.safety_dir / "delegated_review_results").mkdir(parents=True, exist_ok=True)
        result_payload = {
            "verdict": "PASS",
            "event_id": "evt_syn_123",
            "review_id": review_id,
            "run_id": run_id,
            "candidate_sha256": cand_sha,
            "attempt_id": attempt_id,
            "approval_source": DELEGATED_WORK_REVIEW,
            "submission_outcome": "ACCEPTED_ALL",
        }
        (self.safety_dir / "delegated_review_results" / f"{review_id}.json").write_text(
            json.dumps(result_payload), encoding="utf-8"
        )

        # 3. publication_attempts/<attempt_id>.json
        (self.safety_dir / "publication_attempts").mkdir(parents=True, exist_ok=True)
        attempt_payload = {
            "attempt_id": attempt_id,
            "run_id": run_id,
            "product_code": s_product,
            "publication_date": s_day,
            "candidate_sha256": cand_sha,
            "review_id": review_id,
            "recipient_plan_id": "plan_syn_123",
            "recipient_plan_sha256": "plan_sha_syn_123",
            "approval_source": DELEGATED_WORK_REVIEW,
        }
        (self.safety_dir / "publication_attempts" / f"{attempt_id}.json").write_text(
            json.dumps(attempt_payload), encoding="utf-8"
        )

        # 4. publication_outcomes/<attempt_id>.json (actual schema: attempt_id and outcome, no run_id)
        (self.safety_dir / "publication_outcomes").mkdir(parents=True, exist_ok=True)
        outcome_payload = {
            "attempt_id": attempt_id,
            "outcome": "PROVIDER_ACCEPTED",
            "evidence": {"attempt_id": attempt_id},
        }
        (self.safety_dir / "publication_outcomes" / f"{attempt_id}.json").write_text(
            json.dumps(outcome_payload), encoding="utf-8"
        )

        save_run_artifact(meta, email_html=saved_html)
        return meta, saved_html, review_id, attempt_id

    def test_accepted_frozen_preview_reconstruction_via_delegated_target(self) -> None:
        run_id = "20261105_063000_today_genie_12345678"
        meta, saved_html, _, _ = self._build_accepted_today_run(run_id)

        grant = {
            "grant_id": "grant_syn_123",
            "products": ["today_genie"],
            "recipients": ["beta@example.com"],
            "_pointer_generation": 1,
            "recipient_configuration_version": 1,
            "recipient_configuration_hash": "cfg_sha_123",
        }
        from admin_preview_assets import PreviewAsset
        fake_assets = {
            "top": PreviewAsset(slot="top", cid=TODAY_GENIE_EMAIL_CID_TOP, backend="local", local_path=self.top_img),
            "bottom": PreviewAsset(slot="bottom", cid=TODAY_GENIE_EMAIL_CID_BOTTOM, backend="local", local_path=self.bottom_img),
        }
        post09_time = datetime(2026, 11, 5, 9, 30, 0, tzinfo=ZoneInfo("Asia/Seoul"))

        with patch("admin_beta_delegation.load_active_admin_beta_delegation", return_value=grant), \
             patch("admin_preview_assets.preview_assets_for_run", return_value=fake_assets):
            content, binding, target_sha = _delegated_email_preview_target(
                run_id, meta, saved_html, now=post09_time
            )
            self.assertIn(DELEGATED_REVIEW_TEXT, content)
            self.assertEqual(binding["run_id"], run_id)
            self.assertEqual(binding["mode"], "today_genie")
            self.assertTrue(bool(target_sha and len(target_sha) == 64))

    def test_tampered_or_missing_proof_fails_closed(self) -> None:
        run_id = "20261105_063000_today_genie_12345678"
        meta, saved_html, review_id, attempt_id = self._build_accepted_today_run(run_id)

        grant = {
            "grant_id": "grant_syn_123",
            "products": ["today_genie"],
            "recipients": ["beta@example.com"],
            "_pointer_generation": 1,
            "recipient_configuration_version": 1,
            "recipient_configuration_hash": "cfg_sha_123",
        }
        from admin_preview_assets import PreviewAsset
        fake_assets = {
            "top": PreviewAsset(slot="top", cid=TODAY_GENIE_EMAIL_CID_TOP, backend="local", local_path=self.top_img),
            "bottom": PreviewAsset(slot="bottom", cid=TODAY_GENIE_EMAIL_CID_BOTTOM, backend="local", local_path=self.bottom_img),
        }
        post09_time = datetime(2026, 11, 5, 9, 30, 0, tzinfo=ZoneInfo("Asia/Seoul"))

        # 1. Missing review result
        (self.safety_dir / "delegated_review_results" / f"{review_id}.json").unlink()
        with patch("admin_beta_delegation.load_active_admin_beta_delegation", return_value=grant), \
             patch("admin_preview_assets.preview_assets_for_run", return_value=fake_assets):
            with self.assertRaises(ValueError) as ctx:
                _delegated_email_preview_target(run_id, meta, saved_html, now=post09_time)
            self.assertIn("delegated_review_result_missing", str(ctx.exception))

        # Restore result but tamper verdict
        (self.safety_dir / "delegated_review_results" / f"{review_id}.json").write_text(
            json.dumps({"verdict": "HOLD", "review_id": review_id, "run_id": run_id, "candidate_sha256": "c" * 64, "attempt_id": attempt_id}),
            encoding="utf-8",
        )
        with patch("admin_beta_delegation.load_active_admin_beta_delegation", return_value=grant), \
             patch("admin_preview_assets.preview_assets_for_run", return_value=fake_assets):
            with self.assertRaises(ValueError) as ctx:
                _delegated_email_preview_target(run_id, meta, saved_html, now=post09_time)
            self.assertIn("delegated_review_result_not_pass", str(ctx.exception))

        # 2. Tampered body_sha in review event
        ev_file = self.safety_dir / "delegated_review_events" / f"{review_id}.json"
        ev_data = json.loads(ev_file.read_text(encoding="utf-8"))
        ev_data["event"]["review"]["body_sha256"] = "wrong_body_sha"
        ev_file.write_text(json.dumps(ev_data), encoding="utf-8")
        with patch("admin_beta_delegation.load_active_admin_beta_delegation", return_value=grant), \
             patch("admin_preview_assets.preview_assets_for_run", return_value=fake_assets):
            with self.assertRaises(ValueError) as ctx:
                _delegated_email_preview_target(run_id, meta, saved_html, now=post09_time)
            self.assertIn("signed_body_sha_mismatch", str(ctx.exception))

    def test_post09_view_allowed_while_post09_send_remains_blocked(self) -> None:
        run_id = "20261105_063000_today_genie_12345678"
        meta, saved_html, _, _ = self._build_accepted_today_run(run_id)

        post09_time = datetime(2026, 11, 5, 9, 30, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        can_app, app_err = can_approve_customer_send(meta, has_email_html=True, now=post09_time)
        self.assertFalse(can_app)
        self.assertEqual(app_err, "customer_already_sent")

        grant = {
            "grant_id": "grant_syn_123",
            "products": ["today_genie"],
            "recipients": ["beta@example.com"],
            "_pointer_generation": 1,
            "recipient_configuration_version": 1,
            "recipient_configuration_hash": "cfg_sha_123",
        }
        from admin_preview_assets import PreviewAsset
        fake_assets = {
            "top": PreviewAsset(slot="top", cid=TODAY_GENIE_EMAIL_CID_TOP, backend="local", local_path=self.top_img),
            "bottom": PreviewAsset(slot="bottom", cid=TODAY_GENIE_EMAIL_CID_BOTTOM, backend="local", local_path=self.bottom_img),
        }
        with patch("admin_beta_delegation.load_active_admin_beta_delegation", return_value=grant), \
             patch("admin_preview_assets.preview_assets_for_run", return_value=fake_assets):
            content, binding, target_sha = _delegated_email_preview_target(
                run_id, meta, saved_html, now=post09_time
            )
            self.assertIn(DELEGATED_REVIEW_TEXT, content)
            self.assertEqual(binding["run_id"], run_id)

    def test_zero_send_zero_registry_zero_secret_during_preview(self) -> None:
        run_id = "20261105_063000_today_genie_12345678"
        meta, saved_html, _, _ = self._build_accepted_today_run(run_id)

        grant = {
            "grant_id": "grant_syn_123",
            "products": ["today_genie"],
            "recipients": ["beta@example.com"],
            "_pointer_generation": 1,
            "recipient_configuration_version": 1,
            "recipient_configuration_hash": "cfg_sha_123",
        }
        from admin_preview_assets import PreviewAsset
        fake_assets = {
            "top": PreviewAsset(slot="top", cid=TODAY_GENIE_EMAIL_CID_TOP, backend="local", local_path=self.top_img),
            "bottom": PreviewAsset(slot="bottom", cid=TODAY_GENIE_EMAIL_CID_BOTTOM, backend="local", local_path=self.bottom_img),
        }

        send_mock = MagicMock()
        with patch("email_sender.send_genie_email", send_mock), \
             patch("admin_beta_delegation.load_active_admin_beta_delegation", return_value=grant), \
             patch("admin_preview_assets.preview_assets_for_run", return_value=fake_assets):
            _delegated_email_preview_target(
                run_id, meta, saved_html, now=datetime(2026, 11, 5, 8, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
            )
            send_mock.assert_not_called()
