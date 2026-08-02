from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

import execution_state
from execution_state import (
    build_logical_execution_key,
    deliver_owner_review_once,
    execution_lease_seconds,
    load_execution,
    reserve_execution,
    update_execution,
)

KST = ZoneInfo("Asia/Seoul")


class C2DeliverySemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="genie-c2-state-")
        self.env = mock.patch.dict(
            "os.environ",
            {
                "GENIE_EXECUTION_STATE_ROOT": self.temp.name,
                "GENIE_EXECUTION_LEASE_SECONDS": "120",
                "GENIE_ADMIN_ARTIFACT_BUCKET": "",
                "GENIE_ARTIFACT_BUCKET": "",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def key(self, program: str = "keysuri_global_tech") -> str:
        slots = {
            "today_genie": "06:30",
            "keysuri_global_tech": "12:30",
            "keysuri_korea_tech": "18:30",
        }
        return build_logical_execution_key(
            program_id=program,
            scheduled_date_kst="2026-08-03",
            scheduled_slot_kst=slots[program],
            trigger_source="scheduled",
        )

    def test_crash_after_acceptance_then_stale_takeover_repairs_without_resend(self) -> None:
        key = self.key()
        start = datetime(2026, 8, 3, 12, 30, tzinfo=KST)
        calls: list[str] = []
        with mock.patch.object(execution_state, "_now", return_value=start):
            owner_a = reserve_execution(
                key, program_id="keysuri_global_tech", run_id="run-1", owner_id="owner-a"
            )
            first = deliver_owner_review_once(
                key,
                expected_owner_id=owner_a.owner_id,
                send=lambda: calls.append("smtp") or True,
            )
        self.assertTrue(first.accepted)
        self.assertEqual(calls, ["smtp"])
        self.assertTrue((load_execution(key) or {}).get("owner_review_accepted_at"))

        with mock.patch.object(execution_state, "_update", side_effect=RuntimeError("checkpoint_crash")):
            with self.assertRaisesRegex(RuntimeError, "checkpoint_crash"):
                update_execution(
                    key,
                    expected_owner_id=owner_a.owner_id,
                    state="owner_review_emailed",
                )

        with mock.patch.object(execution_state, "_now", return_value=start + timedelta(seconds=121)):
            owner_b = reserve_execution(
                key, program_id="keysuri_global_tech", run_id="run-2", owner_id="owner-b"
            )
            self.assertTrue(owner_b.execute)
            self.assertTrue(owner_b.accepted_repair)
            duplicate = deliver_owner_review_once(
                key,
                expected_owner_id=owner_b.owner_id,
                send=lambda: calls.append("duplicate") or True,
            )
            self.assertFalse(duplicate.sender_called)
            update_execution(
                key,
                expected_owner_id=owner_b.owner_id,
                state="owner_review_emailed",
                last_safe_state="owner_review_emailed",
            )
        self.assertEqual(calls, ["smtp"])
        self.assertEqual((load_execution(key) or {})["state"], "owner_review_emailed")

    def test_stale_owner_is_fenced_after_takeover(self) -> None:
        key = self.key()
        start = datetime(2026, 8, 3, 12, 30, tzinfo=KST)
        with mock.patch.object(execution_state, "_now", return_value=start):
            reserve_execution(key, program_id="keysuri_global_tech", run_id="run-1", owner_id="owner-a")
        with mock.patch.object(execution_state, "_now", return_value=start + timedelta(seconds=121)):
            owner_b = reserve_execution(
                key, program_id="keysuri_global_tech", run_id="run-2", owner_id="owner-b"
            )
            with self.assertRaisesRegex(RuntimeError, "execution_lease_owner_mismatch"):
                update_execution(key, expected_owner_id="owner-a", state="content_ready")
            updated = update_execution(
                key, expected_owner_id=owner_b.owner_id, state="content_ready"
            )
        self.assertEqual(updated["owner_id"], "owner-b")

    def test_missing_owner_id_fails_closed(self) -> None:
        key = self.key()
        reserve_execution(key, program_id="keysuri_global_tech", run_id="run-1")
        with self.assertRaises(TypeError):
            update_execution(key, state="content_ready")  # type: ignore[call-arg]
        with self.assertRaisesRegex(RuntimeError, "expected_owner_id_required"):
            update_execution(key, expected_owner_id="", state="content_ready")

    def test_stage_transition_is_heartbeat_and_dead_api_is_removed(self) -> None:
        key = self.key()
        start = datetime(2026, 8, 3, 12, 30, tzinfo=KST)
        with mock.patch.object(execution_state, "_now", return_value=start):
            reservation = reserve_execution(
                key, program_id="keysuri_global_tech", run_id="run-1", owner_id="owner-a"
            )
        before = load_execution(key) or {}
        with mock.patch.object(execution_state, "_now", return_value=start + timedelta(seconds=20)):
            after = update_execution(
                key, expected_owner_id=reservation.owner_id, state="content_ready"
            )
        self.assertGreater(after["heartbeat_at"], before["heartbeat_at"])
        self.assertGreater(after["lease_expires_at"], before["lease_expires_at"])
        self.assertFalse(hasattr(execution_state, "heartbeat_execution"))

    def test_artifacts_ready_resume_sends_once_and_accepted_resume_sends_zero(self) -> None:
        from keysuri_service_full_run import resume_keysuri_owner_review_email

        image = Path(self.temp.name) / "top.jpg"
        image.write_bytes(b"jpeg")
        meta = {
            "run_id": "keysuri_global_tech-20260803-123000-abcdef12",
            "program_id": "keysuri_global_tech",
            "owner_email_subject": "review",
            "html_path": "saved.html",
        }
        key = self.key()
        reservation = reserve_execution(
            key, program_id="keysuri_global_tech", run_id=meta["run_id"], owner_id="owner-a"
        )
        update_execution(
            key,
            expected_owner_id=reservation.owner_id,
            state="artifacts_ready",
            last_safe_state="artifacts_ready",
        )
        calls: list[str] = []
        with mock.patch.dict("os.environ", {"GENIE_OWNER_REVIEW_SEND": "1"}, clear=False), mock.patch(
            "keysuri_service_full_run.load_run_artifact", return_value=meta
        ), mock.patch(
            "keysuri_service_full_run.load_run_email_html", return_value="<html>review</html>"
        ), mock.patch(
            "keysuri_service_full_run._saved_top_image_reference", return_value=(image, {})
        ), mock.patch(
            "keysuri_service_full_run.inline_jpeg_parts_for_global_service_email", return_value=[]
        ), mock.patch("keysuri_service_full_run.update_run_artifact", return_value=meta):
            first = resume_keysuri_owner_review_email(
                meta["run_id"],
                logical_execution_key=key,
                expected_owner_id=reservation.owner_id,
                send_fn=lambda *args, **kwargs: calls.append("smtp") or True,
            )
            second = resume_keysuri_owner_review_email(
                meta["run_id"],
                logical_execution_key=key,
                expected_owner_id=reservation.owner_id,
                send_fn=lambda *args, **kwargs: calls.append("duplicate") or True,
            )
        self.assertTrue(first["sender_called"])
        self.assertFalse(second["sender_called"])
        self.assertEqual(calls, ["smtp"])

    def test_terminal_and_program_retry_policies(self) -> None:
        terminal_key = self.key()
        terminal = reserve_execution(
            terminal_key, program_id="keysuri_global_tech", run_id="run-1", owner_id="owner-a"
        )
        update_execution(
            terminal_key, expected_owner_id=terminal.owner_id, state="failed_terminal"
        )
        calls: list[str] = []
        result = deliver_owner_review_once(
            terminal_key,
            expected_owner_id=terminal.owner_id,
            send=lambda: calls.append("unexpected") or True,
        )
        self.assertFalse(result.sender_called)
        self.assertEqual(calls, [])

        start = datetime(2026, 8, 3, 6, 30, tzinfo=KST)
        today_key = self.key("today_genie")
        with mock.patch.object(execution_state, "_now", return_value=start):
            today = reserve_execution(
                today_key, program_id="today_genie", run_id="today-1", owner_id="today-a"
            )
            update_execution(
                today_key, expected_owner_id=today.owner_id, state="failed_retryable"
            )
        with mock.patch.object(execution_state, "_now", return_value=start + timedelta(seconds=1)):
            retry = reserve_execution(
                today_key, program_id="today_genie", run_id="today-2", owner_id="today-b"
            )
        self.assertFalse(retry.execute)
        self.assertEqual((load_execution(today_key) or {})["state"], "failed_terminal")

        global_key = self.key("keysuri_global_tech") + ":retry"
        with mock.patch.object(execution_state, "_now", return_value=start):
            first = reserve_execution(
                global_key, program_id="keysuri_global_tech", run_id="global-1", owner_id="global-a"
            )
            update_execution(
                global_key, expected_owner_id=first.owner_id, state="failed_retryable"
            )
        with mock.patch.object(execution_state, "_now", return_value=start + timedelta(seconds=1)):
            second = reserve_execution(
                global_key, program_id="keysuri_global_tech", run_id="global-2", owner_id="global-b"
            )
        self.assertTrue(second.execute)
        self.assertEqual(second.attempt, 2)

    def test_cross_program_identity_and_lease_validation(self) -> None:
        keys = {self.key(program) for program in (
            "today_genie", "keysuri_global_tech", "keysuri_korea_tech"
        )}
        self.assertEqual(len(keys), 3)
        with mock.patch.dict("os.environ", {"GENIE_EXECUTION_LEASE_SECONDS": "119"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "execution_lease_seconds_unsafe"):
                execution_lease_seconds()
        with mock.patch.dict("os.environ", {"GENIE_EXECUTION_LEASE_SECONDS": "120"}, clear=False):
            self.assertEqual(execution_lease_seconds(), 120)

    def test_gcs_precondition_cannot_silently_downgrade(self) -> None:
        import admin_store

        class BlobWithoutPreconditions:
            def upload_from_string(self, text, *, content_type):
                raise AssertionError("unfenced upload must not be attempted")

        bucket = SimpleNamespace(blob=lambda _key: BlobWithoutPreconditions())
        with mock.patch.object(admin_store, "_get_gcs_bucket", return_value=bucket):
            with self.assertRaisesRegex(RuntimeError, "gcs_generation_precondition_unsupported"):
                admin_store._gcs_upload_text(
                    "execution.json",
                    "{}",
                    content_type="application/json",
                    if_generation_match=0,
                )

    def test_today_orchestrator_sender_checks_accepted_marker(self) -> None:
        from orchestrator import OrchestrationResult, send_email_if_allowed
        from publishing_policy import PublishingDecision

        key = self.key("today_genie")
        reservation = reserve_execution(
            key, program_id="today_genie", run_id="today-run", owner_id="owner-a"
        )
        result = OrchestrationResult(
            decision=PublishingDecision(True, False, False, True, False),
            reason_summary="pass",
            response_status=200,
            mode="today_genie",
            response_data={
                "validation_result": "pass",
                "data": {"channel_drafts": {"email_subject": "brief"}},
                "runtime_input": {},
            },
        )
        images = SimpleNamespace(
            inline_parts=[("/tmp/not-opened.jpg", "cid", "image.jpg")],
            fallback_used=False,
            issue_codes=[],
        )
        calls: list[str] = []
        with mock.patch("main.build_today_genie_email_html_for_cid_mime_send", return_value="운영자 검수 화면 열기"), mock.patch(
            "admin_urls.build_owner_review_admin_url", return_value="https://admin.invalid/review"
        ), mock.patch("orchestrator.send_genie_email", side_effect=lambda *a, **k: calls.append("smtp") or True):
            self.assertTrue(send_email_if_allowed(
                result,
                run_id="today-run",
                today_image_result=images,
                logical_execution_key=key,
                expected_owner_id=reservation.owner_id,
            ))
            self.assertTrue(send_email_if_allowed(
                result,
                run_id="today-run",
                today_image_result=images,
                logical_execution_key=key,
                expected_owner_id=reservation.owner_id,
            ))
        self.assertEqual(calls, ["smtp"])


if __name__ == "__main__":
    unittest.main()
