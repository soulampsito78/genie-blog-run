"""Korea 18:30 ellipsis residual + retry actionability closeout harness."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[1]
_FIXTURE = (
    _REPO
    / "ops"
    / "feeds"
    / "incident_fixtures"
    / "20260807_1830_keysuri_korea_ellipsis.json"
)
_GLOBAL_FIXTURE = (
    _REPO
    / "ops"
    / "feeds"
    / "incident_fixtures"
    / "20260807_131133_keysuri_global_recovery1_ellipsis.json"
)


class Korea1830EllipsisHarness(unittest.TestCase):
    def test_01_pre_patch_style_residual_was_closing_quote_then_ellipsis(self) -> None:
        fx = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        text = fx["blocking_pattern_example"]
        self.assertIn("'…삼", text)
        cps = [row["codepoint"] for row in fx["unicode_codepoints_around_ellipsis"]]
        self.assertEqual(cps[7], "U+0027")
        self.assertEqual(cps[8], "U+2026")
        self.assertEqual(cps[9], "U+C0BC")

    def test_02_post_patch_repairs_korea_residual_and_passes_validation(self) -> None:
        from keysuri_visible_text_quality import (
            KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
            repair_korean_connector_ellipsis_text,
            validate_and_repair_keysuri_visible_text_quality,
        )

        fx = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        text = fx["blocking_pattern_example"]
        result = repair_korean_connector_ellipsis_text(text)
        self.assertFalse(result.blocked)
        self.assertTrue(result.repaired)
        self.assertEqual(result.text, fx["expected_post_patch_title"])

        payload = {
            "top_5_news": {
                "items": [
                    {"korean_title": fx["also_repaired_examples"][0], "headline": fx["also_repaired_examples"][0]},
                    {"korean_title": text, "headline": text},
                    {"korean_title": fx["also_repaired_examples"][1], "headline": fx["also_repaired_examples"][1]},
                ]
            }
        }
        _repaired, fields = validate_and_repair_keysuri_visible_text_quality(payload)
        self.assertEqual(fields["visible_text_quality_status"], "pass")
        self.assertFalse(fields.get("visible_text_ellipsis_blocked"))
        self.assertNotIn(
            KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
            fields.get("visible_text_quality_issue_codes") or [],
        )

    def test_03_global_curly_quote_fixture_still_repairs(self) -> None:
        from keysuri_visible_text_quality import (
            repair_korean_connector_ellipsis_text,
            validate_and_repair_keysuri_visible_text_quality,
        )

        fx = json.loads(_GLOBAL_FIXTURE.read_text(encoding="utf-8"))
        text = fx["blocking_pattern_example"]
        result = repair_korean_connector_ellipsis_text(text)
        self.assertFalse(result.blocked)
        _repaired, fields = validate_and_repair_keysuri_visible_text_quality(
            {"top_5_news": {"items": [{"what_happened": text}]}}
        )
        self.assertEqual(fields["visible_text_quality_status"], "pass")

    def test_04_genuine_corruption_still_blocked(self) -> None:
        from keysuri_visible_text_quality import repair_korean_connector_ellipsis_text

        blocked = repair_korean_connector_ellipsis_text("확인 불가 (…)")
        self.assertTrue(blocked.blocked)

    def test_05_sentence_final_ellipsis_preserved_to_pass(self) -> None:
        from keysuri_visible_text_quality import repair_korean_connector_ellipsis_text

        result = repair_korean_connector_ellipsis_text("정상적인 문장 끝…")
        self.assertFalse(result.blocked)
        self.assertEqual(result.text, "정상적인 문장 끝…")

    def test_06_validation_failure_customer_zero_is_actionable(self) -> None:
        from natural_run_incident_store import (
            RETRY_ALLOWED_WITH_WARNING,
            ROOT_CAUSE_PARTIAL,
            classify_retry_actionability,
            is_retry_actionable,
        )

        verdict = classify_retry_actionability(
            email_sent=False,
            customer_send=0,
            smtp_attempted=False,
            execution_terminated=True,
            root_cause_verdict=ROOT_CAUSE_PARTIAL,
        )
        self.assertEqual(verdict, RETRY_ALLOWED_WITH_WARNING)
        self.assertTrue(is_retry_actionable(verdict))

    def test_07_root_unknown_isolated_is_allowed_with_warning(self) -> None:
        from natural_run_incident_store import (
            RETRY_ALLOWED_WITH_WARNING,
            ROOT_CAUSE_UNKNOWN,
            classify_retry_actionability,
            is_retry_actionable,
        )

        verdict = classify_retry_actionability(
            email_sent=False,
            customer_send=0,
            execution_terminated=True,
            root_cause_verdict=ROOT_CAUSE_UNKNOWN,
        )
        self.assertEqual(verdict, RETRY_ALLOWED_WITH_WARNING)
        self.assertTrue(is_retry_actionable(verdict))

    def test_08_customer_send_ambiguity_blocked(self) -> None:
        from natural_run_incident_store import RETRY_BLOCKED, classify_retry_actionability

        self.assertEqual(
            classify_retry_actionability(
                email_sent=False,
                customer_send=1,
                execution_terminated=True,
            ),
            RETRY_BLOCKED,
        )

    def test_09_smtp_ambiguity_blocked(self) -> None:
        from natural_run_incident_store import RETRY_BLOCKED, classify_retry_actionability

        self.assertEqual(
            classify_retry_actionability(
                email_sent=False,
                customer_send=0,
                smtp_outcome_ambiguous=True,
                execution_terminated=True,
            ),
            RETRY_BLOCKED,
        )

    def test_10_owner_review_already_delivered_warning(self) -> None:
        from natural_run_incident_store import (
            RETRY_ALLOWED_WITH_WARNING,
            classify_retry_actionability,
            is_retry_actionable,
        )

        verdict = classify_retry_actionability(
            email_sent=True,
            customer_send=0,
            execution_terminated=True,
        )
        self.assertEqual(verdict, RETRY_ALLOWED_WITH_WARNING)
        self.assertTrue(is_retry_actionable(verdict))

    def test_11_root_confirmed_isolated_is_retry_safe(self) -> None:
        from natural_run_incident_store import (
            RETRY_SAFE,
            ROOT_CAUSE_CONFIRMED,
            classify_retry_actionability,
        )

        self.assertEqual(
            classify_retry_actionability(
                email_sent=False,
                customer_send=0,
                execution_terminated=True,
                root_cause_verdict=ROOT_CAUSE_CONFIRMED,
            ),
            RETRY_SAFE,
        )

    def test_12_email_blocked_does_not_ask_retry_question(self) -> None:
        from natural_run_incident_report import build_failure_report_html
        from natural_run_incident_store import RETRY_BLOCKED, new_incident

        inc = new_incident(
            program_id="keysuri_korea_tech",
            kst_date="2026-08-07",
            scheduled_slot="18:30",
            retry_verdict=RETRY_BLOCKED,
            summary_ko="blocked",
        )
        with mock.patch(
            "admin_urls.build_incident_admin_url",
            return_value="https://example.com/admin/incidents/x",
        ):
            html = build_failure_report_html(inc)
        self.assertNotIn("이 실행을 다시 시도할까요?", html)
        self.assertIn("안전한 재실행 조건이 확보되지 않았습니다", html)
        self.assertIn("장애 상세 보기", html)

    def test_13_email_actionable_asks_and_offers_review(self) -> None:
        from natural_run_incident_report import build_failure_report_html
        from natural_run_incident_store import RETRY_ALLOWED_WITH_WARNING, new_incident

        inc = new_incident(
            program_id="keysuri_korea_tech",
            kst_date="2026-08-07",
            scheduled_slot="18:30",
            retry_verdict=RETRY_ALLOWED_WITH_WARNING,
            summary_ko="warn",
        )
        with mock.patch(
            "admin_urls.build_incident_admin_url",
            return_value="https://example.com/admin/incidents/x",
        ):
            html = build_failure_report_html(inc)
        self.assertIn("이 실행을 다시 시도할까요?", html)
        self.assertIn("재실행 검토하기", html)

    def test_14_notify_force_path_no_longer_leaves_unknown_for_ellipsis(self) -> None:
        from natural_run_watchdog import notify_natural_run_incident_from_failure
        from natural_run_incident_store import (
            RETRY_ALLOWED_WITH_WARNING,
            RETRY_STATUS_UNKNOWN,
            is_retry_actionable,
        )

        captured = {}

        def _capture(incident, send_fn=None):
            captured["incident"] = dict(incident)
            return {"ok": True, "report_sent": False, "deduped": True, "auto_retry": 0}

        with mock.patch(
            "natural_run_watchdog.diagnose_program_sla", return_value=None
        ), mock.patch(
            "natural_run_watchdog.report_incident_once", side_effect=_capture
        ):
            notify_natural_run_incident_from_failure(
                program_id="keysuri_korea_tech",
                run_id="20260807_183002_keysuri_korea_tech_fc4ce837",
                trigger_source="scheduled_service_full_run",
                first_failed_stage="generation_validation",
                error_code="keysuri_korean_connector_ellipsis_blocked",
                email_sent=False,
                artifact_saved=True,
                extra_fields={"called_gemini": True, "final_selected_count": 5},
            )
        inc = captured["incident"]
        self.assertNotEqual(inc.get("retry_verdict"), RETRY_STATUS_UNKNOWN)
        self.assertEqual(inc.get("retry_verdict"), RETRY_ALLOWED_WITH_WARNING)
        self.assertTrue(is_retry_actionable(inc.get("retry_verdict")))


if __name__ == "__main__":
    unittest.main()
