"""Regression proof for natural-run overlap and retry-copy governance.

All endpoint tests are local and mocked: no model, image, SMTP, GCS, customer,
or Scheduler side effect is allowed.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from typing import Any
from unittest import mock
from zoneinfo import ZoneInfo
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


KST = ZoneInfo("Asia/Seoul")
TOKEN = "natural-isolation-test-token"
WATCHDOG_ENDPOINT = "/internal/jobs/natural-run-watchdog"
TODAY_ENDPOINT = "/internal/jobs/create-owner-review"
KEYSURI_ENDPOINT = "/internal/jobs/create-keysuri-owner-review"


def _kst(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 14, hour, minute, second, tzinfo=KST)


def _headers() -> dict[str, str]:
    return {"X-Genie-Internal-Job-Token": TOKEN}


class WatchdogDuePrecheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.env = mock.patch.dict(
            os.environ,
            {"GENIE_INTERNAL_JOB_TOKEN": TOKEN},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_due_calculation_suppresses_each_natural_start_then_restores_due_set(self) -> None:
        from natural_run_watchdog import watchdog_programs_due_for_reconciliation

        cases = [
            (_kst(6, 30), []),
            (_kst(6, 44, 59), []),
            (_kst(6, 45), ["today_genie"]),
            # Today's slot is already due, but Global has just started.  Do not
            # scan until the active slot's own SLA threshold is reached.
            (_kst(12, 30), []),
            (_kst(12, 44, 59), []),
            (
                _kst(12, 45),
                ["today_genie", "keysuri_global_tech"],
            ),
            # Both earlier slots are due, but Korea has just started.
            (_kst(18, 30), []),
            (_kst(18, 44, 59), []),
            (
                _kst(18, 45),
                [
                    "today_genie",
                    "keysuri_global_tech",
                    "keysuri_korea_tech",
                ],
            ),
        ]
        for now, expected in cases:
            with self.subTest(now=now.isoformat()):
                self.assertEqual(
                    watchdog_programs_due_for_reconciliation(
                        now=now,
                        paused_programs=["tomorrow_genie"],
                    ),
                    expected,
                )

    def test_exact_natural_starts_return_before_artifact_or_incident_scan(self) -> None:
        for now in (_kst(6, 30), _kst(12, 30), _kst(18, 30, 2)):
            with self.subTest(now=now.isoformat()), mock.patch(
                "internal_jobs.get_kst_now", return_value=now
            ), mock.patch(
                "internal_jobs.list_run_artifacts",
                side_effect=AssertionError("artifact scan must not run"),
            ) as artifact_scan, mock.patch(
                "natural_run_incident_store.load_incident",
                side_effect=AssertionError("incident load must not run"),
            ) as incident_load, mock.patch(
                "natural_run_incident_store._gcs_storage_client",
                side_effect=AssertionError("GCS client must not be constructed"),
            ) as incident_client, mock.patch(
                "natural_run_watchdog.run_watchdog_poll"
            ) as poll:
                response = self.client.post(
                    WATCHDOG_ENDPOINT,
                    json={},
                    headers=_headers(),
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["reason"], "no_sla_due")
            self.assertTrue(response.json()["watchdog_fast_path"])
            self.assertEqual(response.json()["auto_retry"], 0)
            self.assertEqual(response.json()["customer_send"], 0)
            artifact_scan.assert_not_called()
            incident_load.assert_not_called()
            incident_client.assert_not_called()
            poll.assert_not_called()

    def test_after_sla_reconciles_normally_with_one_bounded_artifact_list(self) -> None:
        summary = {"ok": True, "results": [{"program_id": "today_genie"}]}
        with mock.patch(
            "internal_jobs.get_kst_now", return_value=_kst(18, 45)
        ), mock.patch(
            "internal_jobs.list_run_artifacts", return_value=[{"run_id": "bounded"}]
        ) as artifact_scan, mock.patch(
            "natural_run_watchdog.run_watchdog_poll", return_value=summary
        ) as poll:
            response = self.client.post(
                WATCHDOG_ENDPOINT,
                json={},
                headers=_headers(),
            )

        self.assertEqual(response.status_code, 200)
        artifact_scan.assert_called_once_with(limit=100)
        poll.assert_called_once_with(
            artifacts=[{"run_id": "bounded"}],
            now=_kst(18, 45),
            paused_programs=["tomorrow_genie"],
            programs=[
                "today_genie",
                "keysuri_global_tech",
                "keysuri_korea_tech",
            ],
        )
        self.assertEqual(response.json()["auto_retry"], 0)
        self.assertEqual(response.json()["customer_send"], 0)

    def test_active_natural_run_defers_watchdog_but_health_stays_available(self) -> None:
        from natural_run_activity import (
            natural_run_is_active,
            track_natural_run_activity,
        )
        from today_genie_execution_identity import EXECUTION_CLASS_NATURAL_SCHEDULED

        with track_natural_run_activity(
            program_id="keysuri_korea_tech",
            kst_date="2026-08-14",
            scheduled_slot="18:30",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
        ):
            self.assertTrue(natural_run_is_active())
            health = self.client.get("/health")
            with mock.patch(
                "internal_jobs.get_kst_now", return_value=_kst(18, 45)
            ), mock.patch(
                "internal_jobs.list_run_artifacts",
                side_effect=AssertionError("active run must defer scan"),
            ) as artifact_scan, mock.patch(
                "natural_run_watchdog.run_watchdog_poll"
            ) as poll:
                response = self.client.post(
                    WATCHDOG_ENDPOINT,
                    json={},
                    headers=_headers(),
                )

            self.assertEqual(health.status_code, 200)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["reason"], "natural_execution_in_progress"
            )
            self.assertEqual(response.json()["active_identity_count"], 1)
            artifact_scan.assert_not_called()
            poll.assert_not_called()
        self.assertFalse(natural_run_is_active())


class NaturalRunActivityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app, raise_server_exceptions=False)
        self.env = mock.patch.dict(
            os.environ,
            {"GENIE_INTERNAL_JOB_TOKEN": TOKEN},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_tracker_uses_existing_identity_refcounts_and_releases_on_exception(self) -> None:
        from natural_run_activity import (
            active_natural_run_snapshot,
            natural_run_is_active,
            track_natural_run_activity,
        )
        from today_genie_execution_identity import (
            EXECUTION_CLASS_NATURAL_SCHEDULED,
            EXECUTION_CLASS_QA_MANUAL,
            natural_slot_key,
        )

        expected_key = natural_slot_key(
            program_id="keysuri_korea_tech",
            kst_date="2026-08-14",
            scheduled_slot="18:30",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
        )
        with track_natural_run_activity(
            program_id="keysuri_korea_tech",
            kst_date="2026-08-14",
            scheduled_slot="18:30",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
        ) as first_key:
            self.assertEqual(first_key, expected_key)
            with track_natural_run_activity(
                program_id="keysuri_korea_tech",
                kst_date="2026-08-14",
                scheduled_slot="18:30",
                execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            ) as second_key:
                self.assertEqual(second_key, expected_key)
                snapshot = active_natural_run_snapshot()
                self.assertEqual(snapshot["active_identity_count"], 1)
                self.assertEqual(snapshot["active_request_count"], 2)
            self.assertEqual(
                active_natural_run_snapshot()["active_request_count"], 1
            )
        self.assertFalse(natural_run_is_active())

        with track_natural_run_activity(
            program_id="today_genie",
            kst_date="2026-08-14",
            scheduled_slot="",
            execution_class=EXECUTION_CLASS_QA_MANUAL,
        ) as ignored_key:
            self.assertEqual(ignored_key, "")
            self.assertFalse(natural_run_is_active())

        with self.assertRaisesRegex(RuntimeError, "expected"):
            with track_natural_run_activity(
                program_id="today_genie",
                kst_date="2026-08-14",
                scheduled_slot="06:30",
                execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            ):
                raise RuntimeError("expected")
        self.assertFalse(natural_run_is_active())

    def test_admitted_today_natural_endpoint_is_active_only_during_execution(self) -> None:
        from natural_run_activity import (
            active_natural_run_snapshot,
            natural_run_is_active,
        )

        def _runner(*args: Any, **kwargs: Any):
            snapshot = active_natural_run_snapshot()
            self.assertTrue(snapshot["active"])
            self.assertEqual(snapshot["program_ids"], ["today_genie"])
            self.assertEqual(snapshot["scheduled_slots"], ["06:30"])
            return "20260814_063000_today_genie_activity1", mock.Mock(), False

        with mock.patch(
            "internal_jobs.get_kst_now", return_value=_kst(6, 30)
        ), mock.patch(
            "internal_jobs.list_run_artifacts", return_value=[]
        ), mock.patch(
            "internal_jobs.check_artifact_store_ready", return_value=(None, {})
        ), mock.patch(
            "internal_jobs.execute_orchestrator_run", side_effect=_runner
        ), mock.patch(
            "internal_jobs._safe_owner_review_summary",
            return_value={
                "ok": True,
                "run_id": "20260814_063000_today_genie_activity1",
                "mode": "today_genie",
            },
        ):
            response = self.client.post(
                TODAY_ENDPOINT,
                json={
                    "execution_class": "natural_scheduled",
                    "scheduled_slot": "06:30",
                    "trigger_source": "scheduled_owner_review",
                    "send_owner_email": False,
                },
                headers=_headers(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(natural_run_is_active())

    def test_keysuri_marks_only_exact_scheduled_full_run_and_always_releases(self) -> None:
        from natural_run_activity import natural_run_is_active

        observations: list[bool] = []

        def _runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
            observations.append(natural_run_is_active())
            return {"ok": True, "program_id": "keysuri_korea_tech"}

        scheduled_body = {
            "program_id": "keysuri_korea_tech",
            "service_full_run": True,
            "send_owner_email": False,
            "dry_run": False,
            "trigger_source": "scheduled_service_full_run",
        }
        with mock.patch(
            "internal_jobs.get_kst_now", return_value=_kst(18, 30)
        ), mock.patch(
            "internal_jobs.create_keysuri_owner_review_job", side_effect=_runner
        ):
            scheduled = self.client.post(
                KEYSURI_ENDPOINT,
                json=scheduled_body,
                headers=_headers(),
            )

        manual_body = dict(scheduled_body)
        manual_body["trigger_source"] = "manual_service_full_run"
        with mock.patch(
            "internal_jobs.create_keysuri_owner_review_job", side_effect=_runner
        ):
            manual = self.client.post(
                KEYSURI_ENDPOINT,
                json=manual_body,
                headers=_headers(),
            )

        self.assertEqual(scheduled.status_code, 200)
        self.assertEqual(manual.status_code, 200)
        self.assertEqual(observations, [True, False])
        self.assertFalse(natural_run_is_active())

        with mock.patch(
            "internal_jobs.get_kst_now", return_value=_kst(18, 30)
        ), mock.patch(
            "internal_jobs.create_keysuri_owner_review_job",
            side_effect=RuntimeError("runner failed"),
        ):
            failed = self.client.post(
                KEYSURI_ENDPOINT,
                json=scheduled_body,
                headers=_headers(),
            )
        self.assertEqual(failed.status_code, 500)
        self.assertFalse(natural_run_is_active())

    def test_today_service_full_run_persists_endpoint_admitted_natural_identity(self) -> None:
        from today_genie_service_full_run import _run_today_genie_service_full_run_impl

        saved: list[dict[str, Any]] = []
        upstream = mock.Mock(
            response_status=500,
            response_data={},
            reason_summary="request_failed",
        )
        identity = {
            "execution_class": "natural_scheduled",
            "scheduled_slot": "06:30",
            "natural_slot_key": "today_genie:2026-08-14:06:30:natural_scheduled",
            "kst_schedule_date": "2026-08-14",
        }
        with mock.patch(
            "today_genie_service_full_run.run_genie_job", return_value=upstream
        ), mock.patch(
            "today_genie_service_full_run.generate_run_id",
            return_value="20260814_063002_today_genie_1234abcd",
        ), mock.patch(
            "today_genie_service_full_run.save_run_artifact",
            side_effect=lambda meta, **_kwargs: saved.append(dict(meta)) or meta["run_id"],
        ):
            result = _run_today_genie_service_full_run_impl(
                trigger_source="scheduled_owner_review",
                send_owner_email=False,
                execution_identity_fields=identity,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(len(saved), 1)
        for key, value in identity.items():
            self.assertEqual(saved[0][key], value)

        saved.clear()
        with mock.patch(
            "today_genie_service_full_run.run_genie_job", return_value=upstream
        ), mock.patch(
            "today_genie_service_full_run.generate_run_id",
            return_value="20260814_064002_today_genie_abcdef12",
        ), mock.patch(
            "today_genie_service_full_run.save_run_artifact",
            side_effect=lambda meta, **_kwargs: saved.append(dict(meta)) or meta["run_id"],
        ):
            _run_today_genie_service_full_run_impl(
                trigger_source="manual_service_full_run",
                send_owner_email=False,
                execution_identity_fields=identity,
            )
        self.assertNotIn("execution_class", saved[0])


class KeysuriNaturalCompletionIdentityTests(unittest.TestCase):
    @staticmethod
    def _artifact(**overrides: Any) -> dict[str, Any]:
        artifact = {
            "run_id": "20260814_183450_keysuri_korea_tech_76737863",
            "mode": "keysuri_korea_tech",
            "program_id": "keysuri_korea_tech",
            "trigger_source": "manual_service_full_run",
            "email_sent": True,
            "validation_result": "pass",
            "parent_run_id": None,
        }
        artifact.update(overrides)
        return artifact

    def test_aug14_manual_email_cannot_satisfy_korea_natural_slot(self) -> None:
        from natural_run_watchdog import (
            _natural_completer_exists,
            diagnose_program_sla,
        )

        manual = self._artifact()
        self.assertIsNone(
            _natural_completer_exists(
                [manual],
                program_id="keysuri_korea_tech",
                kst_date="2026-08-14",
                scheduled_slot="18:30",
            )
        )
        incident = diagnose_program_sla(
            program_id="keysuri_korea_tech",
            artifacts=[manual],
            now=_kst(19, 0),
        )
        self.assertIsNotNone(incident)

    def test_only_legacy_scheduled_or_exact_explicit_natural_can_complete(self) -> None:
        from natural_run_watchdog import _natural_completer_exists

        def _match(artifact: dict[str, Any]):
            return _natural_completer_exists(
                [artifact],
                program_id="keysuri_korea_tech",
                kst_date="2026-08-14",
                scheduled_slot="18:30",
            )

        legacy_scheduled = self._artifact(
            trigger_source="scheduled_service_full_run",
        )
        self.assertIs(_match(legacy_scheduled), legacy_scheduled)

        exact_natural = self._artifact(
            trigger_source="scheduled_service_full_run",
            execution_class="natural_scheduled",
            scheduled_slot="18:30",
            kst_schedule_date="2026-08-14",
        )
        self.assertIs(_match(exact_natural), exact_natural)

        for disqualified in (
            self._artifact(
                trigger_source="admin_recovery_approved",
                execution_class="recovery",
                scheduled_slot="18:30",
            ),
            self._artifact(
                trigger_source="scheduled_service_full_run",
                execution_class="natural_scheduled",
                scheduled_slot="12:30",
            ),
            self._artifact(
                trigger_source="manual_service_full_run",
                execution_class="natural_scheduled",
                scheduled_slot="18:30",
            ),
        ):
            with self.subTest(disqualified=disqualified):
                self.assertIsNone(_match(disqualified))

    def test_scheduled_keysuri_failure_artifact_persists_canonical_identity(self) -> None:
        from keysuri_live_source_smoke import LiveSourceSmokeResult
        from keysuri_service_full_run import _run_keysuri_service_full_run_impl

        smoke = LiveSourceSmokeResult(
            ok=False,
            program_id="keysuri_korea_tech",
            source_pack_path="",
            html_path="",
            fetched_item_count=0,
            feed_urls_used=[],
            sample_marker_pass=False,
            validation_status="BLOCK",
            validation_issues=["no_candidates"],
            called_gemini=False,
            error="selection_hold",
        )
        saved: list[dict[str, Any]] = []

        def _save(meta: dict[str, Any], **_kwargs: Any) -> str:
            saved.append(dict(meta))
            return str(meta.get("run_id") or "")

        with mock.patch(
            "keysuri_service_full_run.generate_run_id",
            return_value="20260814_183002_keysuri_korea_tech_identity1",
        ), mock.patch(
            "keysuri_service_full_run.save_run_artifact", side_effect=_save
        ), mock.patch(
            "keysuri_service_full_run.emit_owner_review_failure_from_artifact_meta"
        ):
            result = _run_keysuri_service_full_run_impl(
                "keysuri_korea_tech",
                trigger_source="scheduled_service_full_run",
                send_owner_email=False,
                smoke_runner=lambda **_kwargs: smoke,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["execution_class"], "natural_scheduled")
        self.assertEqual(saved[0]["scheduled_slot"], "18:30")
        self.assertEqual(saved[0]["kst_schedule_date"], "2026-08-14")

        from keysuri_service_full_run import (
            _keysuri_scheduled_natural_identity_fields,
        )

        for trigger in ("manual_service_full_run", "admin_recovery_approved"):
            with self.subTest(trigger=trigger):
                self.assertEqual(
                    _keysuri_scheduled_natural_identity_fields(
                        program_id="keysuri_korea_tech",
                        run_id="20260814_190000_keysuri_korea_tech_other",
                        trigger_source=trigger,
                    ),
                    {},
                )


class RetryCopyGovernanceTests(unittest.TestCase):
    def _render(self, incident: dict[str, Any]) -> tuple[str, str]:
        from natural_run_incident_report import (
            build_failure_report_html,
            failure_report_subject,
        )

        with mock.patch(
            "admin_urls.build_incident_admin_url",
            return_value="https://example.com/admin/incidents/test",
        ):
            return failure_report_subject(incident), build_failure_report_html(incident)

    def _assert_held(self, incident: dict[str, Any]) -> None:
        subject, html = self._render(incident)
        self.assertIn("원인 조사 필요", subject)
        self.assertIn("재실행 보류", subject)
        self.assertIn("원인 조사 필요 — 재실행 보류", html)
        self.assertNotIn("재실행 승인 필요", subject + html)
        self.assertNotIn("이 실행을 다시 시도할까요?", html)
        self.assertNotIn("재실행 검토하기", html)
        self.assertIn("장애 상세 보기", html)

    def test_aug14_korea_oom_unknown_incident_is_investigation_hold(self) -> None:
        from natural_run_incident_store import (
            RETRY_STATUS_UNKNOWN,
            ROOT_CAUSE_UNKNOWN,
            new_incident,
        )

        incident = new_incident(
            program_id="keysuri_korea_tech",
            kst_date="2026-08-14",
            scheduled_slot="18:30",
            root_cause_verdict=ROOT_CAUSE_UNKNOWN,
            retry_verdict=RETRY_STATUS_UNKNOWN,
            facts=[
                "18:30:02 KST 자연실행 시작",
                "Cloud Run 512MiB 제한에서 514MiB 사용 후 종료",
                "HTTP 503 / Scheduler UNAVAILABLE",
            ],
            unknowns=["동일 리비전에서의 동시 요청별 정확한 RSS 기여"],
            summary_ko="2026-08-14 Korea 자연실행이 메모리 한계를 초과했습니다.",
        )
        self._assert_held(incident)

    def test_unknown_or_inconclusive_root_and_unknown_or_blocked_retry_are_held(self) -> None:
        from natural_run_incident_store import (
            RETRY_BLOCKED,
            RETRY_SAFE,
            RETRY_STATUS_UNKNOWN,
            ROOT_CAUSE_CONFIRMED,
            ROOT_CAUSE_UNKNOWN,
            STATUS_RETRY_BLOCKED_PENDING_PATCH,
            new_incident,
        )

        cases = [
            (ROOT_CAUSE_UNKNOWN, RETRY_SAFE),
            ("ROOT_CAUSE_INCONCLUSIVE", RETRY_SAFE),
            (ROOT_CAUSE_CONFIRMED, RETRY_STATUS_UNKNOWN),
            (ROOT_CAUSE_CONFIRMED, RETRY_BLOCKED),
        ]
        for root, retry in cases:
            with self.subTest(root=root, retry=retry):
                incident = new_incident(
                    program_id="keysuri_korea_tech",
                    kst_date="2026-08-14",
                    scheduled_slot="18:30",
                    confirmed_cause="bounded test cause",
                    root_cause_verdict=root,
                    retry_verdict=retry,
                )
                self._assert_held(incident)

        # Even when a newer revision makes an old repeat-failure guard stale,
        # the persisted BLOCKED retry verdict itself remains authoritative.
        stale_guard = new_incident(
            program_id="keysuri_korea_tech",
            kst_date="2026-08-14",
            scheduled_slot="18:30",
            confirmed_cause="known failure",
            root_cause_verdict=ROOT_CAUSE_CONFIRMED,
            retry_verdict=RETRY_BLOCKED,
        )
        stale_guard.update(
            {
                "status": STATUS_RETRY_BLOCKED_PENDING_PATCH,
                "retry_verdict_before_recovery_guard": RETRY_SAFE,
                "recovery_failure_signature_components": {"revision": "old-revision"},
                "revision": "new-revision",
            }
        )
        self._assert_held(stale_guard)

    def test_only_safely_actionable_incident_gets_review_language(self) -> None:
        from natural_run_incident_store import (
            RETRY_ALLOWED_WITH_WARNING,
            RETRY_SAFE,
            ROOT_CAUSE_CONFIRMED,
            ROOT_CAUSE_PARTIAL,
            incident_retry_review_allowed,
            new_incident,
        )

        cases = [
            (ROOT_CAUSE_CONFIRMED, RETRY_SAFE),
            (ROOT_CAUSE_PARTIAL, RETRY_ALLOWED_WITH_WARNING),
        ]
        for root, retry in cases:
            with self.subTest(root=root, retry=retry):
                incident = new_incident(
                    program_id="keysuri_korea_tech",
                    kst_date="2026-08-14",
                    scheduled_slot="18:30",
                    confirmed_cause="isolated terminal validation failure",
                    root_cause_verdict=root,
                    retry_verdict=retry,
                )
                self.assertTrue(incident_retry_review_allowed(incident))
                subject, html = self._render(incident)
                self.assertIn("재실행 검토", subject)
                self.assertNotIn("재실행 승인 필요", subject + html)
                self.assertIn("이 실행을 다시 시도할까요?", html)
                self.assertIn("재실행 검토하기", html)


class IncidentGcsBoundTests(unittest.TestCase):
    class _Blob:
        def __init__(self, name: str, updated: int) -> None:
            self.name = name
            self.updated = updated
            self.time_created = updated

    class _Bucket:
        def __init__(self, blobs: list[Any]) -> None:
            self.blobs = blobs
            self.calls: list[dict[str, Any]] = []
            self.yielded = 0

        def list_blobs(self, *, prefix: str, max_results: int):
            self.calls.append({"prefix": prefix, "max_results": max_results})
            matches = sorted(
                (blob for blob in self.blobs if blob.name.startswith(prefix)),
                key=lambda blob: blob.name,
            )
            for blob in matches[:max_results]:
                self.yielded += 1
                yield blob

    class _Client:
        def __init__(self, bucket: Any) -> None:
            self._bucket = bucket

        def bucket(self, _name: str):
            return self._bucket

    def test_incident_gcs_listing_is_bounded_before_materialization(self) -> None:
        from natural_run_incident_store import (
            INCIDENT_GCS_SCAN_MAX_RESULTS,
            INCIDENT_LIST_MAX_LIMIT,
            _gcs_list_ids,
        )

        programs = (
            ("today_genie", "06-30", 6),
            ("keysuri_global_tech", "12-30", 12),
            ("keysuri_korea_tech", "18-30", 18),
        )
        blobs: list[Any] = []
        for month, day_count in ((8, 14), (7, 31)):
            for day in range(1, day_count + 1):
                for program_id, slot, hour in programs:
                    iid = f"2026-{month:02d}-{day:02d}_{program_id}_{slot}"
                    blobs.append(
                        self._Blob(
                            f"admin_incidents/{iid}.json",
                            datetime(2026, month, day, hour, tzinfo=KST),
                        )
                    )
                verification_id = (
                    f"verification_2026-{month:02d}-{day:02d}_watchdog_test"
                )
                blobs.append(
                    self._Blob(
                        f"admin_incidents/{verification_id}.json",
                        datetime(2026, month, day, 19, tzinfo=KST),
                    )
                )
        # More smoke objects than the per-month cap prove that the separate
        # durable latest pointer preserves the true newest smoke id.
        for minute in range(80):
            hour, minute_of_hour = divmod(minute, 60)
            iid = f"smoke_2026-08-14_{hour:02d}{minute_of_hour:02d}00_watchdog"
            blobs.append(
                self._Blob(
                    f"admin_incidents/{iid}.json",
                    datetime(2026, 8, 14, hour, minute_of_hour, tzinfo=KST),
                )
            )
        latest_smoke = "smoke_2026-08-14_235959_watchdog"
        # A large historical corpus must never be touched by the recent-prefix
        # page, even though a bucket-wide ascending scan would start there.
        for index in range(2_000):
            year = 2000 + (index % 20)
            iid = f"{year:04d}-01-01_today_genie_06-30"
            blobs.append(
                self._Blob(
                    f"admin_incidents/{iid}.json",
                    datetime(year, 1, 1, 6, tzinfo=KST),
                )
            )
        bucket = self._Bucket(blobs)
        client = self._Client(bucket)
        with mock.patch(
            "natural_run_incident_store._gcs_storage_client", return_value=client
        ), mock.patch(
            "natural_run_incident_store._bucket_name", return_value="bounded-bucket"
        ), mock.patch(
            "natural_run_incident_store.load_smoke_latest_incident_id",
            return_value=latest_smoke,
        ):
            incident_ids = _gcs_list_ids(limit=10_000, now=_kst(23, 59, 59))

        self.assertTrue(bucket.calls)
        self.assertNotIn("admin_incidents/", {call["prefix"] for call in bucket.calls})
        self.assertTrue(
            all(
                call["prefix"].startswith(
                    (
                        "admin_incidents/2026-",
                        "admin_incidents/verification_2026-",
                        "admin_incidents/smoke_2026-",
                    )
                )
                for call in bucket.calls
            )
        )
        self.assertLessEqual(bucket.yielded, INCIDENT_GCS_SCAN_MAX_RESULTS)
        self.assertEqual(len(incident_ids), INCIDENT_LIST_MAX_LIMIT)
        self.assertEqual(incident_ids[0], latest_smoke)
        self.assertIn(
            "2026-08-14_keysuri_korea_tech_18-30",
            incident_ids,
        )
        self.assertFalse(any(iid.startswith("2000-") for iid in incident_ids))

    def test_incident_gcs_listing_refines_saturated_day_31_to_true_newest(self) -> None:
        from natural_run_incident_store import _gcs_list_ids

        blobs: list[Any] = []
        for minute in range(80):
            hour, minute_of_hour = divmod(minute, 60)
            iid = f"smoke_2026-08-31_{hour:02d}{minute_of_hour:02d}00_watchdog"
            blobs.append(
                self._Blob(
                    f"admin_incidents/{iid}.json",
                    datetime(
                        2026,
                        8,
                        31,
                        hour,
                        minute_of_hour,
                        tzinfo=KST,
                    ),
                )
            )
        latest = "smoke_2026-08-31_235959_watchdog"
        bucket = self._Bucket(blobs)
        client = self._Client(bucket)
        with mock.patch(
            "natural_run_incident_store._gcs_storage_client", return_value=client
        ), mock.patch(
            "natural_run_incident_store._bucket_name", return_value="bounded-bucket"
        ), mock.patch(
            "natural_run_incident_store.load_smoke_latest_incident_id",
            return_value=latest,
        ):
            incident_ids = _gcs_list_ids(
                limit=10,
                now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=KST),
            )

        self.assertEqual(incident_ids[0], latest)
        self.assertEqual(
            incident_ids[1:],
            [
                f"smoke_2026-08-31_01{minute:02d}00_watchdog"
                for minute in range(19, 10, -1)
            ],
        )

    def test_incident_gcs_cursor_pages_across_mixed_namespaces(self) -> None:
        from natural_run_incident_store import _gcs_list_id_rows

        smoke = "smoke_2026-08-14_200000_watchdog"
        natural = "2026-08-14_keysuri_korea_tech_18-30"
        verification = "verification_2026-08-14_watchdog_test"
        blobs = [
            self._Blob(f"admin_incidents/{smoke}.json", 1),
            self._Blob(f"admin_incidents/{natural}.json", 1),
            self._Blob(f"admin_incidents/{verification}.json", 1),
        ]
        bucket = self._Bucket(blobs)
        client = self._Client(bucket)
        patches = (
            mock.patch(
                "natural_run_incident_store._gcs_storage_client",
                return_value=client,
            ),
            mock.patch(
                "natural_run_incident_store._bucket_name",
                return_value="bounded-bucket",
            ),
            mock.patch(
                "natural_run_incident_store.load_smoke_latest_incident_id",
                return_value=None,
            ),
        )
        with patches[0], patches[1], patches[2]:
            first = _gcs_list_id_rows(
                2, now=datetime(2026, 8, 14, 21, 0, tzinfo=KST)
            )
            second = _gcs_list_id_rows(2, cursor=first[-1][0])

        self.assertEqual([row[0] for row in first], [smoke, natural])
        self.assertEqual([row[0] for row in second], [verification])

    def test_incident_list_reads_summary_only_and_keeps_full_payload_detail_only(self) -> None:
        from natural_run_incident_store import (
            list_incidents,
            load_incident,
            new_incident,
            save_incident,
        )

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "natural_run_incident_store.incidents_local_dir",
            return_value=Path(tmp),
        ), mock.patch("natural_run_incident_store._uses_gcs", return_value=False):
            incident = new_incident(
                program_id="keysuri_korea_tech",
                kst_date="2026-08-14",
                scheduled_slot="18:30",
                failure_event={"large_payload": "x" * 1_000_000},
                retry_verdict="RETRY_STATUS_UNKNOWN",
            )
            save_incident(incident)
            with mock.patch(
                "natural_run_incident_store.load_incident",
                side_effect=AssertionError("list must not load full incident JSON"),
            ):
                rows = list_incidents(limit=10)
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["incident_list_summary"])
            self.assertNotIn("failure_event", rows[0])
            detail = load_incident(incident["incident_id"])
            self.assertEqual(len(detail["failure_event"]["large_payload"]), 1_000_000)


if __name__ == "__main__":
    unittest.main()
