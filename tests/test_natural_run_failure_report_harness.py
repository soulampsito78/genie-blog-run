"""Production-faithful harness: Korean failure report + human-approved recovery.

Fakes: clock, incident store dir, SMTP, orchestrator/Keysuri runners.
Does not fake: report structure, lease semantics, watchdog auto-retry ban.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
# Friday 2026-08-07 after 06:30+grace
AFTER_TODAY_SLOT = datetime(2026, 8, 7, 7, 0, tzinfo=KST)
AFTER_GLOBAL_SLOT = datetime(2026, 8, 7, 13, 0, tzinfo=KST)
AFTER_KOREA_SLOT = datetime(2026, 8, 7, 19, 0, tzinfo=KST)
# Activation before any same-day slot so harness polls are not watermark-skipped.
ACTIVATION_EARLY = datetime(2026, 8, 7, 0, 5, tzinfo=KST)


class _SmtpProbe:
    def __init__(self) -> None:
        self.subjects: List[str] = []
        self.bodies: List[str] = []
        self.customer_sends = 0
        self.calls = 0

    def __call__(self, html_body: str, subject: str, **kwargs: Any) -> bool:
        self.calls += 1
        self.subjects.append(subject)
        self.bodies.append(html_body)
        return True


class NaturalRunFailureReportHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.inc_dir = Path(self.tmp.name) / "admin_incidents"
        self.inc_dir.mkdir(parents=True, exist_ok=True)
        self.smtp = _SmtpProbe()
        self.recovery_calls = 0
        self.auto_retries = 0
        self._patches = [
            mock.patch(
                "natural_run_incident_store.incidents_local_dir",
                return_value=self.inc_dir,
            ),
            mock.patch("natural_run_incident_store._uses_gcs", return_value=False),
            mock.patch.dict(os.environ, {"GENIE_ARTIFACT_BUCKET": "", "GENIE_ADMIN_ARTIFACT_BUCKET": ""}, clear=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self.tmp.cleanup()

    def _assert_korean_report_shape(self, html: str) -> None:
        self.assertIn("GENIE 자연실행 장애 보고", html)
        self.assertIn("무슨 일이 발생했습니까?", html)
        self.assertIn("어디까지 정상적으로 진행됐습니까?", html)
        self.assertIn("장애 원인", html)
        self.assertIn("이번 장애의 결과", html)
        self.assertIn("현재 시스템 상태", html)
        self.assertIn("재실행 가능 여부", html)
        self.assertIn("시스템 권고", html)
        self.assertIn("이 실행을 다시 시도할까요?", html)
        self.assertIn("승인 전에는 시스템이 자동 재실행하지 않습니다.", html)
        self.assertNotIn("Traceback", html)
        self.assertNotIn("smtp_password", html.lower())

    def test_01_scheduler_miss_korean_report(self) -> None:
        from natural_run_watchdog import diagnose_program_sla, report_incident_once

        incident = diagnose_program_sla(
            program_id="today_genie",
            artifacts=[],
            request_evidence={"scheduler_fired": False},
            now=AFTER_TODAY_SLOT,
        )
        self.assertIsNotNone(incident)
        assert incident is not None
        self.assertEqual(incident["confirmed_cause"], "Scheduler가 예정 시각에 실행되지 않았습니다.")
        out = report_incident_once(incident, send_fn=self.smtp)
        self.assertTrue(out["report_sent"])
        self.assertEqual(self.smtp.calls, 1)
        self.assertTrue(self.smtp.subjects[0].startswith("[GENIE 장애보고] Today_Geenee 06:30"))
        self._assert_korean_report_shape(self.smtp.bodies[0])
        self.assertEqual(out["auto_retry"], 0)

    def test_02_http_200_silent_skip_korean_report(self) -> None:
        from natural_run_watchdog import diagnose_program_sla, report_incident_once

        qa = {
            "run_id": "20260807_003207_today_genie_255d3454",
            "mode": "today_genie",
            "execution_class": "qa_manual",
            "email_sent": True,
            "artifact_status": "emailed",
            "validation_result": "pass",
        }
        incident = diagnose_program_sla(
            program_id="today_genie",
            artifacts=[qa],
            request_evidence={
                "scheduler_fired": True,
                "cloud_run_status": 200,
                "latency_seconds": 4.7,
            },
            now=AFTER_TODAY_SLOT,
        )
        self.assertIsNotNone(incident)
        assert incident is not None
        self.assertIn("QA", incident["confirmed_cause"] or "")
        out = report_incident_once(incident, send_fn=self.smtp)
        self.assertTrue(out["report_sent"])
        self._assert_korean_report_shape(self.smtp.bodies[0])
        self.assertIn("HTTP 200", self.smtp.bodies[0])

    def test_03_generation_failure_korean_report(self) -> None:
        from natural_run_watchdog import notify_natural_run_incident_from_failure

        out = notify_natural_run_incident_from_failure(
            program_id="keysuri_global_tech",
            run_id="20260807_123000_keysuri_global_tech_deadbeef",
            trigger_source="scheduled_service_full_run",
            first_failed_stage="generation_validation",
            error_code="generation_failed",
            issue_codes=["gemini_empty"],
            now=AFTER_GLOBAL_SLOT,
            send_fn=self.smtp,
        )
        self.assertIsNotNone(out)
        self.assertTrue(out and out.get("report_sent"))
        self.assertTrue(self.smtp.subjects[0].startswith("[GENIE 장애보고] KeeSuri_Global_Tech 12:30"))

    def test_04_validation_failure_korean_report(self) -> None:
        from natural_run_watchdog import notify_natural_run_incident_from_failure

        out = notify_natural_run_incident_from_failure(
            program_id="keysuri_korea_tech",
            run_id="20260807_183000_keysuri_korea_tech_aabbccdd",
            trigger_source="scheduled_service_full_run",
            first_failed_stage="generation_validation",
            error_code="validation_blocked",
            now=AFTER_KOREA_SLOT,
            send_fn=self.smtp,
        )
        self.assertTrue(out and out.get("report_sent"))
        self.assertIn("검증", self.smtp.bodies[0])

    def test_05_smtp_failure_korean_report(self) -> None:
        from natural_run_watchdog import notify_natural_run_incident_from_failure

        out = notify_natural_run_incident_from_failure(
            program_id="today_genie",
            run_id="20260807_063100_today_genie_smtpfail",
            trigger_source="scheduled_owner_review",
            first_failed_stage="email_delivery",
            error_code="smtp_send_failed",
            artifact_saved=True,
            email_sent=False,
            now=AFTER_TODAY_SLOT,
            send_fn=self.smtp,
        )
        self.assertTrue(out and out.get("report_sent"))
        self.assertIn("SMTP", self.smtp.bodies[0])

    def test_06_unknown_cause_not_asserted(self) -> None:
        from natural_run_incident_report import build_failure_report_html
        from natural_run_incident_store import new_incident

        incident = new_incident(
            program_id="today_genie",
            kst_date="2026-08-07",
            confirmed_cause=None,
            hypotheses=["네트워크 지연 가능성"],
            summary_ko="원인 미확정 상태의 장애입니다.",
        )
        html = build_failure_report_html(incident)
        self.assertIn("직접 원인:", html)
        self.assertIn("원인 미확정", html)
        self.assertIn("추정 또는 가능성", html)
        self.assertIn("네트워크 지연 가능성", html)
        # Must not present hypothesis as sole direct cause
        self.assertNotRegex(html, r"직접 원인:</strong><br>네트워크 지연")

    def test_07_customer_send_always_zero(self) -> None:
        from natural_run_watchdog import run_watchdog_poll

        summary = run_watchdog_poll(
            artifacts=[],
            request_evidence_by_program={"today_genie": {"scheduler_fired": False}},
            now=AFTER_TODAY_SLOT,
            activated_at=ACTIVATION_EARLY,
            send_fn=self.smtp,
            programs=["today_genie"],
        )
        self.assertEqual(summary["customer_send"], 0)
        self.assertEqual(self.smtp.customer_sends, 0)

    def test_08_auto_retry_always_zero(self) -> None:
        from natural_run_watchdog import run_watchdog_poll

        summary = run_watchdog_poll(
            artifacts=[],
            request_evidence_by_program={"today_genie": {"scheduler_fired": False}},
            now=AFTER_TODAY_SLOT,
            activated_at=ACTIVATION_EARLY,
            send_fn=self.smtp,
            programs=["today_genie"],
        )
        self.assertEqual(summary["auto_retry"], 0)

    def test_09_report_ends_with_retry_question(self) -> None:
        from natural_run_incident_report import build_failure_report_html
        from natural_run_incident_store import new_incident

        html = build_failure_report_html(
            new_incident(program_id="today_genie", kst_date="2026-08-07")
        )
        self.assertIn("이 실행을 다시 시도할까요?", html)

    def test_10_no_recovery_before_approval(self) -> None:
        from natural_run_watchdog import report_incident_once
        from natural_run_incident_store import new_incident

        incident = new_incident(
            program_id="today_genie",
            kst_date="2026-08-07",
            confirmed_cause="Scheduler가 예정 시각에 실행되지 않았습니다.",
        )
        report_incident_once(incident, send_fn=self.smtp)
        self.assertEqual(self.recovery_calls, 0)

    def test_11_approval_runs_exactly_one_recovery(self) -> None:
        from natural_run_incident_store import new_incident, save_incident, mark_report_sent
        from natural_run_recovery import execute_approved_recovery

        incident = new_incident(
            program_id="today_genie",
            kst_date="2026-08-07",
            confirmed_cause="Scheduler가 예정 시각에 실행되지 않았습니다.",
            retry_verdict="SAFE_TO_RETRY",
        )
        save_incident(incident)
        mark_report_sent(incident["incident_id"])

        def today_runner(*args, **kwargs):
            self.recovery_calls += 1
            self.assertEqual(kwargs.get("execution_class"), "recovery")
            self.assertEqual(kwargs.get("trigger_source"), "admin_recovery_approved")
            return ("20260807_080000_today_genie_recov001", mock.Mock(response_data={"validation_result": "pass"}), True)

        out = execute_approved_recovery(
            incident["incident_id"],
            today_runner=today_runner,
            send_fn=self.smtp,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(self.recovery_calls, 1)
        self.assertEqual(out["customer_send"], 0)
        self.assertEqual(out["auto_retry"], 0)

        # Second approve blocked by lease/status
        out2 = execute_approved_recovery(
            incident["incident_id"],
            today_runner=today_runner,
            send_fn=self.smtp,
        )
        self.assertFalse(out2["ok"])
        self.assertEqual(self.recovery_calls, 1)

    def test_12_recovery_success_report(self) -> None:
        from natural_run_incident_store import new_incident, save_incident, mark_report_sent
        from natural_run_recovery import execute_approved_recovery

        incident = new_incident(program_id="today_genie", kst_date="2026-08-07")
        save_incident(incident)
        mark_report_sent(incident["incident_id"])
        execute_approved_recovery(
            incident["incident_id"],
            today_runner=lambda *a, **k: (
                "20260807_080000_today_genie_recov001",
                mock.Mock(response_data={"validation_result": "pass"}),
                True,
            ),
            send_fn=self.smtp,
        )
        self.assertTrue(any(s.startswith("[GENIE 복구완료]") for s in self.smtp.subjects))

    def test_13_recovery_failure_report_no_auto_retry(self) -> None:
        from natural_run_incident_store import new_incident, save_incident, mark_report_sent
        from natural_run_recovery import execute_approved_recovery

        incident = new_incident(program_id="today_genie", kst_date="2026-08-07")
        save_incident(incident)
        mark_report_sent(incident["incident_id"])

        def boom(*a, **k):
            raise RuntimeError("recovery boom")

        out = execute_approved_recovery(
            incident["incident_id"],
            today_runner=boom,
            send_fn=self.smtp,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["auto_retry"], 0)
        self.assertTrue(any(s.startswith("[GENIE 복구실패]") for s in self.smtp.subjects))

    def test_14_watchdog_repoll_no_duplicate_failure_mail(self) -> None:
        from natural_run_watchdog import run_watchdog_poll

        evidence = {"today_genie": {"scheduler_fired": False}}
        run_watchdog_poll(
            artifacts=[],
            request_evidence_by_program=evidence,
            now=AFTER_TODAY_SLOT,
            activated_at=ACTIVATION_EARLY,
            send_fn=self.smtp,
            programs=["today_genie"],
        )
        run_watchdog_poll(
            artifacts=[],
            request_evidence_by_program=evidence,
            now=AFTER_TODAY_SLOT,
            activated_at=ACTIVATION_EARLY,
            send_fn=self.smtp,
            programs=["today_genie"],
        )
        failure_mails = [s for s in self.smtp.subjects if s.startswith("[GENIE 장애보고]")]
        self.assertEqual(len(failure_mails), 1)

    def test_15_no_secret_or_token_leak(self) -> None:
        from natural_run_incident_report import build_failure_report_html
        from natural_run_incident_store import new_incident

        incident = new_incident(
            program_id="today_genie",
            kst_date="2026-08-07",
            facts=["smtp_password=supersecret", "Authorization: Bearer abc"],
            hypotheses=["raw_response dump"],
        )
        html = build_failure_report_html(incident)
        self.assertNotIn("supersecret", html)
        self.assertNotIn("Bearer abc", html)
        self.assertIn("생략", html)

    def test_16_no_raw_stack_in_body(self) -> None:
        from natural_run_incident_report import build_failure_report_html
        from natural_run_incident_store import new_incident

        incident = new_incident(
            program_id="today_genie",
            kst_date="2026-08-07",
            summary_ko='Traceback (most recent call last):\n  File "x.py", line 1',
        )
        html = build_failure_report_html(incident)
        self.assertNotIn("Traceback", html)
        self.assertNotIn('File "x.py"', html)

    def test_17_fact_cause_hypothesis_unknown_separated(self) -> None:
        from natural_run_incident_report import build_failure_report_html
        from natural_run_incident_store import new_incident

        html = build_failure_report_html(
            new_incident(
                program_id="today_genie",
                kst_date="2026-08-07",
                facts=["사실A"],
                hypotheses=["추정B"],
                unknowns=["미확인C"],
                confirmed_cause="확정원인D",
            )
        )
        self.assertIn("확인된 사실", html)
        self.assertIn("사실A", html)
        self.assertIn("추정 또는 가능성", html)
        self.assertIn("추정B", html)
        self.assertIn("아직 확인되지 않은 사항", html)
        self.assertIn("미확인C", html)
        self.assertIn("확정원인D", html)

    def test_18_retry_verdict_from_persisted_state(self) -> None:
        from natural_run_incident_report import build_failure_report_html
        from natural_run_incident_store import RETRY_REQUIRES_PATCH, new_incident

        incident = new_incident(
            program_id="today_genie",
            kst_date="2026-08-07",
            retry_verdict=RETRY_REQUIRES_PATCH,
            retry_verdict_ko="수정 완료 전에는 재실행하지 않는 것이 안전합니다.",
        )
        html = build_failure_report_html(incident)
        self.assertIn(RETRY_REQUIRES_PATCH, html)
        self.assertIn("수정 완료 전에는 재실행하지 않는 것이 안전합니다.", html)

    def test_19_qa_reissue_not_mistaken_as_natural_recovery_target(self) -> None:
        from natural_run_watchdog import diagnose_program_sla

        # Natural completer present → no incident
        natural = {
            "run_id": "20260807_063058_today_genie_natok01",
            "mode": "today_genie",
            "execution_class": "natural_scheduled",
            "scheduled_slot": "06:30",
            "email_sent": True,
            "artifact_status": "emailed",
            "validation_result": "pass",
            "owner_review_status": "pending_review",
        }
        self.assertIsNone(
            diagnose_program_sla(
                program_id="today_genie",
                artifacts=[natural],
                request_evidence={"scheduler_fired": True, "cloud_run_status": 200},
                now=AFTER_TODAY_SLOT,
            )
        )
        # QA only → incident (not treated as natural success)
        qa = {
            "run_id": "20260807_003207_today_genie_255d3454",
            "mode": "today_genie",
            "execution_class": "qa_manual",
            "email_sent": True,
            "artifact_status": "emailed",
            "validation_result": "pass",
        }
        incident = diagnose_program_sla(
            program_id="today_genie",
            artifacts=[qa],
            request_evidence={
                "scheduler_fired": True,
                "cloud_run_status": 200,
                "latency_seconds": 5,
            },
            now=AFTER_TODAY_SLOT,
        )
        self.assertIsNotNone(incident)

    def test_20_tomorrow_paused_no_failure_report(self) -> None:
        from natural_run_watchdog import run_watchdog_poll

        summary = run_watchdog_poll(
            artifacts=[],
            now=AFTER_TODAY_SLOT,
            activated_at=ACTIVATION_EARLY,
            send_fn=self.smtp,
            programs=["tomorrow_genie"],
            paused_programs=["tomorrow_genie"],
        )
        self.assertEqual(self.smtp.calls, 0)
        self.assertTrue(summary["results"][0].get("skipped"))

    def test_21_activation_watermark_skips_pre_activation_slots(self) -> None:
        from natural_run_watchdog import run_watchdog_poll

        # Activated after Today's SLA threshold — must not backfill alert.
        late_activation = datetime(2026, 8, 7, 10, 0, tzinfo=KST)
        summary = run_watchdog_poll(
            artifacts=[],
            request_evidence_by_program={"today_genie": {"scheduler_fired": False}},
            now=AFTER_TODAY_SLOT.replace(hour=11),
            activated_at=late_activation,
            send_fn=self.smtp,
            programs=["today_genie"],
        )
        self.assertEqual(self.smtp.calls, 0)
        self.assertEqual(summary["results"][0].get("reason"), "pre_activation_slot")

    def test_22_verification_probe_dedup_and_subject(self) -> None:
        from natural_run_watchdog import run_watchdog_verification_probe
        from natural_run_recovery import execute_approved_recovery

        first = run_watchdog_verification_probe(now=AFTER_TODAY_SLOT, send_fn=self.smtp)
        self.assertTrue(first["report_sent"])
        self.assertTrue(first["subject"].startswith("[GENIE WATCHDOG TEST]"))
        self._assert_korean_report_shape(self.smtp.bodies[0])
        second = run_watchdog_verification_probe(now=AFTER_TODAY_SLOT, send_fn=self.smtp)
        self.assertTrue(second["deduped"])
        self.assertEqual(self.smtp.calls, 1)
        blocked = execute_approved_recovery(first["incident_id"], send_fn=self.smtp)
        self.assertEqual(blocked.get("error"), "verification_only_recovery_blocked")
        self.assertEqual(blocked.get("customer_send"), 0)

    def test_23_smoke_failure_report_dedup_and_detected_at(self) -> None:
        from natural_run_watchdog import run_watchdog_smoke_failure_probe
        from natural_run_recovery import execute_approved_recovery

        with mock.patch("admin_store.save_run_artifact", return_value="ok"):
            first = run_watchdog_smoke_failure_probe(now=AFTER_TODAY_SLOT, send_fn=self.smtp)
        self.assertTrue(first["report_sent"])
        self.assertTrue(first["subject"].startswith("[GENIE SMOKE 장애보고]"))
        self.assertTrue(str(first.get("detected_at") or "").startswith("2026-08-07T"))
        self.assertIn(first["detected_at"], self.smtp.bodies[0])
        self._assert_korean_report_shape(self.smtp.bodies[0])
        with mock.patch("admin_store.save_run_artifact", return_value="ok"):
            second = run_watchdog_smoke_failure_probe(
                now=AFTER_TODAY_SLOT,
                send_fn=self.smtp,
                incident_id=first["incident_id"],
            )
        self.assertTrue(second["deduped"])
        self.assertEqual(self.smtp.calls, 1)
        blocked = execute_approved_recovery(first["incident_id"], send_fn=self.smtp)
        self.assertIn(blocked.get("error"), {"smoke_recovery_blocked", "verification_only_recovery_blocked"})
        self.assertEqual(blocked.get("customer_send"), 0)


class AdminRecoveryRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient
        from main import app

        self.tmp = tempfile.TemporaryDirectory()
        self.inc_dir = Path(self.tmp.name) / "admin_incidents"
        self.inc_dir.mkdir(parents=True, exist_ok=True)
        self.env = mock.patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_PASSWORD": "test-admin-secret",
                "GENIE_ARTIFACT_BUCKET": "",
                "GENIE_ADMIN_ARTIFACT_BUCKET": "",
                "GENIE_ADMIN_PUBLIC_BASE_URL": "https://genie-blog-run.example.run.app",
            },
            clear=False,
        )
        self.env.start()
        self.dir_patch = mock.patch(
            "natural_run_incident_store.incidents_local_dir",
            return_value=self.inc_dir,
        )
        self.gcs_patch = mock.patch("natural_run_incident_store._uses_gcs", return_value=False)
        self.dir_patch.start()
        self.gcs_patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.gcs_patch.stop()
        self.dir_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _login(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})

    def _reported_safe_incident(self, **kwargs):
        from natural_run_incident_store import new_incident, save_incident, mark_report_sent

        defaults = dict(
            program_id="today_genie",
            kst_date="2026-08-07",
            confirmed_cause="Scheduler가 예정 시각에 실행되지 않았습니다.",
            retry_verdict="SAFE_TO_RETRY",
        )
        defaults.update(kwargs)
        incident = new_incident(**defaults)
        save_incident(incident)
        mark_report_sent(incident["incident_id"])
        return incident

    def test_approve_recovery_requires_login_and_calls_executor_once(self) -> None:
        unauth = self.client.post(
            "/admin/incidents/2026-08-07_today_genie_06-30/approve-recovery",
            follow_redirects=False,
        )
        self.assertIn(unauth.status_code, (302, 303))

        incident = self._reported_safe_incident()
        self._login()
        with mock.patch(
            "natural_run_recovery.execute_approved_recovery",
            return_value={
                "ok": True,
                "recovery_run_id": "rid",
                "customer_send": 0,
                "auto_retry": 0,
            },
        ) as exec_mock:
            resp = self.client.post(
                f"/admin/incidents/{incident['incident_id']}/approve-recovery",
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 303)
        exec_mock.assert_called_once()

    def test_email_cta_and_verdict_gating_and_get_no_side_effect(self) -> None:
        from natural_run_incident_report import build_failure_report_html
        from natural_run_incident_store import (
            RETRY_BLOCKED,
            RETRY_REQUIRES_PATCH,
            RETRY_SAFE_TO_RETRY,
            RETRY_STATUS_UNKNOWN,
            load_incident,
            new_incident,
            save_incident,
            mark_report_sent,
        )
        from natural_run_recovery import execute_approved_recovery

        real = new_incident(
            program_id="today_genie",
            kst_date="2026-08-07",
            retry_verdict=RETRY_SAFE_TO_RETRY,
            confirmed_cause="SMTP 실패",
        )
        html = build_failure_report_html(real)
        self.assertIn("재실행 검토하기", html)
        self.assertIn(
            f"https://genie-blog-run.example.run.app/admin/incidents/{real['incident_id']}",
            html,
        )
        self.assertNotIn("token=", html.lower())
        self.assertNotIn("password=", html.lower())

        smoke = dict(real)
        smoke["smoke_failure"] = True
        smoke["smoke_only"] = True
        smoke_html = build_failure_report_html(smoke)
        self.assertIn("검증 incident 보기", smoke_html)
        self.assertNotIn(">재실행 검토하기<", smoke_html)

        save_incident(real)
        mark_report_sent(real["incident_id"])
        unauth = self.client.get(
            f"/admin/incidents/{real['incident_id']}", follow_redirects=False
        )
        self.assertIn(unauth.status_code, (302, 303))
        self._login()
        detail = self.client.get(f"/admin/incidents/{real['incident_id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("재실행 승인 검토", detail.text)
        self.assertIn("만으로는 재실행되지 않습니다", detail.text)
        after = load_incident(real["incident_id"])
        self.assertIsNone(after.get("recovery_run_id"))
        self.assertEqual(after.get("status"), "reported")

        for verdict, needle in [
            (RETRY_REQUIRES_PATCH, "수정 완료 전 재실행할 수 없습니다"),
            (RETRY_BLOCKED, "현재 상태에서는 재실행할 수 없습니다"),
            (RETRY_STATUS_UNKNOWN, "안전성이 확인되지 않아 재실행할 수 없습니다"),
        ]:
            meta = load_incident(real["incident_id"])
            meta["retry_verdict"] = verdict
            save_incident(meta)
            page = self.client.get(f"/admin/incidents/{real['incident_id']}")
            self.assertIn(needle, page.text)
            self.assertNotIn(f"/admin/incidents/{real['incident_id']}/approve-confirm", page.text)

        meta = load_incident(real["incident_id"])
        meta["retry_verdict"] = RETRY_SAFE_TO_RETRY
        save_incident(meta)
        page = self.client.get(f"/admin/incidents/{real['incident_id']}")
        self.assertIn("/approve-confirm", page.text)

        conf = self.client.get(f"/admin/incidents/{real['incident_id']}/approve-confirm")
        self.assertEqual(conf.status_code, 200)
        self.assertIn("정확히 1회 다시 실행합니다", conf.text)
        self.assertIn("고객 발송은 수행하지 않습니다", conf.text)
        self.assertEqual(load_incident(real["incident_id"]).get("status"), "reported")

        out1 = execute_approved_recovery(
            real["incident_id"],
            today_runner=lambda *a, **k: (
                "20260807_120000_today_genie_aaaaaaaa",
                mock.Mock(response_data={"validation_result": "pass"}),
                True,
            ),
            send_fn=lambda *a, **k: True,
        )
        self.assertTrue(out1["ok"])
        self.assertEqual(out1["customer_send"], 0)
        out2 = execute_approved_recovery(
            real["incident_id"],
            today_runner=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("should not run")),
            send_fn=lambda *a, **k: True,
        )
        self.assertFalse(out2["ok"])

        smoke_inc = self._reported_safe_incident(
            program_id="keysuri_korea_tech",
            kst_date="2026-08-07",
            retry_verdict=RETRY_SAFE_TO_RETRY,
        )
        smoke_meta = load_incident(smoke_inc["incident_id"])
        smoke_meta["smoke_only"] = True
        smoke_meta["verification_only"] = True
        save_incident(smoke_meta)
        blocked_page = self.client.get(f"/admin/incidents/{smoke_inc['incident_id']}")
        self.assertIn("실제 recovery 승인이 금지", blocked_page.text)
        post = self.client.post(
            f"/admin/incidents/{smoke_inc['incident_id']}/approve-recovery",
            follow_redirects=False,
        )
        self.assertEqual(post.status_code, 303)
        self.assertIn("smoke_or_verification_blocked", post.headers.get("location", ""))

        done_page = self.client.get(f"/admin/incidents/{real['incident_id']}")
        self.assertIn("재실행 승인 완료", done_page.text)
        self.assertNotIn("/approve-confirm", done_page.text)

    def test_concurrent_approve_exactly_once(self) -> None:
        import threading

        from natural_run_recovery import execute_approved_recovery

        incident = self._reported_safe_incident(
            program_id="today_genie",
            kst_date="2026-08-09",
            retry_verdict="SAFE_TO_RETRY",
        )
        hits = []

        def today_runner(*a, **k):
            hits.append(1)
            return (
                "20260809_130000_today_genie_bbbbbbbb",
                mock.Mock(response_data={"validation_result": "pass"}),
                True,
            )

        results = [None, None]

        def worker(idx: int) -> None:
            results[idx] = execute_approved_recovery(
                incident["incident_id"],
                today_runner=today_runner,
                send_fn=lambda *a, **k: True,
            )

        t1 = threading.Thread(target=worker, args=(0,))
        t2 = threading.Thread(target=worker, args=(1,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        oks = [r for r in results if r and r.get("ok")]
        self.assertEqual(len(oks), 1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(oks[0].get("customer_send"), 0)


if __name__ == "__main__":
    unittest.main()
