"""Batch 8.3: Today_Geenee manual approval + HTML body delivery + timeout removal."""
from __future__ import annotations

import json
import os
import unittest
from email import message_from_string
from unittest.mock import MagicMock, patch

from admin_store import approve_run, can_approve_customer_send, save_run_artifact
from fastapi.testclient import TestClient
from internal_jobs import process_approval_timeouts
from main import app
from orchestrator import OrchestrationResult, create_naver_draft_if_allowed
from programs.registry import list_programs
from publishing_policy import PublishingDecision, decide_publishing_actions
from today_geenee_customer_delivery import (
    customer_html_contains_naver_markers,
    prepare_customer_final_html,
    send_customer_timeout_draft_email,
    strip_owner_operational_handoff,
)

_FULL_RUNTIME = {"overnight_us_market": {"k": 1}, "macro_indicators": {"k": 2}}


class Batch83RegistryPolicyTests(unittest.TestCase):
    def test_all_programs_timeout_disabled_approval_required(self) -> None:
        for spec in list_programs():
            with self.subTest(program_id=spec.program_id):
                self.assertFalse(spec.auto_send_after_timeout_enabled)
                self.assertTrue(spec.customer_send_requires_approval)


class Batch83PublishingPolicyTests(unittest.TestCase):
    def test_today_pass_no_naver_no_customer(self) -> None:
        d = decide_publishing_actions("today_genie", "pass", "validated", [], _FULL_RUNTIME)
        self.assertFalse(d.create_naver_draft)
        self.assertFalse(d.send_customer_email)

    def test_today_draft_only_no_naver(self) -> None:
        d = decide_publishing_actions(
            "today_genie",
            "draft_only",
            "review_required",
            [],
            _FULL_RUNTIME,
        )
        self.assertFalse(d.create_naver_draft)


class Batch83OrchestratorNaverTests(unittest.TestCase):
    def test_today_genie_naver_draft_blocked(self) -> None:
        result = OrchestrationResult(
            decision=PublishingDecision(
                send_email=False,
                create_naver_draft=True,
                auto_publish=False,
                require_review=True,
                suppress_external=False,
            ),
            reason_summary="ok",
            response_status=200,
            mode="today_genie",
            response_data={
                "data": {
                    "rendered_channels": {"naver_blog_body_html": "<p>n</p>"},
                    "channel_drafts": {"naver_blog_title": "t"},
                }
            },
        )
        self.assertFalse(create_naver_draft_if_allowed(result))


class Batch83CustomerRendererTests(unittest.TestCase):
    def test_strip_operational_handoff(self) -> None:
        html = (
            "<p>body</p>"
            '<section id="genie-operational-handoff"><p>ops</p></section>'
            "<p>tail</p>"
        )
        out = strip_owner_operational_handoff(html)
        self.assertNotIn("genie-operational-handoff", out)
        self.assertIn("body", out)

    def test_naver_markers_rejected(self) -> None:
        html = "<p>[네이버 블로그 복사용 본문 시작]</p>"
        self.assertTrue(customer_html_contains_naver_markers(html))
        with self.assertRaises(ValueError):
            prepare_customer_final_html(html)


class Batch83TimeoutRemovalTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"

    def test_timeout_processor_no_send(self) -> None:
        summary = process_approval_timeouts()
        self.assertEqual(summary["sent"], 0)
        self.assertTrue(summary.get("retired"))

    def test_send_customer_timeout_draft_email_noop(self) -> None:
        self.assertFalse(send_customer_timeout_draft_email("<p>x</p>", {}))

    def test_approve_never_writes_timeout_statuses(self) -> None:
        run_id = "20260604_120000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "reason_summary": "ok",
                "email_sent": True,
            },
            email_html="<p>brief</p>",
        )
        with patch(
            "today_geenee_customer_delivery.send_today_geenee_customer_final_email",
            return_value=True,
        ):
            updated, status = approve_run(run_id)
        self.assertEqual(status, "ok")
        assert updated is not None
        self.assertEqual(updated.get("customer_delivery_status"), "customer_sent_after_approval")
        self.assertNotIn(
            updated.get("customer_delivery_status"),
            ("sent_after_timeout", "auto_sent_after_timeout"),
        )


class Batch83ApproveRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        self._prev_customer = os.environ.get("GENIE_CUSTOMER_EMAIL_TO")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        for key, prev in (
            ("GENIE_ADMIN_PASSWORD", self._prev_pwd),
            ("GENIE_CUSTOMER_EMAIL_TO", self._prev_customer),
        ):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    def test_approve_confirm_requires_login(self) -> None:
        run_id = "20260604_120000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "reason_summary": "ok",
            },
            email_html="<p>brief</p>",
        )
        resp = self.client.get(f"/admin/runs/{run_id}/approve-confirm", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_approve_post_sends_once(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260604_130000_today_genie_bbccddee"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "reason_summary": "ok",
            },
            email_html="<p>brief</p>",
        )
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = self.client.post(
            f"/admin/runs/{run_id}/approve",
            data={"approve_note": "ok"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        mock_send.assert_called_once()
        from admin_store import load_run_artifact

        meta = load_run_artifact(run_id) or {}
        ok, err = can_approve_customer_send(meta, has_email_html=True)
        self.assertFalse(ok)
        self.assertEqual(err, "already_approved")

    def test_duplicate_approve_blocked(self) -> None:
        run_id = "20260604_140000_today_genie_ccddeeff"
        meta = {
            "run_id": run_id,
            "mode": "today_genie",
            "validation_result": "pass",
            "workflow_status": "validated",
            "response_status": 200,
            "reason_summary": "ok",
            "owner_review_status": "approved",
            "customer_delivery_status": "customer_sent_after_approval",
        }
        save_run_artifact(meta, email_html="<p>brief</p>")
        ok, err = can_approve_customer_send(meta, has_email_html=True)
        self.assertFalse(ok)
        self.assertEqual(err, "already_approved")


class Batch83MimeTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"

    @patch("today_geenee_customer_delivery.send_genie_email")
    @patch("today_geenee_customer_delivery._resolve_today_genie_inline_jpeg_parts")
    def test_customer_send_no_attachments(self, mock_inline, mock_send) -> None:
        mock_inline.return_value = [("/tmp/top.jpg", "cid.top", "top.jpg")]
        mock_send.return_value = True
        from today_geenee_customer_delivery import send_today_geenee_customer_final_email

        html = "<p>hello</p>"
        send_today_geenee_customer_final_email(html, {"mode": "today_genie"})
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs.get("attachment_jpeg_parts"), [])
        self.assertTrue(kwargs.get("inline_jpeg_parts"))

    def test_simple_html_mime_no_attachment_filenames(self) -> None:
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        root = MIMEMultipart("mixed")
        related = MIMEMultipart("related")
        related.attach(MIMEText("<p>hi</p>", "html", "utf-8"))
        root.attach(related)
        parsed = message_from_string(root.as_string())
        attachment_names = [
            part.get_filename()
            for part in parsed.walk()
            if part.get_content_disposition() == "attachment" and part.get_filename()
        ]
        self.assertEqual(attachment_names, [])


if __name__ == "__main__":
    unittest.main()
