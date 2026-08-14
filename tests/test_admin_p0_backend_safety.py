from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import admin_notice_store
import admin_safety_store
import admin_store
from admin_approval import (
    ApprovalTargetError,
    create_approval_snapshot,
    verify_approval_snapshot,
)
from admin_operational_status import OperationalStatusService
from admin_safety_store import (
    append_operator_audit,
    delivery_command_id_for_snapshot,
    list_operator_audit,
    reserve_delivery_command,
)
from admin_store import (
    approve_run,
    can_approve_customer_send,
    hold_run,
    load_run_artifact,
    load_run_email_html,
    reopen_held_run,
    save_run_artifact,
)
from delivery_trace import build_customer_email_delivery_fields
from main import app


class AdminP0SafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runs = self.root / "runs"
        self.runs.mkdir()
        self.safety = self.root / "safety"
        self.notices = self.root / "notices"
        self.recipients = self.root / "recipients.json"
        self.top = self.root / "top.jpg"
        self.bottom = self.root / "bottom.jpg"
        self.top.write_bytes(b"top-v1")
        self.bottom.write_bytes(b"bottom-v1")
        self.env = mock.patch.dict(
            os.environ,
            {
                "GENIE_CUSTOMER_EMAIL_TO": "alpha@example.com,beta@example.com",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_USER": "mailer@example.com",
                "SMTP_PASSWORD": "never-store-this-secret",
                "GENIE_ADMIN_PASSWORD": "test-admin-secret",
                "GENIE_ADMIN_SAFETY_LOCAL_DIR": str(self.safety),
                "GENIE_ADMIN_NOTICE_LOCAL_DIR": str(self.notices),
                "GENIE_ADMIN_ALLOW_LOCAL_SAFETY_STORE": "1",
                "GENIE_ADMIN_ALLOW_LOCAL_NOTICE_STORE": "1",
            },
            clear=False,
        )
        self.env.start()
        self.patches = [
            mock.patch("admin_store.admin_runs_dir", return_value=self.runs),
            mock.patch("admin_store._uses_gcs_backend", return_value=False),
            mock.patch("admin_safety_store._uses_gcs_backend", return_value=False),
            mock.patch("admin_notice_store._uses_gcs_backend", return_value=False),
            mock.patch("admin_store._beta_recipients_local_path", return_value=self.recipients),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _run(self, suffix: str = "aaaaaaaa") -> str:
        run_id = f"20260814_063000_today_genie_{suffix}"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "email_subject": "[운영자 검토] Safety briefing",
                "image_source": "generated",
                "image_generation_status": "generated",
                "fallback_used": False,
                "generated_image_paths": {"top": str(self.top), "bottom": str(self.bottom)},
            },
            email_html="<html><body><h1>Frozen briefing</h1></body></html>",
        )
        return run_id

    def _snapshot(self, run_id: str, operator: str = "operator:test"):
        return create_approval_snapshot(
            run_id=run_id,
            meta=load_run_artifact(run_id) or {},
            saved_html=load_run_email_html(run_id) or "",
            operator_id=operator,
        )

    def test_snapshot_freezes_content_images_recipients_and_version_without_secrets(self) -> None:
        run_id = self._run()
        snapshot, prepared = self._snapshot(run_id)
        self.assertEqual(snapshot["subject"], "Safety briefing")
        self.assertEqual(snapshot["recipient_count"], 2)
        self.assertEqual(snapshot["recipients"], ["alpha@example.com", "beta@example.com"])
        self.assertEqual(len(snapshot["images"]), 2)
        self.assertTrue(snapshot["rendered_content_sha256"])
        self.assertTrue(snapshot["recipient_configuration_hash"])
        self.assertEqual(snapshot["recipient_configuration_version"], "env+admin:v1")
        self.assertIn("review-confirmation-box", prepared.customer_html)
        raw = json.dumps(snapshot)
        self.assertNotIn("never-store-this-secret", raw)
        self.assertNotIn("SMTP_PASSWORD", raw)

    def test_changed_content_image_or_recipients_blocks_without_send(self) -> None:
        for change in ("content", "image", "recipients"):
            with self.subTest(change=change):
                run_id = self._run({"content": "aaaab001", "image": "aaaab002", "recipients": "aaaab003"}[change])
                snapshot, _ = self._snapshot(run_id)
                if change == "content":
                    admin_store._write_email_blob(run_id, "<html><body>changed</body></html>")
                elif change == "image":
                    self.top.write_bytes(b"top-changed")
                else:
                    os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "alpha@example.com,gamma@example.com"
                with mock.patch(
                    "today_geenee_customer_delivery.send_today_geenee_customer_final_email"
                ) as sender:
                    updated, status = approve_run(
                        run_id,
                        approval_snapshot_id=snapshot["approval_snapshot_id"],
                        operator_id="operator:test",
                    )
                self.assertIsNone(updated)
                self.assertEqual(status, "APPROVAL_TARGET_CHANGED")
                sender.assert_not_called()
                os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "alpha@example.com,beta@example.com"
                self.top.write_bytes(b"top-v1")

    def test_stale_and_forged_snapshot_block(self) -> None:
        run_id = self._run("aaaab004")
        snapshot, _ = self._snapshot(run_id)
        forged = dict(snapshot)
        forged["approval_snapshot_id"] = "aps_20260814_0000000000000000"
        with self.assertRaises(ApprovalTargetError) as forged_error:
            verify_approval_snapshot(
                snapshot_id=forged["approval_snapshot_id"],
                run_id=run_id,
                meta=load_run_artifact(run_id) or {},
                saved_html=load_run_email_html(run_id) or "",
                operator_id="operator:test",
            )
        self.assertEqual(forged_error.exception.code, "INVALID_APPROVAL_SNAPSHOT")
        path = self.safety / "approval_snapshots" / f"{snapshot['approval_snapshot_id']}.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["expires_at"] = (datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(seconds=1)).isoformat()
        path.write_text(json.dumps(stored), encoding="utf-8")
        with self.assertRaises(ApprovalTargetError) as stale_error:
            verify_approval_snapshot(
                snapshot_id=snapshot["approval_snapshot_id"],
                run_id=run_id,
                meta=load_run_artifact(run_id) or {},
                saved_html=load_run_email_html(run_id) or "",
                operator_id="operator:test",
            )
        self.assertEqual(stale_error.exception.code, "STALE_APPROVAL_SNAPSHOT")

    def test_delivery_command_is_stable_and_create_once(self) -> None:
        run_id = self._run("aaaab005")
        snapshot, _ = self._snapshot(run_id)
        command_id = delivery_command_id_for_snapshot(snapshot["approval_snapshot_id"])
        first, _ = reserve_delivery_command(
            command_id=command_id,
            snapshot_id=snapshot["approval_snapshot_id"],
            run_id=run_id,
            operator_id="operator:test",
        )
        second, existing = reserve_delivery_command(
            command_id=command_id,
            snapshot_id=snapshot["approval_snapshot_id"],
            run_id=run_id,
            operator_id="operator:test",
        )
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(existing["status"], "SUBMITTED")
        self.assertFalse(existing["provider_exactly_once"])

    def test_unchanged_snapshot_submits_once_and_repeat_post_is_blocked(self) -> None:
        run_id = self._run("aaaab008")
        snapshot, _ = self._snapshot(run_id)
        trace = {
            "envelope_to": ["alpha@example.com", "beta@example.com"],
            "smtp_submission_started": True,
            "smtp_submission_completed": True,
            "smtp_accepted_recipient_count": 2,
            "smtp_refused_recipients": [],
        }
        with mock.patch(
            "today_geenee_customer_delivery.send_today_geenee_customer_final_email",
            return_value=True,
        ) as sender, mock.patch("email_sender.last_send_trace", return_value=trace):
            first, first_status = approve_run(
                run_id,
                approval_snapshot_id=snapshot["approval_snapshot_id"],
                operator_id="operator:test",
            )
            second, second_status = approve_run(
                run_id,
                approval_snapshot_id=snapshot["approval_snapshot_id"],
                operator_id="operator:test",
            )
        self.assertEqual(first_status, "ok")
        self.assertEqual(first["customer_delivery_status"], "ACCEPTED_ALL")
        self.assertIsNone(second)
        self.assertIn(second_status, {"already_approved", "customer_already_sent"})
        sender.assert_called_once()

    def test_outcome_unknown_is_persisted_and_never_blindly_retried(self) -> None:
        run_id = self._run("aaaab009")
        snapshot, _ = self._snapshot(run_id)
        trace = {
            "envelope_to": ["alpha@example.com", "beta@example.com"],
            "smtp_submission_started": True,
            "smtp_submission_completed": False,
            "smtp_outcome_unknown": True,
            "smtp_accepted_recipient_count": 0,
            "smtp_refused_recipients": [],
        }
        with mock.patch(
            "today_geenee_customer_delivery.send_today_geenee_customer_final_email",
            return_value=False,
        ) as sender, mock.patch("email_sender.last_send_trace", return_value=trace):
            first, status = approve_run(
                run_id,
                approval_snapshot_id=snapshot["approval_snapshot_id"],
                operator_id="operator:test",
            )
            second, retry_status = approve_run(
                run_id,
                approval_snapshot_id=snapshot["approval_snapshot_id"],
                operator_id="operator:test",
            )
        self.assertEqual(status, "ok")
        self.assertEqual(first["customer_delivery_status"], "OUTCOME_UNKNOWN")
        self.assertIsNone(second)
        self.assertEqual(retry_status, "delivery_outcome_unknown")
        sender.assert_called_once()

    def test_delivery_truth_all_partial_refused_and_unknown(self) -> None:
        cases = (
            (13, 0, True, False, "ACCEPTED_ALL"),
            (12, 1, True, False, "PARTIAL_REFUSAL"),
            (0, 13, False, False, "REFUSED_ALL"),
            (0, 0, False, True, "OUTCOME_UNKNOWN"),
        )
        recipients = [f"u{i}@example.com" for i in range(13)]
        for accepted, refused, send_ok, unknown, expected in cases:
            trace = {
                "envelope_to": recipients,
                "smtp_accepted_recipient_count": accepted,
                "smtp_refused_recipients": recipients[:refused],
                "smtp_submission_started": True,
                "smtp_submission_completed": not unknown,
                "smtp_outcome_unknown": unknown,
            }
            fields = build_customer_email_delivery_fields(
                attempted=True,
                send_ok=send_ok,
                subject="x",
                trace=trace,
                diagnostic="",
            )
            self.assertEqual(fields["customer_email_delivery_status"], expected)
            self.assertFalse(fields.get("receipt_confirmed", False))
            if expected in {"PARTIAL_REFUSAL", "OUTCOME_UNKNOWN"}:
                allowed, reason = can_approve_customer_send(
                    {
                        "mode": "today_genie",
                        "validation_result": "pass",
                        "owner_review_status": "pending_review",
                        "customer_delivery_status": expected,
                    },
                    has_email_html=True,
                )
                self.assertFalse(allowed)
                self.assertEqual(
                    reason,
                    {
                        "PARTIAL_REFUSAL": "delivery_partial_refusal",
                        "OUTCOME_UNKNOWN": "delivery_outcome_unknown",
                    }[expected],
                )

    def test_hold_is_durable_blocks_send_and_reopen_does_not_generate(self) -> None:
        run_id = self._run("aaaab006")
        before_html = load_run_email_html(run_id)
        held, status = hold_run(run_id, note="owner pause", operator_id="operator:test")
        self.assertEqual(status, "ok")
        self.assertEqual(held["owner_review_status"], "held")
        reloaded = load_run_artifact(run_id) or {}
        self.assertEqual(reloaded["owner_review_status"], "held")
        self.assertEqual(approve_run(run_id)[1], "review_held")
        reopened, status = reopen_held_run(run_id, operator_id="operator:test")
        self.assertEqual(status, "ok")
        self.assertEqual(reopened["owner_review_status"], "reopened")
        self.assertEqual(load_run_email_html(run_id), before_html)

    def test_operator_audit_is_durable_and_sanitizes_secrets(self) -> None:
        append_operator_audit(
            "review_hold",
            operator_id="operator:test",
            run_id="run",
            result="held",
            metadata={"password": "bad", "authorization": "Bearer bad", "count": 2},
        )
        rows = list_operator_audit()
        self.assertEqual(rows[0]["action"], "review_hold")
        raw = json.dumps(rows[0])
        self.assertNotIn("Bearer bad", raw)
        self.assertNotIn('"password"', raw)
        self.assertEqual(rows[0]["metadata"]["count"], 2)

    def test_notice_store_reloads_and_production_local_store_fails_closed(self) -> None:
        notice = admin_notice_store.create_notice_draft(
            notice_type="custom_notice",
            program_id="today_genie",
            related_run_id=None,
            subject="Notice",
            body_text="Body",
            body_html="<p>Body</p>",
        )
        loaded = admin_notice_store.load_notice(notice["notice_id"])
        self.assertEqual(loaded["subject"], "Notice")
        self.assertEqual(loaded["storage_backend"], "local_test_dev")
        with mock.patch.dict(
            os.environ,
            {"K_SERVICE": "genie-blog-run", "GENIE_ADMIN_ALLOW_LOCAL_NOTICE_STORE": "0"},
        ):
            with self.assertRaisesRegex(RuntimeError, "durable_admin_notice_store_required"):
                admin_notice_store.list_notices()

    def test_production_cookie_secure_and_csrf_rejects_missing_token(self) -> None:
        run_id = self._run("aaaab007")
        with mock.patch.dict(
            os.environ,
            {
                "K_SERVICE": "genie-blog-run",
                "GENIE_ADMIN_CSRF_ENABLED": "1",
                "GENIE_ADMIN_COOKIE_SECURE": "1",
                "GENIE_ADMIN_ALLOW_LOCAL_SAFETY_STORE": "1",
            },
        ):
            client = TestClient(app, base_url="https://testserver")
            login = client.post(
                "/admin/login", data={"password": "test-admin-secret"}, follow_redirects=False
            )
            self.assertIn("Secure", login.headers.get("set-cookie", ""))
            blocked = client.post(
                f"/admin/runs/{run_id}/hold", data={"hold_note": "x"}, follow_redirects=False
            )
            self.assertEqual(blocked.status_code, 403)
            detail = client.get(f"/admin/runs/{run_id}")
            token_match = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)
            self.assertIsNotNone(token_match)
            allowed = client.post(
                f"/admin/runs/{run_id}/hold",
                data={"hold_note": "x", "csrf_token": token_match.group(1)},
                follow_redirects=False,
            )
            self.assertEqual(allowed.status_code, 303)


class OperationalStatusServiceTests(unittest.TestCase):
    def test_live_recent_and_unavailable_are_distinct_and_adapter_is_read_only(self) -> None:
        class Fake:
            def read_scheduler_jobs(self):
                return [
                    {
                        "name": "Today_Geenee",
                        "state": "ENABLED",
                        "schedule": "30 6 * * 1-5",
                        "timezone": "Asia/Seoul",
                        "last_attempt": "now",
                    }
                ]

            def read_cloud_run_service(self):
                return {"serving_revision": "rev", "commit_sha": "sha", "health": "READY"}

        adapter = Fake()
        result = OperationalStatusService(adapter).status(
            recent_evidence={"keysuri_global_tech": {"status": "PASS", "checked_at": "earlier"}}
        )
        by_program = {row["program_id"]: row for row in result["programs"]}
        self.assertEqual(by_program["today_genie"]["provenance"], "LIVE")
        self.assertEqual(by_program["keysuri_global_tech"]["provenance"], "RECENT EVIDENCE")
        self.assertEqual(by_program["keysuri_korea_tech"]["provenance"], "UNAVAILABLE")
        self.assertEqual(result["cloud_run"]["provenance"], "LIVE")
        self.assertFalse(hasattr(adapter, "pause"))
        self.assertNotIn("tomorrow_genie", by_program)
