"""Focused unit tests for today_quality_warning_present and manual quality warning approval."""
from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from admin_store import can_approve_customer_send
from customer_review_confirmation import (
    ALLOWED_WARNING_ISSUE_CODES,
    today_quality_warning_present,
)

KST = ZoneInfo("Asia/Seoul")


class TodayManualQualityWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.aware_pre09 = datetime(2026, 11, 4, 8, 15, tzinfo=KST)
        self.aware_post09 = datetime(2026, 11, 4, 9, 5, tzinfo=KST)

        self.valid_meta = {
            "mode": "today_genie",
            "run_id": "20261104_073000_today_genie_a1b2c3d4",
            "target_date": "2026-11-04",
            "response_status": 200,
            "validation_result": "draft_only",
            "runtime_safety_status": "REVIEW_REQUIRED",
            "customer_surface_status": "PRODUCT_REVIEW_REQUIRED",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
            "required_count": 3,
            "selected_items": ["item1", "item2", "item3"],
            "selected_items_count": 3,
            "created_at": "2026-11-04T07:30:00+09:00",
            "issue_codes": ["today_replay_temporal_conflict"],
        }

    def test_valid_same_day_aware_pre09_warning_detected(self) -> None:
        self.assertTrue(
            today_quality_warning_present(self.valid_meta, now=self.aware_pre09)
        )

    def test_can_approve_manual_warning_allowed_when_flag_true(self) -> None:
        with patch("delegated_delivery_safety.publication_guard_required", return_value=False), \
             patch("today_geenee_customer_delivery.customer_delivery_config_ready", return_value=(True, "ok")), \
             patch("admin_store.superseded_child_check", return_value=(False, None, None, "")):
            ok, reason = can_approve_customer_send(
                self.valid_meta,
                has_email_html=True,
                allow_manual_quality_warning=True,
                now=self.aware_pre09,
            )
            self.assertTrue(ok)
            self.assertEqual(reason, "ok")

    def test_can_approve_blocked_by_default_without_manual_flag(self) -> None:
        with patch("delegated_delivery_safety.publication_guard_required", return_value=False), \
             patch("today_geenee_customer_delivery.customer_delivery_config_ready", return_value=(True, "ok")), \
             patch("admin_store.superseded_child_check", return_value=(False, None, None, "")):
            ok, reason = can_approve_customer_send(
                self.valid_meta,
                has_email_html=True,
                allow_manual_quality_warning=False,
                now=self.aware_pre09,
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "product_surface_remediation_needed")

    def test_unknown_or_hard_issue_code_blocked(self) -> None:
        meta = dict(self.valid_meta, issue_codes=["hard_failure_unexpected"])
        self.assertFalse(today_quality_warning_present(meta, now=self.aware_pre09))

        with patch("delegated_delivery_safety.publication_guard_required", return_value=False), \
             patch("today_geenee_customer_delivery.customer_delivery_config_ready", return_value=(True, "ok")), \
             patch("admin_store.superseded_child_check", return_value=(False, None, None, "")):
            ok, reason = can_approve_customer_send(
                meta,
                has_email_html=True,
                allow_manual_quality_warning=True,
                now=self.aware_pre09,
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "product_surface_remediation_needed")

    def test_post09_time_blocked(self) -> None:
        self.assertFalse(
            today_quality_warning_present(self.valid_meta, now=self.aware_post09)
        )

    def test_stale_or_future_date_blocked(self) -> None:
        stale_meta = dict(self.valid_meta, target_date="2026-11-03")
        self.assertFalse(today_quality_warning_present(stale_meta, now=self.aware_pre09))

        future_meta = dict(self.valid_meta, target_date="2026-11-05")
        self.assertFalse(today_quality_warning_present(future_meta, now=self.aware_pre09))

        mismatched_run_id = dict(self.valid_meta, run_id="20261103_073000_today_genie_a1b2c3d4")
        self.assertFalse(today_quality_warning_present(mismatched_run_id, now=self.aware_pre09))

    def test_timezone_unaware_created_at_blocked(self) -> None:
        unaware_meta = dict(self.valid_meta, created_at="2026-11-04T07:30:00")
        self.assertFalse(today_quality_warning_present(unaware_meta, now=self.aware_pre09))

        malformed_meta = dict(self.valid_meta, created_at="not-a-datetime")
        self.assertFalse(today_quality_warning_present(malformed_meta, now=self.aware_pre09))

    def test_wrong_selected_or_required_count_blocked(self) -> None:
        count2_meta = dict(self.valid_meta, required_count=2, selected_items=["item1", "item2"])
        self.assertFalse(today_quality_warning_present(count2_meta, now=self.aware_pre09))

        item2_meta = dict(self.valid_meta, required_count=3, selected_items=["item1", "item2"])
        self.assertFalse(today_quality_warning_present(item2_meta, now=self.aware_pre09))

        count_mismatch = dict(self.valid_meta, selected_items_count=4)
        self.assertFalse(today_quality_warning_present(count_mismatch, now=self.aware_pre09))

    def test_mixed_nested_unknown_codes_blocked(self) -> None:
        nested_meta = dict(
            self.valid_meta,
            runtime_validation_check={
                "issue_codes": ["unauthorized_nested_issue_code"]
            },
        )
        self.assertFalse(today_quality_warning_present(nested_meta, now=self.aware_pre09))

    def test_legacy_pass_warning_unchanged(self) -> None:
        legacy_meta = {
            "mode": "today_genie",
            "validation_result": "pass",
            "runtime_safety_status": "RUNTIME_SAFETY_PASS",
            "customer_surface_status": "PRODUCT_REVIEW_REQUIRED",
        }
        self.assertTrue(today_quality_warning_present(legacy_meta))

    def test_held_accepted_unknown_guards_preserved(self) -> None:
        with patch("delegated_delivery_safety.publication_guard_required", return_value=False), \
             patch("today_geenee_customer_delivery.customer_delivery_config_ready", return_value=(True, "ok")), \
             patch("admin_store.superseded_child_check", return_value=(False, None, None, "")):

            # Held status
            held_meta = dict(self.valid_meta, owner_review_status="held")
            ok, reason = can_approve_customer_send(
                held_meta,
                has_email_html=True,
                allow_manual_quality_warning=True,
                now=self.aware_pre09,
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "review_held")

            # Accepted all status (blocks via projection/delivery guard)
            accepted_meta = dict(self.valid_meta, customer_delivery_status="accepted_all")
            ok, reason = can_approve_customer_send(
                accepted_meta,
                has_email_html=True,
                allow_manual_quality_warning=True,
                now=self.aware_pre09,
            )
            self.assertFalse(ok)
            self.assertIn(reason, {"customer_already_sent", "delivery_outcome_unknown"})

            # Outcome unknown status
            unknown_meta = dict(self.valid_meta, customer_delivery_status="OUTCOME_UNKNOWN")
            ok, reason = can_approve_customer_send(
                unknown_meta,
                has_email_html=True,
                allow_manual_quality_warning=True,
                now=self.aware_pre09,
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "delivery_outcome_unknown")

            # Already approved status
            approved_meta = dict(self.valid_meta, owner_review_status="approved")
            ok, reason = can_approve_customer_send(
                approved_meta,
                has_email_html=True,
                allow_manual_quality_warning=True,
                now=self.aware_pre09,
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "already_approved")


if __name__ == "__main__":
    unittest.main()
