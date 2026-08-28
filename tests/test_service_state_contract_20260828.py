"""Product invariants for the stabilization contracts (C, D, E, F).

Built from the real 2026-08-26 → 2026-08-28 production runs. The anchor case is
the 12:30 Global run of 2026-08-28: the model contract collapsed, recovery
failed, the scaffold rebuilt the cards out of the raw English claim pool, the
delivery gate correctly sent the owner a quality notice and no customer mail —
and the run still recorded validation_result "pass" with no incident record, so
/admin/incidents reported "현재 장애 없음" for a slot that produced nothing a
customer could read.

These assert the product behaviour, not the implementation: a scheduled slot
that is not customer-ready is DEGRADED, DEGRADED offers the customer notice, and
no essential owner capability disappears on a phone.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from admin_view_models import ACTIVE_PROGRAMS, PROGRAM_BY_ID  # noqa: E402
from service_state import (  # noqa: E402
    CONTENT_QUALITY_DEGRADED,
    CONTENT_READY,
    CONTENT_UNUSABLE,
    DEGRADED,
    HEALTHY,
    INCIDENT,
    NOTICE_RECOMMENDED,
    NOTICE_REQUIRED,
    derive_service_state,
)

GLOBAL = PROGRAM_BY_ID["keysuri_global_tech"]
TODAY = PROGRAM_BY_ID["today_genie"]

# The 2026-08-28 12:30 Global run, as its summary artifact recorded it.
GLOBAL_20260828 = {
    "run_id": "20260828_123001_keysuri_global_tech_9d30c899",
    "program_id": "keysuri_global_tech",
    "execution_class": "natural_scheduled",
    "scheduled_slot": "12:30",
    "artifact_status": "emailed",
    "validation_result": "pass",
    "safety_verdict": "SAFE",
    "editorial_verdict": "POOR",
    "terminal_issue_codes": [],
    "review_issue_codes": [
        "global_visible_raw_english_prose_blocked",
        "global_visible_repeated_template_skeleton_blocked",
        "global_visible_deep_dive_duplication_blocked",
        "global_visible_repeated_low_information_label",
    ],
    "owner_delivery_behavior": "SEND_OWNER_QUALITY_NOTICE",
    "customer_approval_policy": "UNAVAILABLE",
    "customer_approval_available": False,
    "customer_delivery_status": "not_sent",
    "owner_review_status": "pending_review",
    "email_sent": True,
    "generation_recovery_result": "failed",
    "global_recovery_result": "failed",
}


class ScheduledOutputStateTests(unittest.TestCase):
    """C: one state from scheduled output + quality + delivery + recovery."""

    def test_safe_but_poor_scheduled_output_is_degraded(self) -> None:
        state = derive_service_state(GLOBAL_20260828, program=GLOBAL)
        self.assertEqual(state["service_health"], DEGRADED)
        self.assertEqual(state["content_status"], CONTENT_QUALITY_DEGRADED)
        self.assertFalse(state["customer_ready"])

    def test_degraded_is_never_reported_as_no_incident(self) -> None:
        state = derive_service_state(GLOBAL_20260828, program=GLOBAL)
        self.assertNotEqual(state["service_health"], HEALTHY)

    def test_a_validation_pass_field_cannot_override_a_blocking_surface(self) -> None:
        # The run said "pass"; the reader surface said otherwise.
        self.assertEqual(GLOBAL_20260828["validation_result"], "pass")
        state = derive_service_state(GLOBAL_20260828, program=GLOBAL)
        self.assertIn(
            "global_visible_raw_english_prose_blocked", state["blocking_issue_codes"]
        )

    def test_blocking_severity_comes_from_the_shared_registry(self) -> None:
        from issue_code_registry import SEVERITY_BLOCK, get_issue_code

        for code in derive_service_state(GLOBAL_20260828, program=GLOBAL)[
            "blocking_issue_codes"
        ]:
            self.assertEqual(get_issue_code(code).severity, SEVERITY_BLOCK)

    def test_recovery_failure_is_carried_into_the_state(self) -> None:
        state = derive_service_state(GLOBAL_20260828, program=GLOBAL)
        self.assertEqual(state["recovery_state"], "attempted_failed")

    def test_missing_scheduled_run_is_an_incident(self) -> None:
        state = derive_service_state(None, program=GLOBAL)
        self.assertEqual(state["service_health"], INCIDENT)

    def test_validation_block_is_an_incident(self) -> None:
        state = derive_service_state(
            {"run_id": "r", "validation_result": "block", "artifact_status": "failed"},
            program=TODAY,
        )
        self.assertEqual(state["content_status"], CONTENT_UNUSABLE)
        self.assertEqual(state["service_health"], INCIDENT)

    def test_clean_delivered_run_is_healthy(self) -> None:
        state = derive_service_state(
            {
                "run_id": "r",
                "validation_result": "pass",
                "safety_verdict": "SAFE",
                "editorial_verdict": "GOOD",
                "issue_codes": [],
                "customer_delivery_status": "ACCEPTED_ALL",
            },
            program=TODAY,
        )
        self.assertEqual(state["content_status"], CONTENT_READY)
        self.assertEqual(state["service_health"], HEALTHY)
        self.assertTrue(state["customer_ready"])


class ScaffoldCannotHideFailureTests(unittest.TestCase):
    """B: a scaffold restores structure; it never converts failure into success."""

    BASE = {
        "run_id": "r",
        "validation_result": "pass",
        "safety_verdict": "SAFE",
        "editorial_verdict": "GOOD",
        "issue_codes": [],
        "customer_delivery_status": "not_sent",
    }

    def test_scaffolded_top5_with_failed_recovery_is_not_customer_ready(self) -> None:
        # No visible-surface detector fires here: the only evidence is that the
        # model contributed no article prose and the corrective call failed.
        state = derive_service_state(
            {
                **self.BASE,
                "initial_generation_issue_codes": [
                    "global_contract_scaffold_fabricated_top5"
                ],
                "generation_recovery_result": "failed",
            },
            program=GLOBAL,
        )
        self.assertFalse(state["customer_ready"])
        self.assertEqual(state["service_health"], DEGRADED)

    def test_scaffolded_top5_with_successful_recovery_stays_publishable(self) -> None:
        state = derive_service_state(
            {
                **self.BASE,
                "initial_generation_issue_codes": [
                    "global_contract_scaffold_fabricated_top5"
                ],
                "generation_recovery_result": "ok",
            },
            program=GLOBAL,
        )
        self.assertTrue(state["customer_ready"])

    def test_a_failed_recovery_alone_does_not_condemn_a_complete_generation(self) -> None:
        state = derive_service_state(
            {**self.BASE, "generation_recovery_result": "failed"}, program=GLOBAL
        )
        self.assertTrue(state["customer_ready"])


class OwnerActionContractTests(unittest.TestCase):
    """D: the Admin must answer "what does the owner do now?"."""

    def test_degraded_exposes_the_customer_notice_action(self) -> None:
        state = derive_service_state(GLOBAL_20260828, program=GLOBAL)
        self.assertIn(state["customer_notice_state"], {NOTICE_RECOMMENDED, NOTICE_REQUIRED})
        self.assertEqual(state["owner_next_action"]["kind"], "notice")

    def test_the_notice_action_is_scoped_to_the_affected_program(self) -> None:
        state = derive_service_state(GLOBAL_20260828, program=GLOBAL)
        self.assertIn("program_id=keysuri_global_tech", state["owner_next_action"]["href"])

    def test_a_healthy_program_asks_for_nothing(self) -> None:
        state = derive_service_state(
            {
                "run_id": "r",
                "validation_result": "pass",
                "customer_delivery_status": "ACCEPTED_ALL",
            },
            program=TODAY,
        )
        self.assertEqual(state["owner_next_action"]["kind"], "none")

    def test_every_active_program_derives_a_state(self) -> None:
        for program in ACTIVE_PROGRAMS:
            state = derive_service_state(None, program=program)
            self.assertEqual(state["program_id"], program["id"])
            self.assertTrue(state["owner_next_action"]["label"])


class NoticeContractTests(unittest.TestCase):
    """F: notices are incident response, and are program-aware."""

    def test_a_sent_notice_for_the_program_is_reflected(self) -> None:
        state = derive_service_state(
            GLOBAL_20260828,
            program=GLOBAL,
            notices=[{"status": "sent", "program_id": "keysuri_global_tech"}],
        )
        self.assertEqual(state["customer_notice_state"], "sent")

    def test_a_notice_for_another_program_does_not_clear_this_one(self) -> None:
        state = derive_service_state(
            GLOBAL_20260828,
            program=GLOBAL,
            notices=[{"status": "sent", "program_id": "today_genie"}],
        )
        self.assertNotEqual(state["customer_notice_state"], "sent")

    def test_an_all_programs_notice_covers_this_program(self) -> None:
        state = derive_service_state(
            GLOBAL_20260828,
            program=GLOBAL,
            notices=[{"status": "sent", "program_id": "all"}],
        )
        self.assertEqual(state["customer_notice_state"], "sent")


class MobileAdminContractTests(unittest.TestCase):
    """E: no essential owner capability may disappear at phone widths."""

    def _css(self) -> str:
        from admin_components import layout

        return layout("t", "<p>x</p>", active="operations")

    def test_utility_navigation_is_never_hidden_by_a_media_query(self) -> None:
        # The shipped rule was `.utility-link{display:none;}` at max-width:820px,
        # which removed History, Settings and every utility destination on a
        # phone without providing anything in their place.
        page = self._css()
        for block in re.findall(r"@media[^{]*\{(.*?)\}\s*\}", page, re.S):
            self.assertNotRegex(block, r"\.utility-link\s*\{[^}]*display\s*:\s*none")

    def test_required_destinations_are_present_in_the_shell(self) -> None:
        page = self._css()
        for href in (
            "/admin/notices",
            "/admin/history",
            "/admin/settings",
            "/admin/incidents",
            "/admin/delivery",
            "/admin/system",
        ):
            self.assertIn(f'href="{href}"', page, href)

    def test_utility_links_wrap_instead_of_disappearing(self) -> None:
        page = self._css()
        self.assertIn("flex-wrap:wrap", page)


class ProgramIsolationTests(unittest.TestCase):
    """Today, Global and Korea policy must not move each other."""

    def test_service_state_is_program_parameterized_not_hardcoded(self) -> None:
        import service_state

        source = Path(service_state.__file__).read_text(encoding="utf-8")
        for pid in ("today_genie", "keysuri_global_tech", "keysuri_korea_tech"):
            self.assertNotIn(f'"{pid}"', source, pid)

    def test_the_same_facts_yield_the_same_state_for_every_program(self) -> None:
        facts = dict(GLOBAL_20260828)
        healths = set()
        for program in ACTIVE_PROGRAMS:
            healths.add(derive_service_state(facts, program=program)["service_health"])
        self.assertEqual(healths, {DEGRADED})


if __name__ == "__main__":
    unittest.main()


class IncidentsPageContractTests(unittest.TestCase):
    """D + F, end to end: the page the owner actually opens."""

    def setUp(self) -> None:
        import os

        from fastapi.testclient import TestClient

        from main import app

        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        self.client = TestClient(app)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})

    def tearDown(self) -> None:
        import os

        if self._prev_pwd is None:
            os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        else:
            os.environ["GENIE_ADMIN_PASSWORD"] = self._prev_pwd

    def _render_with(self, runs, *, incidents=(), notices=()):
        """Render /admin/incidents against exactly these facts.

        The incident and notice stores are isolated so the assertions describe
        the contract rather than whatever this machine happens to have on disk.
        """
        from unittest.mock import patch

        with patch("admin_routes.list_run_artifacts", return_value=list(runs)), patch(
            "natural_run_incident_store.list_incident_page",
            return_value={"items": list(incidents), "cursor": "", "has_more": False},
        ), patch("admin_notice_store.list_notices", return_value=list(notices)):
            resp = self.client.get("/admin/incidents")
        self.assertEqual(resp.status_code, 200)
        return resp.text

    def test_degraded_program_is_never_reported_as_no_incident(self) -> None:
        # No incident record exists for this run — which is exactly the
        # production situation that produced "현재 장애 없음".
        page = self._render_with([GLOBAL_20260828])
        self.assertIn("DEGRADED", page)
        self.assertNotIn("현재 장애 없음", page)

    def test_an_open_incident_escalates_the_same_run_to_incident(self) -> None:
        page = self._render_with(
            [GLOBAL_20260828],
            incidents=[
                {
                    "incident_id": "2026-08-28_keysuri_global_tech_12-30",
                    "program_id": "keysuri_global_tech",
                    "state": "open",
                }
            ],
        )
        self.assertIn("INCIDENT", page)
        self.assertNotIn("현재 장애 없음", page)

    def test_a_sent_notice_changes_the_action_not_the_health(self) -> None:
        page = self._render_with(
            [GLOBAL_20260828],
            notices=[{"status": "sent", "program_id": "keysuri_global_tech"}],
        )
        self.assertIn("DEGRADED", page)
        self.assertIn("공지 발송 완료", page)

    def test_degraded_program_exposes_the_customer_notice_action(self) -> None:
        page = self._render_with([GLOBAL_20260828])
        self.assertIn("/admin/notices/new?program_id=keysuri_global_tech", page)
        self.assertIn("고객 공지 작성", page)

    def test_every_program_state_is_shown(self) -> None:
        page = self._render_with([GLOBAL_20260828])
        for program in ACTIVE_PROGRAMS:
            self.assertIn(program["name"], page, program["id"])

    def test_notices_stay_reachable_from_the_page_shell(self) -> None:
        page = self._render_with([GLOBAL_20260828])
        self.assertIn('href="/admin/notices"', page)
