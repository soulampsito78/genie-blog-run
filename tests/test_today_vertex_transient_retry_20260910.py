"""Regression pins for the 2026-09-10 06:30 Today GENIE missed natural run.

Evidence being pinned (Cloud Run, revision
genie-blog-run-gcb-f7a79578-b013-41de-9afb-2a614602ac6c):

    2026-09-09T21:30:29Z (= 2026-09-10 06:30:29 KST)
    genie_api failure mode=today_genie internal_reason=vertex_path_unhandled
    exc_type=TooManyRequests message=429 ... Resource exhausted.
    create_owner_review: run_id=20260910_063029_today_genie_72848cab
    email_sent=False response_status=500 execution_class=natural_scheduled

A single transient Vertex 429 on the main-brief call ended the whole natural
run 27.5s after it started, because the model call had no retry at all.  The
owner received no 06:30 briefing.

These tests pin:
  * a transient fault is retried rather than ending the slot,
  * a permanent fault is still NOT retried (fail fast, no budget burn),
  * exhaustion still raises (fail closed — never a fabricated success),
  * retry sleep can never eat the 300s Scheduler attempt deadline,
  * the failed artifact must not satisfy the natural slot (watchdog must see
    the miss), and must not be auto-remediated as a content defect.
"""

from __future__ import annotations

import unittest
from unittest import mock

from google.api_core import exceptions as gexc

import main


# The verbatim message Vertex returned at 06:30:29 KST on 2026-09-10.
INCIDENT_429_MESSAGE = (
    "429 POST https://aiplatform.googleapis.com/v1/projects/"
    "gen-lang-client-0667098249/locations/global/publishers/google/models/"
    "gemini-2.5-flash:generateContent: Resource exhausted. Please try again later."
)

INCIDENT_RUN_ID = "20260910_063029_today_genie_72848cab"


class _FakeModel:
    """Stand-in for GenerativeModel recording each generate_content attempt."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def generate_content(self, prompt, generation_config=None):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class VertexTransientRetryTests(unittest.TestCase):
    def setUp(self):
        self.slept = []
        patcher = mock.patch.object(main.time, "sleep", self.slept.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_incident_429_is_retried_and_then_succeeds(self):
        """The exact 2026-09-10 fault must no longer end the natural run."""
        model = _FakeModel(
            [gexc.TooManyRequests(INCIDENT_429_MESSAGE), _FakeResponse("{}")]
        )
        result = main._generate_content_with_transient_retry(
            model, "p", generation_config=None, mode="today_genie"
        )
        self.assertEqual(model.calls, 2)
        self.assertEqual(result.text, "{}")
        self.assertEqual(len(self.slept), 1)

    def test_every_transient_type_is_retried(self):
        for exc_type in main._VERTEX_TRANSIENT_EXCEPTIONS:
            with self.subTest(exc=exc_type.__name__):
                model = _FakeModel([exc_type("transient"), _FakeResponse("ok")])
                main._generate_content_with_transient_retry(
                    model, "p", generation_config=None, mode="today_genie"
                )
                self.assertEqual(model.calls, 2)

    def test_permanent_error_is_not_retried(self):
        """A request-shaped fault must fail fast, not consume the slot budget."""
        for exc in (
            gexc.InvalidArgument("bad request"),
            gexc.PermissionDenied("no access"),
            gexc.NotFound("no such model"),
        ):
            with self.subTest(exc=type(exc).__name__):
                model = _FakeModel([exc])
                with self.assertRaises(type(exc)):
                    main._generate_content_with_transient_retry(
                        model, "p", generation_config=None, mode="today_genie"
                    )
                self.assertEqual(model.calls, 1)
                self.assertEqual(self.slept, [])

    def test_exhausted_retries_still_raise(self):
        """Fail closed: retry must never manufacture a success."""
        with mock.patch.dict(main.os.environ, {"GENIE_VERTEX_RETRY_ATTEMPTS": "3"}):
            model = _FakeModel([gexc.TooManyRequests(INCIDENT_429_MESSAGE)] * 3)
            with self.assertRaises(gexc.TooManyRequests):
                main._generate_content_with_transient_retry(
                    model, "p", generation_config=None, mode="today_genie"
                )
            self.assertEqual(model.calls, 3)

    def test_retry_sleep_never_exceeds_deadline_budget(self):
        """Retry sleep must stay inside the 300s Scheduler attempt deadline."""
        with mock.patch.dict(
            main.os.environ,
            {
                "GENIE_VERTEX_RETRY_ATTEMPTS": "12",
                "GENIE_VERTEX_RETRY_BASE_DELAY_SEC": "4.0",
                "GENIE_VERTEX_RETRY_MAX_TOTAL_DELAY_SEC": "45.0",
            },
        ):
            model = _FakeModel([gexc.TooManyRequests("429")] * 12)
            with self.assertRaises(gexc.TooManyRequests):
                main._generate_content_with_transient_retry(
                    model, "p", generation_config=None, mode="today_genie"
                )
        self.assertLessEqual(sum(self.slept), 45.0 + 1e-6)

    def test_call_gemini_recovers_through_the_public_entry(self):
        """End to end: call_gemini returns text despite a transient 429."""
        model = _FakeModel(
            [gexc.TooManyRequests(INCIDENT_429_MESSAGE), _FakeResponse('{"a": 1}')]
        )
        with mock.patch.object(main, "init_vertex", lambda: None), mock.patch.object(
            main, "get_model", lambda: model
        ):
            text = main.call_gemini("prompt", "today_genie")
        self.assertEqual(text, '{"a": 1}')
        self.assertEqual(model.calls, 2)


class FailedNaturalArtifactVisibilityTests(unittest.TestCase):
    """The failed 06:30 artifact must stay visible as a miss."""

    def _incident_artifact(self):
        return {
            "run_id": INCIDENT_RUN_ID,
            "mode": "today_genie",
            "execution_class": "natural_scheduled",
            "scheduled_slot": "06:30",
            "artifact_status": "failed",
            "validation_result": None,
            "workflow_status": None,
            "email_sent": False,
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
            "issue_codes": [],
            "parent_run_id": None,
            "trigger_source": "scheduled_owner_review",
        }

    def test_failed_artifact_does_not_satisfy_the_natural_slot(self):
        from today_genie_execution_identity import (
            natural_slot_completer_qualification,
        )

        match = natural_slot_completer_qualification(
            self._incident_artifact(),
            program_id="today_genie",
            kst_date="2026-09-10",
            scheduled_slot="06:30",
        )
        self.assertFalse(match.qualifies)

    def test_watchdog_raises_an_sla_miss_for_the_failed_run(self):
        import datetime

        from natural_run_watchdog import KST, diagnose_program_sla

        incident = diagnose_program_sla(
            program_id="today_genie",
            artifacts=[self._incident_artifact()],
            now=datetime.datetime(2026, 9, 10, 6, 45, 5, tzinfo=KST),
        )
        self.assertIsNotNone(incident)
        self.assertEqual(incident.get("error_code"), "natural_sla_miss")
        self.assertEqual(incident.get("original_run_id"), INCIDENT_RUN_ID)

    def test_hard_failed_run_is_not_auto_remediated_as_a_content_defect(self):
        from admin_store import reissue_parent_review_class
        from auto_remediation import plan_auto_remediation

        meta = self._incident_artifact()
        self.assertEqual(reissue_parent_review_class(meta), "hard_fail")
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)


if __name__ == "__main__":
    unittest.main()
