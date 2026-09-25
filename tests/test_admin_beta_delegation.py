import copy
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import admin_beta_delegation as delegation
import admin_safety_store as store
import admin_store
import delegated_delivery_safety as safety


NOW = dt.datetime(2026, 9, 14, 0, 30, tzinfo=dt.timezone.utc)
BASELINE_RECIPIENT_COUNT = 13


class AdminBetaDelegationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.recipients = [
            f"beta-{index:02d}@example.test"
            for index in range(BASELINE_RECIPIENT_COUNT)
        ]
        self.state = {
            "recipients": self.recipients,
            "disabled": [],
            "version": 6,
            "load_ok": True,
        }

        def load_config():
            return {
                "recipients": list(self.state["recipients"]),
                "disabled_recipients": list(self.state["disabled"]),
                "version": self.state["version"],
                "load_ok": self.state["load_ok"],
            }

        def resolve():
            active = [
                value
                for value in self.state["recipients"]
                if value not in self.state["disabled"]
            ]
            identity = {
                "env_recipients": [],
                "admin_recipients": active,
                "disabled_recipients": sorted(self.state["disabled"]),
                "final_recipients": active,
                "admin_version": self.state["version"],
            }
            return {
                "final_recipients": active,
                "env_recipients": [],
                "admin_recipients": active,
                "invalid_entries": [],
                "admin_config_ok": self.state["load_ok"],
                "recipient_configuration_version": f"env+admin:v{self.state['version']}",
                "recipient_configuration_hash": delegation._digest(identity),
            }

        patches = [
            mock.patch.object(store, "_uses_gcs_backend", return_value=False),
            mock.patch.dict(
                os.environ,
                {"GENIE_ADMIN_SAFETY_LOCAL_DIR": str(Path(self.temp.name) / "safety")},
                clear=False,
            ),
            mock.patch.object(admin_store, "load_beta_recipient_config", load_config),
            mock.patch.object(admin_store, "resolve_customer_recipients", resolve),
            mock.patch("email_sender.parse_customer_to_addrs", return_value=[]),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def activate(self):
        return delegation.activate_admin_beta_delegation(
            products=delegation.ALLOWED_MODES,
            operator_id="owner-chat-delegation",
            now=NOW,
        )

    def test_one_grant_authorizes_future_exact_cohort_without_per_run_approval(self):
        grant = self.activate()
        authority = delegation.AdminBetaRecipientAuthority()
        plan = authority.prepare("keysuri_korea_tech", NOW.date(), NOW)
        self.assertEqual(grant["recipient_count"], len(self.recipients))
        self.assertEqual(plan["authority"], "ADMIN_BETA_DELEGATION")
        self.assertEqual(plan["authority_grant_id"], grant["grant_id"])
        self.assertEqual(
            [row["delivery_email"] for row in plan["recipients"]], self.recipients
        )
        self.assertTrue(authority.revalidate(plan, NOW))

    def test_optional_count_assertion_cannot_authorize_a_different_cohort(self):
        for requested in (0, BASELINE_RECIPIENT_COUNT - 1, BASELINE_RECIPIENT_COUNT + 1):
            with self.subTest(expected_count=requested):
                with self.assertRaisesRegex(
                    safety.DeliverySafetyError, "EXACT_COHORT_MISMATCH"
                ):
                    delegation.activate_admin_beta_delegation(
                        products=delegation.ALLOWED_MODES,
                        operator_id="owner",
                        expected_count=requested,
                        now=NOW,
                    )

    def test_current_thirteen_cohort_activates_and_loads(self):
        self.assertEqual(len(self.recipients), 13)
        grant = self.activate()
        self.assertEqual(grant["recipient_count"], 13)
        self.assertEqual(grant["recipients"], self.recipients)
        loaded = delegation.load_active_admin_beta_delegation()
        self.assertEqual(loaded["grant_id"], grant["grant_id"])
        self.assertEqual(loaded["recipient_count"], 13)
        self.assertEqual(
            loaded["recipient_configuration_hash"],
            grant["recipient_configuration_hash"],
        )
        self.assertEqual(
            loaded["recipient_configuration_version"],
            grant["recipient_configuration_version"],
        )

    def test_cohort_must_contain_distinct_addresses_within_capacity(self):
        self.state["recipients"] = self.recipients[:-1] + [self.recipients[0]]
        with self.assertRaisesRegex(
            safety.DeliverySafetyError, "ADMIN_BETA_EXACT_COHORT_MISMATCH"
        ):
            self.activate()
        self.state["recipients"] = []
        with self.assertRaisesRegex(
            safety.DeliverySafetyError, "ADMIN_BETA_RECIPIENT_CAPACITY_INVALID"
        ):
            self.activate()
        self.state["recipients"] = [
            f"over-cap-{index:02d}@example.test"
            for index in range(delegation.MAX_BETA_RECIPIENT_COUNT + 1)
        ]
        with self.assertRaisesRegex(
            safety.DeliverySafetyError, "ADMIN_BETA_RECIPIENT_CAPACITY_INVALID"
        ):
            self.activate()

    def test_existing_thirteen_grant_remains_valid_after_dynamic_release(self):
        grant = self.activate()
        loaded = delegation.load_active_admin_beta_delegation()
        self.assertEqual(loaded["grant_id"], grant["grant_id"])
        self.assertEqual(loaded["recipient_count"], 13)

    def test_expansion_invalidates_old_grant_until_current_cohort_is_activated(self):
        old_grant = self.activate()
        self.state["recipients"].append("beta-13@example.test")
        self.state["version"] += 1
        with self.assertRaisesRegex(
            safety.DeliverySafetyError, "ADMIN_BETA_EXACT_COHORT_MISMATCH"
        ):
            delegation.load_active_admin_beta_delegation()

        new_grant = self.activate()
        self.assertNotEqual(new_grant["grant_id"], old_grant["grant_id"])
        self.assertEqual(new_grant["recipient_count"], 14)
        self.assertEqual(
            delegation.load_active_admin_beta_delegation()["grant_id"],
            new_grant["grant_id"],
        )

    def test_altered_cohort_is_rejected_after_activation(self):
        grant = self.activate()
        authority = delegation.AdminBetaRecipientAuthority()
        plan = authority.prepare("keysuri_global_tech", NOW.date(), NOW)
        swapped = list(self.recipients)
        swapped[-1] = "swapped-13@example.test"
        self.state["recipients"] = swapped
        with self.assertRaisesRegex(
            safety.DeliverySafetyError, "ADMIN_BETA_DELEGATION_COHORT_CHANGED"
        ):
            delegation.load_active_admin_beta_delegation()
        with self.assertRaisesRegex(
            safety.DeliverySafetyError, "ADMIN_BETA_DELEGATION_COHORT_CHANGED"
        ):
            authority.revalidate(plan, NOW)
        self.state["recipients"] = list(self.recipients)
        self.assertEqual(
            delegation.load_active_admin_beta_delegation()["grant_id"],
            grant["grant_id"],
        )

    def test_approval_snapshot_recipient_plan_uses_the_exact_thirteen(self):
        self.activate()
        run_id = "20260914_123001_keysuri_global_tech_cff48972"
        with mock.patch.dict(
            os.environ, {"GENIE_RECIPIENT_AUTHORITY": "ADMIN_BETA_DELEGATION"}
        ):
            plan = safety.manual_recipient_plan(
                run_id=run_id, mode="keysuri_global_tech", now=NOW
            )
            self.assertEqual(len(plan["recipients"]), 13)
            self.assertEqual(
                [row["delivery_email"] for row in plan["recipients"]], self.recipients
            )
            # Same run keeps its frozen plan; the cohort is not re-resolved.
            self.assertEqual(
                safety.manual_recipient_plan(
                    run_id=run_id, mode="keysuri_global_tech", now=NOW
                )["plan_id"],
                plan["plan_id"],
            )

    def test_approval_snapshot_path_blocks_after_unactivated_expansion(self):
        self.activate()
        self.state["recipients"].append("beta-13@example.test")
        self.state["version"] += 1
        with mock.patch.dict(
            os.environ, {"GENIE_RECIPIENT_AUTHORITY": "ADMIN_BETA_DELEGATION"}
        ):
            with self.assertRaisesRegex(
                safety.DeliverySafetyError, "ADMIN_BETA_EXACT_COHORT_MISMATCH"
            ):
                safety.manual_recipient_plan(
                    run_id="20260914_123001_keysuri_global_tech_cff48972",
                    mode="keysuri_global_tech",
                    now=NOW,
                )

    def test_version_change_fails_closed(self):
        self.activate()
        plan = delegation.AdminBetaRecipientAuthority().prepare(
            "today_genie", NOW.date(), NOW
        )
        self.state["version"] = 7
        with self.assertRaisesRegex(
            safety.DeliverySafetyError, "ADMIN_BETA_DELEGATION_COHORT_CHANGED"
        ):
            delegation.AdminBetaRecipientAuthority().revalidate(plan, NOW)

    def test_address_change_fails_closed(self):
        self.activate()
        plan = delegation.AdminBetaRecipientAuthority().prepare(
            "today_genie", NOW.date(), NOW
        )
        self.state["recipients"].append("extra@example.test")
        with self.assertRaisesRegex(
            safety.DeliverySafetyError, "ADMIN_BETA_EXACT_COHORT_MISMATCH"
        ):
            delegation.AdminBetaRecipientAuthority().revalidate(plan, NOW)

    def test_disabled_recipient_fails_closed(self):
        self.activate()
        plan = delegation.AdminBetaRecipientAuthority().prepare(
            "today_genie", NOW.date(), NOW
        )
        self.state["disabled"].append(self.state["recipients"][0])
        with self.assertRaisesRegex(
            safety.DeliverySafetyError, "ADMIN_BETA_DISABLED_RECIPIENT_PRESENT"
        ):
            delegation.AdminBetaRecipientAuthority().revalidate(plan, NOW)

    def test_config_read_error_fails_closed(self):
        self.activate()
        plan = delegation.AdminBetaRecipientAuthority().prepare(
            "today_genie", NOW.date(), NOW
        )
        self.state["load_ok"] = False
        with self.assertRaisesRegex(
            safety.DeliverySafetyError, "ADMIN_BETA_RECIPIENT_CONFIG_UNAVAILABLE"
        ):
            delegation.AdminBetaRecipientAuthority().revalidate(plan, NOW)

    def test_product_scope_and_revocation_fail_closed(self):
        delegation.activate_admin_beta_delegation(
            products=["keysuri_korea_tech"], operator_id="owner", now=NOW
        )
        authority = delegation.AdminBetaRecipientAuthority()
        with self.assertRaisesRegex(safety.DeliverySafetyError, "PRODUCT_NOT_AUTHORIZED"):
            authority.prepare("today_genie", NOW.date(), NOW)
        plan = authority.prepare("keysuri_korea_tech", NOW.date(), NOW)
        delegation.revoke_admin_beta_delegation(
            operator_id="owner", reason="operator kill switch", now=NOW
        )
        with self.assertRaisesRegex(safety.DeliverySafetyError, "NOT_ACTIVE"):
            authority.revalidate(plan, NOW)

    def test_stale_active_pointer_cannot_overwrite_a_revocation(self):
        grant = self.activate()
        _, stale_generation = delegation._read_current_with_generation()
        delegation.revoke_admin_beta_delegation(
            operator_id="owner", reason="stop", now=NOW
        )
        with self.assertRaisesRegex(safety.DeliverySafetyError, "STATE_CONFLICT"):
            delegation._compare_and_swap_current(
                stale_generation,
                {
                    "schema": delegation.DELEGATION_SCHEMA,
                    "status": "ACTIVE",
                    "grant_id": grant["grant_id"],
                    "grant_sha256": grant["grant_sha256"],
                },
            )

    def test_revocation_during_grant_read_is_detected(self):
        self.activate()
        original = delegation._current_cohort

        def revoke_during_read(*, expected_count):
            result = original(expected_count=expected_count)
            delegation.revoke_admin_beta_delegation(
                operator_id="owner", reason="concurrent stop", now=NOW
            )
            return result

        with mock.patch.object(delegation, "_current_cohort", revoke_during_read):
            with self.assertRaisesRegex(safety.DeliverySafetyError, "STATE_CHANGED"):
                delegation.load_active_admin_beta_delegation()

    def test_plan_tamper_and_stale_publication_do_not_pass(self):
        self.activate()
        authority = delegation.AdminBetaRecipientAuthority()
        plan = authority.prepare("keysuri_global_tech", NOW.date(), NOW)
        changed = copy.deepcopy(plan)
        changed["recipients"][0]["delivery_email"] = "attacker@example.test"
        store._write_json(f"delegated_recipient_plans/{plan['plan_id']}.json", changed)
        with self.assertRaisesRegex(safety.DeliverySafetyError, "RECIPIENT_PLAN_CHANGED"):
            authority.revalidate(plan, NOW)
        with self.assertRaisesRegex(safety.DeliverySafetyError, "STALE_PUBLICATION"):
            authority.prepare(
                "keysuri_global_tech", NOW.date(), NOW + dt.timedelta(days=1)
            )

    def test_existing_plan_expires_at_the_final_boundary(self):
        self.activate()
        authority = delegation.AdminBetaRecipientAuthority()
        plan = authority.prepare("today_genie", NOW.date(), NOW)
        with self.assertRaisesRegex(safety.DeliverySafetyError, "PLAN_CHANGED"):
            authority.revalidate(plan, NOW + dt.timedelta(days=1))

    def test_explicit_factory_selector_only(self):
        self.activate()
        with mock.patch.dict(
            os.environ, {"GENIE_RECIPIENT_AUTHORITY": "ADMIN_BETA_DELEGATION"}
        ):
            self.assertIsInstance(
                safety.recipient_authority(), delegation.AdminBetaRecipientAuthority
            )
        with mock.patch.dict(os.environ, {"GENIE_RECIPIENT_AUTHORITY": "typo"}):
            with self.assertRaisesRegex(safety.DeliverySafetyError, "CONFIG_INVALID"):
                safety.recipient_authority()


if __name__ == "__main__":
    unittest.main()
