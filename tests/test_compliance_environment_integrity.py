"""Fail-closed compliance contract and explicit test-environment ownership."""
from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from admin_store import (
    approve_run,
    load_run_artifact,
    process_approval_timeouts,
    save_run_artifact,
)
from compliance_footer import append_compliance_footer, compliance_readiness
from keysuri_customer_delivery import (
    customer_delivery_config_ready as keysuri_ready,
    send_keysuri_customer_final_email,
)
from sent_news_log_store import load_sent_news_log
from tests.compliance_test_support import (
    TEST_COMPLIANCE_ENV,
    compliance_ready_environment,
    explicit_compliance_ready,
)
from today_geenee_customer_delivery import (
    customer_delivery_config_ready as today_ready,
    send_today_geenee_customer_final_email,
)


_EMPTY_COMPLIANCE_ENV = {key: "" for key in TEST_COMPLIANCE_ENV}
_DELIVERY_ENV = {
    "GENIE_CUSTOMER_EMAIL_TO": "customer@example.com",
    "SMTP_HOST": "smtp.c1-verification.invalid",
    "SMTP_USER": "sender@example.com",
}
_OWNERSHIP_FILES = (
    "test_admin_routes.py",
    "test_batch_8_3_today_geenee_delivery.py",
    "test_beta_customer_recipients.py",
    "test_genie_email_operation_box_semantics.py",
    "test_keysuri_customer_delivery.py",
    "test_sent_news_log_approval_update.py",
    "test_today_genie_customer_image_source.py",
)


def _customer_recipients() -> dict[str, list[str]]:
    return {"final_recipients": ["customer@example.com"]}


class ComplianceEnvironmentIntegrityTests(unittest.TestCase):
    def test_no_compliance_configuration_blocks_both_customer_gates(self) -> None:
        with mock.patch.dict(
            os.environ,
            {**_DELIVERY_ENV, **_EMPTY_COMPLIANCE_ENV},
            clear=False,
        ), mock.patch(
            "keysuri_customer_delivery.resolve_customer_recipients",
            return_value=_customer_recipients(),
        ), mock.patch(
            "today_geenee_customer_delivery.resolve_customer_recipients",
            return_value=_customer_recipients(),
        ):
            self.assertEqual(keysuri_ready(), (False, "compliance_not_ready"))
            self.assertEqual(today_ready(), (False, "compliance_not_ready"))

    def test_partial_compliance_configuration_blocks_customer_send(self) -> None:
        partial = dict(TEST_COMPLIANCE_ENV)
        partial["GENIE_TERMS_URL"] = ""
        with mock.patch.dict(
            os.environ,
            {**_DELIVERY_ENV, **partial},
            clear=False,
        ), mock.patch(
            "keysuri_customer_delivery.resolve_customer_recipients",
            return_value=_customer_recipients(),
        ):
            self.assertEqual(keysuri_ready(), (False, "compliance_not_ready"))

    def test_invalid_compliance_values_block_customer_send(self) -> None:
        invalid_values = (
            ("GENIE_PRIVACY_POLICY_URL", "http://c1-verification.invalid/privacy"),
            ("GENIE_TERMS_URL", "https://user:password@c1-verification.invalid/terms"),
            ("GENIE_UNSUBSCRIBE_URL", "http://c1-verification.invalid/unsubscribe"),
            ("GENIE_UNSUBSCRIBE_SIGNING_SECRET", "   "),
            ("GENIE_UNSUBSCRIBE_HANDLER_CONTRACT", "unsupported_contract"),
        )
        for key, value in invalid_values:
            invalid = dict(TEST_COMPLIANCE_ENV)
            invalid[key] = value
            with self.subTest(key=key), mock.patch.dict(
                os.environ,
                {**_DELIVERY_ENV, **invalid},
                clear=False,
            ), mock.patch(
                "keysuri_customer_delivery.resolve_customer_recipients",
                return_value=_customer_recipients(),
            ):
                self.assertEqual(keysuri_ready(), (False, "compliance_not_ready"))

    def test_missing_compliance_blocks_direct_senders_before_sender_call(self) -> None:
        env = {**_DELIVERY_ENV, **_EMPTY_COMPLIANCE_ENV}
        with mock.patch.dict(os.environ, env, clear=False), mock.patch(
            "keysuri_customer_delivery.resolve_customer_recipients",
            return_value=_customer_recipients(),
        ), mock.patch(
            "today_geenee_customer_delivery.resolve_customer_recipients",
            return_value=_customer_recipients(),
        ), mock.patch(
            "keysuri_customer_delivery.send_genie_email",
        ) as keysuri_sender, mock.patch(
            "today_geenee_customer_delivery.send_genie_email",
        ) as today_sender:
            self.assertFalse(
                send_keysuri_customer_final_email(
                    "<html><body>brief</body></html>",
                    {"run_id": "c1-keysuri", "mode": "keysuri_global_tech"},
                )
            )
            self.assertFalse(
                send_today_geenee_customer_final_email(
                    "<html><body>brief</body></html>",
                    {"run_id": "c1-today", "mode": "today_genie"},
                )
            )
        keysuri_sender.assert_not_called()
        today_sender.assert_not_called()

    @explicit_compliance_ready
    @mock.patch("today_geenee_customer_delivery.send_genie_email")
    @mock.patch("today_geenee_customer_delivery._resolve_today_genie_inline_jpeg_parts")
    def test_explicit_fixture_reaches_original_send_assertion_without_smtp(
        self,
        mock_inline,
        mock_send,
    ) -> None:
        mock_inline.return_value = [("/tmp/c1-top.jpg", "cid.c1.top", "c1-top.jpg")]
        mock_send.return_value = True
        with mock.patch.dict(os.environ, _DELIVERY_ENV, clear=False):
            sent = send_today_geenee_customer_final_email(
                "<html><body>brief</body></html>",
                {"mode": "today_genie", "run_id": "c1-test-run"},
            )
        self.assertTrue(sent)
        mock_send.assert_called_once()
        self.assertIn("genie-compliance-links", mock_send.call_args.args[0])

    def test_compliance_footer_uses_opaque_token_without_secret(self) -> None:
        with compliance_ready_environment():
            rendered = append_compliance_footer(
                "<html><body>brief</body></html>",
                run_id="c1-run",
                program_id="keysuri_global_tech",
            )
        self.assertIn("token=", rendered)
        self.assertNotIn(TEST_COMPLIANCE_ENV["GENIE_UNSUBSCRIBE_SIGNING_SECRET"], rendered)

    def test_admin_approval_cannot_bypass_gate_or_record_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = {
                **_DELIVERY_ENV,
                **_EMPTY_COMPLIANCE_ENV,
                "GENIE_ADMIN_ARTIFACT_ROOT": str(root / "artifacts"),
                "GENIE_SENT_NEWS_LOG_PATH": str(root / "sent-news.json"),
                "GENIE_ADMIN_ARTIFACT_BUCKET": "",
                "GENIE_ARTIFACT_BUCKET": "",
            }
            run_id = "20260802_120000_today_genie_c1c1c1c1"
            with mock.patch.dict(os.environ, env, clear=False):
                save_run_artifact(
                    {
                        "run_id": run_id,
                        "mode": "today_genie",
                        "validation_result": "pass",
                        "workflow_status": "validated",
                        "response_status": 200,
                        "owner_review_status": "pending_review",
                        "customer_delivery_status": "not_sent",
                        "selected_items": [
                            {"title": "brief", "url": "https://example.invalid/brief"}
                        ],
                        "required_count": 1,
                    },
                    email_html="<html><body>brief</body></html>",
                )
                with mock.patch(
                    "today_geenee_customer_delivery.send_genie_email"
                ) as sender:
                    updated, status = approve_run(run_id)
                persisted = load_run_artifact(run_id) or {}
                sent_log = load_sent_news_log()
            self.assertIsNone(updated)
            self.assertEqual(status, "compliance_not_ready")
            sender.assert_not_called()
            self.assertEqual(persisted.get("owner_review_status"), "pending_review")
            self.assertEqual(persisted.get("customer_delivery_status"), "not_sent")
            self.assertIsNone(persisted.get("customer_sent_at"))
            self.assertIsNone(persisted.get("smtp_accepted"))
            self.assertEqual(sent_log, [])

    def test_owner_review_modules_do_not_depend_on_customer_compliance(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        for relative in (
            "orchestrator.py",
            "keysuri_service_full_run.py",
            "today_genie_service_full_run.py",
        ):
            source = (repo / relative).read_text(encoding="utf-8")
            self.assertNotIn("compliance_footer", source)
            for key in TEST_COMPLIANCE_ENV:
                self.assertNotIn(key, source)

    def test_retired_timeout_noop_does_not_require_customer_compliance(self) -> None:
        with mock.patch.dict(os.environ, _EMPTY_COMPLIANCE_ENV, clear=False), mock.patch(
            "admin_store.list_run_artifacts",
            return_value=[],
        ) as artifact_list, mock.patch(
            "today_geenee_customer_delivery.send_customer_timeout_draft_email",
        ) as sender:
            summary = process_approval_timeouts()
        self.assertTrue(summary["ok"])
        self.assertTrue(summary["retired"])
        self.assertEqual(summary["sent"], 0)
        artifact_list.assert_called_once()
        sender.assert_not_called()

    def test_unrelated_test_does_not_inherit_fixture_values(self) -> None:
        for key, test_value in TEST_COMPLIANCE_ENV.items():
            self.assertNotEqual(os.environ.get(key), test_value)

    def test_fixture_restores_all_values_after_normal_exit(self) -> None:
        before = {key: os.environ.get(key) for key in TEST_COMPLIANCE_ENV}
        with compliance_ready_environment():
            self.assertEqual(
                {key: os.environ.get(key) for key in TEST_COMPLIANCE_ENV},
                TEST_COMPLIANCE_ENV,
            )
        self.assertEqual(
            {key: os.environ.get(key) for key in TEST_COMPLIANCE_ENV},
            before,
        )

    def test_fixture_restores_all_values_after_exception(self) -> None:
        before = {key: os.environ.get(key) for key in TEST_COMPLIANCE_ENV}
        with self.assertRaisesRegex(RuntimeError, "fixture-exit"):
            with compliance_ready_environment():
                raise RuntimeError("fixture-exit")
        self.assertEqual(
            {key: os.environ.get(key) for key in TEST_COMPLIANCE_ENV},
            before,
        )

    def test_all_35_success_paths_explicitly_own_valid_configuration(self) -> None:
        tests_root = Path(__file__).resolve().parent
        owned = []
        for filename in _OWNERSHIP_FILES:
            tree = ast.parse((tests_root / filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                names = {
                    decorator.id
                    for decorator in node.decorator_list
                    if isinstance(decorator, ast.Name)
                }
                if "explicit_compliance_ready" in names:
                    owned.append(f"{filename}::{node.name}")
        self.assertEqual(len(owned), 35, owned)

    def test_committed_harness_does_not_inject_compliance_values(self) -> None:
        harness = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "run_isolated_dual_profile_harness.sh"
        ).read_text(encoding="utf-8")
        for key in TEST_COMPLIANCE_ENV:
            self.assertNotIn(key, harness)


if __name__ == "__main__":
    unittest.main()
