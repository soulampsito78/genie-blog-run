"""Offline regression for authorized cohort edits; no send/provider entrypoint."""
import copy
import datetime as dt
import os
import re
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import admin_beta_delegation as delegation
import admin_beta_edits as edits
import admin_safety_store as store
import admin_store
import delegated_delivery_safety as safety

NOW = dt.datetime(2026, 10, 6, 9, 30, tzinfo=dt.timezone.utc)
ACTOR = "owner_session:offline-fixture"


class BetaEditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        patches = [mock.patch.object(admin_store, "repo_root", return_value=root),
                   mock.patch.object(store, "_uses_gcs_backend", return_value=False),
                   mock.patch.object(admin_store, "_uses_gcs_backend", return_value=False),
                   mock.patch("email_sender.parse_customer_to_addrs", return_value=[]),
                   mock.patch.dict(os.environ, {"GENIE_ADMIN_SAFETY_LOCAL_DIR": str(root / "safety"),
                       "GENIE_RECIPIENT_AUTHORITY": "ADMIN_BETA_DELEGATION", "GENIE_CUSTOMER_EMAIL_TO": ""}),
                   mock.patch.object(socket.socket, "connect", side_effect=AssertionError("OFFLINE_NETWORK_DENIED"))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.recipients = [f"beta-{i:02d}@example.test" for i in range(13)]
        admin_store.save_beta_recipient_config(self.recipients, version=7)
        self.parent = delegation.activate_admin_beta_delegation(products=delegation.ALLOWED_MODES, operator_id=ACTOR, now=NOW)

    def edit(self, action="add", email="new@example.test", context=None):
        context = context or edits.form_context(action, email if action == "remove" else "")
        return edits.edit_recipient(context=context, action=action, email=email, operator_id=ACTOR, now=NOW)

    def test_add_then_remove_carries_exact_cohort_version_parent_and_products(self):
        added = self.edit()
        grant = delegation.load_active_admin_beta_delegation()
        self.assertEqual((added["config_saved"], added["connection"]), (True, "LINKED"))
        self.assertEqual(grant["recipients"], self.recipients + ["new@example.test"])
        self.assertEqual(grant["parent_grant_id"], self.parent["grant_id"])
        self.assertEqual(grant["products"], self.parent["products"])
        self.assertEqual(grant["recipient_configuration_version"], "env+admin:v8")
        removed = self.edit("remove", self.recipients[0])
        self.assertEqual(removed["connection"], "LINKED")
        self.assertEqual(delegation.load_active_admin_beta_delegation()["recipient_count"], 13)
        self.assertEqual(admin_store.load_beta_recipient_config()["version"], 9)

    def test_same_operation_replay_is_same_state_and_receipt(self):
        context = edits.form_context("add")
        result = self.edit(context=context)
        before = delegation._read_current_with_generation()
        cfg = admin_store.load_beta_recipient_config()
        self.assertEqual(self.edit(context=context), result)
        self.assertEqual(delegation._read_current_with_generation(), before)
        self.assertEqual(admin_store.load_beta_recipient_config(), cfg)
        with self.assertRaisesRegex(safety.DeliverySafetyError, "IDENTITY_CONFLICT"):
            self.edit(email="different@example.test", context=context)

    def test_stale_form_cannot_overwrite_a_new_edit(self):
        old = edits.form_context("add")
        self.edit(email="first@example.test")
        before = admin_store.load_beta_recipient_config()
        with self.assertRaisesRegex(safety.DeliverySafetyError, "STALE_FORM"):
            self.edit(context=old)
        self.assertEqual(admin_store.load_beta_recipient_config(), before)

    def test_stale_form_after_revoke_does_not_save_or_reactivate(self):
        context = edits.form_context("add")
        delegation.revoke_admin_beta_delegation(operator_id=ACTOR, reason="test")
        with self.assertRaisesRegex(safety.DeliverySafetyError, "STALE_FORM"):
            self.edit(context=context)
        self.assertEqual(admin_store.load_beta_recipient_config()["version"], 7)
        self.assertEqual(delegation._read_current_with_generation()[0]["status"], "REVOKED")

    def test_revoked_edit_saves_but_never_creates_an_active_grant(self):
        delegation.revoke_admin_beta_delegation(operator_id=ACTOR, reason="test")
        result = self.edit()
        self.assertEqual((result["config_saved"], result["connection"]), (True, "STOPPED"))
        self.assertEqual(delegation._read_current_with_generation()[0]["status"], "REVOKED")
        with self.assertRaisesRegex(safety.DeliverySafetyError, "NOT_ACTIVE"):
            delegation.load_active_admin_beta_delegation(reconcile_edits=False)

    def test_stopped_and_missing_pointers_cannot_autoactivate(self):
        for pointer in (None, {"status": "STOPPED"}):
            with self.subTest(pointer=pointer):
                _, gen = delegation._read_current_with_generation()
                delegation._compare_and_swap_current(gen, pointer or {"status": "STOPPED"})
                self.assertEqual(self.edit(email=f"off-{len(admin_store.load_beta_recipient_config()['recipients'])}@example.test")["connection"], "STOPPED")

    def test_stale_active_grant_is_not_auto_repaired_or_inherited(self):
        admin_store.save_beta_recipient_config(self.recipients + ["out-of-band@example.test"], version=8)
        result = self.edit()
        self.assertEqual(result["connection"], "STOPPED")
        self.assertEqual(delegation._read_current_with_generation()[0]["status"], "STOPPED")

    def test_disabled_or_env_recipients_never_inherit_rights(self):
        for env in (False, True):
            with self.subTest(env=env):
                if not env:
                    admin_store.save_beta_recipient_config(self.recipients, disabled_recipients=[self.recipients[0]], version=7)
                with mock.patch("email_sender.parse_customer_to_addrs", return_value=["hidden@example.test"] if env else []):
                    self.assertEqual(self.edit(email=f"no-carry-{env}@example.test")["connection"], "STOPPED")
                self.assertNotEqual(delegation._read_current_with_generation()[0]["status"], "ACTIVE")

    def test_input_duplicates_invalid_and_capacity_do_not_mutate(self):
        before = admin_store.load_beta_recipient_config()
        for target, code in ((self.recipients[0], "ALREADY_EXISTS"), ("bad,email", "INVALID_EMAIL"), ("", "INVALID_EMAIL")):
            with self.subTest(target=target):
                with self.assertRaisesRegex(safety.DeliverySafetyError, code):
                    self.edit(email=target)
                self.assertEqual(admin_store.load_beta_recipient_config(), before)
        admin_store.save_beta_recipient_config([f"cap-{i}@example.test" for i in range(25)], version=8)
        delegation.activate_admin_beta_delegation(products=delegation.ALLOWED_MODES, operator_id=ACTOR, now=NOW)
        with self.assertRaisesRegex(safety.DeliverySafetyError, "CAPACITY_INVALID"):
            self.edit()
        self.assertEqual(delegation.load_active_admin_beta_delegation()["recipient_count"], 25)

    def test_remove_last_recipient_stops_instead_of_active_empty(self):
        admin_store.save_beta_recipient_config([self.recipients[0]], version=8)
        delegation.activate_admin_beta_delegation(products=delegation.ALLOWED_MODES, operator_id=ACTOR, now=NOW)
        result = self.edit("remove", self.recipients[0])
        self.assertEqual((result["config_saved"], result["connection"]), (True, "STOPPED"))
        self.assertEqual(admin_store.load_beta_recipient_config()["recipients"], [])

    def test_product_subset_is_preserved_not_expanded(self):
        delegation.activate_admin_beta_delegation(products=["today_genie"], operator_id=ACTOR, now=NOW)
        self.edit()
        self.assertEqual(delegation.load_active_admin_beta_delegation()["products"], ["today_genie"])

    def test_config_response_lost_after_commit_reconciles_without_second_write(self):
        real = admin_store.save_beta_recipient_config
        def lost(*args, **kwargs):
            real(*args, **kwargs)
            raise TimeoutError("response lost")
        with mock.patch.object(admin_store, "save_beta_recipient_config", side_effect=lost) as write:
            self.assertEqual(self.edit()["connection"], "LINKED")
            self.assertEqual(write.call_count, 1)
        self.assertEqual(admin_store.load_beta_recipient_config()["version"], 8)

    def test_config_failure_before_commit_remains_pending_and_same_intent_recovers(self):
        context = edits.form_context("add")
        with mock.patch.object(admin_store, "save_beta_recipient_config", side_effect=TimeoutError("no commit")):
            with self.assertRaises(TimeoutError):
                self.edit(context=context)
        self.assertEqual(delegation._read_current_with_generation()[0]["status"], "EDITING")
        with self.assertRaisesRegex(safety.DeliverySafetyError, "NOT_ACTIVE"):
            delegation.load_active_admin_beta_delegation(reconcile_edits=False)
        self.assertEqual(edits.reconcile_pending_edit()["connection"], "LINKED")
        self.assertIsNone(edits.reconcile_pending_edit())
        self.assertEqual(admin_store.load_beta_recipient_config()["version"], 8)

    def test_grant_failure_after_config_commit_is_resumable(self):
        real = store._create_json_once
        def fail(key, value):
            if key.startswith("admin_beta_delegation/grants/"):
                raise TimeoutError("before grant")
            return real(key, value)
        with mock.patch.object(store, "_create_json_once", side_effect=fail):
            with self.assertRaises(TimeoutError):
                self.edit()
        self.assertEqual(admin_store.load_beta_recipient_config()["version"], 8)
        self.assertEqual(edits.reconcile_pending_edit()["connection"], "LINKED")

    def test_each_pointer_response_lost_after_commit_reconciles(self):
        real = delegation._compare_and_swap_current
        def lost(*args):
            real(*args)
            raise TimeoutError("pointer committed")
        with mock.patch.object(delegation, "_compare_and_swap_current", side_effect=lost) as write:
            self.assertEqual(self.edit()["connection"], "LINKED")
            self.assertEqual(write.call_count, 2)

    def test_final_pointer_failure_before_commit_get_recovers_same_intent(self):
        real = delegation._compare_and_swap_current
        def fail(gen, value):
            if value["status"] == "ACTIVE":
                raise TimeoutError("final before commit")
            return real(gen, value)
        with mock.patch.object(delegation, "_compare_and_swap_current", side_effect=fail):
            with self.assertRaises(TimeoutError):
                self.edit()
        self.assertEqual(edits.reconcile_pending_edit()["connection"], "LINKED")

    def test_result_response_lost_after_final_commit_is_not_new_effect(self):
        real = store._create_json_once
        def lost(key, value):
            result = real(key, value)
            if key.endswith("/result.json"):
                raise TimeoutError("result committed")
            return result
        with mock.patch.object(store, "_create_json_once", side_effect=lost):
            self.assertEqual(self.edit()["connection"], "LINKED")

    def test_result_failure_before_commit_after_active_get_only_records_receipt(self):
        real = store._create_json_once
        def fail(key, value):
            if key.endswith("/result.json"):
                raise TimeoutError("result missing")
            return real(key, value)
        with mock.patch.object(store, "_create_json_once", side_effect=fail):
            with self.assertRaises(TimeoutError):
                self.edit()
        before = delegation._read_current_with_generation()
        self.assertEqual(edits.reconcile_pending_edit()["connection"], "LINKED")
        self.assertEqual(before, delegation._read_current_with_generation())

    def test_concurrent_revoke_after_config_write_wins(self):
        real = admin_store.save_beta_recipient_config
        def revoke(*args, **kwargs):
            real(*args, **kwargs)
            delegation.revoke_admin_beta_delegation(operator_id=ACTOR, reason="concurrent")
        with mock.patch.object(admin_store, "save_beta_recipient_config", side_effect=revoke):
            result = self.edit()
        self.assertTrue(result["config_saved"])
        self.assertEqual(result["connection"], "CANCELLED")
        self.assertEqual(delegation._read_current_with_generation()[0]["status"], "REVOKED")

    def test_concurrent_revoke_at_final_cas_is_not_overwritten(self):
        real = delegation._compare_and_swap_current
        def revoke(gen, value):
            if value["status"] == "ACTIVE":
                delegation.revoke_admin_beta_delegation(operator_id=ACTOR, reason="final race")
            return real(gen, value)
        with mock.patch.object(delegation, "_compare_and_swap_current", side_effect=revoke):
            with self.assertRaisesRegex(safety.DeliverySafetyError, "STATE_CONFLICT"):
                self.edit()
        self.assertEqual(edits.reconcile_pending_edit()["connection"], "STOPPED")
        self.assertEqual(delegation._read_current_with_generation()[0]["status"], "REVOKED")

    def test_revoke_pending_before_config_does_not_resume_unsaved_edit(self):
        with mock.patch.object(admin_store, "save_beta_recipient_config", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                self.edit()
        delegation.revoke_admin_beta_delegation(operator_id=ACTOR, reason="cancel pending")
        result = edits.reconcile_pending_edit()
        self.assertFalse(result["config_saved"])
        self.assertEqual(result["connection"], "CANCELLED")
        self.assertEqual(admin_store.load_beta_recipient_config()["version"], 7)

    def test_concurrent_out_of_band_config_is_not_overwritten(self):
        with mock.patch.object(admin_store, "save_beta_recipient_config", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                self.edit()
        admin_store.save_beta_recipient_config(["other@example.test"], version=99)
        result = edits.reconcile_pending_edit()
        self.assertEqual(result["connection"], "CONFLICT")
        self.assertEqual(admin_store.load_beta_recipient_config()["version"], 99)
        self.assertEqual(delegation._read_current_with_generation()[0]["status"], "STOPPED")

    def test_plain_get_cannot_repair_stale_or_revoked_rights(self):
        before = delegation._read_current_with_generation()
        admin_store.save_beta_recipient_config(self.recipients + ["direct@example.test"], version=8)
        self.assertIsNone(edits.reconcile_pending_edit())
        self.assertEqual(before, delegation._read_current_with_generation())

    def test_orphan_intent_before_fence_is_not_activated_by_get(self):
        with mock.patch.object(delegation, "_compare_and_swap_current", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                self.edit()
        self.assertIsNone(edits.reconcile_pending_edit())
        self.assertEqual(admin_store.load_beta_recipient_config()["version"], 7)

    def test_frozen_plan_stays_immutable_and_new_confirmation_gets_new_exact_cohort(self):
        run = "20261006_183002_keysuri_korea_tech_247cefc0"
        old = safety.manual_recipient_plan(run_id=run, mode="keysuri_korea_tech", now=NOW)
        old_bytes = copy.deepcopy(store._read_json(f"delegated_recipient_plans/{old['plan_id']}.json"))
        self.edit()
        with self.assertRaisesRegex(safety.DeliverySafetyError, "PLAN_CHANGED"):
            delegation.AdminBetaRecipientAuthority().revalidate(old, NOW)
        new = safety.manual_recipient_plan(run_id=run, mode="keysuri_korea_tech", now=NOW)
        self.assertNotEqual(old["plan_id"], new["plan_id"])
        self.assertEqual(len(new["recipients"]), 14)
        self.assertEqual(old_bytes, store._read_json(f"delegated_recipient_plans/{old['plan_id']}.json"))
        self.assertEqual(safety.manual_recipient_plan(run_id=run, mode="keysuri_korea_tech", now=NOW)["plan_id"], new["plan_id"])

    def test_explicit_activation_cannot_overwrite_pending_fence(self):
        with mock.patch.object(admin_store, "save_beta_recipient_config", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                self.edit()
        with self.assertRaisesRegex(safety.DeliverySafetyError, "EDIT_PENDING"):
            delegation.activate_admin_beta_delegation(products=delegation.ALLOWED_MODES, operator_id=ACTOR, now=NOW)

    def test_activation_pins_pointer_before_grant_create_and_revoke_wins(self):
        real = store._create_json_once
        def revoke(key, value):
            result = real(key, value)
            delegation.revoke_admin_beta_delegation(operator_id=ACTOR, reason="activation race")
            return result
        with mock.patch.object(store, "_create_json_once", side_effect=revoke):
            with self.assertRaisesRegex(safety.DeliverySafetyError, "STATE_CONFLICT"):
                delegation.activate_admin_beta_delegation(products=delegation.ALLOWED_MODES, operator_id=ACTOR, now=NOW)
        self.assertEqual(delegation._read_current_with_generation()[0]["status"], "REVOKED")

    def test_tampered_intent_is_not_resumed(self):
        context = edits.form_context("add")
        with mock.patch.object(admin_store, "save_beta_recipient_config", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                self.edit(context=context)
        key = edits._key(context["operation_id"], "intent")
        value = store._read_json(key)
        value["new_config"]["recipients"].append("tampered@example.test")
        store._write_json(key, value)
        with self.assertRaisesRegex(safety.DeliverySafetyError, "INTENT_INVALID"):
            edits.reconcile_pending_edit()

    def test_natural_authority_read_recovers_crash_without_admin_page_visit(self):
        real = store._create_json_once
        def fail(key, value):
            if key.startswith("admin_beta_delegation/grants/"):
                raise TimeoutError("crash after config commit")
            return real(key, value)
        with mock.patch.object(store, "_create_json_once", side_effect=fail):
            with self.assertRaises(TimeoutError):
                self.edit()
        # The real shared service-owned authority boundary, not a new job/GET.
        grant = delegation.load_active_admin_beta_delegation()
        self.assertEqual(grant["recipient_count"], 14)
        self.assertEqual(grant["recipients"], self.recipients + ["new@example.test"])
        self.assertEqual(admin_store.load_beta_recipient_config()["version"], 8)

    def test_applied_first_edit_missing_result_then_second_edit_preserves_history(self):
        context = edits.form_context("add")
        real = store._create_json_once
        def fail(key, value):
            if key.endswith("/result.json"):
                raise TimeoutError("result missing")
            return real(key, value)
        with mock.patch.object(store, "_create_json_once", side_effect=fail):
            with self.assertRaises(TimeoutError):
                self.edit(context=context)
        self.edit(email="second@example.test")
        before = admin_store.load_beta_recipient_config()
        pointer = delegation._read_current_with_generation()
        result = self.edit(context=context)
        self.assertTrue(result["config_saved"])
        self.assertEqual(result["connection"], "SUPERSEDED")
        self.assertEqual(admin_store.load_beta_recipient_config(), before)
        self.assertEqual(delegation._read_current_with_generation(), pointer)
        self.assertEqual(delegation.load_active_admin_beta_delegation()["recipient_count"], 15)


class BetaEditHTTPTests(unittest.TestCase):
    setUp = BetaEditTests.setUp

    def _client_and_add_form(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import admin_routes as routes
        import html
        self.env = mock.patch.dict(os.environ, {"GENIE_ADMIN_PASSWORD": "offline-admin", "GENIE_ADMIN_CSRF_ENABLED": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        app = FastAPI()
        app.include_router(routes.router)
        client = TestClient(app)
        self.addCleanup(client.close)
        client.cookies.set(routes.SESSION_COOKIE, routes._session_token("offline-admin"))
        page = client.get("/admin/customer-recipients")
        self.assertEqual(page.status_code, 200)
        form = re.search(r'<form method="post" action="/admin/customer-recipients/add">(.*?)</form>', page.text, re.S)
        values = {k: html.unescape(v) for k, v in re.findall(r'name="([^"]+)" value="([^"]*)"', form.group(1))}
        return client, values

    def test_post_first_config_failure_recovers_before_display_snapshot(self):
        import admin_routes as routes
        import base64
        import html
        import json
        client, values = self._client_and_add_form()
        values["email"] = "http-recovery@example.test"
        real = admin_store.save_beta_recipient_config
        calls = []
        def fail_once(*args, **kwargs):
            calls.append(True)
            if len(calls) == 1:
                raise TimeoutError("before first config commit")
            return real(*args, **kwargs)
        with mock.patch.object(admin_store, "save_beta_recipient_config", side_effect=fail_once), \
             mock.patch.object(delegation, "load_active_admin_beta_delegation", wraps=delegation.load_active_admin_beta_delegation) as reads:
            response = client.post("/admin/customer-recipients/add", data=values)
        self.assertEqual(response.status_code, 200)
        cfg = admin_store.load_beta_recipient_config()
        self.assertEqual(len(cfg["recipients"]), 14)
        self.assertEqual(len(calls), 2)
        self.assertIn("최종 수신자 <strong>14명</strong>", response.text)
        self.assertIn("어드민 추가 <strong>14명</strong>", response.text)
        self.assertIn("14명 · 3개 상품 · env+admin:v8", response.text)
        self.assertIn("http-recovery@example.test", response.text)
        self.assertIn("명단 저장 완료", response.text)
        self.assertNotIn("발송은 차단되며 이 페이지를 새로고침", response.text)
        form = re.search(r'<form method="post" action="/admin/customer-recipients/add">(.*?)</form>', response.text, re.S).group(1)
        fields = {k: html.unescape(v) for k, v in re.findall(r'name="([^"]+)" value="([^"]*)"', form)}
        self.assertIn("edit_context", fields)
        context = json.loads(base64.urlsafe_b64decode(fields["edit_context"]))
        self.assertEqual(context["config_generation"], cfg["_storage_generation"])
        self.assertEqual(context["config_sha256"], edits.config_identity(cfg))
        self.assertEqual(context["pointer_generation"], delegation._read_current_with_generation()[1])
        self.assertNotIn("disabled", re.search(r'<button[^>]*>추가 · 활성 승인 연결 갱신</button>', form).group(0))
        self.assertTrue(all(call.kwargs.get("reconcile_edits") is False for call in reads.call_args_list))

    def test_edit_during_render_returns_stale_not_mixed_snapshot(self):
        import admin_routes as routes
        client, _ = self._client_and_add_form()
        real = routes._beta_edit_field
        injected = []
        def concurrent(*args, **kwargs):
            if not injected:
                injected.append(True)
                edits.edit_recipient(context=edits.form_context("add"), action="add", email="newer@example.test", operator_id=ACTOR, now=NOW)
            return real(*args, **kwargs)
        with mock.patch.object(routes, "_beta_edit_field", side_effect=concurrent):
            response = client.get("/admin/customer-recipients")
        self.assertEqual(response.status_code, 409)
        self.assertIn("화면 확인 중 변경", response.text)
        self.assertNotIn("최종 수신자 <strong>", response.text)
        self.assertNotIn('name="edit_context"', response.text)
        self.assertNotIn("<strong>ACTIVE</strong>", response.text)
        self.assertEqual(delegation.load_active_admin_beta_delegation()["recipient_count"], 14)

    def test_authenticated_forms_bind_operation_and_no_customer_session_can_edit(self):
        self._assert_authenticated_forms_bind_operation_and_no_customer_session_can_edit()

    def test_persistent_config_failure_renders_current_pending_without_false_pass(self):
        client, values = self._client_and_add_form()
        values["email"] = "still-pending@example.test"
        with mock.patch.object(admin_store, "save_beta_recipient_config", side_effect=TimeoutError("persistent outage")) as writes:
            response = client.post("/admin/customer-recipients/add", data=values)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(writes.call_count, 2)
        self.assertIn("최종 수신자 <strong>13명</strong>", response.text)
        self.assertIn("<strong>STOPPED</strong>", response.text)
        self.assertNotIn("명단 저장 완료", response.text)
        self.assertNotIn('name="edit_context"', response.text)
        self.assertNotIn("<strong>ACTIVE</strong>", response.text)
        self.assertEqual(admin_store.load_beta_recipient_config()["version"], 7)
        self.assertEqual(delegation._read_current_with_generation()[0]["status"], "EDITING")

    def test_revoke_during_render_returns_stale_and_preserves_revocation(self):
        import admin_routes as routes
        client, _ = self._client_and_add_form()
        real = routes._beta_edit_field
        injected = []
        def concurrent(*args, **kwargs):
            if not injected:
                injected.append(True)
                delegation.revoke_admin_beta_delegation(operator_id=ACTOR, reason="render race")
            return real(*args, **kwargs)
        with mock.patch.object(routes, "_beta_edit_field", side_effect=concurrent):
            response = client.get("/admin/customer-recipients")
        self.assertEqual(response.status_code, 409)
        self.assertIn("화면 확인 중 변경", response.text)
        self.assertNotIn('name="edit_context"', response.text)
        self.assertNotIn("ACTIVE", response.text)
        self.assertEqual(delegation._read_current_with_generation()[0]["status"], "REVOKED")

    def _assert_authenticated_forms_bind_operation_and_no_customer_session_can_edit(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import admin_routes as routes
        app = FastAPI()
        app.include_router(routes.router)
        with mock.patch.dict(os.environ, {"GENIE_ADMIN_PASSWORD": "offline-admin", "GENIE_ADMIN_CSRF_ENABLED": "1"}):
            client = TestClient(app)
            # Session is only a local fixture; no production credentials.
            client.cookies.set(routes.SESSION_COOKIE, routes._session_token("offline-admin"))
            page = client.get("/admin/customer-recipients")
            self.assertEqual(page.status_code, 200)
            match = re.search(r'<form method="post" action="/admin/customer-recipients/add">(.*?)</form>', page.text, re.S)
            self.assertIsNotNone(match)
            values = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', match.group(1)))
            import html
            values = {k: html.unescape(v) for k, v in values.items()}
            values["email"] = "http-added@example.test"
            tampered = dict(values, edit_signature="0" * 64)
            self.assertEqual(client.post("/admin/customer-recipients/add", data=tampered).status_code, 400)
            self.assertEqual(admin_store.load_beta_recipient_config()["version"], 7)
            submitted = client.post("/admin/customer-recipients/add", data=values)
            self.assertEqual(submitted.status_code, 200)
            self.assertIn("명단 저장 완료", submitted.text)
            self.assertIn("기존 활성 승인을 새 명단에 연결", submitted.text)
            self.assertEqual(delegation.load_active_admin_beta_delegation()["recipient_count"], 14)
            before = delegation._read_current_with_generation()
            self.assertEqual(client.post("/admin/customer-recipients/add", data=values).status_code, 200)
            self.assertEqual(before, delegation._read_current_with_generation())
            client.cookies.clear()
            response = client.post("/admin/customer-recipients/add", data=values, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(admin_store.load_beta_recipient_config()["version"], 8)
            client.close()


if __name__ == "__main__":
    unittest.main()
