"""KST weekend guard for scheduled Today_Geenee owner-review creation."""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from genie_schedule_policy import (
    ScheduledWeekendSkip,
    is_weekday_kst,
)
from main import app
from orchestrator import OrchestrationResult, execute_orchestrator_run
from publishing_policy import PublishingDecision

KST = ZoneInfo("Asia/Seoul")
TOKEN = "weekend-guard-test-token"
ENDPOINT = "/internal/jobs/create-owner-review"
KEYSURI_ENDPOINT = "/internal/jobs/create-keysuri-owner-review"


def _kst(year: int, month: int, day: int, hour: int = 6, minute: int = 30) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=KST)


def _result(mode: str = "today_genie") -> OrchestrationResult:
    return OrchestrationResult(
        decision=PublishingDecision(
            send_email=True,
            create_naver_draft=False,
            auto_publish=False,
            require_review=True,
            suppress_external=False,
        ),
        reason_summary="ok",
        response_status=200,
        mode=mode,
        response_data={"validation_result": "pass", "data": {}, "runtime_input": {}},
    )


class KstWeekdayPolicyTests(unittest.TestCase):
    def test_monday_and_friday_are_weekdays(self) -> None:
        self.assertTrue(is_weekday_kst(_kst(2026, 6, 22)))
        self.assertTrue(is_weekday_kst(_kst(2026, 6, 19)))

    def test_saturday_and_sunday_are_weekends(self) -> None:
        self.assertFalse(is_weekday_kst(_kst(2026, 6, 20)))
        self.assertFalse(is_weekday_kst(_kst(2026, 6, 21)))

    def test_utc_friday_can_be_kst_saturday(self) -> None:
        utc_friday = datetime(2026, 6, 19, 21, 30, tzinfo=timezone.utc)
        self.assertFalse(is_weekday_kst(utc_friday))

    def test_utc_sunday_can_be_kst_monday(self) -> None:
        utc_sunday = datetime(2026, 6, 21, 21, 30, tzinfo=timezone.utc)
        self.assertTrue(is_weekday_kst(utc_sunday))


class TodayScheduledEndpointWeekendGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.env = patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": TOKEN}, clear=False)
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def _post(self, now: datetime, body: dict | None = None):
        with patch("internal_jobs.get_kst_now", return_value=now):
            return self.client.post(
                ENDPOINT,
                json=body or {},
                headers={"X-Genie-Internal-Job-Token": TOKEN},
            )

    def test_saturday_skip_response_blocks_all_runtime_work(self) -> None:
        with patch("internal_jobs.check_artifact_store_ready") as store:
            with patch("internal_jobs.find_scheduled_owner_review_for_kst_date") as dedupe:
                with patch("internal_jobs.execute_orchestrator_run") as execute:
                    response = self._post(_kst(2026, 6, 20))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "skipped": True,
                "skipped_reason": "weekend_kst",
                "mode": "today_genie",
                "trigger_source": "scheduled_owner_review",
                "kst_date": "2026-06-20",
                "kst_weekday": "Saturday",
                "email_sent": False,
                "image_generation_skipped": True,
                "artifact_created": False,
            },
        )
        store.assert_not_called()
        dedupe.assert_not_called()
        execute.assert_not_called()

    def test_sunday_service_full_run_is_skipped_before_dispatch(self) -> None:
        with patch("today_genie_service_full_run.run_today_genie_service_full_run") as full_run:
            with patch("internal_jobs.execute_orchestrator_run") as execute:
                response = self._post(
                    _kst(2026, 6, 21),
                    {"service_full_run": True, "send_owner_email": True},
                )
        self.assertTrue(response.json()["skipped"])
        self.assertEqual(response.json()["kst_weekday"], "Sunday")
        full_run.assert_not_called()
        execute.assert_not_called()

    def test_weekday_keeps_existing_duplicate_guard(self) -> None:
        with patch(
            "internal_jobs.find_scheduled_owner_review_for_kst_date",
            return_value="20260622_063000_today_genie_aabbccdd",
        ) as dedupe:
            with patch(
                "internal_jobs._safe_owner_review_summary",
                return_value={"ok": True, "skipped_duplicate": True},
            ):
                with patch("internal_jobs.execute_orchestrator_run") as execute:
                    response = self._post(_kst(2026, 6, 22))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["skipped_duplicate"])
        dedupe.assert_called_once_with("today_genie")
        execute.assert_not_called()

    def test_manual_trigger_is_allowed_on_weekend(self) -> None:
        run_id = "20260620_120000_today_genie_aabbccdd"
        with patch("internal_jobs.find_scheduled_owner_review_for_kst_date", return_value=None):
            with patch(
                "internal_jobs.execute_orchestrator_run",
                return_value=(run_id, _result(), False),
            ) as execute:
                with patch(
                    "internal_jobs._safe_owner_review_summary",
                    return_value={"ok": True, "run_id": run_id, "mode": "today_genie"},
                ):
                    response = self._post(
                        _kst(2026, 6, 20),
                        {"trigger_source": "manual_admin", "send_owner_email": False},
                    )
        self.assertEqual(response.status_code, 200)
        execute.assert_called_once_with(
            "today_genie",
            trigger_source="manual_admin",
            send_owner_email=False,
        )


class OrchestratorWeekendDefenseTests(unittest.TestCase):
    def test_weekend_guard_runs_before_job_image_email_and_artifact(self) -> None:
        with patch("orchestrator.run_genie_job") as run_job:
            with patch("today_genie_orchestrator_images.generate_today_genie_orchestrator_images") as images:
                with patch("orchestrator.send_email_if_allowed") as send:
                    with patch("orchestrator.persist_orchestrator_run_artifact") as persist:
                        with self.assertRaises(ScheduledWeekendSkip) as raised:
                            execute_orchestrator_run(
                                "today_genie",
                                trigger_source="scheduled_owner_review",
                                schedule_now=_kst(2026, 6, 20),
                            )
        self.assertEqual(raised.exception.payload["skipped_reason"], "weekend_kst")
        run_job.assert_not_called()
        images.assert_not_called()
        send.assert_not_called()
        persist.assert_not_called()

    def test_weekday_scheduled_run_is_allowed(self) -> None:
        with patch("orchestrator.run_genie_job", return_value=_result()) as run_job:
            with patch("today_genie_orchestrator_images.generate_today_genie_orchestrator_images") as images:
                images.return_value = MagicMock(inline_parts=[], issue_codes=[])
                with patch("orchestrator.send_email_if_allowed", return_value=False):
                    with patch("orchestrator.persist_orchestrator_run_artifact", return_value="rid"):
                        run_id, _result_value, _sent = execute_orchestrator_run(
                            "today_genie",
                            trigger_source="scheduled_owner_review",
                            schedule_now=_kst(2026, 6, 19),
                        )
        self.assertEqual(run_id, "rid")
        run_job.assert_called_once_with("today_genie")

    def test_tomorrow_genie_is_not_affected(self) -> None:
        with patch("orchestrator.run_genie_job", return_value=_result("tomorrow_genie")) as run_job:
            with patch("orchestrator.send_email_if_allowed", return_value=False):
                with patch("orchestrator.persist_orchestrator_run_artifact", return_value="rid"):
                    execute_orchestrator_run(
                        "tomorrow_genie",
                        trigger_source="scheduler",
                        schedule_now=_kst(2026, 6, 21),
                    )
        run_job.assert_called_once_with("tomorrow_genie")

    def test_keysuri_scheduled_endpoint_is_not_affected_on_weekend(self) -> None:
        expected = {
            "ok": True,
            "program_id": "keysuri_korea_tech",
            "dry_run": True,
            "trigger_source": "scheduled_owner_review",
        }
        with patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": TOKEN}, clear=False):
            with patch("internal_jobs.get_kst_now", return_value=_kst(2026, 6, 21)):
                with patch(
                    "internal_jobs.create_keysuri_owner_review_job",
                    return_value=expected,
                ) as keysuri_job:
                    response = TestClient(app).post(
                        KEYSURI_ENDPOINT,
                        json={"program_id": "keysuri_korea_tech", "dry_run": True},
                        headers={"X-Genie-Internal-Job-Token": TOKEN},
                    )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        keysuri_job.assert_called_once()


if __name__ == "__main__":
    unittest.main()
