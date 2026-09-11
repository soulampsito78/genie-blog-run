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


class AdminBetaDelegationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.recipients = [f"beta-{index:02d}@example.test" for index in range(12)]
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
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def activate(self):
        return delegation.activate_admin_beta_delegation(
            products=delegation.ALLOWED_MODES,
            operator_id="owner-chat-delegation",
            expected_count=12,
            now=NOW,
        )

    def test_one_grant_authorizes_future_exact_cohort_without_per_run_approval(self):
        grant = self.activate()
        authority = delegation.AdminBetaRecipientAuthority()
        plan = authority.prepare("keysuri_korea_tech", NOW.date(), NOW)
        self.assertEqual(grant["recipient_count"], 12)
        self.assertEqual(plan["authority"], "ADMIN_BETA_DELEGATION")
        self.assertEqual(plan["authority_grant_id"], grant["grant_id"])
        self.assertEqual(
            [row["delivery_email"] for row in plan["recipients"]], self.recipients
        )
        self.assertTrue(authority.revalidate(plan, NOW))

    def test_non_twelve_activation_is_never_valid(self):
        with self.assertRaisesRegex(safety.DeliverySafetyError, "EXACT_COHORT_MISMATCH"):
            delegation.activate_admin_beta_delegation(
                products=delegation.ALLOWED_MODES,
                operator_id="owner",
                expected_count=11,
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
